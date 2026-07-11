import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_readiness.tests.test_published_experiments import (
    build_git_measurement_registry,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


def independent_run(run_id: str) -> dict:
    run = copy.deepcopy(load_fixture("run_result_inventory_pass.json"))
    run["run_id"] = run_id
    run["agent"] = {
        "name": "Independent Codex",
        "model": "gpt-5",
        "harness": "fresh Codex thread",
        "tooling": ["shell", "drush"],
    }
    run["metrics"]["human_rescues"] = 0
    run["artifacts"] = {
        role: f"runs/{run_id}/{Path(path).name}"
        for role, path in run["artifacts"].items()
    }
    return run


def independent_task_run(run_id: str, task_id: str) -> dict:
    run = independent_run(run_id)
    run["task_id"] = task_id
    return run


class ReadinessTest(unittest.TestCase):

    def test_smoke_only_package_is_private_ready_but_not_public_v0_package_ready(self) -> None:
        from agent_readiness.readiness import audit_readiness

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            smoke = load_fixture("run_result_inventory_pass.json")
            smoke["run_id"] = "haven-inventory-v0-tooling-smoke"
            smoke["artifacts"] = {
                role: f"runs/{smoke['run_id']}/{Path(path).name}"
                for role, path in smoke["artifacts"].items()
            }
            smoke["agent"] = {
                "name": "Tooling smoke",
                "model": "none",
                "harness": "local evaluator scripts",
            }
            self._write_minimal_publish_assets(base, [smoke])

            report = audit_readiness(base, [smoke])

        self.assertTrue(report["private_circulation_ready"])
        self.assertFalse(report["public_v0_package_ready"])
        self.assertFalse(report["estimate_ready"])
        self.assertIn(
            "no-rescue non-smoke inventory examples: 0/1",
            report["public_v0_package_errors"],
        )

    def test_three_legacy_examples_do_not_make_an_estimate_ready(self) -> None:
        from agent_readiness.readiness import audit_readiness

        runs = [
            independent_run("inventory-pass-001"),
            independent_run("inventory-pass-002"),
            independent_run("inventory-pass-003"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_minimal_publish_assets(base, runs)

            report = audit_readiness(base, runs)

        self.assertTrue(report["private_circulation_ready"])
        self.assertTrue(report["public_v0_package_ready"])
        self.assertTrue(report["legacy_example_count_gate_passed"])
        self.assertFalse(report["estimate_ready"])
        self.assertFalse(report["fixed_estimate_ready"])
        self.assertFalse(report["improvement_ready"])
        self.assertEqual([], report["public_v0_package_errors"])
        self.assertIn(
            "no source-audited measurement_v1 experiment",
            report["estimate_errors"][0],
        )

    def test_source_audited_fixed_null_is_estimate_eligible_not_improvement(self) -> None:
        from agent_readiness.readiness import audit_readiness

        runs = [independent_run("inventory-pass-001")]
        fixture, registry_path = build_git_measurement_registry(improvement=False)
        try:
            self._write_minimal_publish_assets(
                fixture.root, runs
            )
            report = audit_readiness(fixture.root, runs)
        finally:
            fixture.tearDown()

        self.assertTrue(report["estimate_ready"])
        self.assertTrue(report["fixed_estimate_ready"])
        self.assertFalse(report["improvement_ready"])
        self.assertEqual(
            ["path-ownership-regression@v1"],
            report["estimate_eligible_experiments"],
        )
        self.assertEqual(
            ["path-ownership-regression@v1"],
            report["fixed_estimate_eligible_experiments"],
        )
        self.assertEqual([], report["registered_effect_rule_met_experiments"])
        self.assertEqual([], report["improvement_ready_experiments"])

    def test_effect_rule_does_not_bypass_canonical_action_registry(self) -> None:
        from agent_readiness.readiness import audit_readiness

        runs = [independent_run("inventory-pass-001")]
        fixture, registry_path = build_git_measurement_registry()
        try:
            self._write_minimal_publish_assets(
                fixture.root, runs
            )
            report = audit_readiness(fixture.root, runs)
        finally:
            fixture.tearDown()

        self.assertTrue(report["estimate_ready"])
        self.assertTrue(report["fixed_estimate_ready"])
        self.assertFalse(report["improvement_ready"])
        self.assertEqual(
            ["path-ownership-regression@v1"],
            report["registered_effect_rule_met_experiments"],
        )
        self.assertEqual([], report["improvement_ready_experiments"])
        eligibility = report["experiment_eligibility"][0]
        self.assertTrue(eligibility["estimate_reportable"])
        self.assertTrue(eligibility["fixed_estimate_reportable"])
        self.assertTrue(eligibility["registered_effect_rule_met"])
        self.assertFalse(eligibility["action_registry_binding_verified"])
        self.assertFalse(eligibility["improvement_ready"])

    def test_readiness_has_no_published_bundle_injection_parameter(self) -> None:
        from agent_readiness.readiness import audit_readiness

        runs = [independent_run("inventory-pass-001")]
        with self.assertRaisesRegex(TypeError, "published_experiments"):
            audit_readiness(
                Path("."),
                runs,
                published_experiments={"experiments": []},
            )

    def test_readiness_thresholds_cannot_be_weakened(self) -> None:
        from agent_readiness.readiness import audit_readiness

        with self.assertRaisesRegex(ValueError, "cannot be lower than 1"):
            audit_readiness(Path("."), [], public_required_passes=0)
        with self.assertRaisesRegex(ValueError, "cannot be lower than 3"):
            audit_readiness(Path("."), [], legacy_example_required_passes=2)

        command = [
            sys.executable,
            "agent_readiness/scripts/audit_readiness.py",
            "--base-dir",
            "agent_readiness",
            "--run-result",
            str(FIXTURES / "run_result_inventory_pass.json"),
            "--public-required-passes",
            "0",
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("must be at least 1", result.stderr)

    def test_readiness_reloads_registry_on_every_audit(self) -> None:
        from agent_readiness.readiness import audit_readiness

        runs = [independent_run("inventory-pass-001")]
        fixture, registry_path = build_git_measurement_registry(improvement=False)
        try:
            self._write_minimal_publish_assets(
                fixture.root,
                runs,
            )
            complete = audit_readiness(fixture.root, runs)
            self.assertTrue(
                complete["experiment_eligibility"][0]["estimate_reportable"]
            )

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["experiments"][0]["sources"]["runs"].pop()
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            incomplete = audit_readiness(fixture.root, runs)
            self.assertFalse(
                incomplete["experiment_eligibility"][0]["estimate_reportable"]
            )
            self.assertFalse(incomplete["estimate_ready"])
        finally:
            fixture.tearDown()

    def test_generated_snapshot_cannot_claim_current_readiness_after_package_file_is_deleted(self) -> None:
        from agent_readiness.readiness import audit_readiness

        run = independent_run("inventory-pass-001")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_minimal_publish_assets(base, [run])
            snapshot = json.loads(
                (base / "public/readiness.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "drupal_agent_readiness.source_gate_snapshot.v1",
                snapshot["artifact_kind"],
            )
            self.assertFalse(snapshot["authoritative_package_audit"])
            self.assertEqual("not_run", snapshot["package_audit"]["status"])
            self.assertIsNone(snapshot["public_evidence_package_ready"])
            self.assertIsNone(snapshot["publication_errors"])

            (base / "tasks.yml").unlink()
            live = audit_readiness(base, [run])

        self.assertFalse(live["public_evidence_package_ready"])
        self.assertIn("missing publish asset: tasks.yml", live["publication_errors"])

    def test_cli_promotion_gates_require_named_source_audited_experiment(self) -> None:
        runs = [independent_run("inventory-pass-001")]
        fixture, registry_path = build_git_measurement_registry()
        null_fixture, null_registry_path = build_git_measurement_registry(
            improvement=False
        )
        cli_tmp = tempfile.TemporaryDirectory()
        try:
            self._write_minimal_publish_assets(
                fixture.root, runs
            )
            null_runs = [independent_run("inventory-pass-001")]
            self._write_minimal_publish_assets(null_fixture.root, null_runs)
            run_path = Path(cli_tmp.name) / "cli-run.json"
            run_path.write_text(json.dumps(runs[0]), encoding="utf-8")
            null_run_path = Path(cli_tmp.name) / "cli-null-run.json"
            null_run_path.write_text(json.dumps(null_runs[0]), encoding="utf-8")
            base_command = [
                sys.executable,
                "agent_readiness/scripts/audit_readiness.py",
                "--base-dir",
                str(fixture.root),
                "--run-result",
                str(run_path),
            ]
            null_base_command = [
                sys.executable,
                "agent_readiness/scripts/audit_readiness.py",
                "--base-dir",
                str(null_fixture.root),
                "--run-result",
                str(null_run_path),
            ]
            estimate = subprocess.run(
                [*base_command, "--require-estimate", "path-ownership-regression@v1"],
                capture_output=True,
                text=True,
                check=False,
            )
            fixed = subprocess.run(
                [
                    *base_command,
                    "--require-fixed-estimate",
                    "path-ownership-regression@v1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            effect = subprocess.run(
                [
                    *base_command,
                    "--require-effect-rule",
                    "path-ownership-regression@v1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            effect_failed = subprocess.run(
                [
                    *null_base_command,
                    "--require-effect-rule",
                    "path-ownership-regression@v1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            improvement = subprocess.run(
                [*base_command, "--require-improvement", "path-ownership-regression@v1"],
                capture_output=True,
                text=True,
                check=False,
            )
            unknown = subprocess.run(
                [*base_command, "--require-effect-rule", "not-registered"],
                capture_output=True,
                text=True,
                check=False,
            )
            unnamed = subprocess.run(
                [*base_command, "--require-estimate"],
                capture_output=True,
                text=True,
                check=False,
            )
            removed_claim_alias = subprocess.run(
                [
                    *base_command,
                    "--require-claim-grade",
                    "path-ownership-regression@v1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            removed_longitudinal_alias = subprocess.run(
                [
                    *base_command,
                    "--require-longitudinal",
                    "path-ownership-regression@v1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            cli_tmp.cleanup()
            fixture.tearDown()
            null_fixture.tearDown()

        self.assertEqual(0, estimate.returncode, estimate.stdout + estimate.stderr)
        self.assertEqual(0, fixed.returncode, fixed.stdout + fixed.stderr)
        self.assertEqual(0, effect.returncode, effect.stdout + effect.stderr)
        self.assertEqual(
            [{
                "experiment_id": "path-ownership-regression@v1",
                "gate": "effect_rule",
                "known_experiment": True,
                "satisfied": True,
                "status_field": "registered_effect_rule_met",
            }],
            json.loads(effect.stdout)["promotion_gates"],
        )
        self.assertEqual(1, effect_failed.returncode)
        self.assertEqual(1, improvement.returncode)
        self.assertEqual(1, unknown.returncode)
        self.assertEqual(2, unnamed.returncode)
        self.assertEqual(2, removed_claim_alias.returncode)
        self.assertEqual(2, removed_longitudinal_alias.returncode)

    def test_cli_rejects_duplicate_nonfinite_and_malformed_run_json_cleanly(self) -> None:
        runs = [independent_run("inventory-pass-001")]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_minimal_publish_assets(base, runs)
            valid_json = json.dumps(runs[0])
            duplicate_json = (
                '{"run_id": "inventory-pass-001",' + valid_json.lstrip()[1:]
            )
            nonfinite_run = copy.deepcopy(runs[0])
            nonfinite_run["metrics"]["elapsed_seconds"] = float("nan")
            cases = [
                (
                    "duplicate.json",
                    duplicate_json,
                    "duplicate JSON object key 'run_id'",
                ),
                (
                    "nonfinite.json",
                    json.dumps(nonfinite_run),
                    "non-finite JSON number 'NaN'",
                ),
                (
                    "malformed.json",
                    "{bad",
                    "Expecting property name enclosed in double quotes",
                ),
            ]
            results = []
            for filename, payload, expected_error in cases:
                run_path = base / filename
                run_path.write_text(payload, encoding="utf-8")
                result = subprocess.run(
                    [
                        sys.executable,
                        "agent_readiness/scripts/audit_readiness.py",
                        "--base-dir",
                        str(base),
                        "--run-result",
                        str(run_path),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                results.append((result, expected_error))

        for result, expected_error in results:
            self.assertEqual(1, result.returncode)
            self.assertNotIn("Traceback", result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("invalid", payload["status"])
            self.assertEqual("readiness_input_invalid", payload["error_code"])
            self.assertIn(expected_error, payload["error"])

    def test_readiness_lists_independent_runs_by_task_and_claim_scope(self) -> None:
        from agent_readiness.readiness import audit_readiness

        runs = [
            independent_run("inventory-pass-001"),
            independent_run("inventory-pass-002"),
            independent_run("inventory-pass-003"),
            independent_task_run("event-pass-001", "act.event_jsonapi"),
            independent_task_run("recovery-pass-001", "recover.event_jsonapi"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_minimal_publish_assets(base, runs)

            report = audit_readiness(base, runs)

        self.assertEqual(
            "evidence_package_plus_named_measurement_v1_gates",
            report["claim_scope"],
        )
        self.assertEqual(
            [
                "event-pass-001",
                "inventory-pass-001",
                "inventory-pass-002",
                "inventory-pass-003",
                "recovery-pass-001",
            ],
            report["no_rescue_non_smoke_runs"],
        )
        self.assertEqual(
            ["event-pass-001"],
            report["no_rescue_non_smoke_event_passes"],
        )
        self.assertEqual(
            ["recovery-pass-001"],
            report["no_rescue_non_smoke_recovery_passes"],
        )
        self.assertIn(
            "Keep fixed-agent regression and frontier-observation lanes separate and defer an aggregate readiness score.",
            report["next_actions"],
        )

    def _write_minimal_publish_assets(
        self,
        base: Path,
        runs: list[dict],
    ) -> None:
        from agent_readiness.published_experiments import load_published_experiments
        from agent_readiness.publishing import (
            EXECUTED_SOURCE_CLOSURE,
            REPOSITORY_DEPENDENCIES,
            _json_dumps,
            write_package_manifest,
            write_report,
            write_scorecard_csv,
        )
        from agent_readiness.readiness import write_readiness_json
        from agent_readiness.evaluators.event import evaluate as evaluate_event
        from agent_readiness.evaluators.inventory import evaluate as evaluate_inventory
        from agent_readiness.evaluators.recovery import evaluate as evaluate_recovery

        task_fixtures = {
            "inventory.read_only": (
                "inventory_state_pass.json",
                "inventory_answer_pass.json",
                evaluate_inventory,
            ),
            "act.event_jsonapi": (
                "event_state_pass.json",
                "event_answer_pass.json",
                evaluate_event,
            ),
            "recover.event_jsonapi": (
                "recovery_state_pass.json",
                "recovery_answer_pass.json",
                evaluate_recovery,
            ),
        }
        # Non-canonical package roots are self-contained test fixtures. A real
        # package directory named ``agent_readiness`` must use repository-owned
        # method inputs from its sibling repository root; tests for that layout
        # populate those inputs explicitly rather than having this helper do it.
        if base.name != "agent_readiness":
            source_root = FIXTURES.parents[1]
            for relative in REPOSITORY_DEPENDENCIES:
                destination = base / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((source_root / relative).read_bytes())
        for run in runs:
            run_dir = base / "runs" / run["run_id"]
            run_dir.mkdir(parents=True, exist_ok=True)
            state_name, answer_name, evaluator = task_fixtures[run["task_id"]]
            state = load_fixture(state_name)
            answer = load_fixture(answer_name)
            retained_evaluator = evaluator(state, answer).to_dict()
            run["evaluator"] = {
                key: retained_evaluator[key]
                for key in ("passed", "failures", "warnings")
            }
            artifact_payloads = {
                "answer_json": json.dumps(answer, indent=2, sort_keys=True) + "\n",
                "state_json": json.dumps(state, indent=2, sort_keys=True) + "\n",
                "evaluator_json": (
                    json.dumps(retained_evaluator, indent=2, sort_keys=True) + "\n"
                ),
                "transcript": f"# Test transcript\n\nRun ID: `{run['run_id']}`\n",
            }
            for role, payload in artifact_payloads.items():
                path = base / run["artifacts"][role]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload, encoding="utf-8")
            (run_dir / "run-result.json").write_text(
                json.dumps(run, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        (base / "README.md").write_text("readme\n", encoding="utf-8")
        (base / "PUBLISHING.md").write_text("publishing\n", encoding="utf-8")
        (base / "tasks.yml").write_text("version: 1\n", encoding="utf-8")
        (base / "schema").mkdir(exist_ok=True)
        (base / "schema" / "run-result.schema.json").write_bytes(
            (FIXTURES.parent / "schema/run-result.schema.json").read_bytes()
        )
        for filename in (
            "benchmark-experiment-v1.schema.json",
            "benchmark-run-v1.schema.json",
        ):
            (base / "schema" / filename).write_bytes(
                (FIXTURES.parent / "schema" / filename).read_bytes()
            )
        package_source = FIXTURES.parent
        for relative in EXECUTED_SOURCE_CLOSURE:
            destination = base / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((package_source / relative).read_bytes())

        registry_path = base / "experiments/published-experiments-v1.json"
        if not registry_path.exists():
            summary_path = base / "experiments/test-summary/summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary = {
                "selected_run_count": 1,
                "completed_run_count": 1,
                "status": "test-only historical fixture",
                "by_arm": [{
                    "arm": "control",
                    "runs": 1,
                    "M1_preserved_all_4": 0,
                    "M2_target_considered_before_write": 0,
                    "M4_completion": 0,
                }],
            }
            summary_path.write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            registry = {
                "schema_version": "drupal_agent_readiness.experiment_registry.v1",
                "experiments": [{
                    "experiment_id": "test-historical@v0",
                    "task_id": "assess.intent_preservation",
                    "adapter": "intent_behavior_summary_v0",
                    "lane": "frontier_observation",
                    "evidence_class": "exploratory",
                    "claim_boundary": "test fixture only",
                    "artifacts_complete": False,
                    "pins_complete": False,
                    "sources": {"summary": {
                        "path": "experiments/test-summary/summary.json",
                        "sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                    }},
                }],
            }
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        published_experiments = load_published_experiments(base)
        (base / "public").mkdir(exist_ok=True)
        write_scorecard_csv(runs, base / "public" / "scorecard.csv")
        write_report(
            runs,
            base / "public" / "state-of-agents-in-drupal-v0.md",
            published_experiments,
        )
        (base / "public" / "experiments-v1.json").write_text(
            _json_dumps(published_experiments or {}),
            encoding="utf-8",
        )
        (base / "public" / "claims-ledger.md").write_text("# claims\n", encoding="utf-8")
        (base / "public" / "finding-site-self-description-v0.md").write_text("# finding\n", encoding="utf-8")
        (base / "public" / "why-this-bench.md").write_text("# why\n", encoding="utf-8")
        write_readiness_json(base, runs, base / "public" / "readiness.json")
        (base / "prompts").mkdir(exist_ok=True)
        (base / "prompts" / "assess.alias_safety.fully_blind.md").write_text("# blind\n", encoding="utf-8")
        (base / "prompts" / "assess.alias_safety.told.md").write_text("# told/control\n", encoding="utf-8")
        (base / "prompts" / "assess.alias_safety.candidates.public.json").write_text(
            '{"candidates": [{"path": "/x"}]}\n',
            encoding="utf-8",
        )
        write_package_manifest(base, runs, base / "public" / "package-manifest.json")


if __name__ == "__main__":
    unittest.main()
