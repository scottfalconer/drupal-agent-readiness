import csv
import json
import tempfile
import unittest
from pathlib import Path


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


class PublishingTest(unittest.TestCase):

    def test_scorecard_row_contains_required_v0_dimensions(self) -> None:
        from agent_readiness.publishing import scorecard_rows

        row = scorecard_rows([load_fixture("run_result_inventory_pass.json")])[0]

        self.assertEqual("haven-inventory-v0-codex-smoke", row["run_id"])
        self.assertEqual("inventory.read_only", row["task_id"])
        self.assertEqual("true", row["task_success"])
        self.assertEqual("0", row["human_rescues"])
        self.assertEqual("mechanical-pass", row["verification_quality"])
        self.assertEqual("clean", row["blast_radius"])

    def test_report_keeps_v0_framed_as_qualitative_baseline(self) -> None:
        from agent_readiness.publishing import render_report

        report = render_report([load_fixture("run_result_inventory_pass.json")])

        self.assertIn("State of Agents in Drupal", report)
        self.assertIn("qualitative baseline", report)
        self.assertIn("not a cross-CMS comparison", report)
        self.assertIn("public/why-this-bench.md", report)
        self.assertIn("tooling/evaluator smoke", report)
        self.assertIn("haven-inventory-v0-codex-smoke", report)

    def test_report_includes_readiness_status(self) -> None:
        from agent_readiness.publishing import render_report

        run = load_fixture("run_result_inventory_pass.json")
        run["run_id"] = "haven-inventory-v0-tooling-smoke"
        run["agent"] = {
            "name": "Tooling smoke",
            "model": "none",
            "harness": "local evaluator scripts",
        }

        report = render_report([run])

        self.assertIn("Private circulation: ready", report)
        self.assertIn("Public v0 package: not ready", report)
        self.assertIn("Constrained v0 mechanical-pass claims: not ready", report)
        self.assertIn("independent inventory passes: 0/1", report)

    def test_report_splits_smoke_and_independent_runs_with_elapsed_time(self) -> None:
        from agent_readiness.publishing import render_report

        smoke = load_fixture("run_result_inventory_pass.json")
        smoke["run_id"] = "haven-inventory-v0-tooling-smoke"
        smoke["agent"] = {
            "name": "Tooling smoke",
            "model": "none",
            "harness": "local evaluator scripts",
        }
        smoke["metrics"]["elapsed_seconds"] = 12
        smoke["metrics"]["tool_calls"] = 4

        independent = load_fixture("run_result_inventory_pass.json")
        independent["run_id"] = "inventory-independent-001"
        independent["agent"] = {
            "name": "Independent Codex",
            "model": "gpt-5",
            "harness": "fresh Codex thread",
        }
        independent["metrics"]["elapsed_seconds"] = 336
        independent["metrics"]["tool_calls"] = 4

        report = render_report([smoke, independent])

        self.assertIn("Constrained evaluator passes: 2/2", report)
        self.assertIn("These are constrained v0 tasks.", report)
        self.assertIn("### Tooling/evaluator smoke runs", report)
        self.assertIn("### Independent/constrained agent runs", report)
        self.assertIn("| Run | Task | Success | Human rescues | Elapsed seconds | Tool calls | Verification | Blast radius |", report)
        self.assertIn("| haven-inventory-v0-tooling-smoke | inventory.read_only | true | 0 | 12 | 4 | mechanical-pass | clean |", report)
        self.assertIn("| inventory-independent-001 | inventory.read_only | true | 0 | 336 | 4 | mechanical-pass | clean |", report)

    def test_report_includes_next_hardening_steps(self) -> None:
        from agent_readiness.publishing import render_report

        report = render_report([load_fixture("run_result_inventory_pass.json")])

        self.assertIn("## Next hardening steps", report)
        self.assertIn("Completed in v0.2:", report)
        self.assertIn("De-leaked the inventory prompt", report)
        self.assertIn("Repeat the non-Claude alias-safety run at n=10", report)

    def test_report_marks_discrimination_when_failing_run_present(self) -> None:
        from agent_readiness.publishing import render_report

        passing = load_fixture("run_result_inventory_pass.json")
        passing["run_id"] = "inventory-deleaked-equipped"
        passing["agent"] = {"name": "Independent subagent (equipped)", "model": "claude-opus-4-8", "harness": "live drush"}

        failing = load_fixture("run_result_inventory_pass.json")
        failing["run_id"] = "inventory-deleaked-blind"
        failing["agent"] = {"name": "Independent subagent (blind)", "model": "claude-opus-4-8", "harness": "static source only"}
        failing["evaluator"] = {"passed": False, "failures": ["command_runner", "paths./node.owner_kind"], "warnings": []}
        failing["failure_labels"] = ["command_runner", "path_ownership"]

        report = render_report([passing, failing])

        self.assertIn("Failing runs retained: 1", report)
        self.assertIn("Discrimination: demonstrated", report)
        self.assertIn("v0.2 (de-leaked)", report)
        self.assertIn("| inventory-deleaked-blind | inventory.read_only | false |", report)

    def test_write_scorecard_csv_writes_stable_headers(self) -> None:
        from agent_readiness.publishing import write_scorecard_csv

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "scorecard.csv"
            write_scorecard_csv([load_fixture("run_result_inventory_pass.json")], output)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(1, len(rows))
        self.assertEqual("inventory.read_only", rows[0]["task_id"])
        self.assertEqual("mechanical-pass", rows[0]["verification_quality"])

    def test_run_result_validation_reports_missing_required_fields(self) -> None:
        from agent_readiness.publishing import validate_run_result

        errors = validate_run_result({"run_id": "missing-most-fields"})

        self.assertIn("task_id", errors)
        self.assertIn("artifacts", errors)

    def test_publication_audit_reports_missing_artifact_files(self) -> None:
        from agent_readiness.publishing import audit_publication_package

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_dir = base / "runs" / "haven-inventory-v0-codex-smoke"
            run_dir.mkdir(parents=True)
            run_result = load_fixture("run_result_inventory_pass.json")
            (run_dir / "run-result.json").write_text(json.dumps(run_result), encoding="utf-8")

            errors = audit_publication_package(base, [run_result])

        self.assertIn("missing artifact: runs/haven-inventory-v0-codex-smoke/answer.json", errors)

    def test_package_manifest_contains_hashes_for_publish_assets(self) -> None:
        from agent_readiness.publishing import build_package_manifest

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "README.md").write_text("readme\n", encoding="utf-8")
            (base / "run_capture.py").write_text("capture\n", encoding="utf-8")
            (base / "public").mkdir()
            (base / "public" / "scorecard.csv").write_text("run_id\n", encoding="utf-8")
            (base / "public" / "state-of-agents-in-drupal-v0.md").write_text("# report\n", encoding="utf-8")
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
            run_result = load_fixture("run_result_inventory_pass.json")
            for artifact in run_result["artifacts"].values():
                path = base / artifact
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(artifact + "\n", encoding="utf-8")

            manifest = build_package_manifest(base, [run_result])

        files = {entry["path"]: entry for entry in manifest["files"]}
        self.assertIn("public/scorecard.csv", files)
        self.assertIn("public/readiness.json", files)
        self.assertIn("run_capture.py", files)
        self.assertIn("runs/haven-inventory-v0-codex-smoke/answer.json", files)
        self.assertRegex(files["public/scorecard.csv"]["sha256"], r"^[0-9a-f]{64}$")

    def test_publication_audit_requires_readiness_json(self) -> None:
        from agent_readiness.publishing import audit_publication_package, write_package_manifest, write_report, write_scorecard_csv

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_result = load_fixture("run_result_inventory_pass.json")
            for artifact in run_result["artifacts"].values():
                path = base / artifact
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            (base / "README.md").write_text("readme\n", encoding="utf-8")
            (base / "PUBLISHING.md").write_text("publishing\n", encoding="utf-8")
            (base / "tasks.yml").write_text("version: 1\n", encoding="utf-8")
            (base / "schema").mkdir()
            (base / "schema" / "run-result.schema.json").write_text("{}\n", encoding="utf-8")
            (base / "public").mkdir()
            write_scorecard_csv([run_result], base / "public" / "scorecard.csv")
            write_report([run_result], base / "public" / "state-of-agents-in-drupal-v0.md")
            (base / "public" / "finding-site-self-description-v0.md").write_text("# finding\n", encoding="utf-8")
            (base / "public" / "why-this-bench.md").write_text("# why\n", encoding="utf-8")
            (base / "prompts").mkdir()
            (base / "prompts" / "assess.alias_safety.fully_blind.md").write_text("# blind\n", encoding="utf-8")
            (base / "prompts" / "assess.alias_safety.told.md").write_text("# told/control\n", encoding="utf-8")
            (base / "prompts" / "assess.alias_safety.candidates.public.json").write_text(
                '{"candidates": [{"path": "/x"}]}\n',
                encoding="utf-8",
            )
            write_package_manifest(base, [run_result], base / "public" / "package-manifest.json")

            errors = audit_publication_package(base, [run_result])

        self.assertIn("missing publish asset: public/readiness.json", errors)

    def test_publication_audit_catches_prompt_leaks_and_deprecated_claims(self) -> None:
        from agent_readiness.publishing import audit_publication_package, write_package_manifest, write_report, write_scorecard_csv

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_result = load_fixture("run_result_inventory_pass.json")
            for artifact in run_result["artifacts"].values():
                path = base / artifact
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            (base / "public").mkdir()
            write_scorecard_csv([run_result], base / "public" / "scorecard.csv")
            write_report([run_result], base / "public" / "state-of-agents-in-drupal-v0.md")
            (base / "public" / "finding-site-self-description-v0.md").write_text(
                "replicates across vendors\n",
                encoding="utf-8",
            )
            (base / "public" / "why-this-bench.md").write_text("# why\n", encoding="utf-8")
            (base / "public" / "readiness.json").write_text("{}\n", encoding="utf-8")
            (base / "prompts").mkdir()
            (base / "prompts" / "assess.alias_safety.fully_blind.md").write_text(
                "disabled views matter\n",
                encoding="utf-8",
            )
            (base / "prompts" / "assess.alias_safety.told.md").write_text("# prompt\n", encoding="utf-8")
            (base / "prompts" / "assess.alias_safety.candidates.public.json").write_text(
                '{"candidates": [{"path": "/x", "note": "leak"}]}\n',
                encoding="utf-8",
            )
            write_package_manifest(base, [run_result], base / "public" / "package-manifest.json")

            errors = audit_publication_package(base, [run_result])

        self.assertTrue(any(error.startswith("fully blind prompt leak:") for error in errors))
        self.assertTrue(any(error.startswith("fully blind candidate leak:") for error in errors))
        self.assertTrue(any(error.startswith("told prompt unlabeled:") for error in errors))
        self.assertTrue(any(error.startswith("deprecated public claim:") for error in errors))


if __name__ == "__main__":
    unittest.main()
