import copy
import json
import unittest
from pathlib import Path


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
    return run


class BaselineGateTest(unittest.TestCase):

    def test_smoke_runs_do_not_satisfy_independent_baseline_gate(self) -> None:
        from agent_readiness.baseline_gate import audit_inventory_baseline

        run = independent_run("haven-inventory-v0-tooling-smoke")
        run["agent"] = {
            "name": "Tooling smoke",
            "model": "none",
            "harness": "local evaluator scripts",
        }

        errors = audit_inventory_baseline([run], required_passes=1)

        self.assertIn("independent inventory passes: 0/1", errors)

    def test_three_independent_inventory_passes_satisfy_pass3_gate(self) -> None:
        from agent_readiness.baseline_gate import audit_inventory_baseline

        runs = [
            independent_run("inventory-pass-001"),
            independent_run("inventory-pass-002"),
            independent_run("inventory-pass-003"),
        ]

        errors = audit_inventory_baseline(runs, required_passes=3)

        self.assertEqual([], errors)

    def test_human_rescue_prevents_counting_as_independent_pass(self) -> None:
        from agent_readiness.baseline_gate import audit_inventory_baseline

        run = independent_run("inventory-pass-with-rescue")
        run["metrics"]["human_rescues"] = 1

        errors = audit_inventory_baseline([run], required_passes=1)

        self.assertIn("independent inventory passes: 0/1", errors)


if __name__ == "__main__":
    unittest.main()
