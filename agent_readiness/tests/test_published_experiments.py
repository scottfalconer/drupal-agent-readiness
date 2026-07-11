import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_readiness.measurement_v1 import canonical_json_bytes
from agent_readiness.tests import test_measurement_v1 as measurement_fixture

PACKAGE = Path(__file__).resolve().parents[1]


def build_git_measurement_registry(*, improvement: bool = True):
    fixture = measurement_fixture.MeasurementV1Test(
        methodName="test_complete_semantic_census_demonstrates_registered_improvement"
    )
    fixture.setUp()
    if not improvement:
        fixture._set_success(fixture.runs[1], 0)
        fixture._set_success(fixture.runs[3], 0)
    root = fixture.root
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Published Registry"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "registry@example.invalid"],
        check=True,
    )
    manifest_relative = fixture.manifest["registration"]["manifest_path"]
    manifest_path = root / manifest_relative
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(canonical_json_bytes(fixture.manifest))
    subprocess.run(
        ["git", "-C", str(root), "add", manifest_relative],
        check=True,
    )
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-07-09T09:30:00+00:00",
        "GIT_COMMITTER_DATE": "2026-07-09T09:30:00+00:00",
    }
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "Register measurement"],
        check=True,
        env=environment,
    )
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    run_pointers = []
    for index, run in enumerate(fixture.runs):
        run_path = root / "measurement-sources" / f"run-{index}.json"
        run_path.parent.mkdir(parents=True, exist_ok=True)
        run_path.write_bytes(canonical_json_bytes(run))
        run_pointers.append({
            "path": str(run_path.relative_to(root)),
            "sha256": hashlib.sha256(run_path.read_bytes()).hexdigest(),
        })
    registry = {
        "schema_version": "drupal_agent_readiness.experiment_registry.v1",
        "experiments": [{
            "experiment_id": fixture.manifest["experiment_id"],
            "adapter": "measurement_v1",
            "sources": {
                "manifest": {
                    "path": manifest_relative,
                    "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                },
                "runs": run_pointers,
            },
            "artifact_root": ".",
            "registration_commit": commit,
        }],
    }
    registry_path = root / "experiments" / "published-experiments-v1.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return fixture, registry_path


class PublishedExperimentsTest(unittest.TestCase):

    def test_measurement_render_exposes_n_bound_assumptions_and_action_boundary(self) -> None:
        from agent_readiness.published_experiments import render_experiment_markdown

        experiment = {
            "experiment_id": "bounded-effect@v1",
            "adapter": "measurement_v1",
            "lane": "fixed_regression",
            "evidence_complete": True,
            "estimate_reportable": True,
            "fixed_estimate_reportable": True,
            "registered_effect_rule_met": True,
            "improvement_ready": False,
            "action_registry_binding": {
                "verified": False,
                "errors": ["record remains pending"],
            },
            "audit": {
                "claim_class": "comparative",
                "analysis": {
                    "primary_metric_id": "task_success",
                    "n": 24,
                    "sample_unit": "complete_pair",
                    "estimate": 1.0,
                    "favorable_direction_estimate": 1.0,
                    "confidence": {
                        "method": "paired_hoeffding_lower",
                        "level": 0.95,
                        "tail": "lower_one_sided",
                        "favorable_direction_lower_bound": 0.5004,
                    },
                    "inference_scope": {"kind": "target_population"},
                    "sampling_design": {"selection_method": "independent_random_sample"},
                    "assumptions": ["Independent registered pairs."],
                    "limitations": ["Named population only."],
                },
                "guardrails": {"all_passed": True},
                "decision": {
                    "minimum_favorable_effect": 0.5,
                    "reason": "registered_minimum_met",
                },
                "limitations": ["No external attempt custody."],
            },
        }

        text = "\n".join(render_experiment_markdown({"experiments": [experiment]}))

        self.assertIn("N / sample unit: 24 / complete_pair", text)
        self.assertIn("Favorable lower bound: 0.5004", text)
        self.assertIn("Registered minimum favorable effect: 0.5", text)
        self.assertIn("Registered effect rule met: true", text)
        self.assertIn("Improvement ready: false", text)
        self.assertIn("Independent registered pairs.", text)
        self.assertIn("Action registry: record remains pending", text)


class PublishedActionBindingIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from agent_readiness.publishing import REPOSITORY_DEPENDENCIES
        from agent_readiness.tests.test_benchmark_registries_v1 import (
            BenchmarkRegistriesV1Test,
        )

        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.repo_root = Path(cls.temp_dir.name)
        cls.package_root = cls.repo_root / "agent_readiness"
        shutil.copytree(
            PACKAGE,
            cls.package_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for relative in REPOSITORY_DEPENDENCIES:
            destination = cls.repo_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((PACKAGE.parent / relative).read_bytes())

        def evidence_paths(value):
            if isinstance(value, dict):
                path = value.get("path")
                if isinstance(path, str) and path.startswith("evidence/"):
                    yield path
                for child in value.values():
                    yield from evidence_paths(child)
            elif isinstance(value, list):
                for child in value:
                    yield from evidence_paths(child)

        for registry_name in (
            "method/benchmark-coverage-v1.json",
            "method/task-families-v1.json",
        ):
            registry_document = json.loads(
                (PACKAGE.parent / registry_name).read_text(encoding="utf-8")
            )
            for relative in evidence_paths(registry_document):
                destination = cls.repo_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((PACKAGE.parent / relative).read_bytes())

        builder = BenchmarkRegistriesV1Test(methodName="runTest")
        builder.setUp()
        cls.improvements = builder._promoted_improvements(
            cls.repo_root,
            "decided",
        )
        improvement_path = cls.repo_root / "method/improvement-registry-v1.json"
        improvement_path.write_text(
            json.dumps(cls.improvements, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        record = cls.improvements["records"][0]
        bindings = record["experiment_design"]["measurement_v1_binding_plan"][
            "bindings"
        ]
        primary = next(
            binding
            for binding in bindings
            if binding["decision_role"] == "primary_efficacy"
        )
        placebo = next(
            binding
            for binding in bindings
            if binding["decision_role"] == "placebo_control"
        )
        manifest_refs = {
            reference["experiment_id"]: reference
            for reference in record["workflow"]["registration"]["manifest_refs"]
        }
        result_refs = {
            reference["experiment_id"]: reference
            for reference in record["workflow"]["execution"]["run_artifact_refs"]
        }

        def pointer(reference: dict) -> dict:
            return {
                "path": reference["path"].removeprefix("agent_readiness/"),
                "sha256": reference["sha256"],
            }

        entries = []
        for binding in (primary, placebo):
            experiment_id = binding["experiment_id"]
            result = json.loads(
                (cls.repo_root / result_refs[experiment_id]["path"]).read_text(
                    encoding="utf-8"
                )
            )
            entries.append({
                "experiment_id": experiment_id,
                "adapter": "measurement_v1",
                "sources": {
                    "manifest": pointer(manifest_refs[experiment_id]),
                    "runs": [
                        pointer(reference)
                        for reference in result["run_artifact_refs"]
                    ],
                },
                "artifact_root": ".",
                "registration_commit": record["workflow"]["registration"][
                    "git_commit"
                ],
            })
        cls.primary_experiment_id = primary["experiment_id"]
        cls.placebo_experiment_id = placebo["experiment_id"]
        cls.registry = {
            "schema_version": "drupal_agent_readiness.experiment_registry.v1",
            "experiments": entries,
        }
        cls.registry_path = (
            cls.package_root / "experiments/published-experiments-v1.json"
        )
        cls._write_registry(cls.registry)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    @classmethod
    def _write_registry(cls, registry: dict) -> None:
        cls.registry_path.parent.mkdir(parents=True, exist_ok=True)
        cls.registry_path.write_text(
            json.dumps(registry, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def test_decided_action_projection_binds_primary_only_and_validates_once(self) -> None:
        from agent_readiness.benchmark_registries_v1 import (
            validated_improvement_projections,
        )
        from agent_readiness.published_experiments import load_published_experiments

        self._write_registry(copy.deepcopy(self.registry))
        with patch(
            "agent_readiness.published_experiments.validated_improvement_projections",
            wraps=validated_improvement_projections,
        ) as projection:
            bundle = load_published_experiments(
                self.package_root,
                self.registry_path,
            )

        self.assertEqual(1, projection.call_count)
        by_id = {item["experiment_id"]: item for item in bundle["experiments"]}
        primary = by_id[self.primary_experiment_id]
        self.assertTrue(primary["registered_effect_rule_met"])
        self.assertTrue(primary["action_registry_binding"]["verified"])
        self.assertTrue(primary["action_registry_binding"]["source_census_verified"])
        self.assertTrue(primary["action_registry_binding"]["synthesis_verified"])
        self.assertEqual(
            "primary_efficacy",
            primary["action_registry_binding"]["decision_role"],
        )
        self.assertIsInstance(
            primary["action_registry_binding"]["adopted_treatment_code_hashes"],
            dict,
        )
        self.assertTrue(primary["improvement_ready"])

        placebo = by_id[self.placebo_experiment_id]
        self.assertFalse(placebo["action_registry_binding"]["verified"])
        self.assertFalse(placebo["improvement_ready"])
        self.assertIn(
            "action binding decision_role is not primary_efficacy",
            placebo["action_registry_binding"]["errors"],
        )

    def test_lifecycle_custody_rejects_byte_identical_source_path_substitution(self) -> None:
        from agent_readiness.published_experiments import load_published_experiments

        registry = copy.deepcopy(self.registry)
        primary = next(
            item
            for item in registry["experiments"]
            if item["experiment_id"] == self.primary_experiment_id
        )
        substituted = []
        for index, pointer in enumerate(primary["sources"]["runs"]):
            source = self.package_root / pointer["path"]
            destination = (
                self.package_root
                / "evidence/substituted-lifecycle-runs"
                / f"run-{index:02d}.json"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            substituted.append({
                "path": destination.relative_to(self.package_root).as_posix(),
                "sha256": pointer["sha256"],
            })
        primary["sources"]["runs"] = substituted
        self._write_registry(registry)
        try:
            bundle = load_published_experiments(
                self.package_root,
                self.registry_path,
            )
        finally:
            self._write_registry(copy.deepcopy(self.registry))

        primary_result = next(
            item
            for item in bundle["experiments"]
            if item["experiment_id"] == self.primary_experiment_id
        )
        self.assertTrue(primary_result["estimate_reportable"])
        self.assertTrue(primary_result["registered_effect_rule_met"])
        self.assertFalse(
            primary_result["action_registry_binding"]["source_census_verified"]
        )
        self.assertFalse(primary_result["action_registry_binding"]["verified"])
        self.assertFalse(primary_result["improvement_ready"])
        self.assertIn(
            "published measurement runs are not the exact lifecycle-custodied run census",
            primary_result["action_registry_binding"]["errors"],
        )


class PublishedExperimentsSourceTest(unittest.TestCase):

    def test_repository_registry_normalizes_hashed_sources(self) -> None:
        from agent_readiness.published_experiments import load_published_experiments

        bundle = load_published_experiments(PACKAGE)

        self.assertEqual("drupal_agent_readiness.published_experiments.v1", bundle["schema_version"])
        self.assertEqual(2, len(bundle["experiments"]))
        alias = bundle["experiments"][0]
        self.assertFalse(alias["claim_grade"])
        self.assertEqual("frontier_observation", alias["lane"])
        self.assertEqual(6, len(alias["metrics"]))
        run_level_results = {
            (row["model_id"], row["arm"]): (
                row["runs_all_hidden_correct"],
                row["runs"],
            )
            for row in alias["metrics"]
        }
        self.assertEqual({
            ("claude-haiku-4-5", "raw_drush"): (8, 10),
            ("claude-haiku-4-5", "site_architecture"): (10, 10),
            ("claude-opus-4-8", "raw_drush"): (7, 10),
            ("claude-opus-4-8", "site_architecture"): (10, 10),
            ("gpt-5.5-codex", "raw_drush"): (0, 3),
            ("gpt-5.5-codex", "site_architecture"): (3, 3),
        }, run_level_results)
        intent = bundle["experiments"][1]
        self.assertEqual(30, intent["selected_run_count"])
        self.assertTrue(all(row["preserved_all_4"] == 0 for row in intent["metrics"]))

    def test_rendered_numbers_come_from_source_not_prose_constants(self) -> None:
        from agent_readiness.published_experiments import (
            load_published_experiments,
            render_experiment_markdown,
        )

        bundle = load_published_experiments(PACKAGE)
        text = "\n".join(render_experiment_markdown(bundle))

        self.assertIn("The run is the analysis unit", text)
        self.assertIn("| claude-haiku-4-5 | raw_drush | 8/10 | 16/20 |", text)
        self.assertIn("| claude-opus-4-8 | raw_drush | 7/10 | 14/20 |", text)
        self.assertIn("| gpt-5.5-codex | raw_drush | 0/3 | 0/6 |", text)
        self.assertIn("16/20", text)
        self.assertIn("14/20", text)
        self.assertIn("0/10", text)
        self.assertIn("claim-grade: `false`", text)

    def test_source_mutation_without_registry_hash_update_fails_closed(self) -> None:
        from agent_readiness.published_experiments import (
            PublishedExperimentError,
            load_published_experiments,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.json"
            source.write_text('{"summary": {"x": {}}}\n', encoding="utf-8")
            registry = {
                "schema_version": "drupal_agent_readiness.experiment_registry.v1",
                "experiments": [{
                    "experiment_id": "x",
                    "task_id": "x",
                    "adapter": "alias_safety_v0",
                    "lane": "frontier_observation",
                    "evidence_class": "exploratory",
                    "claim_boundary": "narrow",
                    "artifacts_complete": False,
                    "pins_complete": False,
                    "sources": {
                        "headline": {
                            "raw": {"path": "source.json", "sha256": "0" * 64},
                            "ground_truth": {"path": "source.json", "sha256": "0" * 64},
                            "derived": {"path": "source.json", "sha256": "0" * 64},
                        },
                        "breadth": {
                            "raw": {"path": "source.json", "sha256": "0" * 64},
                            "ground_truth": {"path": "source.json", "sha256": "0" * 64},
                            "derived": {"path": "source.json", "sha256": "0" * 64},
                        },
                    },
                }],
            }
            path = root / "registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaisesRegex(PublishedExperimentError, "source hash mismatch"):
                load_published_experiments(root, path)

    def test_alias_metrics_are_recomputed_from_raw_answers_and_truth(self) -> None:
        from agent_readiness.published_experiments import (
            PublishedExperimentError,
            load_published_experiments,
        )

        source_dir = PACKAGE / "experiments" / "alias-safety-haven-n10-fullyblind-v0"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointers = {}
            for key, filename in {
                "raw": "raw-workflow-output.json",
                "ground_truth": "ground-truth.json",
                "derived": "model-ab-results.json",
            }.items():
                destination = root / filename
                shutil.copy2(source_dir / filename, destination)
                pointers[key] = {
                    "path": filename,
                    "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                }
            raw_path = root / "raw-workflow-output.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            first = raw["result"]["blind"][0]["answer"]["assessments"]
            candidate = next(iter(first))
            first[candidate]["safe"] = not first[candidate]["safe"]
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            pointers["raw"]["sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            registry = self._historical_alias_registry(pointers)
            registry_path = root / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaisesRegex(PublishedExperimentError, "metrics do not recompute"):
                load_published_experiments(root, registry_path)

    def test_alias_model_identity_is_bound_to_raw_model_label(self) -> None:
        from agent_readiness.published_experiments import (
            PublishedExperimentError,
            load_published_experiments,
        )

        source_dir = PACKAGE / "experiments" / "alias-safety-haven-n10-fullyblind-v0"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointers = {}
            for key, filename in {
                "raw": "raw-workflow-output.json",
                "ground_truth": "ground-truth.json",
                "derived": "model-ab-results.json",
            }.items():
                destination = root / filename
                shutil.copy2(source_dir / filename, destination)
                pointers[key] = {
                    "path": filename,
                    "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                }
            derived_path = root / "model-ab-results.json"
            derived = json.loads(derived_path.read_text(encoding="utf-8"))
            derived["summary"]["ab-haiku-blind"]["model_id"] = "fabricated-model"
            derived_path.write_text(json.dumps(derived), encoding="utf-8")
            pointers["derived"]["sha256"] = hashlib.sha256(
                derived_path.read_bytes()
            ).hexdigest()
            registry_path = root / "registry.json"
            registry_path.write_text(
                json.dumps(self._historical_alias_registry(pointers)),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(PublishedExperimentError, "metrics do not recompute"):
                load_published_experiments(root, registry_path)

    def test_source_path_cannot_escape_package(self) -> None:
        from agent_readiness.published_experiments import (
            PublishedExperimentError,
            load_published_experiments,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / "outside-evidence.json"
            outside.write_text("{}\n", encoding="utf-8")
            digest = hashlib.sha256(outside.read_bytes()).hexdigest()
            registry = {
                "schema_version": "drupal_agent_readiness.experiment_registry.v1",
                "experiments": [{
                    "experiment_id": "escape",
                    "task_id": "x",
                    "adapter": "intent_behavior_summary_v0",
                    "lane": "frontier_observation",
                    "evidence_class": "exploratory",
                    "claim_boundary": "narrow",
                    "artifacts_complete": False,
                    "pins_complete": False,
                    "sources": {"summary": {"path": "../outside-evidence.json", "sha256": digest}},
                }],
            }
            path = root / "registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaisesRegex(PublishedExperimentError, "escapes package root"):
                load_published_experiments(root, path)

            outside.unlink()

    def test_registry_cannot_self_promote_historical_evidence(self) -> None:
        from agent_readiness.published_experiments import (
            PublishedExperimentError,
            load_published_experiments,
        )

        source = PACKAGE / "experiments" / "intent-behavior-evaluation-v0-clean" / "summary.json"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copied = root / "summary.json"
            copied.write_bytes(source.read_bytes())
            registry = {
                "schema_version": "drupal_agent_readiness.experiment_registry.v1",
                "experiments": [{
                    "experiment_id": "self-promoted",
                    "task_id": "x",
                    "adapter": "intent_behavior_summary_v0",
                    "lane": "frontier_observation",
                    "evidence_class": "claim_grade",
                    "claim_boundary": "narrow",
                    "artifacts_complete": True,
                    "pins_complete": True,
                    "sources": {
                        "summary": {
                            "path": "summary.json",
                            "sha256": hashlib.sha256(copied.read_bytes()).hexdigest(),
                        }
                    },
                }],
            }
            path = root / "registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaisesRegex(
                PublishedExperimentError,
                "historical adapters cannot self-promote to claim-grade",
            ):
                load_published_experiments(root, path)

            registry["experiments"][0].update({
                "lane": "fixed_regression",
                "artifacts_complete": False,
                "pins_complete": False,
            })
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(
                PublishedExperimentError,
                "historical adapters must remain frontier_observation",
            ):
                load_published_experiments(root, path)

    def test_measurement_v1_eligibility_is_derived_from_real_git_anchored_sources(self) -> None:
        from agent_readiness.published_experiments import load_published_experiments

        fixture, registry_path = build_git_measurement_registry()
        try:
            bundle = load_published_experiments(fixture.root, registry_path)
        finally:
            fixture.tearDown()

        measurement = bundle["experiments"][0]
        self.assertEqual("fixed_regression", measurement["lane"])
        self.assertTrue(measurement["evidence_complete"])
        self.assertTrue(measurement["estimate_reportable"])
        self.assertTrue(measurement["fixed_estimate_reportable"])
        self.assertTrue(measurement["registered_effect_rule_met"])
        self.assertFalse(measurement["action_registry_binding"]["verified"])
        self.assertFalse(measurement["improvement_ready"])
        self.assertTrue(measurement["audit"]["registration_anchor"]["verified"])

    def test_measurement_v1_registry_cannot_inject_lane_or_readiness_booleans(self) -> None:
        from agent_readiness.published_experiments import (
            PublishedExperimentError,
            load_published_experiments,
        )

        fixture, registry_path = build_git_measurement_registry()
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["experiments"][0].update({
                "lane": "fixed_regression",
                "claim_grade": True,
                "registered_effect_rule_met": True,
                "improvement_ready": True,
            })
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(
                PublishedExperimentError,
                "registry fields must be source-only",
            ):
                load_published_experiments(fixture.root, registry_path)
        finally:
            fixture.tearDown()

    def test_measurement_v1_reportable_null_does_not_self_promote_to_improvement(self) -> None:
        from agent_readiness.published_experiments import load_published_experiments

        fixture, registry_path = build_git_measurement_registry(improvement=False)
        try:
            measurement = load_published_experiments(
                fixture.root, registry_path
            )["experiments"][0]
        finally:
            fixture.tearDown()

        self.assertTrue(measurement["evidence_complete"])
        self.assertTrue(measurement["estimate_reportable"])
        self.assertTrue(measurement["fixed_estimate_reportable"])
        self.assertFalse(measurement["registered_effect_rule_met"])
        self.assertFalse(measurement["improvement_ready"])

    def test_measurement_v1_run_source_hash_is_enforced_before_audit(self) -> None:
        from agent_readiness.published_experiments import (
            PublishedExperimentError,
            load_published_experiments,
        )

        fixture, registry_path = build_git_measurement_registry()
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            run_path = fixture.root / registry["experiments"][0]["sources"]["runs"][0]["path"]
            run_path.write_bytes(run_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(PublishedExperimentError, "source hash mismatch"):
                load_published_experiments(fixture.root, registry_path)
        finally:
            fixture.tearDown()

    def test_measurement_manifest_source_must_match_committed_canonical_bytes(self) -> None:
        from agent_readiness.published_experiments import (
            PublishedExperimentError,
            load_published_experiments,
        )

        fixture, registry_path = build_git_measurement_registry()
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            manifest_pointer = registry["experiments"][0]["sources"]["manifest"]
            manifest_path = fixture.root / manifest_pointer["path"]
            manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
            manifest_pointer["sha256"] = hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest()
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaisesRegex(
                PublishedExperimentError,
                "exact canonical JSON bytes",
            ):
                load_published_experiments(fixture.root, registry_path)
        finally:
            fixture.tearDown()

    @staticmethod
    def _historical_alias_registry(pointers: dict) -> dict:
        return {
            "schema_version": "drupal_agent_readiness.experiment_registry.v1",
            "experiments": [{
                "experiment_id": "historical-alias-test",
                "task_id": "assess.alias_safety",
                "adapter": "alias_safety_v0",
                "lane": "frontier_observation",
                "evidence_class": "exploratory_legacy_unpinned",
                "claim_boundary": "test-only bounded historical observation",
                "artifacts_complete": False,
                "pins_complete": False,
                "sources": {
                    "headline": copy.deepcopy(pointers),
                    "breadth": copy.deepcopy(pointers),
                },
            }],
        }


if __name__ == "__main__":
    unittest.main()
