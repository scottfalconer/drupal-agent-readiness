import json
import tempfile
import unittest
from pathlib import Path


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


class RunArtifactsTest(unittest.TestCase):

    def test_materialize_inventory_run_writes_publishable_artifacts(self) -> None:
        from agent_readiness.run_artifacts import materialize_inventory_run_from_state

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            result = materialize_inventory_run_from_state(
                run_id="fixture-run",
                state=load_fixture("inventory_state_pass.json"),
                run_dir=run_dir,
                source_path="/source",
                run_site_path="/run/site",
                transcript_lines=["fixture transcript"],
                metrics={"elapsed_seconds": 1.0, "tool_calls": 1, "human_rescues": 0},
            )

            self.assertTrue((run_dir / "state.json").exists())
            self.assertTrue((run_dir / "answer.json").exists())
            self.assertTrue((run_dir / "evaluator.json").exists())
            self.assertTrue((run_dir / "run-result.json").exists())
            self.assertTrue((run_dir / "transcript.md").exists())
            self.assertTrue(result["evaluator"]["passed"])
            self.assertEqual("runs/fixture-run/answer.json", result["artifacts"]["answer_json"])

    def test_materialize_event_run_writes_publishable_artifacts(self) -> None:
        from agent_readiness.run_artifacts import materialize_event_run_from_state

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            result = materialize_event_run_from_state(
                run_id="event-fixture-run",
                state=load_fixture("event_state_pass.json"),
                run_dir=run_dir,
                source_path="/source",
                run_site_path="/run/site",
                transcript_lines=["event fixture transcript"],
                metrics={"elapsed_seconds": 1.0, "tool_calls": 1, "human_rescues": 0},
            )

            self.assertTrue((run_dir / "answer.json").exists())
            self.assertTrue((run_dir / "run-result.json").exists())
            self.assertTrue(result["evaluator"]["passed"])
            self.assertEqual("act.event_jsonapi", result["task_id"])

    def test_materialize_recovery_run_writes_publishable_artifacts(self) -> None:
        from agent_readiness.run_artifacts import materialize_recovery_run_from_state

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            result = materialize_recovery_run_from_state(
                run_id="recovery-fixture-run",
                state=load_fixture("recovery_state_pass.json"),
                run_dir=run_dir,
                source_path="/source",
                run_site_path="/run/site",
                transcript_lines=["recovery fixture transcript"],
                metrics={"elapsed_seconds": 1.0, "tool_calls": 1, "human_rescues": 0},
            )

            self.assertTrue((run_dir / "answer.json").exists())
            self.assertTrue((run_dir / "run-result.json").exists())
            self.assertTrue(result["evaluator"]["passed"])
            self.assertEqual("recover.event_jsonapi", result["task_id"])


if __name__ == "__main__":
    unittest.main()
