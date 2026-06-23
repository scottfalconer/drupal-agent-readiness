import json
import tempfile
import unittest
from pathlib import Path


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


class RunCaptureTest(unittest.TestCase):

    def test_capture_inventory_run_writes_scored_run_package(self) -> None:
        from agent_readiness.run_capture import capture_run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            answer = root / "answer.json"
            transcript = root / "transcript.md"
            answer.write_text(json.dumps(load_fixture("inventory_answer_pass.json")), encoding="utf-8")
            transcript.write_text("agent transcript\n", encoding="utf-8")

            result = capture_run(
                run_id="independent-inventory-001",
                task_id="inventory.read_only",
                state=load_fixture("inventory_state_pass.json"),
                answer_json=answer,
                transcript=transcript,
                runs_dir=root / "runs",
                source_path="/source",
                run_site_path="/run/site",
                prompt_version="v0.1",
                agent={
                    "name": "Independent Codex",
                    "model": "gpt-5",
                    "harness": "fresh Codex thread",
                    "system_prompt": "Default Codex coding-agent prompt",
                    "tooling": ["shell", "drush"],
                },
                metrics={"elapsed_seconds": 90.0, "tool_calls": 7, "human_rescues": 0},
            )

            run_dir = root / "runs" / "independent-inventory-001"
            self.assertTrue(result["evaluator"]["passed"])
            self.assertEqual("runs/independent-inventory-001/answer.json", result["artifacts"]["answer_json"])
            self.assertTrue((run_dir / "answer.json").exists())
            self.assertTrue((run_dir / "transcript.md").exists())
            self.assertTrue((run_dir / "state.json").exists())
            self.assertTrue((run_dir / "evaluator.json").exists())
            self.assertTrue((run_dir / "run-result.json").exists())

    def test_capture_run_records_failures_and_labels(self) -> None:
        from agent_readiness.run_capture import capture_run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            answer = root / "answer.json"
            transcript = root / "transcript.md"
            answer.write_text(json.dumps(load_fixture("inventory_answer_fail.json")), encoding="utf-8")
            transcript.write_text("agent transcript\n", encoding="utf-8")

            result = capture_run(
                run_id="independent-inventory-fail",
                task_id="inventory.read_only",
                state=load_fixture("inventory_state_pass.json"),
                answer_json=answer,
                transcript=transcript,
                runs_dir=root / "runs",
                source_path="/source",
                run_site_path="/run/site",
                prompt_version="v0.1",
                agent={
                    "name": "Independent Codex",
                    "model": "gpt-5",
                    "harness": "fresh Codex thread",
                },
                metrics={"elapsed_seconds": 90.0, "tool_calls": 7, "human_rescues": 0},
            )

            self.assertFalse(result["evaluator"]["passed"])
            self.assertIn("path_ownership", result["failure_labels"])


if __name__ == "__main__":
    unittest.main()
