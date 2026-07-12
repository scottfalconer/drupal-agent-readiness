from __future__ import annotations

import copy
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agent_readiness.eval_references import (
    DEFAULT_JSON_OUTPUT,
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_SCHEMA_PATH,
    DEFAULT_SOURCE_DIR,
    EvalReferenceError,
    REGISTRY_POLICY,
    build_landscape,
    build_outputs,
    check_outputs,
    load_references,
    render_landscape_markdown,
    validate_reference,
)
from agent_readiness.scripts import build_eval_landscape


class EvalReferencesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.references = load_references()

    def test_seed_registry_is_valid_and_allows_more_sources(self) -> None:
        required_seed_ids = {
            "ai-agents-test",
            "ai-bench",
            "ai-best-practices",
            "ai-eval",
            "ai-evaluations",
            "ai-maintenance-skills",
        }
        self.assertTrue(
            required_seed_ids.issubset(
                {reference["id"] for reference in self.references}
            )
        )
        self.assertTrue(all(reference["artifacts"] for reference in self.references))
        self.assertTrue(
            all(
                reference["registry_effect"]
                == "reference_only_no_claim_or_coverage_effect"
                for reference in self.references
            )
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            source_dir = Path(temporary_directory)
            for source_path in DEFAULT_SOURCE_DIR.glob("*.json"):
                shutil.copyfile(source_path, source_dir / source_path.name)
            community = copy.deepcopy(self.references[0])
            community["id"] = "community-example"
            community["name"] = "Community example"
            community["canonical_url"] = "https://example.com/community-eval"
            community["repository_url"] = "https://example.com/community-eval/repo"
            community["provenance"]["source_urls"] = [
                "https://example.com/community-eval"
            ]
            (source_dir / "community-example.json").write_text(
                json.dumps(community), encoding="utf-8"
            )

            with_community = load_references(source_dir, DEFAULT_SCHEMA_PATH)

        self.assertEqual(len(self.references) + 1, len(with_community))
        self.assertIn(
            "community-example", {reference["id"] for reference in with_community}
        )

    def test_records_are_pointer_only(self) -> None:
        fixture = copy.deepcopy(self.references[0])
        fixture["artifacts"][0]["command"] = "curl upstream.example"

        with self.assertRaisesRegex(EvalReferenceError, "prohibited"):
            validate_reference(fixture, self.schema)

    def test_unknown_integration_field_is_rejected_by_closed_schema(self) -> None:
        fixture = copy.deepcopy(self.references[0])
        fixture["artifacts"][0]["adapter"] = "some.module:load"

        with self.assertRaisesRegex(EvalReferenceError, "adapter"):
            validate_reference(fixture, self.schema)

    def test_non_https_and_embedded_credentials_are_rejected(self) -> None:
        for url in (
            "file:///tmp/source.json",
            "http://example.com/source",
            "https://user:password@example.com/source",
            "https://example.com/path) [forged](https://evil.test)",
        ):
            with self.subTest(url=url):
                fixture = copy.deepcopy(self.references[0])
                fixture["canonical_url"] = url
                fixture["provenance"]["source_urls"][0] = url
                with self.assertRaises(EvalReferenceError):
                    validate_reference(fixture, self.schema)

    def test_filename_must_match_source_id(self) -> None:
        with self.assertRaisesRegex(EvalReferenceError, "filename must match"):
            validate_reference(
                self.references[0], self.schema, source_path=Path("wrong-name.json")
            )

    def test_lifecycle_mappings_must_use_canonical_order(self) -> None:
        fixture = copy.deepcopy(self.references[0])
        stages = fixture["artifacts"][0]["lifecycle_stages"]
        fixture["artifacts"][0]["lifecycle_stages"] = list(reversed(stages))

        with self.assertRaisesRegex(EvalReferenceError, "canonical order"):
            validate_reference(fixture, self.schema)

    def test_mapping_scope_controls_lifecycle_and_family_mappings(self) -> None:
        task_fixture = copy.deepcopy(self.references[0])
        task_fixture["artifacts"][0]["lifecycle_stages"] = []
        task_fixture["artifacts"][0]["candidate_task_family_ids"] = []
        with self.assertRaisesRegex(
            EvalReferenceError, "fewer than minimum|task candidates require"
        ):
            validate_reference(task_fixture, self.schema)

        infrastructure_fixture = copy.deepcopy(self.references[0])
        infrastructure_fixture["artifacts"][1]["lifecycle_stages"] = ["verify"]
        infrastructure_fixture["artifacts"][1]["candidate_task_family_ids"] = [
            "governed_editorial_change"
        ]
        with self.assertRaisesRegex(
            EvalReferenceError,
            "more than maximum|supporting infrastructure cannot imply",
        ):
            validate_reference(infrastructure_fixture, self.schema)

    def test_benchmark_plans_cannot_claim_task_or_lifecycle_status(self) -> None:
        ai_bench = next(
            reference for reference in self.references if reference["id"] == "ai-bench"
        )
        self.assertEqual(1, len(ai_bench["artifacts"]))
        plan = ai_bench["artifacts"][0]
        self.assertEqual("benchmark_plan", plan["kind"])
        self.assertEqual("supporting_infrastructure", plan["mapping_scope"])
        self.assertEqual("reference_only", plan["disposition"])
        self.assertEqual([], plan["lifecycle_stages"])
        self.assertEqual([], plan["candidate_task_family_ids"])

        fixture = copy.deepcopy(ai_bench)
        fixture["artifacts"][0]["mapping_scope"] = "task_candidate"
        fixture["artifacts"][0]["disposition"] = "candidate_for_local_adaptation"
        fixture["artifacts"][0]["lifecycle_stages"] = ["act"]
        fixture["artifacts"][0]["candidate_task_family_ids"] = [
            "governed_editorial_change"
        ]

        with self.assertRaises(EvalReferenceError):
            validate_reference(fixture, self.schema)

        duplicate_plan = copy.deepcopy(ai_bench)
        duplicate_plan["artifacts"].append(copy.deepcopy(plan))
        duplicate_plan["artifacts"][1]["id"] = "second-plan"
        with self.assertRaisesRegex(EvalReferenceError, "at most one benchmark plan"):
            validate_reference(duplicate_plan, self.schema)

    def test_task_candidates_require_a_reported_evaluator(self) -> None:
        fixture = copy.deepcopy(self.references[0])
        fixture["artifacts"][0]["evaluator_types"] = ["not_reported"]

        with self.assertRaises(EvalReferenceError):
            validate_reference(fixture, self.schema)

    def test_stdlib_schema_validation_enforces_revision_conditionals(self) -> None:
        fixture = copy.deepcopy(self.references[0])
        fixture["artifacts"][0]["upstream_revision"] = {
            "kind": "tag",
            "value": "1.0.0",
            "immutable": False,
        }

        with self.assertRaisesRegex(EvalReferenceError, "expected constant True"):
            validate_reference(fixture, self.schema)

        malformed_commit = copy.deepcopy(self.references[0])
        malformed_commit["artifacts"][0]["upstream_revision"] = {
            "kind": "commit",
            "value": "ABC123",
            "immutable": True,
        }
        with self.assertRaisesRegex(EvalReferenceError, "does not match pattern"):
            validate_reference(malformed_commit, self.schema)

    def test_repository_commit_pointer_must_anchor_url(self) -> None:
        fixture = copy.deepcopy(self.references[0])
        fixture["artifacts"][0]["url"] = (
            "https://git.drupalcode.org/project/ai_agents_test/-/tree/1.0.x/examples"
        )

        with self.assertRaisesRegex(EvalReferenceError, "anchor the commit"):
            validate_reference(fixture, self.schema)

        unrelated_segment = copy.deepcopy(self.references[0])
        commit = unrelated_segment["artifacts"][0]["upstream_revision"]["value"]
        unrelated_segment["artifacts"][0]["url"] = (
            f"https://git.drupalcode.org/project/ai_agents_test/-/fake/{commit}/examples"
        )
        with self.assertRaisesRegex(EvalReferenceError, "anchor the commit"):
            validate_reference(unrelated_segment, self.schema)

    def test_not_reported_and_not_specific_values_are_exclusive(self) -> None:
        evaluator_fixture = copy.deepcopy(self.references[0])
        evaluator_fixture["artifacts"][1]["evaluator_types"] = [
            "deterministic",
            "not_reported",
        ]
        with self.assertRaisesRegex(EvalReferenceError, "not_reported cannot"):
            validate_reference(evaluator_fixture, self.schema)

        agent_fixture = copy.deepcopy(self.references[0])
        agent_fixture["artifacts"][0]["agent_classes"] = [
            "drupal_native_agent",
            "not_agent_specific",
        ]
        with self.assertRaisesRegex(EvalReferenceError, "not_agent_specific cannot"):
            validate_reference(agent_fixture, self.schema)

    def test_landscape_is_discovery_only(self) -> None:
        landscape = build_landscape(self.references)

        self.assertEqual(REGISTRY_POLICY, landscape["registry_policy"])
        self.assertEqual("none", landscape["registry_policy"]["listing_effect"])
        self.assertFalse(landscape["registry_policy"]["external_results_are_evidence"])
        self.assertFalse(
            landscape["registry_policy"]["scorecard_eligibility_from_listing"]
        )
        self.assertEqual(
            "documented_downstream_conversion",
            landscape["registry_policy"]["success_metric"],
        )
        self.assertEqual(0, landscape["registry_policy"]["recorded_conversions"])
        self.assertFalse(landscape["registry_policy"]["inventory_count_is_success"])
        self.assertEqual(
            1,
            landscape["registry_policy"]["routine_curation_limit_hours_per_week"],
        )
        self.assertEqual("2026-10-15", landscape["registry_policy"]["review_date"])
        self.assertTrue(
            landscape["registry_policy"]["freeze_if_no_conversion_by_review"]
        )
        self.assertEqual(
            "open_pending_review", landscape["registry_policy"]["intake_state"]
        )
        expected_artifact_count = sum(
            len(reference["artifacts"]) for reference in self.references
        )
        self.assertEqual(len(self.references), landscape["counts"]["sources"])
        self.assertEqual(expected_artifact_count, landscape["counts"]["artifacts"])
        self.assertEqual(
            expected_artifact_count,
            landscape["counts"]["task_candidates"]
            + landscape["counts"]["supporting_infrastructure"],
        )
        self.assertEqual(1, landscape["counts"]["plan_only_pointers"])

    def test_supporting_infrastructure_does_not_populate_task_views(self) -> None:
        landscape = build_landscape(self.references)
        infrastructure_ids = {
            f"{reference['id']}:{artifact['id']}"
            for reference in self.references
            for artifact in reference["artifacts"]
            if artifact["mapping_scope"] == "supporting_infrastructure"
        }
        mapped_ids = {
            reference_id
            for view_name in ("by_lifecycle_stage", "by_task_family")
            for group in landscape["views"][view_name]
            for reference_id in group["references"]
        }

        self.assertTrue(infrastructure_ids)
        self.assertTrue(infrastructure_ids.isdisjoint(mapped_ids))

    def test_checked_in_generated_outputs_are_current(self) -> None:
        self.assertEqual([], check_outputs())
        expected_json, expected_markdown = build_outputs()
        self.assertEqual(expected_json, DEFAULT_JSON_OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(
            expected_markdown, DEFAULT_MARKDOWN_OUTPUT.read_text(encoding="utf-8")
        )
        self.assertIn("Discovery only", expected_markdown)
        self.assertIn("has no effect", expected_markdown)
        self.assertIn("consumer-side curation", expected_markdown)
        self.assertIn("Inventory counts describe scope, not success", expected_markdown)
        self.assertIn("## Operating bounds", expected_markdown)
        self.assertIn("Plan-only pointer ratio: 1/9", expected_markdown)
        self.assertIn("Review date: 2026-10-15", expected_markdown)
        for label in (
            "Kind",
            "Mapping scope",
            "Agent classes",
            "Substrate fidelity",
            "Evaluator types",
            "Mapping note",
        ):
            self.assertIn(f"- {label}:", expected_markdown)

    def test_markdown_generation_escapes_contributor_text_and_link_delimiters(
        self,
    ) -> None:
        references = copy.deepcopy(self.references)
        source = references[0]
        source["name"] = "<img src=x onerror=alert(1)> [spoof](https://evil.test)"
        source["summary"] = "<script>alert(1)</script>\n# forged heading"
        artifact = source["artifacts"][0]
        artifact["name"] = "</a><script>alert(2)</script> [close](https://evil.test)"
        artifact["mapping_note"] = "<iframe src=https://evil.test></iframe>"
        artifact["url"] = "https://example.com/path_(safe)"

        markdown = render_landscape_markdown(build_landscape(references))

        self.assertNotIn("<script>", markdown)
        self.assertNotIn("<img ", markdown)
        self.assertNotIn("<iframe ", markdown)
        self.assertIn("&lt;script", markdown)
        self.assertIn(r"\[spoof\]\(https://evil.test\)", markdown)
        self.assertIn("path_%28safe%29", markdown)

    def test_generator_check_detects_stale_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            stale_json = root / "eval-landscape.json"
            stale_markdown = root / "eval-landscape.md"
            stale_json.write_text("{}\n", encoding="utf-8")
            stale_markdown.write_text("stale\n", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = build_eval_landscape.main(
                    [
                        "--check",
                        "--source-dir",
                        str(DEFAULT_SOURCE_DIR),
                        "--schema",
                        str(DEFAULT_SCHEMA_PATH),
                        "--json-output",
                        str(stale_json),
                        "--markdown-output",
                        str(stale_markdown),
                    ]
                )

        self.assertEqual(1, exit_code)
        self.assertIn("stale generated output", output.getvalue())


if __name__ == "__main__":
    unittest.main()
