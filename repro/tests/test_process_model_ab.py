import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("process_model_ab", ROOT / "scripts" / "process_model_ab.py")
pmab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pmab)


STATE = {
    "/free": {"safe": True, "blocker_kind": None},
    "/lat": {"safe": False, "blocker_kind": "latent_disabled_view"},
}


def _workflow_output() -> dict:
    return {"result": {"blind": [
        {"condition": "blind", "model": "haiku", "arm": "raw", "n": 1, "answer": {"command_count": 5, "assessments": {
            "/free": {"safe": True, "reason": "free"},
            "/lat": {"safe": False, "reason": "Claimed by view files"}}}},  # verdict right, reasoned NO
        {"condition": "blind", "model": "haiku", "arm": "equipped", "n": 1, "answer": {"command_count": 6, "assessments": {
            "/free": {"safe": True, "reason": "free"},
            "/lat": {"safe": False, "reason": "Disabled view files:page_1 declares this path"}}}},  # verdict + reasoned
        {"condition": "blind", "model": "opus", "arm": "raw", "n": 1, "answer": {"command_count": 4, "assessments": {
            "/free": {"safe": True, "reason": "free"},
            "/lat": {"safe": True, "reason": "nothing claims it"}}}},  # verdict WRONG
    ]}}


class ReasonHeuristicTest(unittest.TestCase):
    def test_recognizes_disabled_or_latent_only(self) -> None:
        self.assertTrue(pmab.reason_recognizes_latent("Disabled view files:page_1 declares this path"))
        self.assertTrue(pmab.reason_recognizes_latent("a latent claim from a view"))
        self.assertFalse(pmab.reason_recognizes_latent("Claimed by view files"))
        self.assertFalse(pmab.reason_recognizes_latent("admin path is reserved"))
        self.assertFalse(pmab.reason_recognizes_latent(""))


class ProcessTest(unittest.TestCase):
    def _run(self, base: Path) -> dict:
        (base / "wf.json").write_text(json.dumps(_workflow_output()), encoding="utf-8")
        (base / "state.json").write_text(json.dumps(STATE), encoding="utf-8")
        return pmab.process(base / "wf.json", base / "state.json", base / "out")

    def test_persists_per_run_artifacts_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._run(base)
            out = base / "out"
            for name in ["raw-workflow-output.json", "ground-truth.json", "candidates.json", "model-ab-results.json", "model-ab-FINDING.md"]:
                self.assertTrue((out / name).exists(), name)
            run = out / "runs" / "ab-haiku-blind" / "equipped-1"
            for name in ["answer.json", "evaluator.json", "meta.json"]:
                self.assertTrue((run / name).exists(), name)
            meta = json.loads((run / "meta.json").read_text())
            self.assertEqual("claude-haiku-4-5", meta["model_id"])
            self.assertEqual("blind", meta["condition"])
            self.assertIn("processed_at", meta)

    def test_verdict_and_strict_reasoned_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            summary = self._run(base)
            hb = summary["ab-haiku-blind"]
            # raw flagged the latent unsafe (verdict ok) but did NOT say "disabled" (reasoned 0)
            self.assertEqual(1, hb["raw_drush"]["latent_correct"])
            self.assertEqual(0, hb["raw_drush"]["latent_reasoned"])
            # equipped flagged unsafe AND named the disabled view (reasoned 1)
            self.assertEqual(1, hb["site_architecture"]["latent_correct"])
            self.assertEqual(1, hb["site_architecture"]["latent_reasoned"])
            # opus raw said safe -> verdict miss
            self.assertEqual(0, summary["ab-opus-blind"]["raw_drush"]["latent_correct"])


if __name__ == "__main__":
    unittest.main()
