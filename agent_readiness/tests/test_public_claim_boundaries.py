import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "agent_readiness"

HAND_AUTHORED_PUBLIC_FILES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "REVIEW-READINESS.md",
    REPO_ROOT / "evidence" / "experiments" / "alias-safety-SYNTHESIS.md",
    REPO_ROOT / "docs" / "claims-ledger.md",
    REPO_ROOT / "docs" / "finding-first-hour-v0.md",
    REPO_ROOT / "docs" / "finding-site-self-description-v0.md",
    REPO_ROOT / "method" / "PUBLISHING.md",
    PACKAGE_ROOT / "PUBLISHING.md",
    PACKAGE_ROOT / "experiments" / "alias-safety-SYNTHESIS.md",
    PACKAGE_ROOT / "public" / "claims-ledger.md",
    PACKAGE_ROOT / "public" / "finding-site-self-description-v0.md",
]


class PublicClaimBoundariesTest(unittest.TestCase):

    def test_first_hour_summary_freezes_selected_denominators(self) -> None:
        index = json.loads(
            (REPO_ROOT / "docs" / "first-hour-selected-runs-v0.json").read_text(
                encoding="utf-8"
            )
        )
        selected = index["selected_primary_matrix"]
        self.assertEqual(16, len(selected))
        self.assertTrue(all(item["valid"] for item in selected))
        self.assertTrue(all(item["required_rungs_cleared"] == 5 for item in selected))
        self.assertEqual(15, sum(item["optional_stretch"] for item in selected))

        extensions = {item["platform"]: item for item in index["extensions"]}
        self.assertEqual({"wagtail", "joomla", "payload", "strapi"}, set(extensions))
        for platform in ("wagtail", "joomla", "payload"):
            self.assertTrue(extensions[platform]["included_in_result"])
            self.assertTrue(extensions[platform]["valid"])
            self.assertEqual(5, extensions[platform]["required_rungs_cleared"])
        self.assertFalse(extensions["strapi"]["included_in_result"])
        self.assertFalse(extensions["strapi"]["valid"])
        self.assertTrue(extensions["strapi"]["strong_contamination"])

        all_rows = selected + list(extensions.values())
        hashes = [item["source_score_sha256"] for item in all_rows]
        self.assertEqual(len(hashes), len(set(hashes)))
        for digest in hashes:
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

        finding = (REPO_ROOT / "docs" / "finding-first-hour-v0.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "16 valid selected cells",
            "15 of 16",
            "per-run artifacts are not included",
            "not a registered measurement-v1 experiment",
        ):
            self.assertIn(phrase, finding)
        for overclaim in (
            "zero capability failures",
            "every platform tested",
            "every drupal run",
        ):
            self.assertNotIn(overclaim, finding.lower())

    def test_hand_authored_narratives_do_not_copy_registered_result_ratios(self) -> None:
        from agent_readiness.published_experiments import load_published_experiments

        bundle = load_published_experiments(PACKAGE_ROOT)
        ratios: set[str] = set()
        for experiment in bundle["experiments"]:
            for metric in experiment["metrics"]:
                denominator = metric.get("latent_total", metric.get("runs"))
                if denominator is None:
                    continue
                for field in (
                    "latent_correct",
                    "latent_reasoned",
                    "preserved_all_4",
                    "target_considered_before_write",
                    "completion",
                ):
                    if field in metric:
                        ratios.add(f"{metric[field]}/{denominator}")

        for path in HAND_AUTHORED_PUBLIC_FILES:
            text = path.read_text(encoding="utf-8")
            copied = sorted(ratio for ratio in ratios if ratio in text)
            self.assertEqual([], copied, f"{path} copies generated result ratios")

    def test_deprecated_readiness_and_independence_phrases_stay_absent(self) -> None:
        forbidden = [
            "Constrained v0 mechanical-pass claims: ready",
            "package also includes independent/constrained agent runs",
            "For any constrained v0 mechanical-pass claim",
            "Safe public claim",
            "site self-description changed agent behavior",
            "improvement demonstrated",
            "Fresh variants are measurement",
            "Report the named verdict-bearing helper's effect",
            "Independent verification | Covered",
            "package demonstrates a runnable",
            "public_evidence_package_ready: true` certifies",
            "retained failure / discriminator",
            "helper changed agent judgments",
            "helper changed decisions",
            "made those hidden claims visible and changed judgments",
            "the evaluator can discriminate a retained incorrect answer",
            "alias-safety runs are instrumented",
        ]
        for path in HAND_AUTHORED_PUBLIC_FILES:
            text = path.read_text(encoding="utf-8").lower()
            for phrase in forbidden:
                self.assertNotIn(phrase.lower(), text, str(path))

    def test_action_gate_docs_keep_role_specific_improvement_boundary(self) -> None:
        publishing = (REPO_ROOT / "method" / "PUBLISHING.md").read_text(
            encoding="utf-8"
        )
        measurement = (REPO_ROOT / "method" / "MEASUREMENT-V1.md").read_text(
            encoding="utf-8"
        )

        for text in (publishing, measurement):
            self.assertIn("16 in-action bindings", text)
            self.assertIn("primary_efficacy", text)
            self.assertIn("Placebo", text)
            self.assertIn("diagnostic", text)
        self.assertIn("never become `improvement_ready`", publishing)
        self.assertIn("never satisfy this per-experiment gate", measurement)

    def test_current_historical_registry_cannot_enable_measurement_gates(self) -> None:
        from agent_readiness.published_experiments import load_published_experiments

        bundle = load_published_experiments(PACKAGE_ROOT)
        self.assertTrue(bundle["experiments"])
        self.assertTrue(
            all(item.get("claim_grade", False) is False for item in bundle["experiments"])
        )

        readiness = json.loads(
            (PACKAGE_ROOT / "public" / "readiness.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            "drupal_agent_readiness.source_gate_snapshot.v1",
            readiness["artifact_kind"],
        )
        self.assertFalse(readiness["authoritative_package_audit"])
        self.assertEqual("not_run", readiness["package_audit"]["status"])
        self.assertIsNone(readiness["public_evidence_package_ready"])
        self.assertIsNone(readiness["estimate_ready"])
        self.assertIsNone(readiness["fixed_estimate_ready"])
        self.assertIsNone(readiness["improvement_ready"])
        self.assertFalse(readiness["estimate_source_gate_met"])
        self.assertFalse(readiness["fixed_estimate_source_gate_met"])
        self.assertFalse(readiness["improvement_source_gate_met"])
        self.assertEqual([], readiness["registered_effect_rule_met_experiments"])
        self.assertEqual([], readiness["improvement_ready_experiments"])
        self.assertNotIn("claim_grade_ready", readiness)
        self.assertNotIn("numeric_claim_ready", readiness)
        self.assertNotIn("longitudinal_change_ready", readiness)

    def test_generated_distribution_files_are_byte_identical(self) -> None:
        from agent_readiness.publishing import audit_distribution_mirrors

        errors = audit_distribution_mirrors(
            PACKAGE_ROOT / "public",
            REPO_ROOT / "docs",
        )

        self.assertEqual([], errors)

    def test_hand_authored_distribution_mirrors_differ_only_by_relative_links(self) -> None:
        docs = REPO_ROOT / "docs"
        public = PACKAGE_ROOT / "public"
        self.assertEqual(
            (docs / "why-this-bench.md").read_bytes(),
            (public / "why-this-bench.md").read_bytes(),
        )

        finding_docs = (docs / "finding-site-self-description-v0.md").read_text(
            encoding="utf-8"
        )
        finding_public = (
            public / "finding-site-self-description-v0.md"
        ).read_text(encoding="utf-8").replace(
            "../../docs/experiments-v1.json",
            "experiments-v1.json",
        )
        self.assertEqual(finding_docs, finding_public)

        claims_docs = (docs / "claims-ledger.md").read_text(encoding="utf-8")
        claims_public = (public / "claims-ledger.md").read_text(encoding="utf-8")
        claims_public = claims_public.replace(
            "../../docs/experiments-v1.json",
            "experiments-v1.json",
        ).replace(
            "`scorecard.csv`; `../runs/*`",
            "`docs/scorecard.csv`; `evidence/runs/*`",
        ).replace(
            "`../runs/inventory-deleaked-blind/*`",
            "`evidence/runs/inventory-deleaked-blind/*`",
        )
        self.assertEqual(claims_docs, claims_public)

        self.assertEqual(
            (REPO_ROOT / "evidence" / "experiments" / "alias-safety-SYNTHESIS.md").read_bytes(),
            (PACKAGE_ROOT / "experiments" / "alias-safety-SYNTHESIS.md").read_bytes(),
        )

    def test_rerun_docs_describe_the_actual_harness_examples(self) -> None:
        expected = (
            "documented Claude provenance, Codex diagnostic example, and\n"
            "vendor-neutral contract"
        )
        stale = "Claude, Codex, and Gemini runners shown"
        for path in (
            REPO_ROOT / "docs" / "finding-site-self-description-v0.md",
            PACKAGE_ROOT / "public" / "finding-site-self-description-v0.md",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn(expected, text, str(path))
            self.assertNotIn(stale, text, str(path))

        harness = (REPO_ROOT / "method" / "HARNESS.md").read_text(encoding="utf-8")
        self.assertIn("Claude (workflow)", harness)
        self.assertIn("Codex (diagnostic read-only example)", harness)
        self.assertIn("Other vendors", harness)

    def test_ci_keeps_external_registry_canary_effect_and_clean_release_gates(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("Draft202012Validator", workflow)
        self.assertIn("run_frontier_canary.py --help", workflow)
        self.assertIn(
            "--entrypoint agent_readiness/scripts/run_frontier_canary.py",
            workflow,
        )
        self.assertIn(
            'assert report["registered_effect_rule_met_experiments"] == []',
            workflow,
        )
        self.assertIn("--require-clean-worktree", workflow)
        self.assertIn("PYTHONPYCACHEPREFIX", workflow)


if __name__ == "__main__":
    unittest.main()
