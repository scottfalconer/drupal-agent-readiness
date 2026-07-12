from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from agent_readiness.external_eval_results import (
    DEFAULT_EVIDENCE_DIR,
    DEFAULT_JSON_OUTPUT,
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_RUN_SCHEMA_PATH,
    DEFAULT_SOURCE_VALIDATION_SCHEMA_PATH,
    ExternalEvalResultError,
    build_results,
    build_outputs,
    check_outputs,
    load_records,
    render_markdown,
    validate_run,
    validate_source_validation,
    _validate_with_schema,
)
from agent_readiness.scripts import build_external_eval_results


RUN_ID = "2026-07-12-render-pipeline-b01-codex-gpt-5.4"
VALIDATION_ID = "2026-07-12-static-checks-c4511713"
AI_AGENTS_VALIDATION_ID = (
    "2026-07-12-drupal-cms-codebase-standard-profile-preflight-e06f11c3"
)


class ExternalEvalResultsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.run_schema = json.loads(
            DEFAULT_RUN_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        self.source_validation_schema = json.loads(
            DEFAULT_SOURCE_VALIDATION_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        runs, validations = load_records()
        self.run = next(record for record in runs if record["run_id"] == RUN_ID)
        self.validation = next(
            record for record in validations if record["validation_id"] == VALIDATION_ID
        )
        self.ai_agents_validation = next(
            record
            for record in validations
            if record["validation_id"] == AI_AGENTS_VALIDATION_ID
        )

    @staticmethod
    def _copy_artifacts_to_temp_repo(
        record: dict[str, Any], temporary_root: Path
    ) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        for artifact in record["artifacts"]:
            source = repository_root / artifact["path"]
            destination = temporary_root / artifact["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())

    def test_retained_agent_run_is_bounded_pinned_and_registry_linked(self) -> None:
        run = self.run
        self.assertEqual("ai_best_practices_run_evals_v1", run["adapter_id"])
        self.assertEqual("ai-best-practices", run["source"]["source_id"])
        self.assertEqual("skill-eval-cases", run["source"]["artifact_id"])
        self.assertEqual(
            {"kind": "branch", "value": "1.0.x"},
            run["source"]["registry_revision"],
        )
        self.assertEqual(
            "c45117130a4de1fe7d03d3fe225e3f09b8e4e803",
            run["source"]["upstream_commit"],
        )
        self.assertEqual(["B01"], run["suite"]["case_ids"])
        self.assertEqual("skill_injected", run["treatment"]["condition_id"])
        self.assertEqual(
            "single_condition_no_ab", run["treatment"]["comparison_design"]
        )
        self.assertEqual("0.142.5", run["agent"]["agent_version"])
        self.assertEqual("gpt-5.4", run["agent"]["model_id"])
        self.assertFalse(run["substrate"]["real_target_runtime"])
        self.assertEqual(
            ["--ignore-user-config", "--ephemeral"],
            run["adapter_data"]["runner"]["added_cli_arguments"],
        )
        self.assertEqual(
            (1, 0, 1),
            (
                run["result"]["cases_total"],
                run["result"]["cases_passed"],
                run["result"]["cases_failed"],
            ),
        )
        self.assertEqual("failed", run["result"]["automated_outcome"])
        self.assertEqual(
            "upstream_oracle_fail_manual_adjudication_required",
            run["result"]["published_outcome"],
        )
        self.assertEqual(
            "required_unresolved", run["result"]["manual_adjudication_status"]
        )
        self.assertEqual(0, run["adapter_data"]["result"]["php_blocks_failed_lint"])
        self.assertEqual("locally_run_diagnostic", run["evidence"]["classification"])
        self.assertFalse(run["evidence"]["scorecard_eligible"])
        self.assertEqual("none", run["evidence"]["coverage_effect"])

    def test_trace_copy_is_byte_exact(self) -> None:
        artifact = next(
            item for item in self.run["artifacts"] if item["kind"] == "upstream_trace"
        )
        retained = (Path(__file__).resolve().parents[2] / artifact["path"]).read_bytes()
        self.assertEqual(
            "f6efef30de423403ac9b9ebb1627c876d26d77a65c21544ff5294aa3b0bb9531",
            hashlib.sha256(retained).hexdigest(),
        )
        self.assertEqual(artifact["sha256"], hashlib.sha256(retained).hexdigest())

    def test_abp_run_agent_identity_is_pinned(self) -> None:
        run_path = next(DEFAULT_EVIDENCE_DIR.glob(f"*/{RUN_ID}/run.json"))
        for field, value in (
            ("provider", "anthropic"),
            ("agent_id", "other-cli"),
            ("agent_version", "999.0.0"),
            ("model_id", "other-model"),
        ):
            with self.subTest(field=field):
                run = copy.deepcopy(self.run)
                run["agent"][field] = value
                with self.assertRaisesRegex(ExternalEvalResultError, "agent identity"):
                    validate_run(run, self.run_schema, source_path=run_path)

    def test_static_validation_is_five_commands_not_one_performance_run(self) -> None:
        record = self.validation
        validation = record["validation"]
        data = validation["adapter_data"]
        self.assertEqual("ai_best_practices_static_v1", record["adapter_id"])
        self.assertEqual(5, data["commands_total"])
        self.assertEqual(
            (219, 219, 0),
            (
                validation["checks_total"],
                validation["checks_passed"],
                validation["checks_failed"],
            ),
        )
        self.assertEqual(144, data["default_discovery_checks"])
        self.assertEqual(75, data["nested_explicit_checks"])
        self.assertFalse(record["evidence"]["agent_performance_result"])
        self.assertEqual("retained_artifacts", record["evidence"]["support_grade"])
        self.assertEqual(5, len(record["artifacts"]))
        self.assertEqual(
            {command["id"] for command in data["commands"]},
            {artifact["id"] for artifact in record["artifacts"]},
        )
        self.assertEqual(
            [144, 14, 17, 21, 23],
            [command["checks_total"] for command in data["commands"]],
        )

    def test_ai_agents_preflight_is_structured_non_performance_evidence(self) -> None:
        record = self.ai_agents_validation
        validation = record["validation"]
        data = validation["adapter_data"]
        self.assertEqual(
            "ai_agents_test_drupal_cms_codebase_preflight_v1",
            record["adapter_id"],
        )
        self.assertEqual("structured_observations", validation["outcome_model"])
        self.assertNotIn("checks_total", validation)
        self.assertEqual(8, len(data["observations"]))
        by_id = {item["id"]: item for item in data["observations"]}
        self.assertEqual(81, by_id["yaml-catalog-parse"]["facts"]["cases_counted"])
        self.assertEqual(
            "externally_blocked_partial",
            by_id["drupal-cms-ai-recipe"]["outcome"],
        )
        self.assertFalse(
            by_id["real-test-1-no-provider"]["facts"]["real_model_invoked"]
        )
        self.assertEqual(
            "presentation_result_disagreement",
            by_id["unsupported-echo-mock-smoke"]["outcome"],
        )
        self.assertFalse(data["retention"]["raw_stdout_retained"])
        self.assertFalse(data["retention"]["database_dump_retained"])
        self.assertFalse(record["evidence"]["agent_performance_result"])
        self.assertEqual(
            "manifest_only_unverified", record["evidence"]["support_grade"]
        )
        self.assertEqual([], record["artifacts"])
        self.assertFalse(data["substrate"]["drupal_cms_install_profile_used"])
        self.assertEqual("standard", data["substrate"]["install_profile"])
        self.assertTrue(
            all(
                item["evidence_support"] == "manifest_only_unverified"
                for item in data["observations"]
            )
        )

    def test_structured_observations_cannot_be_flattened_to_counts(self) -> None:
        record = copy.deepcopy(self.ai_agents_validation)
        record["validation"].update(
            {"checks_total": 8, "checks_passed": 5, "checks_failed": 3}
        )
        validation_path = next(
            DEFAULT_EVIDENCE_DIR.glob(
                f"*/{AI_AGENTS_VALIDATION_ID}/source-validation.json"
            )
        )
        with self.assertRaisesRegex(ExternalEvalResultError, "must not be flattened"):
            validate_source_validation(
                record,
                self.source_validation_schema,
                source_path=validation_path,
            )

    def test_closed_base_schema_rejects_unknown_envelope_fields(self) -> None:
        run = copy.deepcopy(self.run)
        run["arbitrary_execution"] = {"command": "do-not-run"}
        run_path = next(DEFAULT_EVIDENCE_DIR.glob(f"*/{RUN_ID}/run.json"))
        with self.assertRaisesRegex(ExternalEvalResultError, "unknown properties"):
            validate_run(run, self.run_schema, source_path=run_path)

    def test_run_artifacts_must_remain_inside_their_record_directory(self) -> None:
        run = copy.deepcopy(self.run)
        foreign = next(
            DEFAULT_EVIDENCE_DIR.glob(f"*/{VALIDATION_ID}/source-validation.json")
        )
        artifact = next(
            item for item in run["artifacts"] if item["kind"] == "upstream_trace"
        )
        artifact["path"] = foreign.relative_to(
            Path(__file__).resolve().parents[2]
        ).as_posix()
        artifact["sha256"] = hashlib.sha256(foreign.read_bytes()).hexdigest()
        run_path = next(DEFAULT_EVIDENCE_DIR.glob(f"*/{RUN_ID}/run.json"))
        with self.assertRaisesRegex(ExternalEvalResultError, "record directory"):
            validate_run(run, self.run_schema, source_path=run_path)

    def test_json_cannot_substitute_for_reconstructed_prompt(self) -> None:
        run = copy.deepcopy(self.run)
        prompt = next(
            item
            for item in run["artifacts"]
            if item["kind"] == "reconstructed_full_prompt"
        )
        substitute = next(
            DEFAULT_EVIDENCE_DIR.glob(f"*/{VALIDATION_ID}/source-validation.json")
        ).read_bytes()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._copy_artifacts_to_temp_repo(run, root)
            prompt_path = root / prompt["path"]
            prompt_path.write_bytes(substitute)
            prompt["sha256"] = hashlib.sha256(substitute).hexdigest()
            evidence_dir = root / "evidence" / "external-evals"
            source_path = (
                evidence_dir / run["source"]["source_id"] / run["run_id"] / "run.json"
            )
            with self.assertRaisesRegex(ExternalEvalResultError, "concatenation shape"):
                validate_run(
                    run,
                    self.run_schema,
                    source_path=source_path,
                    evidence_dir=evidence_dir,
                    repo_root=root,
                )

    def test_abp_traces_must_have_unique_exact_case_ids(self) -> None:
        run = copy.deepcopy(self.run)
        original_trace = next(
            item for item in run["artifacts"] if item["kind"] == "upstream_trace"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._copy_artifacts_to_temp_repo(run, root)
            duplicate = copy.deepcopy(original_trace)
            duplicate["path"] = original_trace["path"].replace(
                "traces/B01.json", "traces/B01-copy.json"
            )
            duplicate_path = root / duplicate["path"]
            duplicate_path.parent.mkdir(parents=True, exist_ok=True)
            duplicate_path.write_bytes((root / original_trace["path"]).read_bytes())
            run["artifacts"].append(duplicate)
            evidence_dir = root / "evidence" / "external-evals"
            source_path = (
                evidence_dir / run["source"]["source_id"] / run["run_id"] / "run.json"
            )
            with self.assertRaisesRegex(ExternalEvalResultError, "unique trace"):
                validate_run(
                    run,
                    self.run_schema,
                    source_path=source_path,
                    evidence_dir=evidence_dir,
                    repo_root=root,
                )

    def test_abp_adapter_is_bounded_to_the_audited_b01_case(self) -> None:
        run = copy.deepcopy(self.run)
        run["suite"]["case_ids"] = ["B01", "B02"]
        run["suite"]["cases_selected"] = 2
        run["result"]["cases_total"] = 2
        run["result"]["cases_failed"] = 2
        run_path = next(DEFAULT_EVIDENCE_DIR.glob(f"*/{RUN_ID}/run.json"))

        with self.assertRaisesRegex(ExternalEvalResultError, "bounded.*B01"):
            validate_run(run, self.run_schema, source_path=run_path)

    def test_abp_trace_cannot_self_declare_a_contradictory_pass(self) -> None:
        run = copy.deepcopy(self.run)
        trace_artifact = next(
            item for item in run["artifacts"] if item["kind"] == "upstream_trace"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._copy_artifacts_to_temp_repo(run, root)
            trace_path = root / trace_artifact["path"]
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            self.assertEqual([], trace["assertions"]["found"])
            self.assertIn("missing all of", trace["detail"])
            trace["passed"] = True
            rendered = (json.dumps(trace, indent=2) + "\n").encode("utf-8")
            trace_path.write_bytes(rendered)
            trace_artifact["sha256"] = hashlib.sha256(rendered).hexdigest()
            run["result"]["cases_passed"] = 1
            run["result"]["cases_failed"] = 0
            run["result"]["automated_outcome"] = "passed"
            run["result"]["published_outcome"] = "upstream_oracle_pass"
            run["result"]["manual_adjudication_status"] = "not_required"
            evidence_dir = root / "evidence" / "external-evals"
            source_path = (
                evidence_dir / run["source"]["source_id"] / run["run_id"] / "run.json"
            )

            with self.assertRaisesRegex(
                ExternalEvalResultError, "verdict does not match"
            ):
                validate_run(
                    run,
                    self.run_schema,
                    source_path=source_path,
                    evidence_dir=evidence_dir,
                    repo_root=root,
                )

    def test_abp_trace_cannot_relabel_invalid_php_as_lint_passed(self) -> None:
        run = copy.deepcopy(self.run)
        trace_artifact = next(
            item for item in run["artifacts"] if item["kind"] == "upstream_trace"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._copy_artifacts_to_temp_repo(run, root)
            trace_path = root / trace_artifact["path"]
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["response"] = trace["response"].replace(
                "$nids = $this->entityTypeManager()",
                "$nids = ;\n    $this->entityTypeManager()",
                1,
            )
            rendered = (json.dumps(trace, indent=2) + "\n").encode("utf-8")
            trace_path.write_bytes(rendered)
            trace_artifact["sha256"] = hashlib.sha256(rendered).hexdigest()
            evidence_dir = root / "evidence" / "external-evals"
            source_path = (
                evidence_dir / run["source"]["source_id"] / run["run_id"] / "run.json"
            )

            with self.assertRaisesRegex(
                ExternalEvalResultError, "approved byte-exact artifact hash"
            ):
                validate_run(
                    run,
                    self.run_schema,
                    source_path=source_path,
                    evidence_dir=evidence_dir,
                    repo_root=root,
                )

    def test_stdlib_validator_enforces_source_validation_conditionals(self) -> None:
        manifest_only = copy.deepcopy(self.ai_agents_validation)
        manifest_only["artifacts"] = [
            {
                "id": "forbidden-artifact",
                "kind": "stdout",
                "path": "evidence/external-evals/example/stdout.txt",
                "sha256": "0" * 64,
                "media_type": "text/plain",
            }
        ]
        with self.assertRaisesRegex(ExternalEvalResultError, "at most 0"):
            _validate_with_schema(
                manifest_only,
                self.source_validation_schema,
                label="external source validation",
            )

        retained = copy.deepcopy(self.validation)
        retained["artifacts"] = []
        with self.assertRaisesRegex(ExternalEvalResultError, "at least 1"):
            _validate_with_schema(
                retained,
                self.source_validation_schema,
                label="external source validation",
            )

    def test_upstream_derived_evidence_has_scoped_license_provenance(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        reuse = tomllib.loads(
            (repository_root / "REUSE.toml").read_text(encoding="utf-8")
        )
        licensed_paths = {
            path
            for annotation in reuse["annotations"]
            if annotation["SPDX-License-Identifier"] == "GPL-2.0-or-later"
            for path in (
                annotation["path"]
                if isinstance(annotation["path"], list)
                else [annotation["path"]]
            )
        }
        expected_paths = {
            artifact["path"]
            for record in (self.run, self.validation)
            for artifact in record["artifacts"]
            if artifact["kind"]
            in {
                "reconstructed_full_prompt",
                "upstream_trace",
                "static_check_stdout",
            }
        }
        self.assertEqual(expected_paths, licensed_paths)
        self.assertTrue(
            all((repository_root / path).is_file() for path in licensed_paths)
        )

        notice = (repository_root / "THIRD_PARTY_NOTICES.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("AI Best Practices for Drupal", notice)
        self.assertIn(
            "c45117130a4de1fe7d03d3fe225e3f09b8e4e803",
            notice,
        )
        self.assertTrue(all(path in notice for path in licensed_paths))
        license_text = (
            repository_root / "LICENSES" / "GPL-2.0-or-later.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text)
        self.assertIn("Version 2, June 1991", license_text)

    def test_renderer_selects_artifacts_by_kind_not_position(self) -> None:
        run = copy.deepcopy(self.run)
        run["artifacts"].reverse()
        markdown = render_markdown(build_results([run], []))
        trace = next(
            item for item in run["artifacts"] if item["kind"] == "upstream_trace"
        )
        prompt = next(
            item
            for item in run["artifacts"]
            if item["kind"] == "reconstructed_full_prompt"
        )
        self.assertIn(f"- Trace: `{trace['path']}`", markdown)
        self.assertIn(f"- Reconstructed prompt: `{prompt['path']}`", markdown)

    def test_record_prose_is_escaped_before_markdown_rendering(self) -> None:
        run = copy.deepcopy(self.run)
        run["result"]["detail"] = "<script>unsafe</script>"
        markdown = render_markdown(build_results([run], []))
        self.assertNotIn("<script>unsafe</script>", markdown)
        self.assertIn("&lt;script&gt;unsafe&lt;/script&gt;", markdown)

    def test_unknown_run_adapter_fails_before_future_style_execution(self) -> None:
        run = copy.deepcopy(self.run)
        run["run_id"] = "future-ai-agents-test-run"
        run["adapter_id"] = "ai_agents_test_run_v1"
        run["source"] = {
            "source_id": "ai-agents-test",
            "artifact_id": "drupal-cms-agent-test-suites",
            "registry_revision": {"kind": "branch", "value": "1.0.x"},
            "upstream_commit": "e06f11c33c2fda6beb09008e60bf8a65804a132c",
        }
        run["adapter_data"] = {"future_framework": "ai_agents_test"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_dir = Path(temporary_directory)
            source_path = evidence_dir / "ai-agents-test" / run["run_id"] / "run.json"
            with self.assertRaisesRegex(
                ExternalEvalResultError, "unknown trusted run adapter"
            ):
                validate_run(
                    run,
                    self.run_schema,
                    source_path=source_path,
                    evidence_dir=evidence_dir,
                )

    def test_unknown_source_validation_adapter_fails_closed(self) -> None:
        record = copy.deepcopy(self.validation)
        record["adapter_id"] = "future_static_adapter_v1"
        validation_path = next(
            DEFAULT_EVIDENCE_DIR.glob(f"*/{VALIDATION_ID}/source-validation.json")
        )
        with self.assertRaisesRegex(
            ExternalEvalResultError, "unknown trusted source-validation adapter"
        ):
            validate_source_validation(
                record,
                self.source_validation_schema,
                source_path=validation_path,
            )

    def test_source_artifacts_must_remain_inside_their_record_directory(self) -> None:
        record = copy.deepcopy(self.validation)
        foreign = next(DEFAULT_EVIDENCE_DIR.glob(f"*/{RUN_ID}/traces/B01.json"))
        artifact = record["artifacts"][0]
        artifact["path"] = foreign.relative_to(
            Path(__file__).resolve().parents[2]
        ).as_posix()
        artifact["sha256"] = hashlib.sha256(foreign.read_bytes()).hexdigest()
        validation_path = next(
            DEFAULT_EVIDENCE_DIR.glob(f"*/{VALIDATION_ID}/source-validation.json")
        )
        with self.assertRaisesRegex(ExternalEvalResultError, "record directory"):
            validate_source_validation(
                record,
                self.source_validation_schema,
                source_path=validation_path,
            )

    def test_manifest_only_source_record_cannot_claim_artifacts(self) -> None:
        record = copy.deepcopy(self.ai_agents_validation)
        record["artifacts"] = [copy.deepcopy(self.validation["artifacts"][0])]
        validation_path = next(
            DEFAULT_EVIDENCE_DIR.glob(
                f"*/{AI_AGENTS_VALIDATION_ID}/source-validation.json"
            )
        )
        with self.assertRaisesRegex(ExternalEvalResultError, "at most 0|manifest-only"):
            validate_source_validation(
                record,
                self.source_validation_schema,
                source_path=validation_path,
            )

    def test_static_stdout_must_support_reported_counts(self) -> None:
        record = copy.deepcopy(self.validation)
        artifact = record["artifacts"][0]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._copy_artifacts_to_temp_repo(record, root)
            artifact_path = root / artifact["path"]
            tampered = artifact_path.read_text(encoding="utf-8").replace(
                "[PASS]", "[FAIL]", 1
            )
            artifact_path.write_text(tampered, encoding="utf-8")
            artifact["sha256"] = hashlib.sha256(tampered.encode("utf-8")).hexdigest()
            evidence_dir = root / "evidence" / "external-evals"
            source_path = (
                evidence_dir
                / record["source"]["source_id"]
                / record["validation_id"]
                / "source-validation.json"
            )
            with self.assertRaisesRegex(ExternalEvalResultError, "retained stdout"):
                validate_source_validation(
                    record,
                    self.source_validation_schema,
                    source_path=source_path,
                    evidence_dir=evidence_dir,
                    repo_root=root,
                )

    def test_static_command_and_stdout_are_bound_to_the_approved_skill(self) -> None:
        validation_path = next(
            DEFAULT_EVIDENCE_DIR.glob(f"*/{VALIDATION_ID}/source-validation.json")
        )
        changed_argv = copy.deepcopy(self.validation)
        explicit = next(
            command
            for command in changed_argv["validation"]["adapter_data"]["commands"]
            if not command["default_discovery"]
        )
        explicit["argv"][-1] = "drupal-accessibility/unrelated-suite"
        with self.assertRaisesRegex(ExternalEvalResultError, "approved static target"):
            validate_source_validation(
                changed_argv,
                self.source_validation_schema,
                source_path=validation_path,
            )

        changed_stdout = copy.deepcopy(self.validation)
        explicit = next(
            command
            for command in changed_stdout["validation"]["adapter_data"]["commands"]
            if not command["default_discovery"]
        )
        artifact = next(
            item
            for item in changed_stdout["artifacts"]
            if item["id"] == explicit["artifact_id"]
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._copy_artifacts_to_temp_repo(changed_stdout, root)
            artifact_path = root / artifact["path"]
            original_target = explicit["argv"][-1]
            tampered = artifact_path.read_text(encoding="utf-8").replace(
                f"=== {original_target} ===",
                "=== drupal-accessibility/unrelated-suite ===",
                1,
            )
            artifact_path.write_text(tampered, encoding="utf-8")
            artifact["sha256"] = hashlib.sha256(tampered.encode("utf-8")).hexdigest()
            evidence_dir = root / "evidence" / "external-evals"
            source_path = (
                evidence_dir
                / changed_stdout["source"]["source_id"]
                / changed_stdout["validation_id"]
                / "source-validation.json"
            )
            with self.assertRaisesRegex(ExternalEvalResultError, "stdout headings"):
                validate_source_validation(
                    changed_stdout,
                    self.source_validation_schema,
                    source_path=source_path,
                    evidence_dir=evidence_dir,
                    repo_root=root,
                )

    def test_scorecard_or_performance_promotion_is_schema_invalid(self) -> None:
        run = copy.deepcopy(self.run)
        run["evidence"]["scorecard_eligible"] = True
        run_path = next(DEFAULT_EVIDENCE_DIR.glob(f"*/{RUN_ID}/run.json"))
        with self.assertRaisesRegex(ExternalEvalResultError, "scorecard_eligible"):
            validate_run(run, self.run_schema, source_path=run_path)

        record = copy.deepcopy(self.validation)
        record["evidence"]["agent_performance_result"] = True
        validation_path = next(
            DEFAULT_EVIDENCE_DIR.glob(f"*/{VALIDATION_ID}/source-validation.json")
        )
        with self.assertRaisesRegex(
            ExternalEvalResultError, "agent_performance_result"
        ):
            validate_source_validation(
                record,
                self.source_validation_schema,
                source_path=validation_path,
            )

    def test_registry_revision_mismatch_is_rejected(self) -> None:
        run = copy.deepcopy(self.run)
        run["source"]["registry_revision"]["value"] = "not-the-pointer-revision"
        run_path = next(DEFAULT_EVIDENCE_DIR.glob(f"*/{RUN_ID}/run.json"))
        with self.assertRaisesRegex(ExternalEvalResultError, "registry_revision"):
            validate_run(run, self.run_schema, source_path=run_path)

    def test_mutable_registry_branch_cannot_drift_from_audited_commit(self) -> None:
        run = copy.deepcopy(self.run)
        run["source"]["upstream_commit"] = "0" * 40
        run_path = next(DEFAULT_EVIDENCE_DIR.glob(f"*/{RUN_ID}/run.json"))
        with self.assertRaisesRegex(ExternalEvalResultError, "audited commit"):
            validate_run(run, self.run_schema, source_path=run_path)

        record = copy.deepcopy(self.validation)
        record["source"]["upstream_commit"] = "0" * 40
        validation_path = next(
            DEFAULT_EVIDENCE_DIR.glob(f"*/{VALIDATION_ID}/source-validation.json")
        )
        with self.assertRaisesRegex(ExternalEvalResultError, "audited commit"):
            validate_source_validation(
                record,
                self.source_validation_schema,
                source_path=validation_path,
            )

    def test_static_aggregate_drift_is_rejected(self) -> None:
        record = copy.deepcopy(self.validation)
        record["validation"]["checks_total"] = 220
        validation_path = next(
            DEFAULT_EVIDENCE_DIR.glob(f"*/{VALIDATION_ID}/source-validation.json")
        )
        with self.assertRaisesRegex(ExternalEvalResultError, "sum to checks_total"):
            validate_source_validation(
                record,
                self.source_validation_schema,
                source_path=validation_path,
            )

    def test_generated_outputs_are_current_and_preserve_claim_boundaries(self) -> None:
        self.assertEqual([], check_outputs())
        expected_json, expected_markdown = build_outputs()
        self.assertEqual(expected_json, DEFAULT_JSON_OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(
            expected_markdown, DEFAULT_MARKDOWN_OUTPUT.read_text(encoding="utf-8")
        )
        self.assertIn("current ABP agent run is prompt-only", expected_markdown)
        self.assertIn("No record is a general model score", expected_markdown)
        self.assertIn("upstream project verdict", expected_markdown)
        self.assertIn(
            "upstream_oracle_fail_manual_adjudication_required", expected_markdown
        )
        self.assertIn("likely oracle disagreement", expected_markdown)
        self.assertIn("full injected skill prompt", expected_markdown)
        self.assertIn("Source validation (not agent performance)", expected_markdown)
        self.assertIn("219/219 static checks passed", expected_markdown)
        self.assertIn(
            "ai_agents_test_drupal_cms_codebase_preflight_v1", expected_markdown
        )
        self.assertIn("intentionally not flattened", expected_markdown)
        self.assertIn("No real model or configured AI provider", expected_markdown)
        self.assertIn("manifest-only; independently unverified", expected_markdown)

    def test_generator_check_detects_missing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = build_external_eval_results.main(
                    [
                        "--check",
                        "--json-output",
                        str(root / "results.json"),
                        "--markdown-output",
                        str(root / "results.md"),
                    ]
                )

        self.assertEqual(1, exit_code)
        self.assertIn("missing generated output", output.getvalue())


if __name__ == "__main__":
    unittest.main()
