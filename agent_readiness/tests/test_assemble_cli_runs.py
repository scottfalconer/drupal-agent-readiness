import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("assemble_cli_runs", ROOT / "scripts" / "assemble_cli_runs.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class AssembleTest(unittest.TestCase):
    def test_infers_arm_n_and_handles_missing_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "raw-1").mkdir()
            (base / "raw-1" / "answer.json").write_text(json.dumps(
                {"assessments": {"/x": {"safe": True, "reason": "free"}}, "command_count": 3}), encoding="utf-8")
            (base / "equipped-1").mkdir()
            (base / "equipped-1" / "answer.json").write_text(json.dumps(
                {"assessments": {"/x": {"safe": False, "reason": "disabled view"}}, "command_count": 5}), encoding="utf-8")
            (base / "raw-2").mkdir()  # no answer.json -> None
            (base / "notes.txt").write_text("ignore me", encoding="utf-8")  # non-run dir/file ignored

            data = mod.assemble(base, "gpt-5.5-codex")

        by = {(i["arm"], i["n"]): i for i in data["blind"]}
        self.assertEqual(3, len(data["blind"]))
        self.assertEqual("gpt-5.5-codex", by[("raw", 1)]["model"])
        self.assertEqual(3, by[("raw", 1)]["answer"]["command_count"])
        self.assertEqual("equipped", by[("equipped", 1)]["arm"])
        self.assertIsNone(by[("raw", 2)]["answer"])


if __name__ == "__main__":
    unittest.main()
