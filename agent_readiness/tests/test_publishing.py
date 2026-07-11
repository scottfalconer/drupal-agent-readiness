import csv
import copy
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


def write_valid_test_package(base: Path, runs: list[dict]) -> None:
    from agent_readiness.tests.test_readiness import ReadinessTest

    ReadinessTest()._write_minimal_publish_assets(base, runs)


class PublishingTest(unittest.TestCase):

    def test_scorecard_row_contains_required_v0_dimensions(self) -> None:
        from agent_readiness.publishing import scorecard_rows

        row = scorecard_rows([load_fixture("run_result_inventory_pass.json")])[0]

        self.assertEqual("haven-inventory-v0-codex-smoke", row["run_id"])
        self.assertEqual("inventory.read_only", row["task_id"])
        self.assertEqual("legacy_unpinned", row["run_class"])
        self.assertEqual("v0.1", row["prompt_version"])
        self.assertEqual("haven-clean-install", row["substrate_id"])
        self.assertEqual("gpt-5", row["model"])
        self.assertEqual("operator_supplied_or_unknown", row["metrics_provenance"])
        self.assertEqual("true", row["task_success"])
        self.assertEqual("0", row["human_rescues"])
        self.assertEqual("mechanical-pass", row["verification_quality"])
        self.assertEqual("clean", row["blast_radius"])

    def test_report_keeps_v0_framed_as_qualitative_baseline(self) -> None:
        from agent_readiness.publishing import render_report

        report = render_report([load_fixture("run_result_inventory_pass.json")])

        self.assertIn("State of Agents in Drupal", report)
        self.assertIn("qualitative v0 snapshot", report)
        self.assertIn("not a cross-CMS comparison", report)
        self.assertIn("public/why-this-bench.md", report)
        self.assertIn("tooling/evaluator smoke", report)
        self.assertIn("haven-inventory-v0-codex-smoke", report)

    def test_report_includes_readiness_status(self) -> None:
        from agent_readiness.publishing import render_report

        run = load_fixture("run_result_inventory_pass.json")
        run["run_id"] = "haven-inventory-v0-tooling-smoke"
        run["agent"] = {
            "name": "Tooling smoke",
            "model": "none",
            "harness": "local evaluator scripts",
        }

        report = render_report([run])

        self.assertIn("public/readiness.json` is a generated, non-authoritative source-gate snapshot", report)
        self.assertIn("does not audit the live package tree", report)
        self.assertIn("At least one no-rescue legacy inventory example: no", report)
        self.assertIn("Three-example legacy evidence-loop check: no (not a numeric-claim gate)", report)
        self.assertIn("Reportable measurement-v1 estimate: none", report)
        self.assertIn("Reportable fixed-regression estimate: none", report)
        self.assertIn("Registered measurement effect rule met: none", report)
        self.assertIn("Canonical action-registry improvement decision ready: none", report)
        self.assertIn("no-rescue non-smoke inventory examples: 0/1", report)

    def test_report_splits_smoke_and_independent_runs_with_elapsed_time(self) -> None:
        from agent_readiness.publishing import render_report

        smoke = load_fixture("run_result_inventory_pass.json")
        smoke["run_id"] = "haven-inventory-v0-tooling-smoke"
        smoke["agent"] = {
            "name": "Tooling smoke",
            "model": "none",
            "harness": "local evaluator scripts",
        }
        smoke["metrics"]["elapsed_seconds"] = 12
        smoke["metrics"]["tool_calls"] = 4

        independent = load_fixture("run_result_inventory_pass.json")
        independent["run_id"] = "inventory-independent-001"
        independent["agent"] = {
            "name": "Independent Codex",
            "model": "gpt-5",
            "harness": "fresh Codex thread",
        }
        independent["metrics"]["elapsed_seconds"] = 336
        independent["metrics"]["tool_calls"] = 4

        report = render_report([smoke, independent])

        self.assertIn("Constrained evaluator passes: 2/2", report)
        self.assertIn("These constrained v0 tasks exercise", report)
        self.assertIn("### Tooling/evaluator smoke runs", report)
        self.assertIn("### Non-smoke constrained agent runs", report)
        self.assertIn("does not certify independence", report)
        self.assertIn("| Run | Class | Task | Model | Substrate | Prompt | Success |", report)
        self.assertIn("| haven-inventory-v0-tooling-smoke | tooling_smoke | inventory.read_only | none | haven-clean-install | v0.1 | true | 0 | 12 | 4 | operator_supplied_or_unknown | mechanical-pass | clean |", report)
        self.assertIn("| inventory-independent-001 | legacy_unpinned | inventory.read_only | gpt-5 | haven-clean-install | v0.1 | true | 0 | 336 | 4 | operator_supplied_or_unknown | mechanical-pass | clean |", report)

    def test_report_includes_next_hardening_steps(self) -> None:
        from agent_readiness.publishing import render_report

        report = render_report([load_fixture("run_result_inventory_pass.json")])

        self.assertIn("## Next hardening steps", report)
        self.assertIn("Completed in v0.2:", report)
        self.assertIn("De-leaked the inventory prompt", report)
        self.assertIn("Run paired pre/post fixed-agent experiments", report)

    def test_report_marks_discrimination_when_failing_run_present(self) -> None:
        from agent_readiness.publishing import FORBIDDEN_PUBLIC_CLAIMS, render_report

        passing = load_fixture("run_result_inventory_pass.json")
        passing["run_id"] = "inventory-deleaked-equipped"
        passing["agent"] = {"name": "Independent subagent (equipped)", "model": "claude-opus-4-8", "harness": "live drush"}

        failing = load_fixture("run_result_inventory_pass.json")
        failing["run_id"] = "inventory-deleaked-blind"
        failing["agent"] = {"name": "Independent subagent (blind)", "model": "claude-opus-4-8", "harness": "static source only"}
        failing["evaluator"] = {"passed": False, "failures": ["command_runner", "paths./node.owner_kind"], "warnings": []}
        failing["failure_labels"] = ["command_runner", "path_ownership"]

        report = render_report([passing, failing])

        self.assertIn("Failing runs retained: 1", report)
        self.assertIn("this alone does not establish matched discriminator validity", report)
        self.assertIn("reports retained evaluator outcomes", report)
        self.assertNotIn("runs and discriminates", report)
        self.assertIn("runs and discriminates", FORBIDDEN_PUBLIC_CLAIMS)
        self.assertIn("v0.2 (de-leaked)", report)
        self.assertIn("| inventory-deleaked-blind | legacy_unpinned | inventory.read_only | claude-opus-4-8 | haven-clean-install | v0.1 | false |", report)

    def test_write_scorecard_csv_writes_stable_headers(self) -> None:
        from agent_readiness.publishing import write_scorecard_csv

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "scorecard.csv"
            write_scorecard_csv([load_fixture("run_result_inventory_pass.json")], output)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(1, len(rows))
        self.assertEqual("inventory.read_only", rows[0]["task_id"])
        self.assertEqual("legacy_unpinned", rows[0]["run_class"])
        self.assertEqual("gpt-5", rows[0]["model"])
        self.assertEqual("haven-clean-install", rows[0]["substrate_id"])
        self.assertEqual("mechanical-pass", rows[0]["verification_quality"])

    def test_scorecard_order_is_canonical_by_run_id(self) -> None:
        from agent_readiness.publishing import render_scorecard_csv

        first = load_fixture("run_result_inventory_pass.json")
        first["run_id"] = "run-a"
        second = load_fixture("run_result_inventory_pass.json")
        second["run_id"] = "run-b"

        self.assertEqual(
            render_scorecard_csv([first, second]),
            render_scorecard_csv([second, first]),
        )

    def test_legacy_run_cannot_masquerade_as_fixed_regression_by_name(self) -> None:
        from agent_readiness.publishing import scorecard_rows

        run = load_fixture("run_result_inventory_pass.json")
        run["run_id"] = "independent-fixed-regression-pass"
        run["agent"]["name"] = "Independent fixed agent"

        row = scorecard_rows([run])[0]

        self.assertEqual("legacy_unpinned", row["run_class"])

    def test_measurement_metrics_provenance_and_tokens_are_visible(self) -> None:
        from agent_readiness.publishing import scorecard_rows

        run = load_fixture("run_result_inventory_pass.json")
        run["metrics"].update({
            "tokens_input": 1200,
            "tokens_output": 300,
        })

        row = scorecard_rows([run])[0]

        self.assertEqual("legacy_unpinned", row["run_class"])
        self.assertEqual("1200", row["tokens_input"])
        self.assertEqual("300", row["tokens_output"])
        self.assertEqual("operator_supplied_or_unknown", row["metrics_provenance"])

    def test_legacy_agent_label_cannot_claim_unretained_instrumentation(self) -> None:
        from agent_readiness.publishing import scorecard_rows

        run = load_fixture("run_result_inventory_pass.json")
        run["agent"]["name"] = "Legacy runner; metrics harness-instrumented"

        row = scorecard_rows([run])[0]

        self.assertNotIn("metrics harness-instrumented", row["agent_name"])
        self.assertIn("legacy metric provenance unverified", row["agent_name"])
        self.assertEqual("operator_supplied_or_unknown", row["metrics_provenance"])

    def test_run_result_validation_reports_missing_required_fields(self) -> None:
        from agent_readiness.publishing import validate_run_result

        errors = validate_run_result({"run_id": "missing-most-fields"})

        self.assertTrue(any("required properties" in error for error in errors))
        self.assertTrue(any("task_id" in error and "artifacts" in error for error in errors))

    def test_publication_audit_reports_missing_artifact_files(self) -> None:
        from agent_readiness.publishing import audit_publication_package

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_dir = base / "runs" / "haven-inventory-v0-codex-smoke"
            run_dir.mkdir(parents=True)
            run_result = load_fixture("run_result_inventory_pass.json")
            (run_dir / "run-result.json").write_text(json.dumps(run_result), encoding="utf-8")

            errors = audit_publication_package(base, [run_result])

        self.assertIn("missing artifact: runs/haven-inventory-v0-codex-smoke/answer.json", errors)

    def test_legacy_gate_rejects_string_boolean_and_integer_coercion(self) -> None:
        from agent_readiness.readiness import audit_readiness

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            run["evaluator"]["passed"] = "false"
            run["metrics"]["human_rescues"] = "0"

            report = audit_readiness(base, [run])

        self.assertFalse(report["public_evidence_package_ready"])
        self.assertTrue(
            any("expected integer" in error for error in report["publication_errors"])
        )
        run["metrics"]["human_rescues"] = 0
        from agent_readiness.publishing import validate_run_result
        self.assertTrue(
            any("expected boolean" in error for error in validate_run_result(run))
        )

    def test_duplicate_run_id_cannot_inflate_legacy_count(self) -> None:
        from agent_readiness.readiness import audit_readiness

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])

            report = audit_readiness(base, [run, copy.deepcopy(run)])

        self.assertFalse(report["legacy_example_count_gate_passed"])
        self.assertIn(
            f"duplicate run_id values: {run['run_id']}",
            report["publication_errors"],
        )

    def test_rehashed_evaluator_tamper_still_fails_recomputation(self) -> None:
        from agent_readiness.publishing import (
            audit_publication_package,
            write_package_manifest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            evaluator_path = base / run["artifacts"]["evaluator_json"]
            tampered = json.loads(evaluator_path.read_text(encoding="utf-8"))
            tampered["passed"] = False
            evaluator_path.write_text(json.dumps(tampered), encoding="utf-8")
            write_package_manifest(
                base,
                [run],
                base / "public/package-manifest.json",
            )

            errors = audit_publication_package(base, [run])

        self.assertIn(
            f"legacy run {run['run_id']} retained evaluator differs from recomputation",
            errors,
        )

    def test_run_artifact_path_cannot_escape_or_cross_run_boundary(self) -> None:
        from agent_readiness.publishing import audit_publication_package

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            run["artifacts"]["answer_json"] = "../outside.json"

            errors = audit_publication_package(base, [run])

        self.assertTrue(any("unsafe package path" in error for error in errors))
        self.assertTrue(any("not run-bound" in error for error in errors))

    def test_rehashed_generated_output_injection_is_recomputed_and_rejected(self) -> None:
        from agent_readiness.publishing import (
            audit_publication_package,
            write_package_manifest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            (base / "public/readiness.json").write_text(
                '{"improvement_ready": true}\n', encoding="utf-8"
            )
            (base / "public/scorecard.csv").write_text(
                "run_id,task_success\nfabricated,true\n", encoding="utf-8"
            )
            write_package_manifest(
                base,
                [run],
                base / "public/package-manifest.json",
            )

            errors = audit_publication_package(base, [run])

        self.assertIn("generated artifact drift: public/readiness.json", errors)
        self.assertIn("generated artifact drift: public/scorecard.csv", errors)

    def test_package_manifest_census_detects_unlisted_new_file(self) -> None:
        from agent_readiness.publishing import audit_publication_package

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            (base / "experiments/unlisted-source.json").write_text(
                "{}\n", encoding="utf-8"
            )

            errors = audit_publication_package(base, [run])

        self.assertIn("package manifest drift or incomplete file census", errors)

    def test_package_manifest_binds_external_canonical_registry_dependencies(self) -> None:
        from agent_readiness.publishing import (
            REPOSITORY_DEPENDENCIES,
            audit_publication_package,
        )

        source_root = FIXTURES.parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            base = repo / "agent_readiness"
            for relative in REPOSITORY_DEPENDENCIES:
                destination = repo / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((source_root / relative).read_bytes())
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            manifest = json.loads(
                (base / "public/package-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                REPOSITORY_DEPENDENCIES,
                [item["path"] for item in manifest["repository_dependencies"]],
            )
            (repo / "method/improvement-registry-v1.json").write_text(
                "{}\n", encoding="utf-8"
            )

            errors = audit_publication_package(base, [run])

        self.assertIn(
            "repository dependency hash mismatch: method/improvement-registry-v1.json",
            errors,
        )

    def test_package_manifest_requires_every_repository_dependency(self) -> None:
        from agent_readiness.publishing import REPOSITORY_DEPENDENCIES

        source_root = FIXTURES.parents[1]
        missing = REPOSITORY_DEPENDENCIES[-1]
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            base = repo / "agent_readiness"
            for relative in REPOSITORY_DEPENDENCIES[:-1]:
                destination = repo / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((source_root / relative).read_bytes())
            run = load_fixture("run_result_inventory_pass.json")

            with self.assertRaisesRegex(
                FileNotFoundError,
                f"required repository dependency is missing: {missing}",
            ):
                write_valid_test_package(base, [run])

    def test_package_manifest_rejects_repository_dependency_symlink_escape(self) -> None:
        from agent_readiness.publishing import REPOSITORY_DEPENDENCIES

        source_root = FIXTURES.parents[1]
        linked = REPOSITORY_DEPENDENCIES[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            base = repo / "agent_readiness"
            for relative in REPOSITORY_DEPENDENCIES[1:]:
                destination = repo / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((source_root / relative).read_bytes())
            outside = root / "outside.json"
            outside.write_bytes((source_root / linked).read_bytes())
            linked_path = repo / linked
            linked_path.parent.mkdir(parents=True, exist_ok=True)
            linked_path.symlink_to(outside)
            run = load_fixture("run_result_inventory_pass.json")

            with self.assertRaisesRegex(
                ValueError,
                f"unsafe repository dependency symlink path: '{linked}'",
            ):
                write_valid_test_package(base, [run])

    def test_package_alias_cannot_switch_canonical_repository_root_to_fixture_mode(self) -> None:
        from agent_readiness.publishing import REPOSITORY_DEPENDENCIES

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            base = repo / "agent_readiness"
            base.mkdir(parents=True)
            alias = Path(tmp) / "package-alias"
            alias.symlink_to(base, target_is_directory=True)
            run = load_fixture("run_result_inventory_pass.json")

            with self.assertRaisesRegex(
                FileNotFoundError,
                "required repository dependency is missing: "
                f"{REPOSITORY_DEPENDENCIES[0]}",
            ):
                write_valid_test_package(alias, [run])

    def test_malformed_package_manifest_fails_closed_without_crashing(self) -> None:
        from agent_readiness.publishing import audit_publication_package

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            (base / "public/package-manifest.json").write_text(
                '{"files": "not-an-array"}\n', encoding="utf-8"
            )

            errors = audit_publication_package(base, [run])

        self.assertIn(
            "invalid manifest shape: files must be an array of objects",
            errors,
        )

    def test_malformed_repository_dependency_census_fails_closed(self) -> None:
        from agent_readiness.publishing import audit_publication_package

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            (base / "public/package-manifest.json").write_text(
                '{"files": [], "repository_dependencies": null}\n',
                encoding="utf-8",
            )

            errors = audit_publication_package(base, [run])

        self.assertIn(
            "invalid manifest shape: repository_dependencies must be an array of objects",
            errors,
        )

    def test_package_manifest_contains_hashes_for_publish_assets(self) -> None:
        from agent_readiness.publishing import build_package_manifest

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_result = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run_result])
            (base / "run_capture.py").write_text("capture\n", encoding="utf-8")

            manifest = build_package_manifest(base, [run_result])
            second_manifest = build_package_manifest(base, [run_result])

        files = {entry["path"]: entry for entry in manifest["files"]}
        self.assertEqual(manifest, second_manifest)
        self.assertEqual(
            "drupal_agent_readiness_package_manifest.v1",
            manifest["schema_version"],
        )
        self.assertNotIn("generated_at", manifest)
        self.assertIn("public/scorecard.csv", files)
        self.assertIn("public/readiness.json", files)
        self.assertIn("run_capture.py", files)
        self.assertIn("runs/haven-inventory-v0-codex-smoke/answer.json", files)
        self.assertRegex(files["public/scorecard.csv"]["sha256"], r"^[0-9a-f]{64}$")

    def test_publication_audit_requires_readiness_json(self) -> None:
        from agent_readiness.publishing import audit_publication_package, write_package_manifest, write_report, write_scorecard_csv

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_result = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run_result])
            (base / "public" / "readiness.json").unlink()

            errors = audit_publication_package(base, [run_result])

        self.assertIn("missing publish asset: public/readiness.json", errors)

    def test_publication_audit_requires_canonical_experiment_registry(self) -> None:
        from agent_readiness.publishing import audit_publication_package

        with tempfile.TemporaryDirectory() as tmp:
            errors = audit_publication_package(Path(tmp), [])

        self.assertIn(
            "missing publish asset: experiments/published-experiments-v1.json",
            errors,
        )

    def test_publication_audit_rejects_invalid_registered_measurement(self) -> None:
        from agent_readiness.publishing import audit_publication_package

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            registry = base / "experiments" / "published-experiments-v1.json"
            registry.parent.mkdir()
            registry.write_text("{}\n", encoding="utf-8")
            bundle = {
                "experiments": [{
                    "experiment_id": "invalid-v1",
                    "adapter": "measurement_v1",
                    "audit": {"audit_valid": False},
                }],
            }
            with patch(
                "agent_readiness.publishing.load_published_experiments",
                return_value=bundle,
            ), patch(
                "agent_readiness.publishing.render_report",
                return_value="",
            ):
                errors = audit_publication_package(base, [])

        self.assertIn("registered measurement-v1 audit invalid: invalid-v1", errors)

    def test_distribution_mirror_audit_fails_on_missing_or_drifted_copy(self) -> None:
        from agent_readiness.publishing import (
            GENERATED_DISTRIBUTION_MIRRORS,
            audit_distribution_mirrors,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            mirror = root / "mirror"
            source.mkdir()
            mirror.mkdir()
            for filename in GENERATED_DISTRIBUTION_MIRRORS:
                (source / filename).write_text(f"{filename}\n", encoding="utf-8")
                (mirror / filename).write_text(f"{filename}\n", encoding="utf-8")
            (mirror / "readiness.json").write_text("drift\n", encoding="utf-8")
            (mirror / "experiments-v1.json").unlink()
            (mirror / "claims-ledger.md").write_text(
                "hand-edited claim drift\n", encoding="utf-8"
            )

            errors = audit_distribution_mirrors(source, mirror)

        self.assertIn(
            f"generated distribution mirror drift: {mirror / 'readiness.json'}",
            errors,
        )
        self.assertIn(
            f"generated distribution mirror missing: {mirror / 'experiments-v1.json'}",
            errors,
        )
        self.assertIn(
            f"generated distribution mirror drift: {mirror / 'claims-ledger.md'}",
            errors,
        )

    def test_publication_audit_catches_prompt_leaks_and_deprecated_claims(self) -> None:
        from agent_readiness.publishing import audit_publication_package, write_package_manifest, write_report, write_scorecard_csv

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_result = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run_result])
            (base / "public" / "finding-site-self-description-v0.md").write_text(
                "replicates across vendors\n",
                encoding="utf-8",
            )
            (base / "prompts" / "assess.alias_safety.fully_blind.md").write_text(
                "disabled views matter\n",
                encoding="utf-8",
            )
            (base / "prompts" / "assess.alias_safety.told.md").write_text("# prompt\n", encoding="utf-8")
            (base / "prompts" / "assess.alias_safety.candidates.public.json").write_text(
                '{"candidates": [{"path": "/x", "note": "leak"}]}\n',
                encoding="utf-8",
            )
            errors = audit_publication_package(base, [run_result])

        self.assertTrue(any(error.startswith("fully blind prompt leak:") for error in errors))
        self.assertTrue(any(error.startswith("fully blind candidate leak:") for error in errors))
        self.assertTrue(any(error.startswith("told prompt unlabeled:") for error in errors))
        self.assertTrue(any(error.startswith("deprecated public claim:") for error in errors))

    def test_semantic_claim_audit_rejects_affirmative_broad_claim_on_front_door(self) -> None:
        from agent_readiness.publishing import (
            audit_publication_package,
            write_package_manifest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            (base / "README.md").write_text(
                "# Release\n\nDrupal is agent-ready.\n",
                encoding="utf-8",
            )
            write_package_manifest(base, [run], base / "public/package-manifest.json")

            errors = audit_publication_package(base, [run])

        self.assertTrue(any(error.startswith("broad public claim:") for error in errors))

    def test_semantic_claim_audit_rejects_affirmative_readiness_paraphrases(self) -> None:
        from agent_readiness.publishing import _audit_public_claims

        claims = [
            "Drupal has achieved agent readiness.",
            "Drupal now provides complete agent readiness.",
            "This benchmark confirms Drupal is suitable for autonomous agents.",
            "The results validate Drupal as an agent-ready platform.",
            "Drupal has now attained full agent readiness.",
            "Drupal delivers comprehensive agent readiness.",
            "Drupal can now be considered an agent-ready platform.",
            "Drupal is fit for autonomous agent operations.",
            "The evidence certifies that Drupal is prepared for AI agents.",
            "These findings establish Drupal's agent readiness.",
            "Drupal's suitability for autonomous agents has been confirmed.",
            "Drupal offers a fully agent-ready experience.",
            "Agent readiness in Drupal is proven.",
            "Autonomous agents can reliably operate Drupal now.",
        ]
        for claim in claims:
            with self.subTest(claim=claim), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                base = root / "agent_readiness"
                (base / "public").mkdir(parents=True)
                (base / "README.md").write_text(f"{claim}\n", encoding="utf-8")
                errors: list[str] = []
                _audit_public_claims(base, root, errors)

                self.assertTrue(
                    any(error.startswith("broad public claim:") for error in errors),
                    errors,
                )

    def test_semantic_claim_audit_allows_explicit_negated_caveats(self) -> None:
        from agent_readiness.publishing import _audit_public_claims

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "agent_readiness"
            (base / "public").mkdir(parents=True)
            (base / "README.md").write_text(
                "This does not establish that Drupal is agent-ready.\n"
                "This does not establish that Drupal has achieved agent readiness.\n"
                "We do not claim Drupal now provides complete agent readiness.\n"
                "This benchmark does not confirm Drupal is suitable for autonomous agents.\n"
                "The results do not validate Drupal as an agent-ready platform.\n"
                "Avoid claiming Drupal delivers comprehensive agent readiness.\n",
                encoding="utf-8",
            )
            (base / "PUBLISHING.md").write_text(
                "## Claims to avoid\n\n"
                "- Drupal is broadly agent-ready.\n"
                "- Drupal has achieved agent readiness.\n"
                "- Drupal now provides complete agent readiness.\n"
                "- This benchmark confirms Drupal is suitable for autonomous agents.\n"
                "- The results validate Drupal as an agent-ready platform.\n",
                encoding="utf-8",
            )
            (base / "public/report.md").write_text(
                "| Evidence | This benchmark does not establish |\n"
                "| --- | --- |\n"
                "| bounded result | Drupal is broadly agent-ready. |\n",
                encoding="utf-8",
            )
            errors: list[str] = []
            _audit_public_claims(base, root, errors)

        self.assertEqual([], errors)

    def test_semantic_claim_audit_allows_benchmark_purpose_statement(self) -> None:
        from agent_readiness.publishing import _audit_public_claims

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "agent_readiness"
            (base / "public").mkdir(parents=True)
            (base / "README.md").write_text(
                "A test bench intended to measure how safely AI agents can operate Drupal.\n",
                encoding="utf-8",
            )
            errors: list[str] = []
            _audit_public_claims(base, root, errors)

        self.assertEqual([], errors)

    def test_semantic_claim_audit_includes_repository_review_surface(self) -> None:
        from agent_readiness.publishing import _audit_public_claims

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "agent_readiness"
            (base / "public").mkdir(parents=True)
            (base / "README.md").write_text("bounded package\n", encoding="utf-8")
            (base / "PUBLISHING.md").write_text("bounded checklist\n", encoding="utf-8")
            (root / "REVIEW-READINESS.md").write_text(
                "Benchmark verdict: Drupal is agent-ready.\n",
                encoding="utf-8",
            )
            errors: list[str] = []
            _audit_public_claims(base, root, errors)

        self.assertTrue(
            any("REVIEW-READINESS.md" in error for error in errors),
            errors,
        )

    def test_semantic_claim_audit_includes_linked_historical_synthesis(self) -> None:
        from agent_readiness.publishing import _audit_public_claims

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "agent_readiness"
            (base / "public").mkdir(parents=True)
            (base / "experiments").mkdir()
            (base / "README.md").write_text("bounded package\n", encoding="utf-8")
            (base / "PUBLISHING.md").write_text("bounded checklist\n", encoding="utf-8")
            (base / "experiments" / "alias-safety-SYNTHESIS.md").write_text(
                "Drupal has achieved agent readiness.\n",
                encoding="utf-8",
            )
            evidence = root / "evidence" / "experiments"
            evidence.mkdir(parents=True)
            (evidence / "alias-safety-SYNTHESIS.md").write_text(
                "Drupal now provides complete agent readiness.\n",
                encoding="utf-8",
            )
            errors: list[str] = []
            _audit_public_claims(base, root, errors)

        self.assertTrue(
            any("agent_readiness/experiments/alias-safety-SYNTHESIS.md" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("evidence/experiments/alias-safety-SYNTHESIS.md" in error for error in errors),
            errors,
        )

    def test_fully_blind_candidate_schema_rejects_root_leaks_types_duplicates_and_noncanonical_paths(self) -> None:
        from agent_readiness.publishing import _audit_prompt_leaks

        invalid_payloads = [
            {"candidates": [{"path": "/x"}], "ground_truth": {"/x": True}},
            {"candidates": [{"path": "/x", "safe": True}]},
            {"candidates": [{"path": 7}]},
            {"candidates": [{"path": "/x"}, {"path": "/x"}]},
            {"candidates": [{"path": "/x/../secret"}]},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                path = base / "prompts/assess.alias_safety.candidates.public.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(payload), encoding="utf-8")
                errors: list[str] = []
                _audit_prompt_leaks(base, errors)
                self.assertTrue(
                    any(
                        error.startswith("fully blind candidate leak:")
                        or error.startswith("fully blind candidate schema:")
                        for error in errors
                    ),
                    errors,
                )

    def test_publication_requires_packaged_executed_evaluator_source(self) -> None:
        from agent_readiness.publishing import audit_publication_package

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            (base / "evaluators/inventory.py").unlink()

            errors = audit_publication_package(base, [run])

        self.assertIn("executed source closure missing: evaluators/inventory.py", errors)
        self.assertIn("missing publish asset: evaluators/inventory.py", errors)

    def test_rehashed_packaged_evaluator_substitution_cannot_differ_from_executed_source(self) -> None:
        from agent_readiness.publishing import (
            audit_publication_package,
            write_package_manifest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            evaluator = base / "evaluators/inventory.py"
            evaluator.write_text(
                evaluator.read_text(encoding="utf-8") + "\n# substituted source\n",
                encoding="utf-8",
            )
            write_package_manifest(base, [run], base / "public/package-manifest.json")

            errors = audit_publication_package(base, [run])

        self.assertIn(
            "executed source differs from auditor source: evaluators/inventory.py",
            errors,
        )

    def test_publication_rejects_omitted_retained_run_even_when_manifest_hashes_it(self) -> None:
        from agent_readiness.publishing import (
            audit_publication_package,
            write_package_manifest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            omitted = copy.deepcopy(run)
            omitted["run_id"] = "omitted-failure"
            omitted_path = base / "runs/omitted-failure/run-result.json"
            omitted_path.parent.mkdir(parents=True)
            omitted_path.write_text(json.dumps(omitted), encoding="utf-8")
            write_package_manifest(base, [run], base / "public/package-manifest.json")

            errors = audit_publication_package(base, [run])

        self.assertIn(
            "retained run result omitted from supplied census: runs/omitted-failure/run-result.json",
            errors,
        )

    def test_publication_rejects_executable_bytecode_cache_in_package(self) -> None:
        from agent_readiness.publishing import audit_publication_package

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run = load_fixture("run_result_inventory_pass.json")
            write_valid_test_package(base, [run])
            source = base / "payload.py"
            malicious = "VALUE = 'MALICIOUS'\n"
            benign = "VALUE = 'BENIGN___'\n"
            self.assertEqual(len(malicious), len(benign))
            source.write_text(malicious, encoding="utf-8")
            timestamp = 1_700_000_000
            os.utime(source, (timestamp, timestamp))
            cache = (
                base
                / "__pycache__"
                / f"payload.{sys.implementation.cache_tag}.pyc"
            )
            cache.parent.mkdir()
            py_compile.compile(str(source), cfile=str(cache), doraise=True)
            source.write_text(benign, encoding="utf-8")
            os.utime(source, (timestamp, timestamp))

            environment = dict(os.environ)
            environment.pop("PYTHONPYCACHEPREFIX", None)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            executed = subprocess.run(
                [sys.executable, "-c", "import payload; print(payload.VALUE)"],
                cwd=base,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual("MALICIOUS", executed.stdout.strip(), executed.stderr)

            errors = audit_publication_package(base, [run])

        self.assertIn(
            f"forbidden executable cache in package: {cache.relative_to(base).as_posix()}",
            errors,
        )
        self.assertTrue(any("package manifest cannot be derived" in error for error in errors))

    def test_distribution_mirror_audit_and_writer_reject_symlinks(self) -> None:
        from agent_readiness.publishing import (
            GENERATED_DISTRIBUTION_MIRRORS,
            audit_distribution_mirrors,
            write_distribution_mirrors,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            mirror = root / "mirror"
            source.mkdir()
            mirror.mkdir()
            for filename in GENERATED_DISTRIBUTION_MIRRORS:
                (source / filename).write_text(f"{filename}\n", encoding="utf-8")
                (mirror / filename).write_text(f"{filename}\n", encoding="utf-8")
            (mirror / "readiness.json").unlink()
            (mirror / "readiness.json").symlink_to(source / "readiness.json")

            errors = audit_distribution_mirrors(source, mirror)
            with self.assertRaisesRegex(ValueError, "is a symlink"):
                write_distribution_mirrors(source, mirror)

        self.assertIn(
            f"generated distribution mirror is a symlink: {mirror / 'readiness.json'}",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
