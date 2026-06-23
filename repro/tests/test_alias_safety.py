import copy
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT.parent / "agent_readiness"
FIXTURES = PACKAGE_ROOT / "fixtures"
PROMPTS = PACKAGE_ROOT / "prompts"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


class AliasSafetyEvaluatorTest(unittest.TestCase):

    def test_passes_when_all_verdicts_and_blockers_match(self) -> None:
        from agent_readiness.evaluators.alias_safety import evaluate

        result = evaluate(
            load_fixture("alias_safety_state_pass.json"),
            load_fixture("alias_safety_answer_pass.json"),
        )

        self.assertTrue(result.passed)
        self.assertEqual([], result.failures)
        self.assertEqual(2, result.details["latent_total"])
        self.assertEqual(2, result.details["latent_correct"])

    def test_fails_and_scores_latent_when_disabled_view_claims_are_missed(self) -> None:
        from agent_readiness.evaluators.alias_safety import evaluate

        result = evaluate(
            load_fixture("alias_safety_state_pass.json"),
            load_fixture("alias_safety_answer_fail.json"),
        )

        self.assertFalse(result.passed)
        self.assertIn("/admin/content/files.safe", result.failures)
        self.assertIn("/admin/content/media/scheduled.safe", result.failures)
        self.assertEqual(2, result.details["latent_total"])
        self.assertEqual(0, result.details["latent_correct"])

    def test_fails_when_blocker_kind_is_wrong(self) -> None:
        from agent_readiness.evaluators.alias_safety import evaluate

        answer = copy.deepcopy(load_fixture("alias_safety_answer_pass.json"))
        answer["assessments"]["/blog"]["blocker_kind"] = "view"

        result = evaluate(load_fixture("alias_safety_state_pass.json"), answer)

        self.assertFalse(result.passed)
        self.assertIn("/blog.blocker_kind", result.failures)

    def test_fails_when_path_is_missing_from_answer(self) -> None:
        from agent_readiness.evaluators.alias_safety import evaluate

        answer = copy.deepcopy(load_fixture("alias_safety_answer_pass.json"))
        del answer["assessments"]["/admin/content/files"]

        result = evaluate(load_fixture("alias_safety_state_pass.json"), answer)

        self.assertFalse(result.passed)
        self.assertIn("/admin/content/files.missing", result.failures)

    def test_fully_blind_candidates_are_path_only(self) -> None:
        with (PROMPTS / "assess.alias_safety.candidates.public.json").open(encoding="utf-8") as handle:
            data = json.load(handle)

        for candidate in data["candidates"]:
            self.assertEqual(["path"], sorted(candidate.keys()))

    def test_fully_blind_prompt_does_not_name_hidden_criterion(self) -> None:
        text = (PROMPTS / "assess.alias_safety.fully_blind.md").read_text(encoding="utf-8").lower()

        for forbidden in ["disabled view", "disabled views", "latent claim", "latent claims", "latent_disabled_view"]:
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
