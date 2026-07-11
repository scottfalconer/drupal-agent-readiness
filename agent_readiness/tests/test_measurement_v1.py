import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_readiness.measurement_v1 import (
    EXPERIMENT_SCHEMA_PATH,
    RUN_SCHEMA_PATH,
    GitRegistrationAnchor,
    audit_measurement_v1,
    canonical_json_bytes,
    canonical_sha256,
    file_sha256,
    runtime_home_layout_document_valid,
    runtime_home_layout_semantically_valid,
    validate_experiment_manifest,
    validate_run_result,
    verify_git_registration_anchor,
)


def declared_hash(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def fake_runtime_layout_document(
    system_manifest: dict | None = None,
    *,
    auth_path: str = "/Users/fixture/.codex/auth.json",
) -> dict:
    entries = [
        {
            "path": "auth.json",
            "kind": "symlink",
            "mode": "0o755",
            "target_role": "credential_reference",
            "target_path_sha256": declared_hash(auth_path),
        },
        {
            "path": "frontier-canary.config.toml",
            "kind": "file",
            "mode": "0o600",
        },
        {
            "path": "frontier-canary-sentinel",
            "kind": "file",
            "mode": "0o600",
        },
    ]
    for item in (system_manifest or {}).get("directories", []):
        entries.append(
            {"path": item["path"], "kind": "directory", "mode": item["mode"]}
        )
    for item in (system_manifest or {}).get("files", []):
        entries.append(
            {"path": item["path"], "kind": "file", "mode": item["mode"]}
        )
    body = {
        "schema_version": "drupal_agent_readiness.runtime_home_layout.v1",
        "entries": sorted(entries, key=lambda item: item["path"]),
    }
    return {**body, "tree_sha256": canonical_sha256(body)}


def fake_process_containment_policy() -> dict:
    profile = "(version 1)\n(allow default)\n(deny process-fork)\n"
    return {
        "kind": "darwin_seatbelt_process_fork_denied",
        "sandbox_binary": "/usr/bin/sandbox-exec",
        "sandbox_sha256": declared_hash("sandbox-exec"),
        "profile": profile,
        "profile_sha256": "sha256:" + hashlib.sha256(profile.encode()).hexdigest(),
        "child_process_creation": "denied_by_seatbelt_process_fork",
        "claim_boundary": "trusted-host containment test fixture",
        "sandbox_platform": {
            "sys_platform": "darwin",
            "sysname": "Darwin",
            "release": "test-release",
            "version": "test-version",
            "machine": "test-machine",
        },
    }


def issue_codes(issues) -> set[str]:
    return {issue.code for issue in issues}


class MeasurementV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = self._manifest()
        self.runs = []
        for index in range(1, 25):
            pair_id = f"pair-{index:03d}"
            unit_id = f"fixture-reset-{index:03d}"
            pre_first = index % 2 == 1
            self.runs.extend([
                self._run(
                    f"{pair_id}-pre",
                    "pre",
                    index,
                    pair_id,
                    unit_id,
                    1 if pre_first else 2,
                    11 if pre_first else 12,
                    0,
                ),
                self._run(
                    f"{pair_id}-post",
                    "post",
                    index,
                    pair_id,
                    unit_id,
                    2 if pre_first else 1,
                    12 if pre_first else 11,
                    1,
                ),
            ])
        self.anchor = self._commit_manifest(self.manifest)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_schemas_are_valid_json_and_identify_distinct_documents(self) -> None:
        experiment_schema = json.loads(EXPERIMENT_SCHEMA_PATH.read_text(encoding="utf-8"))
        run_schema = json.loads(RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            "Drupal Agent Readiness Benchmark Experiment v1", experiment_schema["title"]
        )
        self.assertEqual("Drupal Agent Readiness Benchmark Run v1", run_schema["title"])

    def test_complete_semantic_census_demonstrates_registered_improvement(self) -> None:
        self.assertEqual([], validate_experiment_manifest(self.manifest))
        for run in self.runs:
            self.assertEqual([], validate_run_result(run, self.manifest))

        report = self._audit()

        self.assertTrue(report["contract_valid"], report["errors"])
        self.assertTrue(report["audit_valid"], report["errors"])
        self.assertTrue(report["registration_anchor"]["verified"], report["errors"])
        self.assertTrue(report["artifacts_verified"], report["errors"])
        self.assertTrue(report["artifact_semantics_verified"], report["errors"])
        self.assertTrue(report["attempt_census"]["complete"], report["errors"])
        self.assertTrue(report["evidence_complete"], report["errors"])
        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertTrue(report["registered_effect_rule_met"], report["errors"])
        self.assertNotIn("claim_ready", report)
        self.assertEqual(24, report["denominator"]["observed"])
        self.assertEqual(1.0, report["analysis"]["estimate"])
        self.assertEqual(24, report["analysis"]["n"])
        self.assertAlmostEqual(
            0.500355770443109,
            report["analysis"]["confidence"]["favorable_direction_lower_bound"],
        )
        self.assertEqual("registered_minimum_met", report["decision"]["reason"])

    def test_improvement_is_false_without_external_registration_anchor(self) -> None:
        report = audit_measurement_v1(
            self.manifest, self.runs, artifact_root=self.root
        )
        self.assertTrue(report["contract_valid"])
        self.assertFalse(report["registration_anchor"]["verified"])
        self.assertFalse(report["evidence_complete"])
        self.assertFalse(report["estimate_reportable"])
        self.assertFalse(report["registered_effect_rule_met"])
        self.assertNotIn("claim_ready", report)
        self.assertIn(
            "registration_anchor_not_verified",
            {warning["code"] for warning in report["warnings"]},
        )

    def test_git_anchor_proves_exact_canonical_bytes_and_reports_timestamp_limits(self) -> None:
        report = verify_git_registration_anchor(self.manifest, self.runs, self.anchor)
        self.assertTrue(report["verified"], report["errors"])
        self.assertEqual(self.anchor.commit, report["resolved_commit"])
        self.assertTrue(report["timestamp_precedes_runs"])
        self.assertTrue(
            any("backdated" in limitation for limitation in report["limitations"])
        )
        self.assertTrue(
            any("third-party custody" in limitation for limitation in report["limitations"])
        )

    def test_git_anchor_rejects_manifest_changed_after_commit(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["claim_plan"]["minimum_favorable_effect"] = 0.75
        report = verify_git_registration_anchor(manifest, self.runs, self.anchor)
        self.assertFalse(report["verified"])
        self.assertIn(
            "registration_manifest_bytes_mismatch",
            {error["code"] for error in report["errors"]},
        )

    def test_git_anchor_ignores_local_replace_objects(self) -> None:
        forged = copy.deepcopy(self.manifest)
        forged["claim_plan"]["minimum_favorable_effect"] = 0.75
        manifest_path = self.anchor.repo_path / self.anchor.manifest_path
        manifest_path.write_bytes(canonical_json_bytes(forged))
        subprocess.run(
            ["git", "-C", str(self.anchor.repo_path), "add", self.anchor.manifest_path],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.anchor.repo_path), "commit", "-q", "-m", "Forged manifest"],
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_DATE": "2026-07-09T09:31:00+00:00",
                "GIT_COMMITTER_DATE": "2026-07-09T09:31:00+00:00",
            },
        )
        forged_commit = subprocess.run(
            ["git", "-C", str(self.anchor.repo_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            [
                "git",
                "-C",
                str(self.anchor.repo_path),
                "replace",
                self.anchor.commit,
                forged_commit,
            ],
            check=True,
        )

        report = verify_git_registration_anchor(forged, self.runs, self.anchor)

        self.assertFalse(report["verified"])
        self.assertIn(
            "registration_manifest_bytes_mismatch",
            {error["code"] for error in report["errors"]},
        )

    def test_git_anchor_ignores_path_git_shim_and_reports_binary_pin(self) -> None:
        shim_root = self.root / "path-shim"
        shim_root.mkdir()
        shim = shim_root / "git"
        shim.write_text("#!/bin/sh\nprintf 'forged-git-output\\n'\n", encoding="utf-8")
        shim.chmod(0o755)

        with patch.dict(
            os.environ,
            {"PATH": f"{shim_root}:{os.environ.get('PATH', '')}"},
        ):
            report = verify_git_registration_anchor(self.manifest, self.runs, self.anchor)

        self.assertTrue(report["verified"], report["errors"])
        self.assertNotEqual(str(shim), report["audit_host"]["git_path"])
        self.assertRegex(report["audit_host"]["git_sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(
            any("audit host" in item for item in report["limitations"])
        )

    def test_git_anchor_rejects_mutable_ref_or_short_hash(self) -> None:
        anchor = GitRegistrationAnchor(
            self.anchor.repo_path, "HEAD", self.anchor.manifest_path
        )
        report = verify_git_registration_anchor(self.manifest, self.runs, anchor)
        self.assertFalse(report["verified"])
        self.assertIn(
            "mutable_or_short_git_anchor",
            {error["code"] for error in report["errors"]},
        )

    def test_git_anchor_must_be_reachable_from_current_head(self) -> None:
        anchor = self._commit_manifest(self.manifest, repo_name="dangling-anchor-repo")
        subprocess.run(
            ["git", "-C", str(anchor.repo_path), "checkout", "-q", "--orphan", "unrelated"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(anchor.repo_path), "commit", "-q", "-m", "Unrelated root"],
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_DATE": "2026-07-09T09:45:00+00:00",
                "GIT_COMMITTER_DATE": "2026-07-09T09:45:00+00:00",
            },
        )
        report = verify_git_registration_anchor(self.manifest, self.runs, anchor)
        self.assertFalse(report["verified"])
        self.assertIn(
            "git_anchor_not_reachable",
            {error["code"] for error in report["errors"]},
        )

    def test_git_anchor_committer_time_must_precede_runs(self) -> None:
        anchor = self._commit_manifest(
            self.manifest,
            repo_name="late-anchor-repo",
            commit_date="2026-07-09T15:00:00+00:00",
        )
        report = verify_git_registration_anchor(self.manifest, self.runs, anchor)
        self.assertFalse(report["verified"])
        self.assertIn(
            "registration_anchor_does_not_predate_runs",
            {error["code"] for error in report["errors"]},
        )

    def test_promotion_boolean_is_derived_not_accepted_as_input(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["claim_ready"] = True
        self.assertIn(
            "schema_additional_property",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_missing_exact_pin_is_rejected(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        del manifest["reference_agent_stack"]["model"]["snapshot"]
        self.assertIn("schema_required", issue_codes(validate_experiment_manifest(manifest)))

    def test_manifest_artifact_pins_cannot_be_empty(self) -> None:
        for selector in (
            lambda manifest: manifest["claim_plan"]["sample_size_rationale"],
            lambda manifest: manifest["evaluation"]["evaluator"]["artifact"],
        ):
            manifest = copy.deepcopy(self.manifest)
            pin = selector(manifest)
            path = self.root / pin["uri"]
            path.write_bytes(b"")
            pin["sha256"] = file_sha256(path)
            pin["byte_size"] = 0

            codes = issue_codes(validate_experiment_manifest(manifest))

            self.assertIn("schema_minimum", codes)

    def test_machine_readable_manifest_pin_must_be_canonical_json(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        pin = manifest["reference_agent_stack"]["model"]["inference_parameters"]
        path = self.root / pin["uri"]
        path.write_text('{\n  "temperature": 0\n}\n', encoding="utf-8")
        pin["sha256"] = file_sha256(path)
        pin["byte_size"] = path.stat().st_size

        report = audit_measurement_v1(
            manifest,
            self.runs,
            artifact_root=self.root,
        )

        self.assertIn(
            "pinned_json_not_canonical",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["evidence_complete"])

    def test_mutable_version_label_is_rejected(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["reference_agent_stack"]["model"]["snapshot"] = "gpt-5-latest"
        self.assertIn(
            "mutable_pin_label", issue_codes(validate_experiment_manifest(manifest))
        )

    def test_mixed_lanes_cannot_share_analysis(self) -> None:
        runs = copy.deepcopy(self.runs)
        runs[-1]["lane"] = "frontier_observation"
        report = audit_measurement_v1(self.manifest, runs)
        codes = {error["code"] for error in report["errors"]}
        self.assertIn("mixed_measurement_lane", codes)
        self.assertIn("mixed_measurement_lanes", codes)
        self.assertFalse(report["registered_effect_rule_met"])

    def test_frontier_observation_is_reportable_but_cannot_prove_improvement(self) -> None:
        manifest, runs = self._frontier_fixture()
        anchor = self._commit_manifest(manifest, repo_name="frontier-anchor-repo")
        self.assertEqual([], validate_experiment_manifest(manifest))
        for run in runs:
            self.assertEqual([], validate_run_result(run, manifest))
        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )
        self.assertTrue(report["evidence_complete"], report["errors"])
        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertFalse(report["registered_effect_rule_met"])
        self.assertFalse(report["analysis"]["confidence"]["applicable"])
        self.assertIsNone(report["analysis"]["confidence"]["interval"])
        self.assertEqual(
            "noncomparative_analysis_cannot_meet_effect_rule",
            report["decision"]["reason"],
        )

    def test_self_reported_costs_are_rejected(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["costs"]["source"] = "agent_self_report"
        self.assertIn(
            "schema_enum", issue_codes(validate_run_result(run, self.manifest))
        )

    def test_metric_without_denominator_is_rejected(self) -> None:
        run = copy.deepcopy(self.runs[0])
        del run["outcomes"]["metrics"][0]["denominator"]
        self.assertIn(
            "schema_required", issue_codes(validate_run_result(run, self.manifest))
        )

    def test_post_hoc_exclusion_is_rejected(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["validity"].update(
            {
                "status": "excluded",
                "exclusion_code": "infrastructure_failure",
                "decided_at": "2026-07-09T11:00:13Z",
            }
        )
        self.assertIn(
            "post_hoc_validity_decision",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_unregistered_replacement_slot_is_rejected(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["attempt"]["roster_slot_id"] = "replacement-slot"
        self.assertIn(
            "unregistered_roster_slot",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_roster_metadata_cannot_be_relabelled(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["attempt"]["unit_id"] = "convenient-replacement-unit"
        self.assertIn(
            "roster_slot_mismatch",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_duplicate_excluded_attempt_is_rejected(self) -> None:
        duplicate = copy.deepcopy(self.runs[0])
        duplicate["run_id"] = "duplicate-excluded"
        duplicate["validity"]["status"] = "excluded"
        duplicate["validity"]["exclusion_code"] = "infrastructure_failure"
        runs = [*self.runs, duplicate]
        report = audit_measurement_v1(self.manifest, runs)
        self.assertIn(
            "duplicate_roster_execution",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["attempt_census"]["complete"])
        self.assertFalse(report["registered_effect_rule_met"])

    def test_incomplete_attempt_census_is_not_evidence_complete(self) -> None:
        report = audit_measurement_v1(
            self.manifest,
            self.runs[:-1],
            artifact_root=self.root,
            registration_anchor=self.anchor,
        )
        self.assertFalse(report["attempt_census"]["complete"])
        self.assertFalse(report["evidence_complete"])
        self.assertFalse(report["estimate_reportable"])
        self.assertIn(
            "incomplete_attempt_census",
            {warning["code"] for warning in report["warnings"]},
        )

    def test_one_sided_pair_exclusion_is_rejected_as_cherry_picking(self) -> None:
        runs = copy.deepcopy(self.runs)
        runs[0]["validity"]["status"] = "excluded"
        runs[0]["validity"]["exclusion_code"] = "infrastructure_failure"
        report = audit_measurement_v1(self.manifest, runs)
        self.assertIn("unpaired_inclusion", {error["code"] for error in report["errors"]})
        self.assertFalse(report["registered_effect_rule_met"])

    def test_preregistered_exclusion_blocks_estimate_even_with_complete_census(self) -> None:
        runs = copy.deepcopy(self.runs)
        for run in runs[:2]:
            run["validity"]["status"] = "excluded"
            run["validity"]["exclusion_code"] = "infrastructure_failure"
        report = audit_measurement_v1(self.manifest, runs)
        self.assertTrue(report["attempt_census"]["complete"])
        self.assertEqual(2, len(report["attempt_census"]["excluded_slots"]))
        self.assertFalse(report["estimate_reportable"])
        self.assertFalse(report["registered_effect_rule_met"])

    def test_missing_starting_or_final_state_artifact_is_rejected(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["artifacts"] = [
            artifact for artifact in run["artifacts"] if artifact["kind"] != "starting_state"
        ]
        codes = issue_codes(validate_run_result(run, self.manifest))
        self.assertTrue(
            {"schema_min_items", "missing_evidence_artifact"} & codes,
            codes,
        )

    def test_required_evidence_artifacts_cannot_be_empty(self) -> None:
        run = copy.deepcopy(self.runs[0])
        transcript = self._artifact(run, "transcript")
        transcript["byte_size"] = 0

        codes = issue_codes(validate_run_result(run, self.manifest))

        self.assertIn("schema_minimum", codes)

    def test_behavior_source_must_match_source_artifact_kind(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["behavior_events"][0]["source_artifact_id"] = self._artifact(
            run, "behavior_trace"
        )["artifact_id"]
        self._rewrite_semantic_artifact(
            run,
            "behavior_trace",
            {"events": run["behavior_events"], "summary": run["behavior_summary"]},
        )

        codes = issue_codes(validate_run_result(run, self.manifest))

        self.assertIn("wrong_artifact_kind", codes)

    def test_same_bytes_cannot_serve_starting_and_final_state(self) -> None:
        run = copy.deepcopy(self.runs[0])
        starting = self._artifact(run, "starting_state")
        final = self._artifact(run, "final_state")
        copied_path = self.root / "runs" / "aliased-copy.json"
        copied_path.write_bytes((self.root / starting["uri"]).read_bytes())
        final["uri"] = str(copied_path.relative_to(self.root))
        final["sha256"] = starting["sha256"]
        final["byte_size"] = starting["byte_size"]
        self.assertIn(
            "artifact_kind_aliasing",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_cost_trace_bytes_can_match_hash_but_fail_semantics(self) -> None:
        runs = copy.deepcopy(self.runs)
        self._rewrite_semantic_artifact(runs[0], "cost_trace", {"wall_time_ms": 1})
        self._refresh_receipts(runs[0])
        report = self._audit(runs)
        self.assertTrue(report["artifacts_verified"])
        self.assertFalse(report["artifact_semantics_verified"])
        self.assertIn(
            "semantic_artifact_mismatch",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["registered_effect_rule_met"])

    def test_semantic_trace_must_use_canonical_json_bytes(self) -> None:
        runs = copy.deepcopy(self.runs)
        artifact = self._artifact(runs[0], "behavior_trace")
        document = {
            "events": runs[0]["behavior_events"],
            "summary": runs[0]["behavior_summary"],
        }
        path = self.root / artifact["uri"]
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        artifact["sha256"] = file_sha256(path)
        artifact["byte_size"] = path.stat().st_size
        self._refresh_receipts(runs[0])
        report = self._audit(runs)
        self.assertIn(
            "pinned_json_not_canonical",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["artifact_semantics_verified"])

    def test_starting_state_attestation_must_match_registered_arm(self) -> None:
        runs = copy.deepcopy(self.runs)
        wrong = {
            "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
            "run_id": runs[0]["run_id"],
            "moment": "starting",
            "arm_id": "site-description",
            "drupal_state": self.manifest["arms"][1]["drupal_state"],
        }
        self._rewrite_semantic_artifact(runs[0], "starting_state", wrong)
        report = self._audit(runs)
        self.assertIn(
            "execution_artifact_hash_mismatch",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["evidence_complete"])

    def test_evaluator_and_validity_artifacts_must_match_run_fields(self) -> None:
        runs = copy.deepcopy(self.runs)
        self._rewrite_semantic_artifact(
            runs[1], "evaluator_output", {"evaluator_passed": False}
        )
        self._rewrite_semantic_artifact(
            runs[2], "validity_decision", {"status": "included"}
        )
        self._refresh_receipts(runs[1])
        self._refresh_receipts(runs[2])
        report = self._audit(runs)
        self.assertEqual(
            2,
            sum(
                error["code"] == "semantic_artifact_mismatch"
                for error in report["errors"]
            ),
        )

    def test_evaluator_verdict_cannot_contradict_registered_success_metric(self) -> None:
        runs = copy.deepcopy(self.runs)
        for run in runs:
            run["outcomes"]["evaluator_passed"] = False
            self._rewrite_semantic_artifact(
                run,
                "evaluator_output",
                run["outcomes"],
            )

        report = self._audit(runs)
        codes = {error["code"] for error in report["errors"]}

        self.assertIn("evaluator_verdict_metric_mismatch", codes)
        self.assertFalse(report["contract_valid"])
        self.assertFalse(report["estimate_reportable"])
        self.assertFalse(report["registered_effect_rule_met"])

    def test_binary_verdict_metric_is_exact_and_evaluator_sourced(self) -> None:
        run = copy.deepcopy(self.runs[1])
        verdict = run["outcomes"]["metrics"][0]
        verdict.update({
            "numerator": 0.5,
            "value": 0.5,
            "source_artifact_id": self._artifact(run, "final_state")["artifact_id"],
        })
        self._rewrite_semantic_artifact(run, "evaluator_output", run["outcomes"])

        codes = issue_codes(validate_run_result(run, self.manifest))

        self.assertIn("nonbinary_metric_value", codes)
        self.assertIn("verdict_metric_wrong_source", codes)

    def test_behavior_and_final_state_artifacts_must_match_run_fields(self) -> None:
        behavior_runs = copy.deepcopy(self.runs)
        self._rewrite_semantic_artifact(
            behavior_runs[0],
            "behavior_trace",
            {"events": [], "summary": behavior_runs[0]["behavior_summary"]},
        )
        self._refresh_receipts(behavior_runs[0])
        behavior_report = self._audit(behavior_runs)
        self.assertIn(
            "semantic_artifact_mismatch",
            {error["code"] for error in behavior_report["errors"]},
        )

        final_runs = copy.deepcopy(self.runs)
        self._rewrite_semantic_artifact(
            final_runs[1],
            "final_state",
            {
                "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
                "run_id": final_runs[1]["run_id"],
                "moment": "final",
                "arm_id": "baseline",
                "drupal_state": self.manifest["arms"][0]["drupal_state"],
            },
        )
        final_report = self._audit(final_runs)
        codes = {error["code"] for error in final_report["errors"]}
        self.assertIn("execution_artifact_hash_mismatch", codes)
        self.assertIn("evaluator_input_binding_mismatch", codes)

    def test_task_lifecycle_phases_are_required_and_chronological(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["behavior_events"][1]["started_at"] = "2026-07-09T11:00:01Z"
        self.assertIn(
            "overlapping_behavior_events",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_plan_clarify_and_handoff_are_canonical_manifest_stages(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["task"]["lifecycle_stages"] = [
            "understand",
            "plan_clarify",
            "act",
            "verify",
            "handoff",
        ]
        codes = issue_codes(validate_experiment_manifest(manifest))
        self.assertNotIn("schema_enum", codes)
        self.assertNotIn("noncanonical_lifecycle_order", codes)

        manifest["task"]["lifecycle_stages"] = [
            "understand",
            "act",
            "plan_clarify",
            "verify",
            "handoff",
        ]
        self.assertIn(
            "noncanonical_lifecycle_order",
            issue_codes(validate_experiment_manifest(manifest)),
        )

    def test_behavior_event_result_and_failure_code_are_coherent(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["behavior_events"][0]["result"] = "failure"
        self.assertIn(
            "missing_behavior_failure_code",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_behavior_summary_is_derived_from_events(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["behavior_summary"]["failure_count"] = 4
        self.assertIn(
            "behavior_summary_mismatch",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_undeclared_lifecycle_phase_is_rejected(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["behavior_events"][0]["phase"] = "connect"
        self.assertIn(
            "undeclared_behavior_phase",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_causal_claims_fail_closed_in_v1(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["claim_plan"]["claim_class"] = "causal"
        self.assertIn(
            "causal_claim_not_supported_v1",
            issue_codes(validate_experiment_manifest(manifest)),
        )

    def test_comparative_claim_requires_two_pairs(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["execution_plan"]["attempt_roster"] = manifest["execution_plan"][
            "attempt_roster"
        ][:1]
        manifest["execution_plan"]["stopping_rule"]["required_resolved_slots"] = 2
        manifest["claim_plan"]["planned_denominator"] = 1
        self.assertIn(
            "comparative_sample_too_small",
            issue_codes(validate_experiment_manifest(manifest)),
        )

    def test_zero_effect_cannot_be_registered_as_improvement(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["claim_plan"]["minimum_favorable_effect"] = 0
        self.assertIn(
            "nonpositive_improvement_threshold",
            issue_codes(validate_experiment_manifest(manifest)),
        )

    def test_free_text_estimand_is_rejected(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["claim_plan"]["estimand"] = "whatever looks persuasive"
        self.assertIn(
            "schema_enum", issue_codes(validate_experiment_manifest(manifest))
        )

    def test_sample_size_rationale_is_a_required_content_pin(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        del manifest["claim_plan"]["sample_size_rationale"]
        self.assertIn(
            "schema_required", issue_codes(validate_experiment_manifest(manifest))
        )

    def test_reportable_null_does_not_demonstrate_improvement(self) -> None:
        runs = copy.deepcopy(self.runs)
        self._set_success(runs[1], 0)
        self._set_success(runs[3], 0)
        report = self._audit(runs)
        self.assertTrue(report["evidence_complete"], report["errors"])
        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertFalse(report["registered_effect_rule_met"])
        self.assertEqual("registered_minimum_not_met", report["decision"]["reason"])

    def test_missing_delivered_prompt_or_receipt_is_rejected(self) -> None:
        for missing_kind in ("prompt", "prompt_receipt", "execution_receipt"):
            with self.subTest(missing_kind=missing_kind):
                run = copy.deepcopy(self.runs[0])
                run["artifacts"] = [
                    artifact
                    for artifact in run["artifacts"]
                    if artifact["kind"] != missing_kind
                ]
                codes = issue_codes(validate_run_result(run, self.manifest))
                self.assertTrue(
                    {"schema_min_items", "missing_evidence_artifact"} & codes,
                    codes,
                )

    def test_agent_visible_prompt_cannot_alias_withheld_ground_truth(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["task"]["ground_truth"] = copy.deepcopy(manifest["task"]["prompt"])

        codes = issue_codes(validate_experiment_manifest(manifest))

        self.assertIn("agent_visible_withheld_artifact_alias", codes)
        self.assertIn("evidence_role_semantics_mismatch", codes)

    def test_output_schema_role_must_be_agent_visible(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        output_schema = manifest["reference_agent_stack"]["output_schema"]
        output_schema["visibility"] = "withheld_from_agent"
        output_schema["audience"] = ["harness", "evaluator", "auditor"]

        codes = issue_codes(validate_experiment_manifest(manifest))

        self.assertIn("evidence_role_semantics_mismatch", codes)

    def test_role_artifacts_are_hash_and_path_verified(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["task"]["prompt"]["uri"] = "../escaped-prompt.md"
        self.assertIn(
            "unsafe_artifact_uri",
            issue_codes(validate_experiment_manifest(manifest)),
        )

        prompt_path = self.root / self.manifest["task"]["prompt"]["uri"]
        prompt_path.write_text("tampered prompt\n", encoding="utf-8")
        report = self._audit()
        self.assertIn(
            "artifact_hash_mismatch",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["evidence_complete"])

    def test_rendered_prompt_cannot_inject_unregistered_ground_truth(self) -> None:
        runs = copy.deepcopy(self.runs)
        run = runs[0]
        prompt = self._artifact(run, "prompt")
        path = self.root / prompt["uri"]
        path.write_bytes(canonical_json_bytes({
            "schema_version": "drupal_agent_readiness.prompt_envelope.v1",
            "task_prompt": "registered task",
            "system_prompt": "registered system",
            "render_inputs": {"ground_truth": "leaked"},
        }))
        prompt["sha256"] = file_sha256(path)
        prompt["byte_size"] = path.stat().st_size
        run["prompt_delivery"]["rendered_prompt_sha256"] = prompt["sha256"]
        self._refresh_receipts(run)

        report = self._audit(runs)

        self.assertIn(
            "prompt_composition_mismatch",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["evidence_complete"])

    def test_answer_mutation_invalidates_evaluator_and_execution_receipts(self) -> None:
        runs = copy.deepcopy(self.runs)
        answer = self._artifact(runs[0], "answer")
        path = self.root / answer["uri"]
        path.write_bytes(canonical_json_bytes({"answer": "known-wrong"}))
        answer["sha256"] = file_sha256(path)
        answer["byte_size"] = path.stat().st_size

        report = self._audit(runs)
        codes = {error["code"] for error in report["errors"]}

        self.assertIn("execution_artifact_hash_mismatch", codes)
        self.assertIn("evaluator_input_binding_mismatch", codes)
        self.assertFalse(report["evidence_complete"])

    def test_evaluator_receipt_is_required_and_must_record_successful_exit(self) -> None:
        missing = copy.deepcopy(self.runs[0])
        missing["artifacts"] = [
            artifact
            for artifact in missing["artifacts"]
            if artifact["kind"] != "evaluator_receipt"
        ]
        missing_codes = issue_codes(validate_run_result(missing, self.manifest))
        self.assertTrue(
            {"schema_min_items", "missing_evidence_artifact"} & missing_codes,
            missing_codes,
        )

        failed = copy.deepcopy(self.runs[0])
        failed["evaluator_receipt"]["exit_code"] = 1
        self.assertIn(
            "schema_const",
            issue_codes(validate_run_result(failed, self.manifest)),
        )

    def test_exploratory_fixed_analysis_cannot_meet_effect_rule(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        runs = copy.deepcopy(self.runs)
        claim = manifest["claim_plan"]
        claim["claim_class"] = "exploratory"
        claim["minimum_favorable_effect"] = 0
        claim["decision_rule"] = "descriptive_only"
        claim["confidence"] = {"method": "none", "level": 0.95, "tail": "none"}
        self._rebind_runs_to_manifest(manifest, runs)
        anchor = self._commit_manifest(manifest, repo_name="exploratory-anchor")

        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )

        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertFalse(report["registered_effect_rule_met"])
        self.assertEqual(
            "noncomparative_analysis_cannot_meet_effect_rule",
            report["decision"]["reason"],
        )

    def test_exact_roster_scope_reports_estimate_without_population_effect(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        runs = copy.deepcopy(self.runs)
        manifest["inference_scope"].update({
            "kind": "registered_roster_only",
            "target_population": None,
        })
        manifest["sampling_design"].update({
            "selection_method": "fixed_registered_census",
            "independence_assumption": "correlated_or_unknown",
        })
        self._rebind_runs_to_manifest(manifest, runs)
        anchor = self._commit_manifest(manifest, repo_name="exact-roster-anchor")

        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )

        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertIsNone(
            report["analysis"]["confidence"]["favorable_direction_lower_bound"]
        )
        self.assertFalse(report["registered_effect_rule_met"])
        self.assertEqual(
            "inference_scope_not_eligible_for_effect_rule",
            report["decision"]["reason"],
        )

    def test_correlated_population_sample_cannot_meet_effect_rule(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        runs = copy.deepcopy(self.runs)
        manifest["sampling_design"]["independence_assumption"] = (
            "correlated_or_unknown"
        )
        self._rebind_runs_to_manifest(manifest, runs)
        anchor = self._commit_manifest(manifest, repo_name="correlated-anchor")

        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )

        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertFalse(report["registered_effect_rule_met"])

    def test_two_perfect_pairs_cannot_meet_hoeffding_effect_rule(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["execution_plan"]["attempt_roster"] = manifest["execution_plan"][
            "attempt_roster"
        ][:2]
        manifest["execution_plan"]["stopping_rule"]["required_resolved_slots"] = 4
        manifest["claim_plan"]["planned_denominator"] = 2
        runs = copy.deepcopy(self.runs[:4])
        self._rebind_runs_to_manifest(manifest, runs)
        anchor = self._commit_manifest(manifest, repo_name="two-pair-anchor")

        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )

        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertAlmostEqual(
            -0.7308183826022854,
            report["analysis"]["confidence"]["favorable_direction_lower_bound"],
        )
        self.assertFalse(report["registered_effect_rule_met"])

    def test_twenty_three_perfect_pairs_are_below_registered_half_point_rule(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["execution_plan"]["attempt_roster"] = manifest["execution_plan"][
            "attempt_roster"
        ][:23]
        manifest["execution_plan"]["stopping_rule"]["required_resolved_slots"] = 46
        manifest["claim_plan"]["planned_denominator"] = 23
        runs = copy.deepcopy(self.runs[:46])
        self._rebind_runs_to_manifest(manifest, runs)
        anchor = self._commit_manifest(manifest, repo_name="twenty-three-pair-anchor")

        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )

        self.assertLess(
            report["analysis"]["confidence"]["favorable_direction_lower_bound"],
            0.5,
        )
        self.assertFalse(report["registered_effect_rule_met"])

    def test_catastrophic_guardrail_blocks_effect_rule_but_not_estimate(self) -> None:
        runs = copy.deepcopy(self.runs)
        self._set_metric(runs[1], "catastrophic_write_rate", 1)

        report = self._audit(runs)

        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertFalse(report["guardrails"]["all_passed"])
        self.assertFalse(report["registered_effect_rule_met"])
        self.assertEqual("registered_guardrail_failed", report["decision"]["reason"])

    def test_comparative_plan_cannot_delete_all_outcome_guardrails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["claim_plan"]["guardrails"] = [
            guardrail
            for guardrail in manifest["claim_plan"]["guardrails"]
            if guardrail["source"]["kind"] == "cost"
        ]
        self.assertIn(
            "missing_outcome_guardrail",
            issue_codes(validate_experiment_manifest(manifest)),
        )

    def test_latency_guardrail_blocks_resource_bought_effect(self) -> None:
        runs = copy.deepcopy(self.runs)
        self._set_cost(runs[1], "wall_time_ms", 40000)

        report = self._audit(runs)

        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertFalse(report["registered_effect_rule_met"])
        latency = next(
            item
            for item in report["guardrails"]["guardrails"]
            if item["guardrail_id"] == "bounded-latency-regression"
        )
        self.assertFalse(latency["passed"])

    def test_unknown_price_is_null_and_does_not_block_task_estimate(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        runs = copy.deepcopy(self.runs)
        manifest["cost_measurement"] = {
            "mode": "unavailable",
            "price_schedule": None,
        }
        self._rebind_runs_to_manifest(manifest, runs)
        for run in runs:
            run["costs"]["cost_microusd"] = None
            self._rewrite_semantic_artifact(run, "cost_trace", run["costs"])
            self._refresh_receipts(run)
        anchor = self._commit_manifest(manifest, repo_name="unknown-price-anchor")

        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )

        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertFalse(report["cost_measurement"]["cost_reportable"])
        self.assertTrue(
            any("zero does not mean unknown" in item for item in report["limitations"])
        )

    def test_cost_provenance_status_and_derived_price_schedule_are_required(self) -> None:
        run = copy.deepcopy(self.runs[0])
        del run["costs"]["cost_status"]
        self.assertIn(
            "schema_required",
            issue_codes(validate_run_result(run, self.manifest)),
        )

        manifest = copy.deepcopy(self.manifest)
        manifest["cost_measurement"]["price_schedule"] = None
        self.assertIn(
            "derived_cost_missing_price_schedule",
            issue_codes(validate_experiment_manifest(manifest)),
        )

    def test_duplicate_execution_identity_and_cloned_trace_are_rejected(self) -> None:
        runs = copy.deepcopy(self.runs)
        runs[1]["execution_receipt"]["invocation_id"] = runs[0][
            "execution_receipt"
        ]["invocation_id"]
        self._refresh_receipts(runs[1])
        source = self._artifact(runs[0], "transcript")
        target = self._artifact(runs[1], "transcript")
        target.update({
            "uri": source["uri"],
            "sha256": source["sha256"],
            "byte_size": source["byte_size"],
            "media_type": source["media_type"],
        })
        self._refresh_receipts(runs[1])

        report = self._audit(runs)
        codes = {error["code"] for error in report["errors"]}

        self.assertIn("duplicate_execution_identity", codes)
        self.assertIn("cross_run_execution_trace_reuse", codes)
        self.assertFalse(report["evidence_complete"])

    def test_unreported_provider_request_ids_are_null_and_thread_ids_stay_unique(self) -> None:
        runs = copy.deepcopy(self.runs)
        for run in runs:
            run["execution_receipt"]["provider_request_id"] = None
            run["execution_receipt"]["provider_request_id_status"] = (
                "unverified_not_reported"
            )
            self._refresh_receipts(run)

        report = self._audit(runs)

        self.assertTrue(report["evidence_complete"], report["errors"])
        self.assertNotIn(
            "duplicate_execution_identity",
            {error["code"] for error in report["errors"]},
        )

    def test_duplicate_thread_is_rejected_when_provider_request_is_unreported(self) -> None:
        runs = copy.deepcopy(self.runs)
        for run in runs:
            run["execution_receipt"]["provider_request_id"] = None
            run["execution_receipt"]["provider_request_id_status"] = (
                "unverified_not_reported"
            )
        runs[1]["execution_receipt"]["thread_id"] = runs[0]["execution_receipt"][
            "thread_id"
        ]
        for run in runs:
            self._refresh_receipts(run)

        report = self._audit(runs)

        self.assertIn(
            "duplicate_execution_identity",
            {error["code"] for error in report["errors"]},
        )

    def test_provider_request_identity_status_controls_nullable_id(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["execution_receipt"]["provider_request_id_status"] = (
            "unverified_not_reported"
        )
        # Draft 2020-12 if/then now rejects the mismatched nullable identity at
        # the shape boundary before the redundant semantic check can run.
        self.assertIn(
            "schema_type",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_self_authored_provider_attestation_cannot_promote_fixed_result(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        provider_contract = {
            "id": "self-authored-provider-attestation",
            "version": "1.0.0",
            "artifact": self._pin("self-authored-provider-attestation.json"),
        }
        backend_identity = "openai:gpt-5:backend-2026-07-01-weights-a1"
        manifest["reference_agent_stack"]["model"]["backend_identity_contract"] = {
            "mode": "provider_attested_snapshot",
            "expected_backend_identity": backend_identity,
            "attestation_contract": provider_contract,
            "local_model_artifact": None,
            "runner_attestation_contract": None,
            "required_invocation_argument": None,
        }
        anchor = self._commit_manifest(
            manifest,
            repo_name="self-authored-provider-anchor",
        )
        runs = copy.deepcopy(self.runs)
        for run in runs:
            run["experiment_manifest_sha256"] = canonical_sha256(manifest)
            run["agent_stack"] = copy.deepcopy(manifest["reference_agent_stack"])
            receipt = run["model_identity_receipt"]
            receipt.update({
                "status": "provider_attested_immutable",
                "source": "provider_attestation",
                "model_provider": run["agent_stack"]["model"]["provider"],
                "model_id": run["agent_stack"]["model"]["id"],
                "declared_selector": run["agent_stack"]["model"]["snapshot"],
                "backend_identity": backend_identity,
                "provider_request_id": run["execution_receipt"][
                    "provider_request_id"
                ],
                "attestation_contract_sha256": provider_contract["artifact"][
                    "sha256"
                ],
                "local_model_artifact_sha256": None,
                "runner_attestation_contract_sha256": None,
            })
            self._rewrite_semantic_artifact(
                run,
                "model_identity_receipt",
                {
                    "schema_version": (
                        "drupal_agent_readiness.model_identity_receipt.v1"
                    ),
                    "run_id": run["run_id"],
                    **receipt,
                },
            )
            run["execution_receipt"]["artifact_hashes"][
                "model_identity_receipt"
            ] = self._artifact(run, "model_identity_receipt")["sha256"]
            self._rewrite_semantic_artifact(
                run,
                "execution_receipt",
                {
                    "schema_version": (
                        "drupal_agent_readiness.execution_receipt.v1"
                    ),
                    "run_id": run["run_id"],
                    **run["execution_receipt"],
                },
            )

        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )

        self.assertTrue(report["evidence_complete"], report["errors"])
        self.assertTrue(report["directional_result_available"])
        self.assertFalse(report["estimate_reportable"])
        self.assertFalse(report["registered_effect_rule_met"])
        self.assertFalse(report["model_backend_identity"]["claim_grade_eligible"])
        self.assertEqual(
            "provider_attestation_verification_unimplemented",
            report["model_backend_identity"]["assurance_reason"],
        )
        self.assertEqual(
            "backend_identity_not_claim_grade",
            report["decision"]["reason"],
        )

    def test_local_model_contract_must_bind_exact_digest_argument(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["reference_agent_stack"]["model"]["backend_identity_contract"][
            "required_invocation_argument"
        ] = "--model-artifact-sha256=sha256:" + "0" * 64

        codes = issue_codes(validate_experiment_manifest(manifest))

        self.assertIn("local_model_invocation_binding_invalid", codes)

        run = copy.deepcopy(self.runs[0])
        run["execution_receipt"]["provider_request_id"] = None
        # The schema conditional is the first fail-closed layer for this
        # malformed receipt; semantic validation is intentionally not reached.
        self.assertIn(
            "schema_type",
            issue_codes(validate_run_result(run, self.manifest)),
        )

    def test_randomized_order_label_is_not_accepted_without_recomputation(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["comparison"]["order_policy"] = "randomized"
        self.assertIn(
            "schema_enum",
            issue_codes(validate_experiment_manifest(manifest)),
        )

    def test_noncounterbalanced_plan_cannot_meet_effect_rule(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["comparison"]["order_policy"] = "pre_then_post"
        for entry in manifest["execution_plan"]["attempt_roster"]:
            for slot in entry["executions"]:
                slot["order"] = 1 if slot["arm_id"] == "baseline" else 2
        self.assertEqual([], validate_experiment_manifest(manifest))
        analysis = {
            "confidence": {"favorable_direction_lower_bound": 1.0},
        }
        from agent_readiness.measurement_v1 import _derive_effect_rule_decision

        decision = _derive_effect_rule_decision(
            manifest,
            analysis,
            {"all_passed": True},
            True,
        )
        self.assertFalse(decision["registered_effect_rule_met"])
        self.assertEqual("paired_order_confounded_effect_rule", decision["reason"])

    def test_substrate_seed_must_equal_pre_arm_site(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["substrate"]["starting_site_seed"]["database_sha256"] = declared_hash(
            "invented-database"
        )
        codes = issue_codes(validate_experiment_manifest(manifest))
        self.assertIn("state_source_hash_mismatch", codes)
        self.assertIn("substrate_pre_arm_site_mismatch", codes)

    def test_owner_described_substrate_attestation_is_separately_pinned(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        runs = copy.deepcopy(self.runs)
        attestation = {
            "schema_version": "drupal_agent_readiness.owner_attestation.v1",
            "substrate_id": "messy_owner_described",
            "owner_class": "site_owner",
            "starting_site_manifest_sha256": manifest["substrate"][
                "starting_site_seed"
            ]["manifest"]["sha256"],
        }
        pin = self._pin_document("state/site/owner-attestation.json", attestation)
        manifest["substrate"].update({
            "substrate_id": "messy_owner_described",
            "owner_attestation": pin,
        })
        self._rebind_runs_to_manifest(manifest, runs)
        anchor = self._commit_manifest(manifest, repo_name="owner-attestation-anchor")

        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )
        self.assertTrue(report["evidence_complete"], report["errors"])

        (self.root / pin["uri"]).write_bytes(canonical_json_bytes({"forged": True}))
        tampered = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )
        self.assertIn(
            "artifact_hash_mismatch",
            {error["code"] for error in tampered["errors"]},
        )
        self.assertFalse(tampered["evidence_complete"])

    def test_schema_any_of_cannot_be_bypassed_to_reach_effect_rule(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        runs = copy.deepcopy(self.runs)
        manifest["substrate"]["owner_attestation"] = 42
        self._rebind_runs_to_manifest(manifest, runs)

        manifest_codes = issue_codes(validate_experiment_manifest(manifest))
        run_codes = issue_codes(validate_run_result(runs[0], manifest))
        self.assertIn("schema_any_of", manifest_codes)
        self.assertTrue(
            {"schema_any_of", "invalid_experiment_manifest"} & run_codes,
            run_codes,
        )

        anchor = self._commit_manifest(
            manifest,
            repo_name="schema-any-of-registration",
        )
        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )
        self.assertFalse(report["audit_valid"])
        self.assertFalse(report["estimate_reportable"])
        self.assertFalse(report["registered_effect_rule_met"])

    def test_rehashed_fabricated_state_manifest_fails_semantic_reconciliation(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        runs = copy.deepcopy(self.runs)
        state_manifest_path = self.root / manifest["substrate"]["starting_site_seed"][
            "manifest"
        ]["uri"]
        state_manifest_path.write_bytes(canonical_json_bytes({}))
        fabricated_hash = file_sha256(state_manifest_path)
        fabricated_size = state_manifest_path.stat().st_size
        for site in [
            manifest["substrate"]["starting_site_seed"],
            *(arm["drupal_state"]["site"] for arm in manifest["arms"]),
        ]:
            site["manifest"]["sha256"] = fabricated_hash
            site["manifest"]["byte_size"] = fabricated_size
            site["composite_sha256"] = fabricated_hash
        arm_by_id = {arm["arm_id"]: arm for arm in manifest["arms"]}
        for run in runs:
            registered = arm_by_id[run["arm"]["arm_id"]]
            run["arm"]["drupal_state"] = copy.deepcopy(registered["drupal_state"])
            run["final_drupal_state"] = copy.deepcopy(registered["drupal_state"])
        self._rebind_runs_to_manifest(manifest, runs)
        anchor = self._commit_manifest(manifest, repo_name="fabricated-state-anchor")

        report = audit_measurement_v1(
            manifest,
            runs,
            artifact_root=self.root,
            registration_anchor=anchor,
        )

        self.assertIn(
            "state_manifest_semantic_mismatch",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["evidence_complete"])

    def test_final_state_nested_artifact_path_escape_fails_closed(self) -> None:
        runs = copy.deepcopy(self.runs)
        runs[0]["final_drupal_state"]["site"]["sources"]["database"]["uri"] = (
            "../../not-retained.database"
        )
        self._refresh_receipts(runs[0])

        report = self._audit(runs)

        self.assertIn("unsafe_artifact_uri", {error["code"] for error in report["errors"]})
        self.assertFalse(report["artifacts_verified"])
        self.assertFalse(report["evidence_complete"])
        self.assertFalse(report["registered_effect_rule_met"])

    def test_final_state_missing_nested_artifact_fails_closed(self) -> None:
        runs = copy.deepcopy(self.runs)
        site = runs[0]["final_drupal_state"]["site"]
        database = site["sources"]["database"]
        database.update({
            "uri": "runs/not-retained/final.database",
            "sha256": declared_hash("nonexistent-final-database"),
            "media_type": "application/octet-stream",
            "byte_size": 987654,
        })
        site["database_sha256"] = database["sha256"]
        self._refresh_receipts(runs[0])

        report = self._audit(runs)

        self.assertIn("artifact_missing", {error["code"] for error in report["errors"]})
        self.assertFalse(report["artifacts_verified"])
        self.assertFalse(report["evidence_complete"])
        self.assertFalse(report["registered_effect_rule_met"])

    def test_final_state_declared_hashes_must_match_nested_source_pins(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["final_drupal_state"]["site"]["database_sha256"] = declared_hash(
            "unretained-final-database"
        )

        codes = issue_codes(validate_run_result(run, self.manifest))

        self.assertIn("state_source_hash_mismatch", codes)

    def test_rehashed_final_site_and_code_manifests_fail_semantic_reconciliation(self) -> None:
        for state_part in ("site", "code"):
            with self.subTest(state_part=state_part):
                runs = copy.deepcopy(self.runs)
                state = runs[0]["final_drupal_state"][state_part]
                path = self.root / "runs" / runs[0]["run_id"] / (
                    f"forged-final-{state_part}-manifest.json"
                )
                path.write_bytes(canonical_json_bytes({"forged": state_part}))
                state["manifest"] = {
                    "uri": str(path.relative_to(self.root)),
                    "sha256": file_sha256(path),
                    "media_type": "application/json",
                    "byte_size": path.stat().st_size,
                }
                if state_part == "site":
                    state["composite_sha256"] = state["manifest"]["sha256"]
                self._refresh_receipts(runs[0])

                report = self._audit(runs)

                self.assertTrue(report["artifacts_verified"], report["errors"])
                self.assertIn(
                    "state_manifest_semantic_mismatch",
                    {error["code"] for error in report["errors"]},
                )
                self.assertFalse(report["artifact_semantics_verified"])
                self.assertFalse(report["evidence_complete"])
                self.assertFalse(report["registered_effect_rule_met"])

    def test_attempt_receipt_and_raw_logs_are_required_and_hash_bound(self) -> None:
        for missing_kind in ("attempt_receipt", "attempt_stdout", "attempt_stderr"):
            with self.subTest(missing_kind=missing_kind):
                missing = copy.deepcopy(self.runs[0])
                missing["artifacts"] = [
                    artifact
                    for artifact in missing["artifacts"]
                    if artifact["kind"] != missing_kind
                ]
                self.assertIn(
                    "missing_evidence_artifact",
                    issue_codes(validate_run_result(missing, self.manifest)),
                )

        mismatched = copy.deepcopy(self.runs[0])
        mismatched["execution_receipt"]["artifact_hashes"]["attempt_receipt"] = (
            declared_hash("other-attempt-receipt")
        )
        self.assertIn(
            "execution_artifact_hash_mismatch",
            issue_codes(validate_run_result(mismatched, self.manifest)),
        )

    def test_rehashed_attempt_receipt_cannot_change_execution_identity(self) -> None:
        runs = copy.deepcopy(self.runs)
        receipt = self._attempt_receipt_document(runs[0])
        receipt.update({
            "run_id": "other-run",
            "roster_slot_id": "other-slot",
            "attempt_id": "other-attempt",
            "argv": ["unregistered", "command"],
            "thread_id": "other-thread",
            "provider_request_id": "other-provider-request",
            "environment_policy_sha256": declared_hash("other-policy"),
        })
        self._rewrite_attempt_receipt_and_execution_binding(runs[0], receipt)

        report = self._audit(runs)
        errors = [
            error
            for error in report["errors"]
            if error["code"] == "attempt_receipt_semantic_mismatch"
        ]

        self.assertTrue(report["artifacts_verified"], report["errors"])
        self.assertEqual(1, len(errors), report["errors"])
        for field in (
            "run_id",
            "roster_slot_id",
            "attempt_id",
            "argv",
            "thread_id",
            "provider_request_id",
            "environment_policy_sha256",
        ):
            self.assertIn(field, errors[0]["message"])
        self.assertFalse(report["evidence_complete"])
        self.assertFalse(report["registered_effect_rule_met"])

    def test_attempt_receipt_requires_clean_runtime_and_system_skill_proof(self) -> None:
        runs = copy.deepcopy(self.runs)
        receipt = self._attempt_receipt_document(runs[0])
        receipt["runtime_home_verification"].update({
            "after_forbidden_entries": ["skills"],
            "after_system_skills_verified": False,
        })
        self._rewrite_attempt_receipt_and_execution_binding(runs[0], receipt)

        report = self._audit(runs)

        self.assertTrue(report["artifacts_verified"], report["errors"])
        self.assertIn(
            "attempt_runtime_home_verification_failed",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["evidence_complete"])

    def test_attempt_receipt_runtime_identity_booleans_fail_closed(self) -> None:
        for field in (
            "after_home_identity_verified",
            "after_home_mode_verified",
            "after_layout_verified",
            "after_auth_reference_verified",
            "after_profile_regular_file_verified",
            "after_sentinel_regular_file_verified",
        ):
            with self.subTest(field=field):
                runs = copy.deepcopy(self.runs)
                receipt = self._attempt_receipt_document(runs[0])
                receipt["runtime_home_verification"][field] = False
                self._rewrite_attempt_receipt_and_execution_binding(runs[0], receipt)

                report = self._audit(runs)

                self.assertIn(
                    "attempt_runtime_home_verification_failed",
                    {error["code"] for error in report["errors"]},
                )
                self.assertFalse(report["evidence_complete"])

    def test_attempt_receipt_rejects_empty_or_unsafe_rehashed_layouts(self) -> None:
        cases = {
            "empty": [],
            "unsafe": [
                {
                    "path": "installation_id",
                    "kind": "file",
                    "mode": "0o777",
                }
            ],
        }
        for name, entries in cases.items():
            with self.subTest(name=name):
                body = {
                    "schema_version": (
                        "drupal_agent_readiness.runtime_home_layout.v1"
                    ),
                    "entries": entries,
                }
                document = {**body, "tree_sha256": canonical_sha256(body)}
                self.assertTrue(runtime_home_layout_document_valid(document))
                self.assertFalse(
                    runtime_home_layout_semantically_valid(
                        document,
                        phase="after",
                        system_manifest={"directories": [], "files": []},
                        auth_target_path_sha256=declared_hash("auth-path"),
                        codex_target_path_sha256=declared_hash("codex-path"),
                        codex_file_sha256=declared_hash("codex-file"),
                    )
                )
                runs = copy.deepcopy(self.runs)
                receipt = self._attempt_receipt_document(runs[0])
                for phase in ("before", "after"):
                    receipt["runtime_home_verification"][
                        f"{phase}_layout_document"
                    ] = document
                    receipt["runtime_home_verification"][
                        f"{phase}_layout_sha256"
                    ] = document["tree_sha256"]
                self._rewrite_attempt_receipt_and_execution_binding(
                    runs[0], receipt
                )

                report = self._audit(runs)

                self.assertIn(
                    "attempt_runtime_home_verification_failed",
                    {error["code"] for error in report["errors"]},
                )
                self.assertFalse(report["evidence_complete"])

        valid = fake_runtime_layout_document(
            {
                "schema_version": (
                    "drupal_agent_readiness.system_skills_manifest.v1"
                ),
                "directories": [],
                "files": [],
                "tree_sha256": canonical_sha256(
                    {
                        "schema_version": (
                            "drupal_agent_readiness.system_skills_manifest.v1"
                        ),
                        "directories": [],
                        "files": [],
                    }
                ),
            }
        )
        orphan_body = {
            "schema_version": valid["schema_version"],
            "entries": sorted(
                [
                    *valid["entries"],
                    {"path": "tmp/arg0", "kind": "directory", "mode": "0o700"},
                ],
                key=lambda item: item["path"],
            ),
        }
        orphan = {**orphan_body, "tree_sha256": canonical_sha256(orphan_body)}
        self.assertFalse(
            runtime_home_layout_semantically_valid(
                orphan,
                phase="after",
                system_manifest={
                    "schema_version": (
                        "drupal_agent_readiness.system_skills_manifest.v1"
                    ),
                    "directories": [],
                    "files": [],
                    "tree_sha256": canonical_sha256(
                        {
                            "schema_version": (
                                "drupal_agent_readiness.system_skills_manifest.v1"
                            ),
                            "directories": [],
                            "files": [],
                        }
                    ),
                },
                auth_target_path_sha256=declared_hash(
                    "/Users/fixture/.codex/auth.json"
                ),
                codex_target_path_sha256=declared_hash("codex-path"),
                codex_file_sha256=declared_hash("codex-file"),
            )
        )
        malicious_manifest_body = {
            "schema_version": "drupal_agent_readiness.system_skills_manifest.v1",
            "directories": [{"path": "auth.json", "mode": "0o700"}],
            "files": [],
        }
        malicious_manifest = {
            **malicious_manifest_body,
            "tree_sha256": canonical_sha256(malicious_manifest_body),
        }
        self.assertFalse(
            runtime_home_layout_semantically_valid(
                valid,
                phase="before",
                system_manifest=malicious_manifest,
                auth_target_path_sha256=declared_hash(
                    "/Users/fixture/.codex/auth.json"
                ),
                codex_target_path_sha256=declared_hash("codex-path"),
                codex_file_sha256=declared_hash("codex-file"),
            )
        )
        noncanonical_body = {
            "schema_version": valid["schema_version"],
            "entries": [
                *valid["entries"],
                {"path": "tmp", "kind": "directory", "mode": "0o0755"},
            ],
        }
        noncanonical = {
            **noncanonical_body,
            "tree_sha256": canonical_sha256(noncanonical_body),
        }
        self.assertFalse(runtime_home_layout_document_valid(noncanonical))

    def test_runtime_layout_requires_preregistered_model_cache_content(self) -> None:
        manifest_body = {
            "schema_version": "drupal_agent_readiness.system_skills_manifest.v1",
            "directories": [],
            "files": [],
        }
        manifest = {
            **manifest_body,
            "tree_sha256": canonical_sha256(manifest_body),
        }
        base = fake_runtime_layout_document(manifest)

        def document_with(*entries: dict) -> dict:
            body = {
                "schema_version": base["schema_version"],
                "entries": sorted(
                    [*base["entries"], *entries], key=lambda item: item["path"]
                ),
            }
            return {**body, "tree_sha256": canonical_sha256(body)}

        model_cache_contract = {
            "schema_version": "drupal_agent_readiness.model_cache_contract.v1",
            "file_sha256": declared_hash("model-cache-file"),
            "byte_size": 123,
            "selected_model_selector": "gpt-5.4",
            "selected_model_entry_sha256": declared_hash("model-entry"),
            "catalog_client_version": "0.142.5",
            "catalog_fetched_at": "2026-07-10T09:00:00Z",
            "content_role": "behavior_affecting_model_metadata",
            "bytes_retained": False,
        }
        model_cache_entry = {
            "path": "models_cache.json",
            "kind": "file",
            "mode": "0o400",
            "byte_size": model_cache_contract["byte_size"],
            "sha256": model_cache_contract["file_sha256"],
        }
        model_cache = document_with(model_cache_entry)
        kwargs = {
            "system_manifest": manifest,
            "auth_target_path_sha256": declared_hash(
                "/Users/fixture/.codex/auth.json"
            ),
            "codex_target_path_sha256": declared_hash("codex-path"),
            "codex_file_sha256": declared_hash("codex-file"),
            "model_cache_contract": model_cache_contract,
        }
        self.assertTrue(
            runtime_home_layout_semantically_valid(
                model_cache, phase="before", **kwargs
            )
        )
        self.assertTrue(
            runtime_home_layout_semantically_valid(
                model_cache, phase="after", **kwargs
            )
        )
        tampered_entry = {**model_cache_entry, "sha256": declared_hash("tampered")}
        self.assertFalse(
            runtime_home_layout_semantically_valid(
                document_with(tampered_entry), phase="after", **kwargs
            )
        )
        self.assertFalse(
            runtime_home_layout_semantically_valid(
                model_cache,
                phase="after",
                **{**kwargs, "model_cache_contract": None},
            )
        )

        app_cache = document_with(
            model_cache_entry,
            {"path": "cache", "kind": "directory", "mode": "0o755"},
            {
                "path": "cache/codex_apps_tools",
                "kind": "directory",
                "mode": "0o755",
            },
            {
                "path": f"cache/codex_apps_tools/{'a' * 32}.json",
                "kind": "file",
                "mode": "0o644",
            },
        )
        self.assertFalse(
            runtime_home_layout_semantically_valid(
                app_cache, phase="after", **kwargs
            )
        )

    def test_attempt_process_containment_receipt_fails_closed(self) -> None:
        runs = copy.deepcopy(self.runs)
        receipt = self._attempt_receipt_document(runs[0])
        receipt["process_containment"]["child_process_creation_denied"] = False
        self._rewrite_attempt_receipt_and_execution_binding(runs[0], receipt)

        report = self._audit(runs)

        self.assertIn(
            "attempt_process_containment_failed",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["evidence_complete"])

    def test_attempt_system_skills_tree_must_equal_registered_policy(self) -> None:
        runs = copy.deepcopy(self.runs)
        receipt = self._attempt_receipt_document(runs[0])
        receipt["runtime_home_verification"]["system_skills_tree_sha256"] = (
            declared_hash("unregistered-system-skills-tree")
        )
        self._rewrite_attempt_receipt_and_execution_binding(runs[0], receipt)

        report = self._audit(runs)

        self.assertTrue(report["artifacts_verified"], report["errors"])
        self.assertIn(
            "attempt_runtime_home_verification_failed",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["artifact_semantics_verified"])
        self.assertFalse(report["evidence_complete"])

    def test_attempt_receipt_must_bind_exact_raw_stdout_and_stderr(self) -> None:
        runs = copy.deepcopy(self.runs)
        receipt = self._attempt_receipt_document(runs[0])
        receipt["stdout_sha256"] = declared_hash("substituted-stdout")
        receipt["stderr_artifact_id"] = "substituted-stderr"
        self._rewrite_attempt_receipt_and_execution_binding(runs[0], receipt)

        report = self._audit(runs)

        self.assertTrue(report["artifacts_verified"], report["errors"])
        self.assertEqual(
            2,
            sum(
                error["code"] == "attempt_raw_log_binding_mismatch"
                for error in report["errors"]
            ),
        )
        self.assertFalse(report["evidence_complete"])

    def test_metric_components_must_match_registered_domain(self) -> None:
        binary = copy.deepcopy(self.runs[0])
        binary_metric = binary["outcomes"]["metrics"][0]
        binary_metric.update({"numerator": 2, "denominator": 2, "value": 1.0})
        self.assertIn(
            "invalid_binary_metric_components",
            issue_codes(validate_run_result(binary, self.manifest)),
        )

        rate = copy.deepcopy(self.runs[0])
        rate_metric = rate["outcomes"]["metrics"][1]
        rate_metric.update({"numerator": -1, "denominator": 1, "value": -1.0})
        codes = issue_codes(validate_run_result(rate, self.manifest))
        self.assertIn("invalid_rate_metric_components", codes)
        self.assertIn("bounded_metric_out_of_range", codes)

    def test_inference_scope_is_required(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        del manifest["inference_scope"]
        self.assertIn(
            "schema_required",
            issue_codes(validate_experiment_manifest(manifest)),
        )

    def test_cli_rejects_noncanonical_and_duplicate_key_sources(self) -> None:
        run_path = self.root / "canonical-cli-run.json"
        run_path.write_bytes(canonical_json_bytes(self.runs[0]))
        for name, payload in (
            ("noncanonical", canonical_json_bytes(self.manifest) + b"\n"),
            ("duplicate", b'{"schema_version":"x","schema_version":"y"}'),
        ):
            with self.subTest(name=name):
                manifest_path = self.root / f"{name}-manifest.json"
                manifest_path.write_bytes(payload)
                completed = subprocess.run(
                    [
                        sys.executable,
                        "agent_readiness/scripts/audit_measurement_v1.py",
                        "--manifest",
                        str(manifest_path),
                        "--run",
                        str(run_path),
                        "--artifact-root",
                        str(self.root),
                        "--require",
                        "contract",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                report = json.loads(completed.stdout)
                self.assertEqual(1, completed.returncode)
                self.assertEqual(
                    "measurement_input_noncanonical",
                    report["errors"][0]["code"],
                )

    def test_measurement_effect_rule_is_not_final_workflow_improvement(self) -> None:
        report = self._audit()
        self.assertTrue(report["registered_effect_rule_met"])
        self.assertNotIn("improvement_demonstrated", report)
        self.assertEqual(self.manifest["governance"], report["governance"])
        self.assertTrue(
            any(
                "compatible decided or adopted action record" in limitation
                for limitation in report["limitations"]
            )
        )

    def test_module_and_theme_with_same_name_do_not_hide_differences(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        for arm, suffix in zip(manifest["arms"], ("pre", "post")):
            arm["drupal_state"]["code"]["components"].append(
                {
                    "kind": "theme",
                    "name": "site_architecture",
                    "version": "1.0.0",
                    "revision": "4d813c",
                    "tree_sha256": declared_hash(f"same-name-theme-{suffix}"),
                }
            )
        manifest["comparison"]["allowed_changed_paths"].append(
            "/code/components/theme:site_architecture/tree_sha256"
        )
        self.assertEqual([], validate_experiment_manifest(manifest))

        manifest["comparison"]["allowed_changed_paths"].remove(
            "/code/components/theme:site_architecture/tree_sha256"
        )
        self.assertIn(
            "unregistered_treatment_difference",
            issue_codes(validate_experiment_manifest(manifest)),
        )

    def test_duplicate_kind_and_name_is_explicit_collision(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        duplicate = copy.deepcopy(
            manifest["arms"][0]["drupal_state"]["code"]["components"][0]
        )
        manifest["arms"][0]["drupal_state"]["code"]["components"].append(duplicate)
        codes = issue_codes(validate_experiment_manifest(manifest))
        self.assertIn("duplicate_drupal_component", codes)
        self.assertIn("colliding_list_identity", codes)

    def test_manifest_hash_and_artifact_hash_mismatch_are_rejected(self) -> None:
        run = copy.deepcopy(self.runs[0])
        run["experiment_manifest_sha256"] = declared_hash("other manifest")
        self.assertIn(
            "manifest_hash_mismatch",
            issue_codes(validate_run_result(run, self.manifest)),
        )

        transcript = self.root / self.runs[0]["artifacts"][0]["uri"]
        transcript.write_text("tampered\n", encoding="utf-8")
        report = self._audit()
        self.assertIn(
            "artifact_hash_mismatch",
            {error["code"] for error in report["errors"]},
        )
        self.assertFalse(report["artifacts_verified"])

    def test_cli_requires_and_accepts_external_git_anchor(self) -> None:
        completed = self._run_cli(self.runs)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual("estimate", report["cli_requirement"]["level"])
        self.assertTrue(report["estimate_reportable"], report["errors"])
        self.assertTrue(report["registered_effect_rule_met"], report["errors"])

    def test_cli_default_accepts_reportable_null_but_improvement_gate_rejects_it(self) -> None:
        runs = copy.deepcopy(self.runs)
        self._set_success(runs[1], 0)
        self._set_success(runs[3], 0)
        estimate = self._run_cli(runs)
        effect_rule = self._run_cli(runs, "effect-rule")
        self.assertEqual(0, estimate.returncode, estimate.stdout + estimate.stderr)
        self.assertEqual(1, effect_rule.returncode, effect_rule.stdout + effect_rule.stderr)
        report = json.loads(estimate.stdout)
        self.assertTrue(report["estimate_reportable"])
        self.assertFalse(report["registered_effect_rule_met"])

    def test_cli_returns_machine_readable_error_for_invalid_json(self) -> None:
        invalid = self.root / "invalid-manifest.json"
        invalid.write_text("{not json\n", encoding="utf-8")
        run_path = self.root / "valid-run-input.json"
        run_path.write_bytes(canonical_json_bytes(self.runs[0]))

        completed = subprocess.run(
            [
                sys.executable,
                "agent_readiness/scripts/audit_measurement_v1.py",
                "--manifest",
                str(invalid),
                "--run",
                str(run_path),
                "--artifact-root",
                str(self.root),
                "--require",
                "contract",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(1, completed.returncode, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual("measurement_input_unreadable", report["errors"][0]["code"])
        self.assertFalse(report["cli_requirement"]["satisfied"])

    def _audit(self, runs=None):
        return audit_measurement_v1(
            self.manifest,
            runs or self.runs,
            artifact_root=self.root,
            registration_anchor=self.anchor,
        )

    def _run_cli(self, runs: list[dict], requirement: str | None = None):
        manifest_path = self.root / "manifest-input.json"
        manifest_path.write_bytes(canonical_json_bytes(self.manifest))
        command = [
            sys.executable,
            "agent_readiness/scripts/audit_measurement_v1.py",
            "--manifest",
            str(manifest_path),
            "--artifact-root",
            str(self.root),
            "--registration-repo",
            str(self.anchor.repo_path),
            "--registration-commit",
            self.anchor.commit,
            "--registration-manifest-path",
            self.anchor.manifest_path,
        ]
        if requirement is not None:
            command.extend(["--require", requirement])
        for index, run in enumerate(runs):
            path = self.root / f"run-input-{requirement or 'default'}-{index}.json"
            path.write_bytes(canonical_json_bytes(run))
            command.extend(["--run", str(path)])
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def _pin(self, name: str) -> dict:
        path = self.root / "pins" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        media_type = {
            ".json": "application/json",
            ".py": "text/x-python",
            ".md": "text/markdown",
            ".patch": "text/x-diff",
        }.get(path.suffix.lower(), "application/octet-stream")
        if media_type == "application/json":
            path.write_bytes(canonical_json_bytes({"fixture": name}))
        else:
            path.write_text(f"immutable artifact: {name}\n", encoding="utf-8")
        return {
            "uri": str(path.relative_to(self.root)),
            "sha256": file_sha256(path),
            "media_type": media_type,
            "byte_size": path.stat().st_size,
        }

    def _pin_document(self, name: str, document: dict) -> dict:
        path = self.root / "pins" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(document))
        return {
            "uri": str(path.relative_to(self.root)),
            "sha256": file_sha256(path),
            "media_type": "application/json",
            "byte_size": path.stat().st_size,
        }

    def _role_pin(
        self,
        name: str,
        evidence_role: str,
        visibility: str,
        audience: list[str],
    ) -> dict:
        pin = self._pin(name)
        pin.update({
            "evidence_role": evidence_role,
            "visibility": visibility,
            "audience": audience,
        })
        return pin

    def _site(self) -> dict:
        sources = {
            "database": self._pin("state/site/database.snapshot"),
            "active_config": self._pin("state/site/active-config.json"),
            "public_files": self._pin("state/site/public-files.snapshot"),
            "private_files": self._pin("state/site/private-files.snapshot"),
        }
        manifest_document = {
            "schema_version": "drupal_agent_readiness.site_state_manifest.v1",
            "fixture_id": "events-fixture@v1",
            "database_sha256": sources["database"]["sha256"],
            "active_config_sha256": sources["active_config"]["sha256"],
            "public_files_sha256": sources["public_files"]["sha256"],
            "private_files_sha256": sources["private_files"]["sha256"],
        }
        manifest_pin = self._pin_document(
            "state/site/site-state-manifest.json", manifest_document
        )
        return {
            **{key: value for key, value in manifest_document.items() if key != "schema_version"},
            "composite_sha256": manifest_pin["sha256"],
            "sources": sources,
            "manifest": manifest_pin,
        }

    def _drupal_state(self, suffix: str) -> dict:
        core = {
            "kind": "core",
            "name": "drupal/core",
            "version": "11.2.2",
            "revision": "8d5e9d4b2a4c",
            "tree_sha256": declared_hash("core-tree"),
        }
        components = [
            {
                "kind": "module",
                "name": "site_architecture",
                "version": "1.0.0",
                "revision": "c71e9b801f0a",
                "tree_sha256": declared_hash(f"module-tree-{suffix}"),
            }
        ]
        sources = {
            "composer_lock": self._pin("state/code/composer-lock.json"),
            "extensions_manifest": self._pin(
                f"state/code/extensions-{suffix}.json"
            ),
            "codebase": self._pin(f"state/code/codebase-{suffix}.snapshot"),
        }
        manifest_document = {
            "schema_version": "drupal_agent_readiness.code_state_manifest.v1",
            "core": core,
            "components": components,
            "composer_lock_sha256": sources["composer_lock"]["sha256"],
            "extensions_manifest_sha256": sources["extensions_manifest"]["sha256"],
            "codebase_tree_sha256": sources["codebase"]["sha256"],
        }
        manifest_pin = self._pin_document(
            f"state/code/code-state-{suffix}.json", manifest_document
        )
        return {
            "code": {
                **{
                    key: value
                    for key, value in manifest_document.items()
                    if key != "schema_version"
                },
                "sources": sources,
                "manifest": manifest_pin,
            },
            "site": self._site(),
        }

    def _manifest(self) -> dict:
        system_skills_manifest = {
            "schema_version": "drupal_agent_readiness.system_skills_manifest.v1",
            "directories": [],
            "files": [],
        }
        system_skills_manifest["tree_sha256"] = canonical_sha256(
            system_skills_manifest
        )
        system_skills_tree_sha256 = system_skills_manifest["tree_sha256"]
        execution_environment_policy = self._pin_document(
            "execution-environment-policy.json",
            {
                "schema_version": (
                    "drupal_agent_readiness.execution_environment_policy.v1"
                ),
                "system_skills_preflight": {
                    "manifest": system_skills_manifest,
                    "host_read_denials": {
                        "auth_file": {
                            "path": "/Users/fixture/.codex/auth.json",
                            "kind": "literal",
                        }
                    },
                },
                "process_containment": fake_process_containment_policy(),
            },
        )
        local_model_artifact = self._pin("model-weights.gguf")
        required_model_argument = (
            "--model-artifact-sha256=" + local_model_artifact["sha256"]
        )
        runner_attestation_contract = self._pin_document(
            "local-model-runner-attestation-contract.json",
            {
                "schema_version": (
                    "drupal_agent_readiness.local_model_runner_attestation_contract.v1"
                ),
                "required_invocation_argument": required_model_argument,
                "trust_boundary": "pinned_harness_and_retained_execution_receipt",
            },
        )
        return {
            "schema_version": "drupal_agent_readiness.benchmark_experiment.v1",
            "experiment_id": "path-ownership-regression@v1",
            "registered_at": "2026-07-09T10:00:00Z",
            "registration": {
                "manifest_path": "registry/benchmark-manifest.json",
                "protocol": self._pin("protocol.md"),
            },
            "governance": {
                "coverage_claim_id": "coverage.path-ownership",
                "task_family_id": "task-family.path-ownership",
                "improvement_record_id": "improvement.path-ownership",
                "registry_design": {
                    "id": "benchmark-registry-design",
                    "version": "1.0.0",
                    "artifact": self._pin("registry-design.json"),
                },
            },
            "lane": "fixed_regression",
            "task": {
                "id": "assess.path_ownership",
                "version": "1.0.0",
                "lifecycle_stages": ["understand", "act", "verify"],
                "definition": self._pin("task.json"),
                "prompt": self._role_pin(
                    "prompt.md",
                    "task_prompt",
                    "agent_visible",
                    ["agent", "harness", "auditor"],
                ),
                "ground_truth": self._role_pin(
                    "ground-truth.json",
                    "ground_truth",
                    "withheld_from_agent",
                    ["evaluator", "auditor"],
                ),
            },
            "prompt_composition": {
                "algorithm": "canonical_prompt_envelope_v1",
                "renderer": {
                    "id": "canonical-prompt-envelope",
                    "version": "1.0.0",
                    "artifact": self._pin("prompt-renderer.json"),
                },
                "render_inputs": self._role_pin(
                    "render-inputs.json",
                    "render_inputs",
                    "agent_visible",
                    ["agent", "harness", "auditor"],
                ),
            },
            "reference_agent_stack": {
                "agent": {
                    "id": "codex-cli",
                    "version": "0.65.0",
                    "artifact": self._pin("agent-source.json"),
                },
                "model": {
                    "provider": "openai",
                    "id": "gpt-5",
                    "snapshot": "gpt-5-2026-07-01",
                    "inference_parameters": self._pin_document(
                        "inference.json",
                        {
                            "temperature": 0,
                            "execution_environment_policy_sha256": (
                                execution_environment_policy["sha256"]
                            ),
                        },
                    ),
                    "backend_identity_contract": {
                        "mode": "local_model_artifact",
                        "expected_backend_identity": local_model_artifact["sha256"],
                        "attestation_contract": None,
                        "local_model_artifact": local_model_artifact,
                        "runner_attestation_contract": {
                            "id": "local-model-runner-attestation",
                            "version": "1.0.0",
                            "artifact": runner_attestation_contract,
                        },
                        "required_invocation_argument": required_model_argument,
                    },
                },
                "harness": {
                    "id": "agent-readiness-runner",
                    "version": "1.0.0",
                    "artifact": self._pin("harness.py"),
                },
                "system_prompt": self._role_pin(
                    "system-prompt.md",
                    "system_prompt",
                    "agent_visible",
                    ["agent", "harness", "auditor"],
                ),
                "output_schema": self._role_pin(
                    "agent-output.schema.json",
                    "output_schema",
                    "agent_visible",
                    ["agent", "harness", "auditor"],
                ),
                "tools": [
                    {
                        "id": "shell",
                        "version": "5.2.37",
                        "artifact": self._pin("shell-tool.json"),
                    },
                    {
                        "id": "execution-environment-policy",
                        "version": "1.0.0",
                        "artifact": execution_environment_policy,
                    },
                ],
                "permissions": {
                    "profile_id": "fixture-readwrite-v1",
                    "policy": self._pin("permissions.json"),
                    "allowed_capabilities": ["shell", "fixture_read", "fixture_write"],
                    "denied_capabilities": ["network", "host_write"],
                    "network_access": False,
                    "filesystem_scope": "fixture_only",
                },
            },
            "substrate": {
                "substrate_id": "clean",
                "starting_site_seed": self._site(),
                "owner_attestation": None,
                "runtime": {
                    "php_version": "8.3.23",
                    "database_driver": "mariadb",
                    "database_version": "11.4.7",
                    "os_image_digest": declared_hash("os-image"),
                    "container_image_digest": declared_hash("container-image"),
                },
            },
            "state_capture": {
                "collector": {
                    "id": "drupal-state-collector",
                    "version": "1.0.0",
                    "artifact": self._pin("state-collector.py"),
                },
                "protocol": self._pin("state-capture-protocol.json"),
            },
            "arms": [
                {
                    "arm_id": "baseline",
                    "role": "pre",
                    "treatment": {
                        "id": "no-change",
                        "kind": "none",
                        "artifact": self._pin("no-treatment.json"),
                    },
                    "drupal_state": self._drupal_state("pre"),
                },
                {
                    "arm_id": "site-description",
                    "role": "post",
                    "treatment": {
                        "id": "site-description-command",
                        "kind": "drupal_code",
                        "artifact": self._pin("treatment.patch"),
                    },
                    "drupal_state": self._drupal_state("post"),
                },
            ],
            "evaluation": {
                "evaluator": {
                    "id": "path-safety-evaluator",
                    "version": "1.0.0",
                    "artifact": self._role_pin(
                        "evaluator.py",
                        "evaluator_implementation",
                        "withheld_from_agent",
                        ["harness", "evaluator", "auditor"],
                    ),
                },
                "rubric": {
                    "id": "path-safety-rubric",
                    "version": "1.0.0",
                    "artifact": self._role_pin(
                        "rubric.json",
                        "evaluation_rubric",
                        "withheld_from_agent",
                        ["harness", "evaluator", "auditor"],
                    ),
                },
                "scoring": {
                    "id": "binary-success-scoring",
                    "version": "1.0.0",
                    "artifact": self._role_pin(
                        "scoring.py",
                        "scoring_implementation",
                        "withheld_from_agent",
                        ["harness", "evaluator", "auditor"],
                    ),
                },
                "verdict_metric_id": "task_success",
                "assurance": {
                    "mode": "trusted_execution_receipt",
                    "receipt_contract": self._pin("evaluator-receipt-contract.json"),
                    "trusted_issuer": {
                        "id": "independent-evaluation-harness",
                        "version": "1.0.0",
                        "artifact": self._pin("evaluation-harness.py"),
                    },
                },
            },
            "budget": {
                "wall_time_ms": 600000,
                "input_tokens": 100000,
                "output_tokens": 20000,
                "tool_calls": 100,
                "human_interventions": 0,
                "cost_microusd": 5000000,
            },
            "cost_measurement": {
                "mode": "derived_from_usage",
                "price_schedule": self._pin("provider-price-schedule.json"),
            },
            "outcome_metrics": [
                {
                    "metric_id": "task_success",
                    "kind": "binary",
                    "unit": "proportion",
                    "direction": "higher_is_better",
                    "denominator_unit": "task_attempt",
                    "aggregation": "proportion",
                },
                {
                    "metric_id": "catastrophic_write_rate",
                    "kind": "rate",
                    "unit": "proportion",
                    "direction": "lower_is_better",
                    "denominator_unit": "task_attempt",
                    "aggregation": "proportion",
                }
            ],
            "comparison": {
                "mode": "paired_pre_post",
                "pre_arm_id": "baseline",
                "post_arm_id": "site-description",
                "order_policy": "counterbalanced",
                "assignment_seed_sha256": declared_hash("assignment-seed"),
                "allowed_changed_paths": [
                    "/code/components/module:site_architecture/tree_sha256",
                    "/code/extensions_manifest_sha256",
                    "/code/codebase_tree_sha256",
                    "/code/manifest/sha256",
                    "/code/manifest/uri",
                    "/code/sources/codebase/byte_size",
                    "/code/sources/codebase/sha256",
                    "/code/sources/codebase/uri",
                    "/code/sources/extensions_manifest/byte_size",
                    "/code/sources/extensions_manifest/sha256",
                    "/code/sources/extensions_manifest/uri",
                ],
            },
            "execution_plan": {
                "attempt_roster": [
                    {
                        "index": index,
                        "pair_id": f"pair-{index:03d}",
                        "unit_id": f"fixture-reset-{index:03d}",
                        "executions": [
                            {
                                "slot_id": f"pair-{index:03d}-pre",
                                "arm_id": "baseline",
                                "order": 1 if index % 2 == 1 else 2,
                            },
                            {
                                "slot_id": f"pair-{index:03d}-post",
                                "arm_id": "site-description",
                                "order": 2 if index % 2 == 1 else 1,
                            },
                        ],
                    }
                    for index in range(1, 25)
                ],
                "stopping_rule": {
                    "kind": "fixed_census",
                    "required_resolved_slots": 48,
                    "allow_replacements": False,
                    "on_exclusion": "no_claim",
                },
            },
            "inference_scope": {
                "kind": "target_population",
                "target_population": "Independent clean Drupal fixture resets matching the registered task family.",
                "generalization_boundary": self._pin("generalization-boundary.md"),
            },
            "sampling_design": {
                "sampling_unit": "complete_pair",
                "selection_method": "independent_random_sample",
                "independence_assumption": "independent_units",
                "independence_basis": self._pin("independence-basis.md"),
            },
            "claim_plan": {
                "claim_class": "comparative",
                "primary_metric_id": "task_success",
                "estimand": "mean_paired_difference",
                "planned_denominator": 24,
                "denominator_unit": "complete_pair",
                "confidence": {
                    "method": "paired_hoeffding_lower",
                    "level": 0.95,
                    "tail": "one_sided_lower",
                },
                "minimum_favorable_effect": 0.5,
                "decision_rule": "confidence_lower_bound_at_least_minimum",
                "sample_size_rationale": self._pin("sample-size-rationale.md"),
                "guardrails": [
                    {
                        "guardrail_id": "no-catastrophic-writes",
                        "source": {
                            "kind": "outcome_metric",
                            "metric_id": "catastrophic_write_rate",
                        },
                        "rules": [
                            {
                                "statistic": "maximum_post",
                                "operator": "at_most",
                                "threshold": 0,
                            }
                        ],
                    },
                    {
                        "guardrail_id": "zero-human-interventions",
                        "source": {
                            "kind": "cost",
                            "metric_id": "human_interventions",
                        },
                        "rules": [
                            {
                                "statistic": "maximum_all",
                                "operator": "at_most",
                                "threshold": 0,
                            }
                        ],
                    },
                    {
                        "guardrail_id": "bounded-latency-regression",
                        "source": {"kind": "cost", "metric_id": "wall_time_ms"},
                        "rules": [
                            {
                                "statistic": "mean_post_minus_pre",
                                "operator": "at_most",
                                "threshold": 1000,
                            }
                        ],
                    },
                ],
            },
            "exclusion_policy": {
                "locked_at": "2026-07-09T09:59:00Z",
                "policy": self._pin("exclusions.md"),
                "codes": [
                    {"code": "budget_exceeded", "description": "Instrumented budget breach."},
                    {
                        "code": "infrastructure_failure",
                        "description": "Harness failed independently of agent behavior.",
                    },
                ],
            },
        }

    def _frontier_fixture(self) -> tuple[dict, list[dict]]:
        manifest = copy.deepcopy(self.manifest)
        manifest["experiment_id"] = "frontier-observation@v1"
        manifest["registration"]["manifest_path"] = "registry/frontier-manifest.json"
        observation_arm = copy.deepcopy(manifest["arms"][0])
        observation_arm["role"] = "observation"
        manifest["arms"] = [observation_arm]
        manifest["lane"] = "frontier_observation"
        manifest["comparison"] = {
            "mode": "unpaired_observation",
            "order_policy": "not_applicable",
            "assignment_seed_sha256": declared_hash("frontier-order"),
            "allowed_changed_paths": [],
        }
        manifest["execution_plan"] = {
            "attempt_roster": [
                {
                    "index": 1,
                    "pair_id": None,
                    "unit_id": "frontier-unit-001",
                    "executions": [
                        {"slot_id": "frontier-001", "arm_id": "baseline", "order": 1}
                    ],
                },
                {
                    "index": 2,
                    "pair_id": None,
                    "unit_id": "frontier-unit-002",
                    "executions": [
                        {"slot_id": "frontier-002", "arm_id": "baseline", "order": 1}
                    ],
                },
            ],
            "stopping_rule": {
                "kind": "fixed_census",
                "required_resolved_slots": 2,
                "allow_replacements": False,
                "on_exclusion": "no_claim",
            },
        }
        manifest["inference_scope"] = {
            "kind": "registered_roster_only",
            "target_population": None,
            "generalization_boundary": self._pin(
                "frontier-generalization-boundary.md"
            ),
        }
        manifest["sampling_design"] = {
            "sampling_unit": "included_run",
            "selection_method": "fixed_registered_census",
            "independence_assumption": "correlated_or_unknown",
            "independence_basis": self._pin("frontier-independence-basis.md"),
        }
        claim = manifest["claim_plan"]
        claim.update(
            {
                "claim_class": "descriptive",
                "estimand": "mean_observed_value",
                "planned_denominator": 2,
                "denominator_unit": "included_run",
                "confidence": {
                    "method": "none",
                    "level": 0.95,
                    "tail": "none",
                },
                "minimum_favorable_effect": 0,
                "decision_rule": "descriptive_only",
            }
        )
        runs = [copy.deepcopy(self.runs[0]), copy.deepcopy(self.runs[2])]
        for index, run in enumerate(runs, start=1):
            run["experiment_id"] = manifest["experiment_id"]
            run["lane"] = manifest["lane"]
            run["arm"]["role"] = "observation"
            run["attempt"] = {
                "roster_slot_id": f"frontier-00{index}",
                "index": index,
                "unit_id": f"frontier-unit-00{index}",
                "pair_id": None,
                "order_in_pair": None,
            }
            run["claim_context"] = {
                "claim_class": claim["claim_class"],
                "primary_metric_id": claim["primary_metric_id"],
                "estimand": claim["estimand"],
                "planned_denominator": claim["planned_denominator"],
                "denominator_unit": claim["denominator_unit"],
                "confidence": copy.deepcopy(claim["confidence"]),
                "minimum_favorable_effect": claim["minimum_favorable_effect"],
                "decision_rule": claim["decision_rule"],
                "inference_scope": copy.deepcopy(manifest["inference_scope"]),
                "sampling_design": copy.deepcopy(manifest["sampling_design"]),
                "guardrails": copy.deepcopy(claim["guardrails"]),
            }
            run["experiment_manifest_sha256"] = canonical_sha256(manifest)
            self._refresh_receipts(run)
        runs[1]["agent_stack"]["model"]["snapshot"] = "gpt-5-2026-07-02"
        runs[1]["prompt_delivery"]["recipient"]["model_snapshot"] = (
            "gpt-5-2026-07-02"
        )
        self._refresh_receipts(runs[1])
        return manifest, runs

    def _run(
        self,
        slot_id: str,
        role: str,
        index: int,
        pair_id: str,
        unit_id: str,
        order: int,
        hour: int,
        success: int,
    ) -> dict:
        arm = next(item for item in self.manifest["arms"] if item["role"] == role)
        prefix = f"run-{slot_id}"
        timestamps = {
            "started_at": f"2026-07-09T{hour:02d}:00:00Z",
            "completed_at": f"2026-07-09T{hour:02d}:00:10Z",
            "evaluation_started_at": f"2026-07-09T{hour:02d}:00:12Z",
            "evaluation_completed_at": f"2026-07-09T{hour:02d}:00:13Z",
            "recorded_at": f"2026-07-09T{hour:02d}:00:14Z",
        }
        costs = {
            "source": "harness_instrumentation",
            "cost_status": "derived_from_usage",
            "price_schedule_sha256": self.manifest["cost_measurement"][
                "price_schedule"
            ]["sha256"],
            "measurement_artifact_id": f"{prefix}-cost",
            "wall_time_ms": 10000,
            "input_tokens": 1000,
            "output_tokens": 200,
            "cached_input_tokens": 0,
            "tool_calls": 5,
            "human_interventions": 0,
            "cost_microusd": 50000,
        }
        validity = {
            "status": "included",
            "exclusion_code": None,
            "decided_at": f"2026-07-09T{hour:02d}:00:11Z",
            "decision_source": "automatic_preregistered_gate",
            "decision_basis_artifact_id": f"{prefix}-validity",
        }
        events = [
            {
                "sequence": 1,
                "phase": "understand",
                "event_type": "inspect_site",
                "started_at": f"2026-07-09T{hour:02d}:00:01Z",
                "ended_at": f"2026-07-09T{hour:02d}:00:02Z",
                "source": "tool_log",
                "source_artifact_id": f"{prefix}-tools",
                "result": "success",
                "failure_code": None,
            },
            {
                "sequence": 2,
                "phase": "act",
                "event_type": "assess_path",
                "started_at": f"2026-07-09T{hour:02d}:00:03Z",
                "ended_at": f"2026-07-09T{hour:02d}:00:06Z",
                "source": "harness_trace",
                "source_artifact_id": f"{prefix}-behavior",
                "result": "success",
                "failure_code": None,
            },
            {
                "sequence": 3,
                "phase": "verify",
                "event_type": "check_collision",
                "started_at": f"2026-07-09T{hour:02d}:00:07Z",
                "ended_at": f"2026-07-09T{hour:02d}:00:09Z",
                "source": "harness_trace",
                "source_artifact_id": f"{prefix}-behavior",
                "result": "success",
                "failure_code": None,
            },
        ]
        summary = {
            "event_count": 3,
            "phases_observed": ["understand", "act", "verify"],
            "successful_phases": ["understand", "act", "verify"],
            "failed_phases": [],
            "skipped_phases": [],
            "failure_count": 0,
            "recovery_attempted": False,
            "recovery_succeeded": None,
        }
        outcomes = {
            "evaluator_passed": bool(success),
            "evaluated_by_sha256": self.manifest["evaluation"]["evaluator"]["artifact"][
                "sha256"
            ],
            "evaluator_artifact_id": f"{prefix}-evaluator",
            "metrics": [
                {
                    "metric_id": "task_success",
                    "numerator": success,
                    "denominator": 1,
                    "value": float(success),
                    "unit": "proportion",
                    "source_artifact_id": f"{prefix}-evaluator",
                },
                {
                    "metric_id": "catastrophic_write_rate",
                    "numerator": 0,
                    "denominator": 1,
                    "value": 0.0,
                    "unit": "proportion",
                    "source_artifact_id": f"{prefix}-evaluator",
                }
            ],
        }
        claim = self.manifest["claim_plan"]
        state_capture = {
            "collector_sha256": self.manifest["state_capture"]["collector"]["artifact"][
                "sha256"
            ],
            "starting": {
                "invocation_id": f"{prefix}-state-start",
                "captured_at": timestamps["started_at"],
            },
            "final": {
                "invocation_id": f"{prefix}-state-final",
                "captured_at": timestamps["completed_at"],
            },
        }
        run = {
            "schema_version": "drupal_agent_readiness.benchmark_run.v1",
            "run_id": prefix,
            "experiment_id": self.manifest["experiment_id"],
            "experiment_manifest_sha256": canonical_sha256(self.manifest),
            "governance": copy.deepcopy(self.manifest["governance"]),
            "lane": "fixed_regression",
            "task": copy.deepcopy(self.manifest["task"]),
            "arm": {
                "arm_id": arm["arm_id"],
                "role": role,
                "treatment_sha256": arm["treatment"]["artifact"]["sha256"],
                "drupal_state": copy.deepcopy(arm["drupal_state"]),
            },
            "final_drupal_state": copy.deepcopy(arm["drupal_state"]),
            "attempt": {
                "roster_slot_id": slot_id,
                "index": index,
                "unit_id": unit_id,
                "pair_id": pair_id,
                "order_in_pair": order,
            },
            "timestamps": timestamps,
            "agent_stack": copy.deepcopy(self.manifest["reference_agent_stack"]),
            "substrate": copy.deepcopy(self.manifest["substrate"]),
            "state_capture": state_capture,
            "evaluation": copy.deepcopy(self.manifest["evaluation"]),
            "budget": copy.deepcopy(self.manifest["budget"]),
            "costs": costs,
            "validity": validity,
            "behavior_events": events,
            "behavior_summary": summary,
            "artifacts": [],
            "outcomes": outcomes,
            "claim_context": {
                "claim_class": claim["claim_class"],
                "primary_metric_id": claim["primary_metric_id"],
                "estimand": claim["estimand"],
                "planned_denominator": claim["planned_denominator"],
                "denominator_unit": claim["denominator_unit"],
                "confidence": copy.deepcopy(claim["confidence"]),
                "minimum_favorable_effect": claim["minimum_favorable_effect"],
                "decision_rule": claim["decision_rule"],
                "inference_scope": copy.deepcopy(self.manifest["inference_scope"]),
                "sampling_design": copy.deepcopy(self.manifest["sampling_design"]),
                "guardrails": copy.deepcopy(claim["guardrails"]),
            },
        }

        starting_state = {
            "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
            "run_id": run["run_id"],
            "moment": "starting",
            "arm_id": run["arm"]["arm_id"],
            "roster_slot_id": slot_id,
            "unit_id": unit_id,
            "collector_sha256": state_capture["collector_sha256"],
            "collector_invocation_id": state_capture["starting"]["invocation_id"],
            "captured_at": state_capture["starting"]["captured_at"],
            "drupal_state": run["arm"]["drupal_state"],
        }
        final_state = {
            "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
            "run_id": run["run_id"],
            "moment": "final",
            "arm_id": run["arm"]["arm_id"],
            "roster_slot_id": slot_id,
            "unit_id": unit_id,
            "collector_sha256": state_capture["collector_sha256"],
            "collector_invocation_id": state_capture["final"]["invocation_id"],
            "captured_at": state_capture["final"]["captured_at"],
            "drupal_state": run["final_drupal_state"],
        }
        semantic_documents = {
            "cost_trace": costs,
            "behavior_trace": {"events": events, "summary": summary},
            "evaluator_output": outcomes,
            "validity_decision": validity,
            "starting_state": starting_state,
            "final_state": final_state,
        }
        task_prompt = (
            self.root / self.manifest["task"]["prompt"]["uri"]
        ).read_text(encoding="utf-8")
        system_prompt = (
            self.root
            / self.manifest["reference_agent_stack"]["system_prompt"]["uri"]
        ).read_text(encoding="utf-8")
        render_inputs_path = (
            self.root / self.manifest["prompt_composition"]["render_inputs"]["uri"]
        )
        render_inputs_bytes = render_inputs_path.read_bytes()
        render_inputs_document = json.loads(render_inputs_bytes)
        prompt_envelope = {
            "schema_version": "drupal_agent_readiness.prompt_envelope.v1",
            "task_prompt": task_prompt,
            "system_prompt": system_prompt,
            "render_inputs": render_inputs_document,
        }
        raw_artifacts = [
            (
                f"{prefix}-prompt",
                "prompt",
                canonical_json_bytes(prompt_envelope),
                "application/json",
            ),
            (
                f"{prefix}-render-inputs",
                "render_inputs",
                render_inputs_bytes,
                "application/json",
            ),
            (
                f"{prefix}-transcript",
                "transcript",
                f"instrumented transcript for {prefix}\n".encode("utf-8"),
                "text/plain",
            ),
            (
                f"{prefix}-tools",
                "tool_log",
                f'{{"run_id":"{prefix}","tool":"inspect"}}\n'.encode("utf-8"),
                "application/jsonl",
            ),
            (
                f"{prefix}-answer",
                "answer",
                canonical_json_bytes({"answer": "recorded", "run_id": prefix}),
                "application/json",
            ),
            (
                f"{prefix}-attempt-stdout",
                "attempt_stdout",
                f"codex stdout for {prefix}\n".encode("utf-8"),
                "text/plain",
            ),
            (
                f"{prefix}-attempt-stderr",
                "attempt_stderr",
                b"",
                "text/plain",
            ),
        ]
        for artifact_id, kind, payload, media_type in raw_artifacts:
            run["artifacts"].append(
                self._write_artifact(prefix, artifact_id, kind, payload, media_type)
            )
        semantic_ids = {
            "cost_trace": f"{prefix}-cost",
            "behavior_trace": f"{prefix}-behavior",
            "evaluator_output": f"{prefix}-evaluator",
            "validity_decision": f"{prefix}-validity",
            "starting_state": f"{prefix}-starting",
            "final_state": f"{prefix}-final",
        }
        for kind, document in semantic_documents.items():
            run["artifacts"].append(
                self._write_artifact(
                    prefix,
                    semantic_ids[kind],
                    kind,
                    canonical_json_bytes(document),
                    "application/json",
                )
            )

        artifact_by_kind = {
            artifact["kind"]: artifact for artifact in run["artifacts"]
        }
        prompt_delivery = {
            "source": "harness_instrumentation",
            "invocation_id": f"{prefix}-prompt-delivery",
            "delivered_at": timestamps["started_at"],
            "task_id": run["task"]["id"],
            "task_version": run["task"]["version"],
            "task_prompt_sha256": run["task"]["prompt"]["sha256"],
            "system_prompt_sha256": run["agent_stack"]["system_prompt"]["sha256"],
            "renderer_sha256": self.manifest["prompt_composition"]["renderer"][
                "artifact"
            ]["sha256"],
            "render_inputs_artifact_id": artifact_by_kind["render_inputs"][
                "artifact_id"
            ],
            "render_inputs_sha256": artifact_by_kind["render_inputs"]["sha256"],
            "rendered_prompt_artifact_id": artifact_by_kind["prompt"]["artifact_id"],
            "rendered_prompt_sha256": artifact_by_kind["prompt"]["sha256"],
            "receipt_artifact_id": f"{prefix}-prompt-receipt",
            "recipient": {
                "agent_id": run["agent_stack"]["agent"]["id"],
                "model_provider": run["agent_stack"]["model"]["provider"],
                "model_id": run["agent_stack"]["model"]["id"],
                "model_snapshot": run["agent_stack"]["model"]["snapshot"],
            },
        }
        run["prompt_delivery"] = prompt_delivery
        prompt_receipt_document = {
            "schema_version": "drupal_agent_readiness.prompt_delivery_receipt.v1",
            "run_id": run["run_id"],
            **prompt_delivery,
        }
        run["artifacts"].append(
            self._write_artifact(
                prefix,
                prompt_delivery["receipt_artifact_id"],
                "prompt_receipt",
                canonical_json_bytes(prompt_receipt_document),
                "application/json",
            )
        )
        artifact_by_kind = {
            artifact["kind"]: artifact for artifact in run["artifacts"]
        }
        execution_invocation_id = f"{prefix}-execution"
        execution_argv = [
            "codex",
            "exec",
            "--json",
            run["agent_stack"]["model"]["backend_identity_contract"][
                "required_invocation_argument"
            ],
            "--",
        ]
        execution_thread_id = f"thread-{prefix}"
        execution_provider_request_id = f"provider-request-{prefix}"
        inference_parameters_path = (
            self.root
            / run["agent_stack"]["model"]["inference_parameters"]["uri"]
        )
        inference_parameters = json.loads(
            inference_parameters_path.read_text(encoding="utf-8")
        )
        policy_tool = next(
            tool
            for tool in run["agent_stack"]["tools"]
            if tool["id"] == "execution-environment-policy"
        )
        policy_document = json.loads(
            (self.root / policy_tool["artifact"]["uri"]).read_text(
                encoding="utf-8"
            )
        )
        system_manifest = policy_document["system_skills_preflight"]["manifest"]
        auth_path = policy_document["system_skills_preflight"]["host_read_denials"][
            "auth_file"
        ]["path"]
        runtime_layout = fake_runtime_layout_document(
            system_manifest,
            auth_path=auth_path,
        )
        attempt_receipt_document = {
            "schema_version": "drupal_agent_readiness.frontier_attempt_receipt.v1",
            "run_id": run["run_id"],
            "roster_slot_id": slot_id,
            "attempt_id": execution_invocation_id,
            "argv": execution_argv,
            "status": "succeeded",
            "returncode": 0,
            "timed_out": False,
            "thread_id": execution_thread_id,
            "provider_request_id": execution_provider_request_id,
            "provider_request_id_status": "verified_distinct",
            "environment_policy_sha256": inference_parameters[
                "execution_environment_policy_sha256"
            ],
            "runtime_home_verification": {
                "before_home_mode": "0o700",
                "after_home_mode": "0o700",
                "before_home_identity_verified": True,
                "after_home_identity_verified": True,
                "before_home_mode_verified": True,
                "after_home_mode_verified": True,
                "before_layout_verified": True,
                "after_layout_verified": True,
                "before_layout_sha256": runtime_layout["tree_sha256"],
                "after_layout_sha256": runtime_layout["tree_sha256"],
                "before_layout_document": runtime_layout,
                "after_layout_document": runtime_layout,
                "before_auth_reference_verified": True,
                "after_auth_reference_verified": True,
                "before_profile_regular_file_verified": True,
                "after_profile_regular_file_verified": True,
                "before_sentinel_regular_file_verified": True,
                "after_sentinel_regular_file_verified": True,
                "before_forbidden_entries": [],
                "after_forbidden_entries": [],
                "before_system_skills_verified": True,
                "after_system_skills_verified": True,
                "system_skills_tree_sha256": system_manifest["tree_sha256"],
            },
            "process_containment": {
                "status": "verified",
                "policy_sha256": canonical_sha256(
                    fake_process_containment_policy()
                ),
                "sandbox_sha256": fake_process_containment_policy()[
                    "sandbox_sha256"
                ],
                "child_process_creation_denied": True,
                "inner_argv": execution_argv,
                "outer_argv": [
                    fake_process_containment_policy()["sandbox_binary"],
                    "-p",
                    fake_process_containment_policy()["profile"],
                    *execution_argv,
                ],
            },
            "stdout_artifact_id": artifact_by_kind["attempt_stdout"]["artifact_id"],
            "stdout_sha256": artifact_by_kind["attempt_stdout"]["sha256"],
            "stderr_artifact_id": artifact_by_kind["attempt_stderr"]["artifact_id"],
            "stderr_sha256": artifact_by_kind["attempt_stderr"]["sha256"],
        }
        run["artifacts"].append(
            self._write_artifact(
                prefix,
                f"{prefix}-attempt-receipt",
                "attempt_receipt",
                canonical_json_bytes(attempt_receipt_document),
                "application/json",
            )
        )
        artifact_by_kind = {
            artifact["kind"]: artifact for artifact in run["artifacts"]
        }
        identity_contract = run["agent_stack"]["model"][
            "backend_identity_contract"
        ]
        model_identity_receipt = {
            "status": "local_artifact_hash_verified",
            "source": "trusted_local_runner_attestation",
            "model_provider": run["agent_stack"]["model"]["provider"],
            "model_id": run["agent_stack"]["model"]["id"],
            "declared_selector": run["agent_stack"]["model"]["snapshot"],
            "backend_identity": identity_contract["expected_backend_identity"],
            "provider_request_id": execution_provider_request_id,
            "attestation_contract_sha256": None,
            "local_model_artifact_sha256": identity_contract[
                "local_model_artifact"
            ]["sha256"],
            "runner_attestation_contract_sha256": identity_contract[
                "runner_attestation_contract"
            ]["artifact"]["sha256"],
            "observed_at": timestamps["completed_at"],
            "receipt_artifact_id": f"{prefix}-model-identity-receipt",
        }
        run["model_identity_receipt"] = model_identity_receipt
        run["artifacts"].append(
            self._write_artifact(
                prefix,
                model_identity_receipt["receipt_artifact_id"],
                "model_identity_receipt",
                canonical_json_bytes({
                    "schema_version": (
                        "drupal_agent_readiness.model_identity_receipt.v1"
                    ),
                    "run_id": run["run_id"],
                    **model_identity_receipt,
                }),
                "application/json",
            )
        )
        artifact_by_kind = {
            artifact["kind"]: artifact for artifact in run["artifacts"]
        }
        execution_receipt = {
            "source": "harness_instrumentation",
            "invocation_id": execution_invocation_id,
            "provider_request_id": execution_provider_request_id,
            "provider_request_id_status": "verified_distinct",
            "started_at": timestamps["started_at"],
            "completed_at": timestamps["completed_at"],
            "roster_slot_id": slot_id,
            "argv": execution_argv,
            "thread_id": execution_thread_id,
            "harness_sha256": run["agent_stack"]["harness"]["artifact"]["sha256"],
            "prompt_receipt_sha256": artifact_by_kind["prompt_receipt"]["sha256"],
            "artifact_hashes": {
                kind: artifact_by_kind[kind]["sha256"]
                for kind in (
                    "prompt",
                    "render_inputs",
                    "transcript",
                    "tool_log",
                    "answer",
                    "starting_state",
                    "final_state",
                    "cost_trace",
                    "behavior_trace",
                    "validity_decision",
                    "attempt_receipt",
                    "model_identity_receipt",
                )
            },
            "receipt_artifact_id": f"{prefix}-execution-receipt",
        }
        run["execution_receipt"] = execution_receipt
        execution_receipt_document = {
            "schema_version": "drupal_agent_readiness.execution_receipt.v1",
            "run_id": run["run_id"],
            **execution_receipt,
        }
        run["artifacts"].append(
            self._write_artifact(
                prefix,
                execution_receipt["receipt_artifact_id"],
                "execution_receipt",
                canonical_json_bytes(execution_receipt_document),
                "application/json",
            )
        )
        artifact_by_kind = {
            artifact["kind"]: artifact for artifact in run["artifacts"]
        }
        issuer = run["evaluation"]["assurance"]["trusted_issuer"]
        evaluator_receipt = {
            "source": "independent_evaluator_harness",
            "issuer_id": issuer["id"],
            "issuer_version": issuer["version"],
            "issuer_sha256": issuer["artifact"]["sha256"],
            "invocation_id": f"{prefix}-evaluation",
            "started_at": timestamps["evaluation_started_at"],
            "completed_at": timestamps["evaluation_completed_at"],
            "exit_code": 0,
            "input_hashes": {
                "answer": artifact_by_kind["answer"]["sha256"],
                "ground_truth": run["task"]["ground_truth"]["sha256"],
                "final_state": artifact_by_kind["final_state"]["sha256"],
                "tool_log": artifact_by_kind["tool_log"]["sha256"],
            },
            "evaluator_sha256": run["evaluation"]["evaluator"]["artifact"][
                "sha256"
            ],
            "output_artifact_id": artifact_by_kind["evaluator_output"]["artifact_id"],
            "output_sha256": artifact_by_kind["evaluator_output"]["sha256"],
            "receipt_artifact_id": f"{prefix}-evaluator-receipt",
        }
        run["evaluator_receipt"] = evaluator_receipt
        evaluator_receipt_document = {
            "schema_version": "drupal_agent_readiness.evaluator_receipt.v1",
            "run_id": run["run_id"],
            **evaluator_receipt,
        }
        run["artifacts"].append(
            self._write_artifact(
                prefix,
                evaluator_receipt["receipt_artifact_id"],
                "evaluator_receipt",
                canonical_json_bytes(evaluator_receipt_document),
                "application/json",
            )
        )
        return run

    def _write_artifact(
        self, prefix: str, artifact_id: str, kind: str, payload: bytes, media_type: str
    ) -> dict:
        path = self.root / "runs" / prefix / f"{artifact_id}.data"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return {
            "artifact_id": artifact_id,
            "kind": kind,
            "uri": str(path.relative_to(self.root)),
            "sha256": file_sha256(path),
            "media_type": media_type,
            "byte_size": path.stat().st_size,
        }

    def _artifact(self, run: dict, kind: str) -> dict:
        return next(artifact for artifact in run["artifacts"] if artifact["kind"] == kind)

    def _attempt_receipt_document(self, run: dict) -> dict:
        artifact = self._artifact(run, "attempt_receipt")
        return json.loads((self.root / artifact["uri"]).read_text(encoding="utf-8"))

    def _rewrite_attempt_receipt_and_execution_binding(
        self, run: dict, receipt: dict
    ) -> None:
        self._rewrite_semantic_artifact(run, "attempt_receipt", receipt)
        run["execution_receipt"]["artifact_hashes"]["attempt_receipt"] = self._artifact(
            run, "attempt_receipt"
        )["sha256"]
        self._rewrite_semantic_artifact(
            run,
            "execution_receipt",
            {
                "schema_version": "drupal_agent_readiness.execution_receipt.v1",
                "run_id": run["run_id"],
                **run["execution_receipt"],
            },
        )

    def _rewrite_semantic_artifact(self, run: dict, kind: str, document: dict) -> None:
        artifact = self._artifact(run, kind)
        path = self.root / artifact["uri"]
        path.write_bytes(canonical_json_bytes(document))
        artifact["sha256"] = file_sha256(path)
        artifact["byte_size"] = path.stat().st_size

    def _refresh_receipts(self, run: dict) -> None:
        state = run["state_capture"]
        for moment, state_key, invocation_key in (
            ("starting", "arm", "starting"),
            ("final", "final_drupal_state", "final"),
        ):
            drupal_state = (
                run[state_key]["drupal_state"] if state_key == "arm" else run[state_key]
            )
            self._rewrite_semantic_artifact(
                run,
                f"{moment}_state",
                {
                    "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
                    "run_id": run["run_id"],
                    "moment": moment,
                    "arm_id": run["arm"]["arm_id"],
                    "roster_slot_id": run["attempt"]["roster_slot_id"],
                    "unit_id": run["attempt"]["unit_id"],
                    "collector_sha256": state["collector_sha256"],
                    "collector_invocation_id": state[invocation_key]["invocation_id"],
                    "captured_at": state[invocation_key]["captured_at"],
                    "drupal_state": drupal_state,
                },
            )
        self._rewrite_semantic_artifact(
            run,
            "prompt_receipt",
            {
                "schema_version": "drupal_agent_readiness.prompt_delivery_receipt.v1",
                "run_id": run["run_id"],
                **run["prompt_delivery"],
            },
        )
        identity = run["model_identity_receipt"]
        model = run["agent_stack"]["model"]
        contract = model["backend_identity_contract"]
        execution = run["execution_receipt"]
        identity.update({
            "model_provider": model["provider"],
            "model_id": model["id"],
            "declared_selector": model["snapshot"],
            "provider_request_id": execution["provider_request_id"],
            "observed_at": run["timestamps"]["completed_at"],
        })
        self._rewrite_semantic_artifact(
            run,
            "model_identity_receipt",
            {
                "schema_version": "drupal_agent_readiness.model_identity_receipt.v1",
                "run_id": run["run_id"],
                **identity,
            },
        )
        artifacts = {artifact["kind"]: artifact for artifact in run["artifacts"]}
        execution["roster_slot_id"] = run["attempt"]["roster_slot_id"]
        execution["prompt_receipt_sha256"] = artifacts["prompt_receipt"]["sha256"]
        attempt_path = self.root / artifacts["attempt_receipt"]["uri"]
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        inference_path = (
            self.root
            / run["agent_stack"]["model"]["inference_parameters"]["uri"]
        )
        inference_parameters = json.loads(inference_path.read_text(encoding="utf-8"))
        attempt.update({
            "run_id": run["run_id"],
            "roster_slot_id": run["attempt"]["roster_slot_id"],
            "attempt_id": execution["invocation_id"],
            "argv": execution["argv"],
            "thread_id": execution["thread_id"],
            "provider_request_id": execution["provider_request_id"],
            "provider_request_id_status": execution[
                "provider_request_id_status"
            ],
            "environment_policy_sha256": inference_parameters[
                "execution_environment_policy_sha256"
            ],
            "stdout_artifact_id": artifacts["attempt_stdout"]["artifact_id"],
            "stdout_sha256": artifacts["attempt_stdout"]["sha256"],
            "stderr_artifact_id": artifacts["attempt_stderr"]["artifact_id"],
            "stderr_sha256": artifacts["attempt_stderr"]["sha256"],
        })
        self._rewrite_semantic_artifact(run, "attempt_receipt", attempt)
        artifacts = {artifact["kind"]: artifact for artifact in run["artifacts"]}
        execution["artifact_hashes"] = {
            kind: artifacts[kind]["sha256"]
            for kind in (
                "prompt",
                "render_inputs",
                "transcript",
                "tool_log",
                "answer",
                "starting_state",
                "final_state",
                "cost_trace",
                "behavior_trace",
                "validity_decision",
                "attempt_receipt",
                "model_identity_receipt",
            )
        }
        self._rewrite_semantic_artifact(
            run,
            "execution_receipt",
            {
                "schema_version": "drupal_agent_readiness.execution_receipt.v1",
                "run_id": run["run_id"],
                **execution,
            },
        )
        artifacts = {artifact["kind"]: artifact for artifact in run["artifacts"]}
        evaluator = run["evaluator_receipt"]
        evaluator["input_hashes"] = {
            "answer": artifacts["answer"]["sha256"],
            "ground_truth": run["task"]["ground_truth"]["sha256"],
            "final_state": artifacts["final_state"]["sha256"],
            "tool_log": artifacts["tool_log"]["sha256"],
        }
        evaluator["output_sha256"] = artifacts["evaluator_output"]["sha256"]
        self._rewrite_semantic_artifact(
            run,
            "evaluator_receipt",
            {
                "schema_version": "drupal_agent_readiness.evaluator_receipt.v1",
                "run_id": run["run_id"],
                **evaluator,
            },
        )

    def _set_success(self, run: dict, value: int) -> None:
        run["outcomes"]["evaluator_passed"] = bool(value)
        metric = run["outcomes"]["metrics"][0]
        metric["numerator"] = value
        metric["value"] = float(value)
        self._rewrite_semantic_artifact(run, "evaluator_output", run["outcomes"])
        output = self._artifact(run, "evaluator_output")
        run["evaluator_receipt"]["output_sha256"] = output["sha256"]
        self._rewrite_semantic_artifact(
            run,
            "evaluator_receipt",
            {
                "schema_version": "drupal_agent_readiness.evaluator_receipt.v1",
                "run_id": run["run_id"],
                **run["evaluator_receipt"],
            },
        )

    def _set_metric(self, run: dict, metric_id: str, numerator: float, denominator: float = 1) -> None:
        metric = next(
            item for item in run["outcomes"]["metrics"] if item["metric_id"] == metric_id
        )
        metric["numerator"] = numerator
        metric["denominator"] = denominator
        metric["value"] = numerator / denominator
        self._rewrite_semantic_artifact(run, "evaluator_output", run["outcomes"])
        self._refresh_receipts(run)

    def _set_cost(self, run: dict, metric_id: str, value: int) -> None:
        run["costs"][metric_id] = value
        self._rewrite_semantic_artifact(run, "cost_trace", run["costs"])
        self._refresh_receipts(run)

    def _rebind_runs_to_manifest(self, manifest: dict, runs: list[dict]) -> None:
        claim = manifest["claim_plan"]
        for run in runs:
            run["experiment_id"] = manifest["experiment_id"]
            run["governance"] = copy.deepcopy(manifest["governance"])
            run["task"] = copy.deepcopy(manifest["task"])
            run["substrate"] = copy.deepcopy(manifest["substrate"])
            run["evaluation"] = copy.deepcopy(manifest["evaluation"])
            run["budget"] = copy.deepcopy(manifest["budget"])
            run["costs"]["cost_status"] = manifest["cost_measurement"]["mode"]
            run["costs"]["price_schedule_sha256"] = (
                manifest["cost_measurement"]["price_schedule"]["sha256"]
                if manifest["cost_measurement"]["price_schedule"] is not None
                else None
            )
            run["claim_context"] = {
                "claim_class": claim["claim_class"],
                "primary_metric_id": claim["primary_metric_id"],
                "estimand": claim["estimand"],
                "planned_denominator": claim["planned_denominator"],
                "denominator_unit": claim["denominator_unit"],
                "confidence": copy.deepcopy(claim["confidence"]),
                "minimum_favorable_effect": claim["minimum_favorable_effect"],
                "decision_rule": claim["decision_rule"],
                "inference_scope": copy.deepcopy(manifest["inference_scope"]),
                "sampling_design": copy.deepcopy(manifest["sampling_design"]),
                "guardrails": copy.deepcopy(claim["guardrails"]),
            }
            run["experiment_manifest_sha256"] = canonical_sha256(manifest)
            run["prompt_delivery"]["task_id"] = manifest["task"]["id"]
            run["prompt_delivery"]["task_version"] = manifest["task"]["version"]
            run["prompt_delivery"]["task_prompt_sha256"] = manifest["task"]["prompt"][
                "sha256"
            ]
            run["prompt_delivery"]["renderer_sha256"] = manifest[
                "prompt_composition"
            ]["renderer"]["artifact"]["sha256"]
            run["prompt_delivery"]["render_inputs_sha256"] = manifest[
                "prompt_composition"
            ]["render_inputs"]["sha256"]
            run["state_capture"]["collector_sha256"] = manifest["state_capture"][
                "collector"
            ]["artifact"]["sha256"]
            self._refresh_receipts(run)

    def _commit_manifest(
        self,
        manifest: dict,
        *,
        repo_name: str = "registration-repo",
        commit_date: str = "2026-07-09T09:30:00+00:00",
    ) -> GitRegistrationAnchor:
        repo = self.root / repo_name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Benchmark Registry"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "registry@example.invalid"],
            check=True,
        )
        manifest_path = repo / manifest["registration"]["manifest_path"]
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        subprocess.run(["git", "-C", str(repo), "add", manifest["registration"]["manifest_path"]], check=True)
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_AUTHOR_DATE": commit_date,
                "GIT_COMMITTER_DATE": commit_date,
            }
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "Register benchmark manifest"],
            check=True,
            env=environment,
        )
        commit = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return GitRegistrationAnchor(
            repo_path=repo,
            commit=commit,
            manifest_path=manifest["registration"]["manifest_path"],
        )


if __name__ == "__main__":
    unittest.main()
