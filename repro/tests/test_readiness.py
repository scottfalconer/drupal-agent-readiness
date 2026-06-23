import copy
import json
import tempfile
import unittest
from pathlib import Path


FIXTURES = Path(__file__).resolve().parents[2] / "agent_readiness" / "fixtures"


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
            self._write_minimal_publish_assets(base, [load_fixture("run_result_inventory_pass.json")])
            smoke = load_fixture("run_result_inventory_pass.json")
            smoke["run_id"] = "haven-inventory-v0-tooling-smoke"
            smoke["agent"] = {
                "name": "Tooling smoke",
                "model": "none",
                "harness": "local evaluator scripts",
            }

            report = audit_readiness(base, [smoke])

        self.assertTrue(report["private_circulation_ready"])
        self.assertFalse(report["public_v0_package_ready"])
        self.assertFalse(report["numeric_claim_ready"])
        self.assertIn("independent inventory passes: 0/1", report["public_v0_package_errors"])

    def test_three_independent_inventory_passes_make_numeric_claim_ready(self) -> None:
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
        self.assertTrue(report["numeric_claim_ready"])
        self.assertEqual([], report["public_v0_package_errors"])
        self.assertEqual([], report["numeric_claim_errors"])

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

        self.assertEqual("constrained_v0_mechanical_evidence_loop", report["claim_scope"])
        self.assertEqual(
            [
                "inventory-pass-001",
                "inventory-pass-002",
                "inventory-pass-003",
                "event-pass-001",
                "recovery-pass-001",
            ],
            report["independent_runs"],
        )
        self.assertEqual(
            ["event-pass-001"],
            report["independent_event_passes"],
        )
        self.assertEqual(
            ["recovery-pass-001"],
            report["independent_recovery_passes"],
        )
        self.assertIn(
            "Repeat the non-Claude alias-safety run at n=10 and add another non-Claude stack before making a claim across model providers.",
            report["next_actions"],
        )

    def _write_minimal_publish_assets(self, base: Path, runs: list[dict]) -> None:
        from agent_readiness.publishing import write_package_manifest, write_report, write_scorecard_csv

        for run in runs:
            run_dir = base / "runs" / run["run_id"]
            run_dir.mkdir(parents=True)
            for artifact in run["artifacts"].values():
                path = base / artifact
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
        (base / "README.md").write_text("readme\n", encoding="utf-8")
        (base / "PUBLISHING.md").write_text("publishing\n", encoding="utf-8")
        (base / "tasks.yml").write_text("version: 1\n", encoding="utf-8")
        (base / "schema").mkdir()
        (base / "schema" / "run-result.schema.json").write_text("{}\n", encoding="utf-8")
        (base / "public").mkdir()
        write_scorecard_csv(runs, base / "public" / "scorecard.csv")
        write_report(runs, base / "public" / "state-of-agents-in-drupal-v0.md")
        (base / "public" / "finding-site-self-description-v0.md").write_text("# finding\n", encoding="utf-8")
        (base / "public" / "why-this-bench.md").write_text("# why\n", encoding="utf-8")
        (base / "public" / "readiness.json").write_text("{}\n", encoding="utf-8")
        (base / "prompts").mkdir()
        (base / "prompts" / "assess.alias_safety.fully_blind.md").write_text("# blind\n", encoding="utf-8")
        (base / "prompts" / "assess.alias_safety.told.md").write_text("# told/control\n", encoding="utf-8")
        (base / "prompts" / "assess.alias_safety.candidates.public.json").write_text(
            '{"candidates": [{"path": "/x"}]}\n',
            encoding="utf-8",
        )
        write_package_manifest(base, runs, base / "public" / "package-manifest.json")


if __name__ == "__main__":
    unittest.main()
