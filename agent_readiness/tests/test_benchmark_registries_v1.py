from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_readiness.benchmark_registries_v1 import (
    ACTION_SUCCESS_FINAL_STATE_DELTA,
    REPO_ROOT,
    RegistryValidationError,
    _immutable_design_snapshot,
    _prioritization_snapshot_sha256,
    _materialize_binding_attempt_roster,
    _derive_registered_contrast_gate,
    _expected_calibration_decision,
    _expected_measurement_guardrails,
    _expected_measurement_outcome_metrics,
    _expected_precision_rationale,
    _held_fixed_stack_projection,
    _portable_measurement_audit,
    _state_leaf_differences,
    _validate_actual_write_behavior,
    _validate_alias_arms,
    _validate_design_cell_pins,
    _validate_owner_attestation,
    _validate_prioritization,
    _validate_prioritization_ranks,
    _validate_substrate_ground_truth,
    _validate_workflow_state,
    load_default_registries,
    resolve_hashed_artifact,
    validate_schema_instance,
    validate_registries,
)
from agent_readiness.measurement_v1 import GitRegistrationAnchor, audit_measurement_v1
from agent_readiness.tests import test_measurement_v1 as measurement_fixture_module
from agent_readiness.alias_safety_metrics import (
    AliasSafetyMetricError,
    recompute_action_alias_metrics,
    validate_retained_alias_safety_results,
)
from agent_readiness.scripts import audit_benchmark_registries_v1


class BenchmarkRegistriesV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.coverage, self.tasks, self.improvements = load_default_registries()

    def validate(
        self,
        coverage: dict | None = None,
        tasks: dict | None = None,
        improvements: dict | None = None,
    ) -> None:
        validate_registries(
            coverage or self.coverage,
            tasks or self.tasks,
            improvements or self.improvements,
        )

    @staticmethod
    def _canonical_bytes(payload: dict) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def _write_workflow_artifact(
        self,
        root: Path,
        *,
        artifact_id: str,
        relative_path: str,
        artifact_type: str,
        payload: dict,
        experiment_id: str | None = None,
    ) -> dict:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = self._canonical_bytes(payload)
        path.write_bytes(raw)
        reference = {
            "id": artifact_id,
            "path": relative_path,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "artifact_type": artifact_type,
        }
        if experiment_id is not None:
            reference["experiment_id"] = experiment_id
        return reference

    def _rewrite_workflow_artifact(
        self, root: Path, reference: dict, payload: dict
    ) -> None:
        raw = self._canonical_bytes(payload)
        (root / reference["path"]).write_bytes(raw)
        reference["sha256"] = hashlib.sha256(raw).hexdigest()

    def _complete_prioritization(
        self, improvements: dict, *, state: str = "unranked_owner_decision_pending"
    ) -> dict:
        record = improvements["records"][0]
        prioritization = record["prioritization"]
        for score, dimension in enumerate(
            (
                "occurrence",
                "consequence",
                "lifecycle_reach",
                "owner_site_reach",
                "delivery_effort",
                "strategic_fit",
            ),
            start=1,
        ):
            prioritization[dimension] = {
                "status": "evidence_complete",
                "score": min(score, 5),
                "evidence_ids": ["alias-safety-derived-metrics"],
            }
        prioritization["state"] = state
        prioritization["evidence_ids"] = ["alias-safety-derived-metrics"]
        prioritization["owner_decision_artifact"] = None
        prioritization["rank"] = None
        return record

    def _write_prioritization_owner_decision(
        self,
        root: Path,
        record: dict,
        *,
        rank: int = 1,
        owner_ids: list[str] | None = None,
    ) -> dict:
        owner_ids = owner_ids or ["ai-context-maintainers"]
        prioritization = record["prioritization"]
        prioritization["state"] = "ranked"
        prioritization["rank"] = rank
        payload = {
            "schema_version": (
                "drupal_agent_readiness.improvement_prioritization_owner_decision.v1"
            ),
            "improvement_record_id": record["id"],
            "decision": "rank",
            "rank": rank,
            "owner_ids": owner_ids,
            "dimension_scores": {
                dimension: prioritization[dimension]["score"]
                for dimension in (
                    "occurrence",
                    "consequence",
                    "lifecycle_reach",
                    "owner_site_reach",
                    "delivery_effort",
                    "strategic_fit",
                )
            },
            "evidence_ids": prioritization["evidence_ids"],
            "prioritization_snapshot_sha256": (
                _prioritization_snapshot_sha256(prioritization)
            ),
        }
        reference = self._write_workflow_artifact(
            root,
            artifact_id=f"{record['id']}-prioritization-owner-decision-v1",
            relative_path=(
                "agent_readiness/evidence/decisions/"
                f"{record['id']}/prioritization-owner-decision-v1.json"
            ),
            artifact_type="improvement_prioritization_owner_decision",
            payload=payload,
        )
        reference["owner_ids"] = owner_ids
        prioritization["owner_decision_artifact"] = reference
        return reference

    def _rewrite_run_artifact(
        self,
        package_root: Path,
        run: dict,
        kind: str,
        payload: dict,
    ) -> None:
        artifact = next(item for item in run["artifacts"] if item["kind"] == kind)
        raw = self._canonical_bytes(payload)
        path = package_root / artifact["uri"]
        path.write_bytes(raw)
        artifact["sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
        artifact["byte_size"] = len(raw)

    def _materialize_action_write_evidence(
        self,
        fixture: measurement_fixture_module.MeasurementV1Test,
        package_root: Path,
        run: dict,
        ground_truth: dict,
        answer: dict,
    ) -> dict:
        truth_by_path = {item["path"]: item for item in ground_truth["path_truth"]}
        judgments = {item["path"]: item for item in answer["candidate_path_judgments"]}
        artifacts = {artifact["kind"]: artifact for artifact in run["artifacts"]}
        attempt = json.loads(
            (package_root / artifacts["attempt_receipt"]["uri"]).read_text()
        )
        tool_failure = not (
            attempt.get("status") == "succeeded"
            and attempt.get("returncode") == 0
            and attempt.get("timed_out") is False
        )
        collision_paths = sorted(
            path
            for path, truth in truth_by_path.items()
            if truth["truth"] != "free"
            and judgments[path]["write_decision"] == "attempt"
        )
        refused_paths = sorted(
            path
            for path, truth in truth_by_path.items()
            if truth["truth"] == "free"
            and judgments[path]["write_decision"] == "withhold"
        )
        atomic_failure = bool(collision_paths or refused_paths or tool_failure)
        completed_paths = sorted(
            path
            for path, truth in truth_by_path.items()
            if not atomic_failure
            and truth["truth"] == "free"
            and judgments[path]["write_decision"] == "attempt"
        )
        run["final_drupal_state"] = copy.deepcopy(run["arm"]["drupal_state"])
        if completed_paths:
            start_site = run["arm"]["drupal_state"]["site"]
            start_aliases = json.loads(
                (package_root / start_site["sources"]["database"]["uri"]).read_text()
            )["aliases"]
            final_aliases = list(start_aliases)
            final_aliases.extend(
                {
                    "path": path,
                    "owner_id": truth_by_path[path]["requested_post_owner_id"],
                    "identity": truth_by_path[path]["requested_post_identity"],
                }
                for path in completed_paths
            )
            final_aliases.sort(key=lambda alias: alias["path"])
            final_database = fixture._pin_document(
                f"runs/{run['run_id']}/final-database.json",
                {
                    "schema_version": "drupal_agent_readiness.alias_state.v1",
                    "fixture_id": start_site["fixture_id"],
                    "aliases": final_aliases,
                },
            )
            final_site = copy.deepcopy(start_site)
            final_site["sources"]["database"] = final_database
            final_site["database_sha256"] = final_database["sha256"]
            site_manifest_document = {
                "schema_version": "drupal_agent_readiness.site_state_manifest.v1",
                "fixture_id": final_site["fixture_id"],
                "database_sha256": final_database["sha256"],
                "active_config_sha256": final_site["sources"]["active_config"][
                    "sha256"
                ],
                "public_files_sha256": final_site["sources"]["public_files"]["sha256"],
                "private_files_sha256": final_site["sources"]["private_files"][
                    "sha256"
                ],
            }
            final_manifest = fixture._pin_document(
                f"runs/{run['run_id']}/final-site-manifest.json",
                site_manifest_document,
            )
            final_site["manifest"] = final_manifest
            final_site["composite_sha256"] = final_manifest["sha256"]
            run["final_drupal_state"]["site"] = final_site

        fixture._refresh_receipts(run)
        artifacts = {artifact["kind"]: artifact for artifact in run["artifacts"]}
        observed_delta = sorted(
            _state_leaf_differences(
                run["arm"]["drupal_state"], run["final_drupal_state"]
            )
        )
        allowed_delta = [] if atomic_failure else ACTION_SUCCESS_FINAL_STATE_DELTA
        path_probes = []
        for truth in ground_truth["path_truth"]:
            path = truth["path"]
            decision = judgments[path]["write_decision"]
            if path in collision_paths:
                outcome = "collision"
            elif path in refused_paths:
                outcome = "refused"
            elif path in completed_paths:
                outcome = "completed"
            elif decision == "attempt":
                outcome = "rolled_back"
            else:
                outcome = "withheld"
            post_owner_id = truth["owner_id"]
            post_identity = truth["identity"]
            if outcome == "completed":
                post_owner_id = truth["requested_post_owner_id"]
                post_identity = truth["requested_post_identity"]
            path_probes.append(
                {
                    "path": path,
                    "truth": truth["truth"],
                    "write_decision": decision,
                    "outcome": outcome,
                    "pre_owner_id": truth["owner_id"],
                    "pre_identity": truth["identity"],
                    "post_owner_id": post_owner_id,
                    "post_identity": post_identity,
                }
            )
        probe = {
            "schema_version": "drupal_agent_readiness.post_write_probe.v1",
            "run_id": run["run_id"],
            "roster_slot_id": run["attempt"]["roster_slot_id"],
            "starting_state_artifact_sha256": artifacts["starting_state"]["sha256"],
            "final_state_artifact_sha256": artifacts["final_state"]["sha256"],
            "attempt_receipt_artifact_sha256": artifacts["attempt_receipt"]["sha256"],
            "starting_site_composite_sha256": run["arm"]["drupal_state"]["site"][
                "composite_sha256"
            ],
            "final_site_composite_sha256": run["final_drupal_state"]["site"][
                "composite_sha256"
            ],
            "allowed_final_state_delta": allowed_delta,
            "observed_final_state_delta": observed_delta,
            "tool_failure": tool_failure,
            "path_probes": path_probes,
        }
        artifacts["tool_log"]["media_type"] = "application/json"
        self._rewrite_run_artifact(package_root, run, "tool_log", probe)
        return {
            "completed_paths": completed_paths,
            "collision_paths": collision_paths,
            "refused_paths": refused_paths,
            "state_delta_valid": observed_delta == allowed_delta,
            "tool_failure": tool_failure,
        }

    def _promoted_improvements(
        self,
        root: Path,
        state: str,
        *,
        outcome: str = "adopt",
        failing_contrast_id: str | None = None,
        placebo_effect: bool = False,
    ) -> dict:
        improvements = copy.deepcopy(self.improvements)
        record = improvements["records"][0]
        record["workflow_state"] = state
        package_root = root / "agent_readiness"
        package_root.mkdir(parents=True, exist_ok=True)
        fixture = measurement_fixture_module.MeasurementV1Test(methodName="runTest")
        fixture.root = package_root
        fixture.manifest = fixture._manifest()
        base_manifest = copy.deepcopy(fixture.manifest)
        base_manifest["task"]["id"] = "assess.alias_safety"
        base_manifest["task"]["lifecycle_stages"] = [
            "understand",
            "act",
            "verify",
        ]
        base_manifest["reference_agent_stack"]["tools"].append(
            {
                "id": "drush",
                "version": "13.6.2",
                "artifact": fixture._pin("drush-tool.json"),
            }
        )
        base_manifest["reference_agent_stack"]["permissions"][
            "allowed_capabilities"
        ].append("drush")
        base_manifest["execution_plan"]["stopping_rule"] = {
            "kind": "fixed_census",
            "required_resolved_slots": 40,
            "allow_replacements": False,
            "on_exclusion": "no_claim",
        }

        execution_environment_policy_sha256 = json.loads(
            (
                package_root
                / base_manifest["reference_agent_stack"]["model"][
                    "inference_parameters"
                ]["uri"]
            ).read_text()
        )["execution_environment_policy_sha256"]
        model_documents = {
            "fixed-model-primary": {
                "seed": 41001,
                "temperature": 0,
                "top_p": 1,
                "execution_environment_policy_sha256": execution_environment_policy_sha256,
            },
            "fixed-model-replication": {
                "seed": 41002,
                "temperature": 0,
                "top_p": 1,
                "execution_environment_policy_sha256": execution_environment_policy_sha256,
            },
        }
        model_profiles = {
            "fixed-model-primary": (
                "local-fixture-primary",
                "fixture-model-a",
                "fixture-model-a-2026-07-01",
            ),
            "fixed-model-replication": (
                "local-fixture-replication",
                "fixture-model-b",
                "fixture-model-b-2026-06-15",
            ),
        }
        model_pins = {}
        model_backend_contracts = {}
        model_cells = {
            item["id"]: item for item in record["experiment_design"]["model_cells"]
        }
        for model_cell_id, document in model_documents.items():
            pin = fixture._pin_document(
                f"models/{model_cell_id}-inference.json", document
            )
            model_pins[model_cell_id] = pin
            provider, model_id, snapshot = model_profiles[model_cell_id]
            local_model_artifact = fixture._pin(
                f"models/{model_cell_id}-weights.gguf"
            )
            required_model_argument = (
                "--model-artifact-sha256=" + local_model_artifact["sha256"]
            )
            runner_contract_pin = fixture._pin_document(
                f"models/{model_cell_id}-runner-contract.json",
                {
                    "schema_version": (
                        "drupal_agent_readiness.local_model_runner_attestation_contract.v1"
                    ),
                    "required_invocation_argument": required_model_argument,
                    "trust_boundary": (
                        "pinned_harness_and_retained_execution_receipt"
                    ),
                },
            )
            backend_contract = {
                "mode": "local_model_artifact",
                "expected_backend_identity": local_model_artifact["sha256"],
                "attestation_contract": None,
                "local_model_artifact": local_model_artifact,
                "runner_attestation_contract": {
                    "id": f"{model_cell_id}-runner-attestation",
                    "version": "1.0.0",
                    "artifact": runner_contract_pin,
                },
                "required_invocation_argument": required_model_argument,
            }
            model_backend_contracts[model_cell_id] = backend_contract
            projection_manifest = copy.deepcopy(base_manifest)
            projection_manifest["reference_agent_stack"]["model"] = {
                "provider": provider,
                "id": model_id,
                "snapshot": snapshot,
                "inference_parameters": pin,
                "backend_identity_contract": copy.deepcopy(backend_contract),
            }
            held_fixed_stack_sha256 = hashlib.sha256(
                self._canonical_bytes(_held_fixed_stack_projection(projection_manifest))
            ).hexdigest()
            model_cells[model_cell_id].update(
                {
                    "pin_state": "frozen",
                    "provider": provider,
                    "model_id": model_id,
                    "snapshot": snapshot,
                    "inference_parameters_sha256": pin["sha256"].removeprefix(
                        "sha256:"
                    ),
                    "held_fixed_stack_sha256": held_fixed_stack_sha256,
                }
            )

        arms_by_id = {item["id"]: item for item in record["experiment_design"]["arms"]}
        arm_states = {}
        arm_treatment_pins = {}
        for arm_id, arm in arms_by_id.items():
            arm_state = fixture._drupal_state(arm_id)
            if not arm["capability_installed"]:
                arm_state["code"]["components"] = []
                code_manifest = {
                    "schema_version": "drupal_agent_readiness.code_state_manifest.v1",
                    "core": arm_state["code"]["core"],
                    "components": [],
                    "composer_lock_sha256": arm_state["code"]["composer_lock_sha256"],
                    "extensions_manifest_sha256": arm_state["code"][
                        "extensions_manifest_sha256"
                    ],
                    "codebase_tree_sha256": arm_state["code"]["codebase_tree_sha256"],
                }
                arm_state["code"]["manifest"] = fixture._pin_document(
                    f"state/code/code-state-{arm_id}-absent.json", code_manifest
                )
            treatment_pin = fixture._pin_document(
                f"treatments/{arm_id}.json",
                {
                    "schema_version": "drupal_agent_readiness.arm_implementation.v1",
                    "arm_id": arm_id,
                    "capability_mode": arm["capability_mode"],
                    "help_discoverable": arm["help_discoverable"],
                    "facts_available": arm["facts_available"],
                    "advice_available": arm["advice_available"],
                },
            )
            arm_states[arm_id] = arm_state
            arm_treatment_pins[arm_id] = treatment_pin
            arm.update(
                {
                    "implementation_pin_state": "frozen",
                    "drupal_code_tree_sha256": arm_state["code"][
                        "codebase_tree_sha256"
                    ].removeprefix("sha256:"),
                    "capability_component_tree_sha256": (
                        arm_state["code"]["components"][0]["tree_sha256"].removeprefix(
                            "sha256:"
                        )
                        if arm["capability_installed"]
                        else None
                    ),
                    "treatment_artifact_sha256": treatment_pin["sha256"].removeprefix(
                        "sha256:"
                    ),
                }
            )

        clean_seed = copy.deepcopy(base_manifest["substrate"]["starting_site_seed"])
        clean_database = fixture._pin_document(
            "state/site/database-clean.json",
            {
                "schema_version": "drupal_agent_readiness.alias_state.v1",
                "fixture_id": clean_seed["fixture_id"],
                "aliases": [],
            },
        )
        clean_seed["sources"]["database"] = clean_database
        clean_manifest_document = {
            "schema_version": "drupal_agent_readiness.site_state_manifest.v1",
            "fixture_id": clean_seed["fixture_id"],
            "database_sha256": clean_database["sha256"],
            "active_config_sha256": clean_seed["sources"]["active_config"]["sha256"],
            "public_files_sha256": clean_seed["sources"]["public_files"]["sha256"],
            "private_files_sha256": clean_seed["sources"]["private_files"]["sha256"],
        }
        clean_manifest_pin = fixture._pin_document(
            "state/site/site-state-manifest-clean.json", clean_manifest_document
        )
        clean_seed.update(
            {
                key: value
                for key, value in clean_manifest_document.items()
                if key != "schema_version"
            }
        )
        clean_seed["composite_sha256"] = clean_manifest_pin["sha256"]
        clean_seed["manifest"] = clean_manifest_pin
        messy_seed = copy.deepcopy(clean_seed)
        messy_database = fixture._pin_document(
            "state/site/database-messy.json",
            {
                "schema_version": "drupal_agent_readiness.alias_state.v1",
                "fixture_id": "alias-messy-owner-described-v1",
                "aliases": [
                    {
                        "path": "/preexisting-alias",
                        "owner_id": "fixture-site-owner",
                        "identity": "existing-target:preexisting-alias",
                    }
                ],
            },
        )
        messy_seed["sources"]["database"] = messy_database
        messy_manifest_document = {
            "schema_version": "drupal_agent_readiness.site_state_manifest.v1",
            "fixture_id": "alias-messy-owner-described-v1",
            "database_sha256": messy_database["sha256"],
            "active_config_sha256": messy_seed["sources"]["active_config"]["sha256"],
            "public_files_sha256": messy_seed["sources"]["public_files"]["sha256"],
            "private_files_sha256": messy_seed["sources"]["private_files"]["sha256"],
        }
        messy_manifest_pin = fixture._pin_document(
            "state/site/site-state-manifest-messy.json", messy_manifest_document
        )
        messy_seed.update(
            {
                key: value
                for key, value in messy_manifest_document.items()
                if key != "schema_version"
            }
        )
        messy_seed["composite_sha256"] = messy_manifest_pin["sha256"]
        messy_seed["manifest"] = messy_manifest_pin
        substrate_seeds = {
            "clean": clean_seed,
            "messy_owner_described": messy_seed,
        }
        owned_path_inventory = [
            {
                "path": "/preexisting-alias",
                "owner_id": "fixture-site-owner",
                "identity": "existing-target:preexisting-alias",
                "status": "preexisting_owned",
                "authority": "site_owner",
            }
        ]
        messy_owner_attestation = fixture._pin_document(
            "substrates/messy-owner-attestation.json",
            {
                "schema_version": "drupal_agent_readiness.owner_attestation.v1",
                "fixture_id": messy_seed["fixture_id"],
                "starting_site_manifest_sha256": messy_seed["manifest"]["sha256"],
                "coverage_claim_id": record["failure"]["claim_id"],
                "scope": {
                    "task_family_id": record["task_family_id"],
                    "task_id": "assess.alias_safety",
                    "authority": "site_owner",
                    "claim": "preexisting_path_ownership_only",
                },
                "path_inventory": owned_path_inventory,
                "issuer": {
                    "id": "fixture-site-owner",
                    "authority": "site_owner",
                    "attested_at": "2026-07-09T08:00:00Z",
                },
            },
        )
        substrate_context_pins = {}
        for substrate_id, seed in substrate_seeds.items():
            path_truth = [
                {
                    "path": "/requested-alias",
                    "truth": "free",
                    "owner_id": None,
                    "identity": None,
                    "requested_post_owner_id": "benchmark-agent",
                    "requested_post_identity": "requested-target:requested-alias",
                },
                {
                    "path": "/hidden-reservation",
                    "truth": "hidden_claim",
                    "owner_id": "evaluator-hidden-claim",
                    "identity": "hidden-target:hidden-reservation",
                    "requested_post_owner_id": "benchmark-agent",
                    "requested_post_identity": "requested-target:hidden-reservation",
                },
            ]
            if substrate_id == "messy_owner_described":
                path_truth.append(
                    {
                        "path": "/preexisting-alias",
                        "truth": "preexisting_owned",
                        "owner_id": "fixture-site-owner",
                        "identity": "existing-target:preexisting-alias",
                        "requested_post_owner_id": "benchmark-agent",
                        "requested_post_identity": "requested-target:preexisting-alias",
                    }
                )
            ground_truth_pin = fixture._pin_document(
                f"substrates/{substrate_id}-ground-truth.json",
                {
                    "schema_version": "drupal_agent_readiness.alias_safety_ground_truth.v1",
                    "substrate_id": substrate_id,
                    "fixture_id": seed["fixture_id"],
                    "starting_site_manifest_sha256": seed["manifest"]["sha256"],
                    "coverage_claim_id": record["failure"]["claim_id"],
                    "task_id": "assess.alias_safety",
                    "path_truth": path_truth,
                },
            )
            ground_truth_pin.update(
                {
                    "evidence_role": "ground_truth",
                    "visibility": "withheld_from_agent",
                    "audience": ["evaluator", "auditor"],
                }
            )
            render_inputs_pin = fixture._pin_document(
                f"substrates/{substrate_id}-render-inputs.json",
                {
                    "schema_version": "drupal_agent_readiness.alias_safety_render_inputs.v1",
                    "fixture_id": seed["fixture_id"],
                    "owner_described_paths": (
                        owned_path_inventory
                        if substrate_id == "messy_owner_described"
                        else []
                    ),
                },
            )
            render_inputs_pin.update(
                {
                    "evidence_role": "render_inputs",
                    "visibility": "agent_visible",
                    "audience": ["agent", "harness", "auditor"],
                }
            )
            substrate_context_pins[substrate_id] = {
                "ground_truth": ground_truth_pin,
                "render_inputs": render_inputs_pin,
            }
        substrate_cells = {
            item["id"]: item for item in record["experiment_design"]["substrate_cells"]
        }
        for substrate_id, seed in substrate_seeds.items():
            substrate_cells[substrate_id].update(
                {
                    "pin_state": "frozen",
                    "fixture_id": seed["fixture_id"],
                    "starting_site_manifest_sha256": seed["manifest"][
                        "sha256"
                    ].removeprefix("sha256:"),
                    "owner_attestation_sha256": (
                        messy_owner_attestation["sha256"].removeprefix("sha256:")
                        if substrate_id == "messy_owner_described"
                        else None
                    ),
                }
            )

        binding_plan = record["experiment_design"]["measurement_v1_binding_plan"]
        state_index = [
            "pending_registration",
            "frozen",
            "executed",
            "analyzed",
            "decided",
        ].index(state)

        snapshot_payload = _immutable_design_snapshot(record)
        snapshot_ref = self._write_workflow_artifact(
            root,
            artifact_id=f"{record['id']}-design-snapshot",
            relative_path=(
                "agent_readiness/evidence/registrations/"
                f"{record['id']}/design-snapshot.json"
            ),
            artifact_type="improvement_design_snapshot",
            payload=snapshot_payload,
        )
        snapshot_path = root / snapshot_ref["path"]
        snapshot_pin = {
            "uri": snapshot_ref["path"].removeprefix("agent_readiness/"),
            "sha256": f"sha256:{snapshot_ref['sha256']}",
            "media_type": "application/json",
            "byte_size": snapshot_path.stat().st_size,
        }
        design_basis_payload = _expected_precision_rationale(
            record, snapshot_ref["sha256"]
        )
        design_basis_ref = self._write_workflow_artifact(
            root,
            artifact_id=f"{record['id']}-precision-feasibility-rationale",
            relative_path=(
                "agent_readiness/evidence/registrations/"
                f"{record['id']}/precision-feasibility-rationale.json"
            ),
            artifact_type="sample_size_rationale",
            payload=design_basis_payload,
        )
        design_basis_path = root / design_basis_ref["path"]
        design_basis_pin = {
            "uri": design_basis_ref["path"].removeprefix("agent_readiness/"),
            "sha256": f"sha256:{design_basis_ref['sha256']}",
            "media_type": "application/json",
            "byte_size": design_basis_path.stat().st_size,
        }
        calibration_decision_ref = self._write_workflow_artifact(
            root,
            artifact_id=f"{record['id']}-calibration-design-decision",
            relative_path=(
                "agent_readiness/evidence/registrations/"
                f"{record['id']}/calibration-design-decision.json"
            ),
            artifact_type="calibration_design_decision",
            payload=_expected_calibration_decision(record, snapshot_ref["sha256"]),
        )

        manifest_refs = {}
        manifests = {}
        binding_ids = {}
        bindings_by_experiment = {}
        for binding in binding_plan["bindings"]:
            experiment_id = binding["experiment_id"]
            binding_ids[experiment_id] = binding["id"]
            bindings_by_experiment[experiment_id] = binding
            manifest = copy.deepcopy(base_manifest)
            manifest["experiment_id"] = experiment_id
            manifest_path = (
                "agent_readiness/evidence/registrations/"
                f"{record['id']}/manifests/{binding['id']}.json"
            )
            manifest["registration"]["manifest_path"] = manifest_path
            manifest["governance"] = {
                "coverage_claim_id": record["failure"]["claim_id"],
                "task_family_id": record["task_family_id"],
                "improvement_record_id": record["id"],
                "registry_design": {
                    "id": improvements["registry_id"],
                    "version": improvements["schema_version"],
                    "artifact": snapshot_pin,
                },
            }
            claim = next(
                item
                for item in self.coverage["published_claims"]
                if item["id"] == record["failure"]["claim_id"]
            )
            manifest["task"]["id"] = claim["task_id"]
            manifest["task"]["ground_truth"] = copy.deepcopy(
                substrate_context_pins[binding["substrate_id"]]["ground_truth"]
            )
            manifest["prompt_composition"]["render_inputs"] = copy.deepcopy(
                substrate_context_pins[binding["substrate_id"]]["render_inputs"]
            )
            manifest["arms"][0]["arm_id"] = binding["pre_arm_id"]
            manifest["arms"][1]["arm_id"] = binding["post_arm_id"]
            for role_index, arm_id in enumerate(
                (binding["pre_arm_id"], binding["post_arm_id"])
            ):
                manifest_arm = manifest["arms"][role_index]
                manifest_arm["treatment"] = {
                    "id": arm_id,
                    "kind": "none" if role_index == 0 else "drupal_code",
                    "artifact": copy.deepcopy(arm_treatment_pins[arm_id]),
                }
                manifest_arm["drupal_state"] = copy.deepcopy(arm_states[arm_id])
            manifest["comparison"]["pre_arm_id"] = binding["pre_arm_id"]
            manifest["comparison"]["post_arm_id"] = binding["post_arm_id"]
            if not arms_by_id[binding["pre_arm_id"]]["capability_installed"]:
                manifest["comparison"]["allowed_changed_paths"].extend(
                    [
                        "/code/components/module:site_architecture/kind",
                        "/code/components/module:site_architecture/name",
                        "/code/components/module:site_architecture/revision",
                        "/code/components/module:site_architecture/version",
                        "/code/manifest/byte_size",
                    ]
                )
            manifest["execution_plan"] = {
                "attempt_roster": _materialize_binding_attempt_roster(
                    binding, binding_plan["roster_contract"]
                ),
                "stopping_rule": {
                    "kind": "fixed_census",
                    "required_resolved_slots": 40,
                    "allow_replacements": False,
                    "on_exclusion": "no_claim",
                },
            }
            primary_metric_id = record["analysis_plan"]["primary_metric"]["id"]
            manifest["outcome_metrics"] = _expected_measurement_outcome_metrics(record)
            manifest["evaluation"]["verdict_metric_id"] = "task_success"
            manifest["claim_plan"].update(
                {
                    "primary_metric_id": primary_metric_id,
                    "planned_denominator": 20,
                    "minimum_favorable_effect": record["expected_delta"][
                        "minimum_effect"
                    ],
                    "sample_size_rationale": design_basis_pin,
                    "guardrails": _expected_measurement_guardrails(
                        record, binding["decision_role"]
                    ),
                }
            )
            model = model_cells[binding["model_cell_id"]]
            manifest["reference_agent_stack"]["model"] = {
                "provider": model["provider"],
                "id": model["model_id"],
                "snapshot": model["snapshot"],
                "inference_parameters": model_pins[binding["model_cell_id"]],
                "backend_identity_contract": copy.deepcopy(
                    model_backend_contracts[binding["model_cell_id"]]
                ),
            }
            manifest["substrate"]["starting_site_seed"] = copy.deepcopy(
                substrate_seeds[binding["substrate_id"]]
            )
            manifest["substrate"]["substrate_id"] = binding["substrate_id"]
            manifest["substrate"]["owner_attestation"] = (
                copy.deepcopy(messy_owner_attestation)
                if binding["substrate_id"] == "messy_owner_described"
                else None
            )
            for arm in manifest["arms"]:
                arm["drupal_state"]["site"] = copy.deepcopy(
                    substrate_seeds[binding["substrate_id"]]
                )
            manifest_refs[experiment_id] = self._write_workflow_artifact(
                root,
                artifact_id=f"{binding['id']}-manifest",
                relative_path=manifest_path,
                artifact_type="measurement_v1_manifest",
                payload=manifest,
                experiment_id=experiment_id,
            )
            manifests[experiment_id] = manifest

        for command in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "benchmark@example.invalid"],
            ["git", "config", "user.name", "Benchmark Fixture"],
            ["git", "add", "agent_readiness/evidence/registrations"],
        ):
            completed = subprocess.run(
                command, cwd=root, check=False, capture_output=True, text=True
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
        commit_env = {
            **os.environ,
            "GIT_AUTHOR_DATE": "2026-07-09T09:00:00Z",
            "GIT_COMMITTER_DATE": "2026-07-09T09:00:00Z",
        }
        completed = subprocess.run(
            ["git", "commit", "-q", "-m", "Freeze benchmark manifests"],
            cwd=root,
            env=commit_env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        workflow = {
            "registration": {
                "state": "frozen",
                "design_snapshot_sha256": snapshot_ref["sha256"],
                "design_snapshot_ref": snapshot_ref,
                "design_basis_ref": design_basis_ref,
                "calibration_decision_ref": calibration_decision_ref,
                "git_commit": git_commit,
                "manifest_refs": list(manifest_refs.values()),
            },
            "execution": {"state": "not_started", "run_artifact_refs": []},
            "analysis": {"state": "not_computed", "derived_metric_refs": []},
            "decision": {
                "state": "pending",
                "outcome": "none",
                "artifact_refs": [],
                "derived_metric_ids": [],
            },
            "transitions": [],
        }

        result_refs = {}
        runs_by_experiment = {}
        if state_index >= 2:
            for experiment_id, manifest_ref in manifest_refs.items():
                binding = bindings_by_experiment[experiment_id]
                binding_id = binding_ids[experiment_id]
                manifest = manifests[experiment_id]
                fixture.manifest = manifest
                contrast_id = binding["contrast_id"]
                favorable_effect = contrast_id == "structured-facts"
                if contrast_id.endswith("placebo"):
                    favorable_effect = placebo_effect
                if failing_contrast_id == contrast_id:
                    favorable_effect = False
                run_refs = []
                runs = []
                for attempt in manifest["execution_plan"]["attempt_roster"]:
                    for slot in attempt["executions"]:
                        role = (
                            "pre" if slot["arm_id"] == binding["pre_arm_id"] else "post"
                        )
                        if favorable_effect:
                            metric_value = 1 if role == "pre" else 0
                        else:
                            metric_value = 0
                        run = fixture._run(
                            slot["slot_id"],
                            role,
                            attempt["index"],
                            attempt["pair_id"],
                            attempt["unit_id"],
                            slot["order"],
                            11 if slot["order"] == 1 else 12,
                            1,
                        )
                        for event, event_type in zip(
                            run["behavior_events"],
                            (
                                "path_owner_inspection",
                                "actual_write_attempt",
                                "post_write_collision_probe",
                            ),
                            strict=True,
                        ):
                            event["event_type"] = event_type
                        ground_truth = json.loads(
                            (
                                package_root / manifest["task"]["ground_truth"]["uri"]
                            ).read_text()
                        )
                        judgments = []
                        for truth in ground_truth["path_truth"]:
                            false_safe = (
                                truth["truth"] == "hidden_claim" and metric_value == 1
                            )
                            is_free = truth["truth"] == "free"
                            judgments.append(
                                {
                                    "path": truth["path"],
                                    "classification": (
                                        "safe_to_write"
                                        if is_free or false_safe
                                        else "unsafe_claimed"
                                    ),
                                    "write_decision": (
                                        "attempt"
                                        if is_free or false_safe
                                        else "withhold"
                                    ),
                                }
                            )
                        answer = {
                            "schema_version": "drupal_agent_readiness.alias_safety_action_answer.v1",
                            "run_id": run["run_id"],
                            "candidate_path_judgments": judgments,
                        }
                        self._rewrite_run_artifact(package_root, run, "answer", answer)
                        write_evidence = self._materialize_action_write_evidence(
                            fixture,
                            package_root,
                            run,
                            ground_truth,
                            answer,
                        )
                        mechanical = recompute_action_alias_metrics(
                            answer, ground_truth, write_evidence
                        )
                        write_outcome = mechanical["write_outcome"]
                        write_event = run["behavior_events"][1]
                        probe_event = run["behavior_events"][2]
                        write_event["result"] = (
                            "failure" if write_outcome["refused"] else "success"
                        )
                        write_event["failure_code"] = (
                            "unjustified_refusal" if write_outcome["refused"] else None
                        )
                        probe_event["result"] = (
                            "failure" if write_outcome["collision"] else "success"
                        )
                        probe_event["failure_code"] = (
                            "write_collision" if write_outcome["collision"] else None
                        )
                        failed_phases = [
                            event["phase"]
                            for event in run["behavior_events"]
                            if event["result"] == "failure"
                        ]
                        run["behavior_summary"].update(
                            {
                                "successful_phases": [
                                    event["phase"]
                                    for event in run["behavior_events"]
                                    if event["result"] == "success"
                                ],
                                "failed_phases": failed_phases,
                                "failure_count": len(failed_phases),
                            }
                        )
                        source_artifact_id = run["outcomes"]["evaluator_artifact_id"]
                        run["outcomes"]["evaluator_passed"] = write_outcome[
                            "task_success"
                        ]
                        run["outcomes"]["metrics"] = [
                            {
                                "metric_id": definition["metric_id"],
                                **mechanical["metrics"][definition["metric_id"]],
                                "unit": "proportion",
                                "source_artifact_id": source_artifact_id,
                            }
                            for definition in manifest["outcome_metrics"]
                        ]
                        fixture._rewrite_semantic_artifact(
                            run,
                            "behavior_trace",
                            {
                                "events": run["behavior_events"],
                                "summary": run["behavior_summary"],
                            },
                        )
                        fixture._rewrite_semantic_artifact(
                            run, "evaluator_output", run["outcomes"]
                        )
                        fixture._refresh_receipts(run)
                        run_ref = self._write_workflow_artifact(
                            root,
                            artifact_id=slot["slot_id"],
                            relative_path=(
                                "agent_readiness/evidence/runs/"
                                f"{record['id']}/{binding_id}/slots/"
                                f"{slot['slot_id']}.json"
                            ),
                            artifact_type="measurement_v1_run",
                            payload=run,
                            experiment_id=experiment_id,
                        )
                        run_refs.append(run_ref)
                        runs.append(run)
                result = {
                    "schema_version": (
                        "drupal_agent_readiness.bound_experiment_result.v1"
                    ),
                    "improvement_record_id": record["id"],
                    "experiment_id": experiment_id,
                    "design_snapshot_sha256": snapshot_ref["sha256"],
                    "manifest_artifact_ref": manifest_ref,
                    "result_status": "complete",
                    "planned_slots": 40,
                    "resolved_slots": 40,
                    "run_artifact_refs": sorted(
                        run_refs, key=lambda reference: reference["id"]
                    ),
                }
                result_refs[experiment_id] = self._write_workflow_artifact(
                    root,
                    artifact_id=f"{binding_id}-result",
                    relative_path=(
                        "agent_readiness/evidence/runs/"
                        f"{record['id']}/{binding_id}.json"
                    ),
                    artifact_type="measurement_v1_result",
                    payload=result,
                    experiment_id=experiment_id,
                )
                runs_by_experiment[experiment_id] = runs
            workflow["execution"] = {
                "state": "complete",
                "run_artifact_refs": list(result_refs.values()),
            }

        metric_ids = sorted(
            {record["analysis_plan"]["primary_metric"]["id"]}
            | {item["id"] for item in record["analysis_plan"]["guardrails"]}
            | {record["analysis_plan"]["task_completion_guardrail"]["id"]}
            | {
                item["id"]
                for item in record["analysis_plan"]["measurement_integrity_guardrails"]
            }
        )
        analysis_refs = {}
        analysis_status_by_experiment = {}
        if state_index >= 3:
            for experiment_id, result_ref in result_refs.items():
                binding = bindings_by_experiment[experiment_id]
                binding_id = binding_ids[experiment_id]
                manifest = manifests[experiment_id]
                audit = _portable_measurement_audit(
                    audit_measurement_v1(
                        manifest,
                        runs_by_experiment[experiment_id],
                        artifact_root=package_root,
                        registration_anchor=GitRegistrationAnchor(
                            repo_path=root,
                            commit=git_commit,
                            manifest_path=manifest["registration"]["manifest_path"],
                        ),
                    )
                )
                contrast = next(
                    item
                    for item in record["experiment_design"]["contrasts"]
                    if item["id"] == binding["contrast_id"]
                )
                registered_gate = _derive_registered_contrast_gate(contrast, audit)
                guardrails_passed = audit["guardrails"]["all_passed"] is True
                analysis = {
                    "schema_version": (
                        "drupal_agent_readiness.bound_experiment_analysis.v1"
                    ),
                    "improvement_record_id": record["id"],
                    "experiment_id": experiment_id,
                    "design_snapshot_sha256": snapshot_ref["sha256"],
                    "result_artifact_ref": result_ref,
                    "derived_metric_ids": metric_ids,
                    "measurement_audit": audit,
                    "registered_gate": registered_gate,
                    "registered_gate_passed": registered_gate["passed"],
                    "guardrails_passed": guardrails_passed,
                }
                analysis_refs[experiment_id] = self._write_workflow_artifact(
                    root,
                    artifact_id=f"{binding_id}-analysis",
                    relative_path=(
                        "agent_readiness/evidence/experiments/"
                        f"{record['id']}/analysis/{binding_id}.json"
                    ),
                    artifact_type="measurement_v1_analysis",
                    payload=analysis,
                    experiment_id=experiment_id,
                )
                analysis_status_by_experiment[experiment_id] = {
                    "experiment_id": experiment_id,
                    "contrast_id": binding["contrast_id"],
                    "decision_role": binding["decision_role"],
                    "decision_rule": binding["decision_rule"],
                    "registered_gate_passed": registered_gate["passed"],
                    "guardrails_passed": guardrails_passed,
                    "eligible_for_synthesis": bool(
                        registered_gate["passed"] and guardrails_passed
                    ),
                }
            workflow["analysis"] = {
                "state": "complete",
                "derived_metric_refs": list(analysis_refs.values()),
            }

        decision_refs = {}
        final_decision_refs = []
        if state_index >= 4:
            for experiment_id, analysis_ref in analysis_refs.items():
                binding_id = binding_ids[experiment_id]
                status = analysis_status_by_experiment[experiment_id]
                binding_decision = {
                    "schema_version": "drupal_agent_readiness.binding_decision.v1",
                    "improvement_record_id": record["id"],
                    "experiment_id": experiment_id,
                    "design_snapshot_sha256": snapshot_ref["sha256"],
                    "result_artifact_ref": result_refs[experiment_id],
                    "analysis_artifact_ref": analysis_ref,
                    "decision_role": status["decision_role"],
                    "decision_rule": status["decision_rule"],
                    "registered_gate_passed": status["registered_gate_passed"],
                    "guardrails_passed": status["guardrails_passed"],
                    "eligible_for_synthesis": status["eligible_for_synthesis"],
                }
                decision_refs[experiment_id] = self._write_workflow_artifact(
                    root,
                    artifact_id=f"{binding_id}-decision",
                    relative_path=(
                        "agent_readiness/evidence/decisions/"
                        f"{record['id']}/bindings/{binding_id}.json"
                    ),
                    artifact_type="measurement_v1_binding_decision",
                    payload=binding_decision,
                    experiment_id=experiment_id,
                )
            gate_status = sorted(
                analysis_status_by_experiment.values(),
                key=lambda item: item["experiment_id"],
            )
            eligible_experiment_ids = sorted(
                item["experiment_id"]
                for item in gate_status
                if item["eligible_for_synthesis"]
            )
            primary_experiment_ids = sorted(
                item["experiment_id"]
                for item in gate_status
                if item["decision_role"] == "primary_efficacy"
            )
            all_registered_gates_passed = eligible_experiment_ids == sorted(
                manifest_refs
            )
            primary_treatment_ids = sorted(
                {
                    bindings_by_experiment[experiment_id]["post_arm_id"]
                    for experiment_id in primary_experiment_ids
                }
            )
            adoption_allowed = outcome == "adopt" and all_registered_gates_passed
            synthesis = {
                "schema_version": "drupal_agent_readiness.synthesis_decision.v1",
                "improvement_record_id": record["id"],
                "design_snapshot_sha256": snapshot_ref["sha256"],
                "bound_experiment_ids": sorted(manifest_refs),
                "result_artifact_refs": sorted(
                    result_refs.values(), key=lambda reference: reference["id"]
                ),
                "analysis_artifact_refs": sorted(
                    analysis_refs.values(), key=lambda reference: reference["id"]
                ),
                "binding_decision_artifact_refs": sorted(
                    decision_refs.values(), key=lambda reference: reference["id"]
                ),
                "derived_metric_ids": metric_ids,
                "gate_status": gate_status,
                "eligible_experiment_ids": eligible_experiment_ids,
                "all_registered_gates_passed": all_registered_gates_passed,
                "primary_efficacy_experiment_ids": primary_experiment_ids,
                "adopted_primary_efficacy_experiment_ids": (
                    primary_experiment_ids if adoption_allowed else []
                ),
                "adopted_treatment_ids": (
                    primary_treatment_ids if adoption_allowed else []
                ),
                "adopted_treatment_code_hashes": (
                    {
                        treatment_id: {
                            "drupal_code_tree_sha256": arms_by_id[treatment_id][
                                "drupal_code_tree_sha256"
                            ],
                            "capability_component_tree_sha256": arms_by_id[
                                treatment_id
                            ]["capability_component_tree_sha256"],
                            "treatment_artifact_sha256": arms_by_id[treatment_id][
                                "treatment_artifact_sha256"
                            ],
                        }
                        for treatment_id in primary_treatment_ids
                    }
                    if adoption_allowed
                    else {}
                ),
                "outcome": outcome,
            }
            synthesis_ref = self._write_workflow_artifact(
                root,
                artifact_id=f"{record['id']}-synthesis-decision",
                relative_path=(
                    f"agent_readiness/evidence/decisions/{record['id']}/synthesis.json"
                ),
                artifact_type="improvement_synthesis_decision",
                payload=synthesis,
            )
            final_decision_refs = [*decision_refs.values(), synthesis_ref]
            workflow["decision"] = {
                "state": "decided",
                "outcome": outcome,
                "artifact_refs": final_decision_refs,
                "derived_metric_ids": metric_ids,
            }

        evidence_by_state = {
            "frozen": [
                snapshot_ref,
                design_basis_ref,
                calibration_decision_ref,
                *manifest_refs.values(),
            ],
            "executed": [
                snapshot_ref,
                design_basis_ref,
                calibration_decision_ref,
                *manifest_refs.values(),
                *result_refs.values(),
            ],
            "analyzed": [
                snapshot_ref,
                design_basis_ref,
                calibration_decision_ref,
                *manifest_refs.values(),
                *result_refs.values(),
                *analysis_refs.values(),
            ],
            "decided": [
                snapshot_ref,
                design_basis_ref,
                calibration_decision_ref,
                *manifest_refs.values(),
                *result_refs.values(),
                *analysis_refs.values(),
                *final_decision_refs,
            ],
        }
        states = [
            "pending_registration",
            "frozen",
            "executed",
            "analyzed",
            "decided",
        ]
        previous_hash = None
        transitions = []
        for sequence, to_state in enumerate(states[1 : state_index + 1], start=1):
            transition_payload = {
                "schema_version": ("drupal_agent_readiness.improvement_transition.v1"),
                "improvement_record_id": record["id"],
                "sequence": sequence,
                "from_state": states[sequence - 1],
                "to_state": to_state,
                "previous_transition_sha256": previous_hash,
                "design_snapshot_sha256": snapshot_ref["sha256"],
                "bound_experiment_ids": sorted(manifest_refs),
                "result_artifact_refs": (
                    sorted(result_refs.values(), key=lambda reference: reference["id"])
                    if sequence >= 2
                    else []
                ),
                "evidence_artifact_refs": sorted(
                    evidence_by_state[to_state],
                    key=lambda reference: reference["id"],
                ),
            }
            transition_ref = self._write_workflow_artifact(
                root,
                artifact_id=(f"{record['id']}-transition-{sequence:02d}-{to_state}"),
                relative_path=(
                    "agent_readiness/evidence/registrations/"
                    f"{record['id']}/transitions/{sequence:02d}-{to_state}.json"
                ),
                artifact_type="improvement_workflow_transition",
                payload=transition_payload,
            )
            transitions.append({"sequence": sequence, "artifact_ref": transition_ref})
            previous_hash = transition_ref["sha256"]
        workflow["transitions"] = transitions
        record["workflow"] = workflow
        return improvements

    def _validate_promoted_workflow(self, improvements: dict, root: Path) -> None:
        schema = json.loads(
            (
                REPO_ROOT / "method/schema/improvement-registry-v1.schema.json"
            ).read_text()
        )
        validate_schema_instance(improvements, schema)
        record = improvements["records"][0]
        design = record["experiment_design"]
        cells = {item["id"]: item for item in design["cells"]}
        metric_ids = (
            {record["analysis_plan"]["primary_metric"]["id"]}
            | {item["id"] for item in record["analysis_plan"]["guardrails"]}
            | {record["analysis_plan"]["task_completion_guardrail"]["id"]}
            | {
                item["id"]
                for item in record["analysis_plan"]["measurement_integrity_guardrails"]
            }
        )
        claim = next(
            item
            for item in self.coverage["published_claims"]
            if item["id"] == record["failure"]["claim_id"]
        )
        _validate_workflow_state(
            record,
            root,
            cells,
            metric_ids,
            design["measurement_v1_binding_plan"],
            improvements["registry_id"],
            improvements["schema_version"],
            claim["id"],
            record["task_family_id"],
            claim["task_id"],
            {item["id"]: item for item in design["contrasts"]},
            {item["id"]: item for item in design["model_cells"]},
            {item["id"]: item for item in design["substrate_cells"]},
        )

    def test_public_registries_pass_production_validator(self) -> None:
        self.validate()
        claim = self.coverage["published_claims"][0]
        self.assertEqual("bounded_observed_difference", claim["claim_type"])
        self.assertEqual("historical_frontier_observation", claim["evidence_lane"])
        self.assertFalse(claim["claim_grade"])
        self.assertFalse(claim["causal_attribution"])
        self.assertNotIn("intervention_effect", json.dumps(claim))

    def test_prioritization_starts_unranked_without_fabricated_scores(self) -> None:
        prioritization = self.improvements["records"][0]["prioritization"]
        self.assertEqual("unranked_insufficient_evidence", prioritization["state"])
        self.assertIsNone(prioritization["rank"])
        self.assertIsNone(prioritization["owner_decision_artifact"])
        self.assertEqual([], prioritization["evidence_ids"])
        for dimension in (
            "occurrence",
            "consequence",
            "lifecycle_reach",
            "owner_site_reach",
            "delivery_effort",
            "strategic_fit",
        ):
            self.assertEqual(
                {
                    "status": "insufficient_evidence",
                    "score": None,
                    "evidence_ids": [],
                },
                prioritization[dimension],
            )

    def test_prioritization_cannot_rank_with_an_incomplete_dimension(self) -> None:
        improvements = copy.deepcopy(self.improvements)
        record = self._complete_prioritization(improvements, state="ranked")
        prioritization = record["prioritization"]
        prioritization["occurrence"] = {
            "status": "insufficient_evidence",
            "score": None,
            "evidence_ids": [],
        }
        prioritization["rank"] = 1
        prioritization["owner_decision_artifact"] = {
            "id": f"{record['id']}-prioritization-owner-decision-v1",
            "path": (
                "agent_readiness/evidence/decisions/"
                f"{record['id']}/prioritization-owner-decision-v1.json"
            ),
            "sha256": "0" * 64,
            "artifact_type": "improvement_prioritization_owner_decision",
            "owner_ids": ["ai-context-maintainers"],
        }
        evidence = {item["id"]: item for item in self.coverage["evidence_records"]}
        owners = {item["id"]: item for item in record["upstream"]["owners"]}
        with self.assertRaisesRegex(RegistryValidationError, "complete.*dimensions"):
            _validate_prioritization(record, evidence, owners, REPO_ROOT)

    def test_complete_prioritization_waits_for_an_owner_decision(self) -> None:
        improvements = copy.deepcopy(self.improvements)
        record = self._complete_prioritization(improvements)
        evidence = {item["id"]: item for item in self.coverage["evidence_records"]}
        owners = {item["id"]: item for item in record["upstream"]["owners"]}
        self.assertIsNone(
            _validate_prioritization(record, evidence, owners, REPO_ROOT)
        )

        record["prioritization"]["state"] = "ranked"
        record["prioritization"]["rank"] = 1
        with self.assertRaisesRegex(RegistryValidationError, "owner decision"):
            _validate_prioritization(record, evidence, owners, REPO_ROOT)

    def test_prioritization_evidence_must_be_known_and_exactly_aggregated(self) -> None:
        evidence = {item["id"]: item for item in self.coverage["evidence_records"]}
        improvements = copy.deepcopy(self.improvements)
        record = self._complete_prioritization(improvements)
        owners = {item["id"]: item for item in record["upstream"]["owners"]}

        record["prioritization"]["evidence_ids"] = []
        with self.assertRaisesRegex(RegistryValidationError, "sorted union"):
            _validate_prioritization(record, evidence, owners, REPO_ROOT)

        record = self._complete_prioritization(copy.deepcopy(self.improvements))
        owners = {item["id"]: item for item in record["upstream"]["owners"]}
        record["prioritization"]["occurrence"]["evidence_ids"] = [
            "invented-priority-evidence"
        ]
        record["prioritization"]["evidence_ids"] = [
            "alias-safety-derived-metrics",
            "invented-priority-evidence",
        ]
        with self.assertRaisesRegex(RegistryValidationError, "unknown evidence"):
            _validate_prioritization(record, evidence, owners, REPO_ROOT)

    def test_rank_requires_a_content_addressed_owner_decision(self) -> None:
        evidence = {item["id"]: item for item in self.coverage["evidence_records"]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = copy.deepcopy(self.improvements)
            record = self._complete_prioritization(improvements)
            reference = self._write_prioritization_owner_decision(root, record)
            owners = {item["id"]: item for item in record["upstream"]["owners"]}
            self.assertEqual(
                1, _validate_prioritization(record, evidence, owners, root)
            )

            valid_sha256 = reference["sha256"]
            reference["sha256"] = "0" * 64
            with self.assertRaisesRegex(RegistryValidationError, "hash mismatch"):
                _validate_prioritization(record, evidence, owners, root)
            reference["sha256"] = valid_sha256

            payload = json.loads((root / reference["path"]).read_text())
            payload["rank"] = 2
            self._rewrite_workflow_artifact(root, reference, payload)
            with self.assertRaisesRegex(RegistryValidationError, "does not bind"):
                _validate_prioritization(record, evidence, owners, root)

    def test_measurement_owner_alone_cannot_rank_an_improvement(self) -> None:
        evidence = {item["id"]: item for item in self.coverage["evidence_records"]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = copy.deepcopy(self.improvements)
            record = self._complete_prioritization(improvements)
            self._write_prioritization_owner_decision(
                root,
                record,
                owner_ids=["agent-readiness-benchmark-maintainer"],
            )
            owners = {item["id"]: item for item in record["upstream"]["owners"]}
            with self.assertRaisesRegex(RegistryValidationError, "non-measurement"):
                _validate_prioritization(record, evidence, owners, root)

    def test_prioritization_rank_sequence_rejects_duplicates_and_gaps(self) -> None:
        _validate_prioritization_ranks([])
        _validate_prioritization_ranks([1, 2, 3])
        for ranks in ([1, 1], [2], [1, 3]):
            with self.subTest(ranks=ranks), self.assertRaises(
                RegistryValidationError
            ):
                _validate_prioritization_ranks(ranks)

    def test_prioritization_schema_has_no_automatic_composite_surface(self) -> None:
        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["prioritization"]["composite_score"] = 99
        with self.assertRaises(RegistryValidationError):
            self.validate(improvements=improvements)

    def test_cli_machine_report_passes(self) -> None:
        command = [
            sys.executable,
            "-B",
            "agent_readiness/scripts/audit_benchmark_registries_v1.py",
            "--format",
            "json",
        ]
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["valid"])
        self.assertEqual(6, report["evidence_records"])

    def test_cli_returns_nonzero_machine_report_on_semantic_error(self) -> None:
        output = io.StringIO()
        with (
            patch.object(
                audit_benchmark_registries_v1,
                "validate_default_registries",
                side_effect=RegistryValidationError("semantic failure"),
            ),
            redirect_stdout(output),
        ):
            result = audit_benchmark_registries_v1.main(["--format", "json"])
        self.assertEqual(1, result)
        self.assertEqual(
            {"valid": False, "error": "semantic failure"},
            json.loads(output.getvalue()),
        )

    def test_current_evidence_is_contained_and_sha256_pinned(self) -> None:
        for record in self.coverage["evidence_records"]:
            resolved = resolve_hashed_artifact(
                REPO_ROOT,
                record,
                allowed_roots=("evidence/runs", "evidence/experiments"),
            )
            self.assertTrue(resolved.is_file())

    def test_historical_alias_metrics_recompute_from_raw_answers_and_truth(
        self,
    ) -> None:
        root = REPO_ROOT / "evidence/experiments/alias-safety-haven-n10-fullyblind-v0"
        raw = json.loads((root / "raw-workflow-output.json").read_text())
        truth = json.loads((root / "ground-truth.json").read_text())
        retained = json.loads((root / "model-ab-results.json").read_text())
        canonical = validate_retained_alias_safety_results(raw, truth, retained)
        self.assertEqual(
            40, sum(len(cell["runs"]) for cell in canonical["cells"].values())
        )

        retained["cells"]["ab-haiku-blind"]["runs"][0]["latent_correct"] = 999
        with self.assertRaises(AliasSafetyMetricError):
            validate_retained_alias_safety_results(raw, truth, retained)

        retained = json.loads((root / "model-ab-results.json").read_text())
        retained["model_ids"]["haiku"] = "relabeled-provider"
        with self.assertRaises(AliasSafetyMetricError):
            validate_retained_alias_safety_results(raw, truth, retained)

    def test_validator_rejects_rehashed_invented_alias_derived_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for schema_name in (
                "benchmark-coverage-v1.schema.json",
                "task-families-v1.schema.json",
                "improvement-registry-v1.schema.json",
            ):
                destination = root / "method/schema" / schema_name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO_ROOT / "method/schema" / schema_name, destination)
            for record in self.coverage["evidence_records"]:
                references = [{"path": record["path"], "sha256": record["sha256"]}]
                references.extend(record.get("companions", {}).values())
                for reference in references:
                    source = REPO_ROOT / reference["path"]
                    destination = root / reference["path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)

            coverage = copy.deepcopy(self.coverage)
            record = next(
                item
                for item in coverage["evidence_records"]
                if item["id"] == "alias-safety-derived-metrics"
            )
            path = root / record["path"]
            derived = json.loads(path.read_text())
            for cell in derived["cells"].values():
                for run in cell["runs"]:
                    run["latent_correct"] = (
                        0 if run["arm"] == "raw" else run["latent_total"]
                    )
            path.write_text(json.dumps(derived), encoding="utf-8")
            record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

            with self.assertRaisesRegex(RegistryValidationError, "recompute"):
                validate_registries(
                    coverage,
                    self.tasks,
                    self.improvements,
                    repo_root=root,
                )

    def test_rejects_hash_mismatch(self) -> None:
        coverage = copy.deepcopy(self.coverage)
        coverage["evidence_records"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(RegistryValidationError, "hash mismatch"):
            self.validate(coverage=coverage)

    def test_rejects_evidence_task_metric_and_companion_semantic_mismatch(self) -> None:
        mutations = []
        coverage = copy.deepcopy(self.coverage)
        coverage["evidence_records"][0]["task_id"] = "act.event_jsonapi"
        mutations.append(coverage)
        coverage = copy.deepcopy(self.coverage)
        coverage["evidence_records"][1]["metric_ids"] = ["inventory_mechanical_pass"]
        mutations.append(coverage)
        for index, value in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(RegistryValidationError):
                self.validate(coverage=value)

    def test_legacy_run_bundle_requires_recomputed_task_evaluator(self) -> None:
        coverage = copy.deepcopy(self.coverage)
        event = next(
            item
            for item in coverage["evidence_records"]
            if item["id"] == "event-run-result"
        )
        event["companions"]["evaluator"] = {
            "path": "evidence/runs/recovery-independent-20260620151052/evaluator.json",
            "sha256": "af4fba92e76014bcd07f5b7d72de45ce255408467768913ac93fbac9ebcd76b2",
        }
        with self.assertRaisesRegex(RegistryValidationError, "same run"):
            self.validate(coverage=coverage)

        coverage = copy.deepcopy(self.coverage)
        del coverage["evidence_records"][0]["companions"]
        with self.assertRaises(RegistryValidationError):
            self.validate(coverage=coverage)

    def test_rejects_path_traversal_even_with_matching_target_hash(self) -> None:
        coverage = copy.deepcopy(self.coverage)
        record = coverage["evidence_records"][0]
        target = REPO_ROOT / "method/task-families-v1.json"
        record["path"] = "evidence/runs/../../method/task-families-v1.json"
        record["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        with self.assertRaises(RegistryValidationError):
            self.validate(coverage=coverage)

    def test_rejects_target_method_as_current_evidence(self) -> None:
        coverage = copy.deepcopy(self.coverage)
        record = coverage["evidence_records"][0]
        target = REPO_ROOT / "method/task-families-v1.json"
        record["path"] = "method/task-families-v1.json"
        record["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        with self.assertRaises(RegistryValidationError):
            self.validate(coverage=coverage)

    def test_rejects_absolute_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            evidence_dir = root / "evidence/runs"
            evidence_dir.mkdir(parents=True)
            outside = Path(directory) / "outside.json"
            outside.write_text("outside", encoding="utf-8")
            (evidence_dir / "escape.json").symlink_to(outside)
            digest = hashlib.sha256(outside.read_bytes()).hexdigest()
            for path in (str(outside), "evidence/runs/escape.json"):
                with (
                    self.subTest(path=path),
                    self.assertRaises(RegistryValidationError),
                ):
                    resolve_hashed_artifact(
                        root,
                        {"path": path, "sha256": digest},
                        allowed_roots=("evidence/runs",),
                    )

    def test_rejects_orphan_finding_and_missing_action_fields(self) -> None:
        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["failure"]["claim_id"] = "missing-claim"
        with self.assertRaisesRegex(RegistryValidationError, "orphaned"):
            self.validate(improvements=improvements)

        removals = [
            ("owners", ("upstream", "owners")),
            ("issues", ("upstream", "issues")),
            ("expected_delta", ("expected_delta",)),
        ]
        for label, keys in removals:
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.improvements)
                node = candidate["records"][0]
                for key in keys[:-1]:
                    node = node[key]
                del node[keys[-1]]
                with self.assertRaises(RegistryValidationError):
                    self.validate(improvements=candidate)

    def test_typed_claim_and_comparison_scopes_reject_aggregate_output(self) -> None:
        mutations = []
        coverage = copy.deepcopy(self.coverage)
        coverage["published_claims"][0]["scope"]["readiness_output"] = True
        mutations.append((coverage, self.tasks, self.improvements))

        tasks = copy.deepcopy(self.tasks)
        tasks["task_families"][0]["proof_contract"]["cross_task_aggregation"] = True
        mutations.append((self.coverage, tasks, self.improvements))

        tasks = copy.deepcopy(self.tasks)
        scope = tasks["task_families"][0]["fixed_regression_lane"]["comparison_scope"]
        scope["cross_task_pooling"] = True
        mutations.append((self.coverage, tasks, self.improvements))

        for index, (coverage_value, tasks_value, improvements_value) in enumerate(
            mutations
        ):
            with self.subTest(index=index), self.assertRaises(RegistryValidationError):
                self.validate(coverage_value, tasks_value, improvements_value)

    def test_claim_shape_has_no_freeform_aggregate_output_surface(self) -> None:
        coverage = copy.deepcopy(self.coverage)
        coverage["published_claims"][0]["summary"] = (
            "Drupal agents earn an overall 87 out of 100"
        )
        with self.assertRaises(RegistryValidationError):
            self.validate(coverage=coverage)

    def test_rejects_claim_on_uncovered_lifecycle_stage(self) -> None:
        coverage = copy.deepcopy(self.coverage)
        coverage["published_claims"][0]["lifecycle_stages"] = ["connect"]
        with self.assertRaisesRegex(RegistryValidationError, "uncovered lifecycle"):
            self.validate(coverage=coverage)

    def test_rejects_duplicate_ids_in_nested_scopes(self) -> None:
        task_mutations = []
        tasks = copy.deepcopy(self.tasks)
        tasks["task_families"][0]["constraints"][1]["id"] = tasks["task_families"][0][
            "constraints"
        ][0]["id"]
        task_mutations.append(tasks)
        tasks = copy.deepcopy(self.tasks)
        tasks["task_families"][0]["mechanical_outcomes"][1]["id"] = tasks[
            "task_families"
        ][0]["mechanical_outcomes"][0]["id"]
        task_mutations.append(tasks)
        tasks = copy.deepcopy(self.tasks)
        tasks["task_families"][0]["fixed_regression_lane"]["variants"][1]["id"] = tasks[
            "task_families"
        ][0]["fixed_regression_lane"]["variants"][0]["id"]
        task_mutations.append(tasks)
        for index, tasks_value in enumerate(task_mutations):
            with (
                self.subTest(index=index),
                self.assertRaisesRegex(RegistryValidationError, "duplicate"),
            ):
                self.validate(tasks=tasks_value)

    def test_rejects_site_owner_as_upstream_support_certifier(self) -> None:
        tasks = copy.deepcopy(self.tasks)
        constraint = tasks["task_families"][0]["constraints"][0]
        self.assertEqual("upstream_support", constraint["authority"]["class"])
        constraint["authority"]["certifier_class"] = (
            "site_owner_or_delegated_product_owner"
        )
        with self.assertRaises(RegistryValidationError):
            self.validate(tasks=tasks)

    def test_rejects_non_versioned_authority_attestation(self) -> None:
        tasks = copy.deepcopy(self.tasks)
        tasks["task_families"][1]["constraints"][0]["authority"]["attestation"][
            "versioned"
        ] = False
        with self.assertRaises(RegistryValidationError):
            self.validate(tasks=tasks)

    def test_rejects_non_receipt_behavior_measure(self) -> None:
        tasks = copy.deepcopy(self.tasks)
        outcome = tasks["task_families"][2]["behavior_outcomes"][0]
        outcome["private_reasoning_required"] = True
        with self.assertRaises(RegistryValidationError):
            self.validate(tasks=tasks)

        tasks = copy.deepcopy(self.tasks)
        tasks["task_families"][2]["behavior_outcomes"][0][
            "receipt_requirements"
        ] = []
        with self.assertRaises(RegistryValidationError):
            self.validate(tasks=tasks)

    def test_plan_and_handoff_are_unexecuted_observable_targets(self) -> None:
        self.validate()
        stages = {item["id"]: item for item in self.coverage["lifecycle"]}
        contracts = {
            item["lifecycle_stage"]: item
            for item in self.tasks["lifecycle_target_contracts"]
        }

        for stage_id in ("plan_clarify", "handoff"):
            with self.subTest(stage=stage_id):
                self.assertEqual("not_covered", stages[stage_id]["current_status"])
                self.assertEqual([], stages[stage_id]["current_evidence_ids"])
                self.assertEqual(
                    "target_not_executed", contracts[stage_id]["measurement_state"]
                )
                self.assertFalse(contracts[stage_id]["private_reasoning_required"])
                self.assertEqual(
                    set(stages[stage_id]["target"]["required_metric_ids"]),
                    {
                        metric["id"]
                        for metric in contracts[stage_id]["metric_contracts"]
                    },
                )

        self.assertEqual(
            ["proceed", "ask", "refuse", "escalate"],
            contracts["plan_clarify"]["decision_options"],
        )
        self.assertEqual(
            "registered_task_and_handoff_artifact_only",
            contracts["handoff"]["continuation_context_policy"],
        )

    def test_rejects_narrative_or_incomplete_plan_target(self) -> None:
        mutations = []

        tasks = copy.deepcopy(self.tasks)
        plan = next(
            item
            for item in tasks["lifecycle_target_contracts"]
            if item["lifecycle_stage"] == "plan_clarify"
        )
        plan["decision_options"] = ["proceed", "ask", "refuse", "explain"]
        mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        plan = next(
            item
            for item in tasks["lifecycle_target_contracts"]
            if item["lifecycle_stage"] == "plan_clarify"
        )
        plan["receipt_requirements"][0]["required_attributes"].remove(
            "authority_gaps_digest"
        )
        mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        plan = next(
            item
            for item in tasks["lifecycle_target_contracts"]
            if item["lifecycle_stage"] == "plan_clarify"
        )
        plan["metric_contracts"][0]["denominator_predicate"] = (
            "only_successful_decision_points"
        )
        mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        plan = next(
            item
            for item in tasks["lifecycle_target_contracts"]
            if item["lifecycle_stage"] == "plan_clarify"
        )
        plan["artifact_contract"]["fields"] = [
            field
            for field in plan["artifact_contract"]["fields"]
            if field["name"] != "planned_verification"
        ]
        mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        plan = next(
            item
            for item in tasks["lifecycle_target_contracts"]
            if item["lifecycle_stage"] == "plan_clarify"
        )
        plan["private_reasoning_required"] = True
        mutations.append(tasks)

        for index, tasks_value in enumerate(mutations):
            with (
                self.subTest(index=index),
                self.assertRaises(RegistryValidationError),
            ):
                self.validate(tasks=tasks_value)

    def test_rejects_non_cold_or_incomplete_handoff_target(self) -> None:
        mutations = []

        tasks = copy.deepcopy(self.tasks)
        handoff = next(
            item
            for item in tasks["lifecycle_target_contracts"]
            if item["lifecycle_stage"] == "handoff"
        )
        handoff["continuation_context_policy"] = "prior_conversation_allowed"
        mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        handoff = next(
            item
            for item in tasks["lifecycle_target_contracts"]
            if item["lifecycle_stage"] == "handoff"
        )
        handoff["receipt_requirements"][0]["required_attributes"].remove(
            "next_command_digest"
        )
        mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        handoff = next(
            item
            for item in tasks["lifecycle_target_contracts"]
            if item["lifecycle_stage"] == "handoff"
        )
        handoff["receipt_requirements"][1]["required_attributes"].remove(
            "predecessor_handoff_artifact_id"
        )
        mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        handoff = next(
            item
            for item in tasks["lifecycle_target_contracts"]
            if item["lifecycle_stage"] == "handoff"
        )
        handoff["metric_contracts"][2]["zero_denominator"] = "pass"
        mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        handoff = next(
            item
            for item in tasks["lifecycle_target_contracts"]
            if item["lifecycle_stage"] == "handoff"
        )
        next_command = next(
            field
            for field in handoff["artifact_contract"]["fields"]
            if field["name"] == "exact_next_command"
        )
        next_command["type"] = "array"
        mutations.append(tasks)

        for index, tasks_value in enumerate(mutations):
            with (
                self.subTest(index=index),
                self.assertRaises(RegistryValidationError),
            ):
                self.validate(tasks=tasks_value)

    def test_rejects_target_metric_or_lifecycle_link_drift(self) -> None:
        coverage = copy.deepcopy(self.coverage)
        plan = next(
            item for item in coverage["lifecycle"] if item["id"] == "plan_clarify"
        )
        plan["target"]["required_metric_ids"].remove(
            "planned_verification_complete_rate"
        )
        with self.assertRaisesRegex(RegistryValidationError, "target metrics"):
            self.validate(coverage=coverage)

        tasks = copy.deepcopy(self.tasks)
        tasks["task_families"][0]["lifecycle_stages"].remove("handoff")
        with self.assertRaises(RegistryValidationError):
            self.validate(tasks=tasks)

        coverage = copy.deepcopy(self.coverage)
        coverage["lifecycle"][3], coverage["lifecycle"][4] = (
            coverage["lifecycle"][4],
            coverage["lifecycle"][3],
        )
        with self.assertRaisesRegex(RegistryValidationError, "lifecycle spine"):
            self.validate(coverage=coverage)

        tasks = copy.deepcopy(self.tasks)
        stages = tasks["task_families"][1]["lifecycle_stages"]
        stages[1], stages[2] = stages[2], stages[1]
        with self.assertRaisesRegex(RegistryValidationError, "canonical order"):
            self.validate(tasks=tasks)

    def test_rejects_non_executable_substrate_or_fault_plan(self) -> None:
        tasks = copy.deepcopy(self.tasks)
        messy = tasks["task_families"][0]["substrate_plan"]["substrates"][1]
        messy["inject_inventory"] = []
        with self.assertRaises(RegistryValidationError):
            self.validate(tasks=tasks)

        tasks = copy.deepcopy(self.tasks)
        tasks["task_families"][1]["substrate_plan"]["case_matrix"].pop()
        with self.assertRaises(RegistryValidationError):
            self.validate(tasks=tasks)

    def test_rejects_byte_stability_over_volatile_state(self) -> None:
        tasks = copy.deepcopy(self.tasks)
        tasks["task_families"][0]["semantic_blast_radius"][
            "byte_stability_required"
        ] = True
        with self.assertRaises(RegistryValidationError):
            self.validate(tasks=tasks)

    def test_alias_arm_matrix_is_coherent_and_complete(self) -> None:
        improvements = copy.deepcopy(self.improvements)
        arm = improvements["records"][0]["experiment_design"]["arms"][1]
        arm["tool_allowlist"] = [
            "shell",
            "drush",
            "site_architecture.path_owner",
        ]
        with self.assertRaisesRegex(RegistryValidationError, "allowlist"):
            self.validate(improvements=improvements)

        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["experiment_design"]["cells"].pop()
        with self.assertRaises(RegistryValidationError):
            self.validate(improvements=improvements)

        improvements = copy.deepcopy(self.improvements)
        contrast = improvements["records"][0]["experiment_design"]["contrasts"][3]
        contrast["right_arm_id"] = "installed-stub-hidden"
        with self.assertRaisesRegex(RegistryValidationError, "does not isolate"):
            self.validate(improvements=improvements)

    def test_measurement_v1_binding_plan_covers_the_full_fixed_product(self) -> None:
        design = self.improvements["records"][0]["experiment_design"]
        plan = design["measurement_v1_binding_plan"]
        contrasts = {
            item["id"]
            for item in design["contrasts"]
            if item["binding_lane"] == "drupal_action"
        }
        models = {item["id"] for item in design["model_cells"]}
        expected = {
            (contrast, substrate, model)
            for contrast in contrasts
            for substrate in {"clean", "messy_owner_described"}
            for model in models
        }
        actual = {
            (
                binding["contrast_id"],
                binding["substrate_id"],
                binding["model_cell_id"],
            )
            for binding in plan["bindings"]
        }
        self.assertEqual(expected, actual)
        self.assertEqual(16, len(plan["bindings"]))
        self.assertEqual(
            16, len({binding["experiment_id"] for binding in plan["bindings"]})
        )
        self.assertNotIn("prompt-naming", contrasts)
        self.assertNotIn(
            "facts-discoverable-named",
            {arm["id"] for arm in design["arms"]},
        )
        self.assertEqual(
            [
                {
                    "id": "prompt-naming",
                    "status": "not_executed",
                    "registration_requirement": "separate_registration_required",
                    "domain": "non_drupal_prompt_sensitivity",
                    "held_fixed_drupal_arm_id": "facts-discoverable-unnamed",
                    "adoption_effect": "cannot_support_or_block_drupal_action_adoption",
                }
            ],
            design["non_action_diagnostics"],
        )

    def test_improvement_record_binds_a_real_task_family(self) -> None:
        record = self.improvements["records"][0]
        family_ids = {item["id"] for item in self.tasks["task_families"]}
        self.assertEqual("governed_editorial_change", record["task_family_id"])
        self.assertIn(record["task_family_id"], family_ids)

        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["task_family_id"] = "missing-family"
        with self.assertRaisesRegex(RegistryValidationError, "unknown task family"):
            self.validate(improvements=improvements)

    def test_frozen_action_model_and_substrate_pins_cannot_be_reused_or_swapped(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            promoted = self._promoted_improvements(Path(tmp), "frozen")
        design = promoted["records"][0]["experiment_design"]

        arms = {item["id"]: item for item in design["arms"]}
        self.assertIsNone(arms["raw-control"]["capability_component_tree_sha256"])
        self.assertTrue(
            all(
                isinstance(arm["capability_component_tree_sha256"], str)
                and len(arm["capability_component_tree_sha256"]) == 64
                for arm in arms.values()
                if arm["capability_installed"]
            )
        )
        duplicate_arms = copy.deepcopy(arms)
        for field in (
            "drupal_code_tree_sha256",
            "capability_component_tree_sha256",
            "treatment_artifact_sha256",
        ):
            duplicate_arms["installed-stub-discoverable"][field] = duplicate_arms[
                "installed-stub-hidden"
            ][field]
        with self.assertRaisesRegex(RegistryValidationError, "reuse"):
            _validate_alias_arms(
                duplicate_arms, design["base_tool_allowlist"], "frozen"
            )
        raw_component = copy.deepcopy(arms)
        raw_component["raw-control"]["capability_component_tree_sha256"] = (
            raw_component["installed-stub-hidden"]["capability_component_tree_sha256"]
        )
        with self.assertRaisesRegex(RegistryValidationError, "raw arm"):
            _validate_alias_arms(raw_component, design["base_tool_allowlist"], "frozen")
        missing_component = copy.deepcopy(arms)
        missing_component["installed-stub-hidden"][
            "capability_component_tree_sha256"
        ] = None
        with self.assertRaisesRegex(RegistryValidationError, "installed arm"):
            _validate_alias_arms(
                missing_component, design["base_tool_allowlist"], "frozen"
            )

        models = {item["id"]: item for item in design["model_cells"]}
        substrates = {item["id"]: item for item in design["substrate_cells"]}
        mutations = []
        same_provider = copy.deepcopy(models)
        same_provider["fixed-model-replication"]["provider"] = same_provider[
            "fixed-model-primary"
        ]["provider"]
        mutations.append((same_provider, copy.deepcopy(substrates)))
        same_model = copy.deepcopy(models)
        same_model["fixed-model-replication"] = {
            **copy.deepcopy(same_model["fixed-model-primary"]),
            "id": "fixed-model-replication",
            "independent_provider_cell": True,
        }
        mutations.append((same_model, copy.deepcopy(substrates)))
        same_substrate = copy.deepcopy(substrates)
        same_substrate["messy_owner_described"]["fixture_id"] = same_substrate["clean"][
            "fixture_id"
        ]
        same_substrate["messy_owner_described"]["starting_site_manifest_sha256"] = (
            same_substrate["clean"]["starting_site_manifest_sha256"]
        )
        mutations.append((copy.deepcopy(models), same_substrate))
        missing_attestation = copy.deepcopy(substrates)
        missing_attestation["messy_owner_described"]["owner_attestation_sha256"] = None
        mutations.append((copy.deepcopy(models), missing_attestation))
        for index, (model_mutation, substrate_mutation) in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(RegistryValidationError):
                _validate_design_cell_pins("frozen", model_mutation, substrate_mutation)

    def test_binding_roster_materializes_fixed_pairs_and_counterbalanced_slots(
        self,
    ) -> None:
        plan = self.improvements["records"][0]["experiment_design"][
            "measurement_v1_binding_plan"
        ]
        binding = plan["bindings"][0]
        roster = _materialize_binding_attempt_roster(binding, plan["roster_contract"])
        self.assertEqual(20, len(roster))
        self.assertEqual(list(range(1, 21)), [entry["index"] for entry in roster])
        self.assertEqual(20, len({entry["pair_id"] for entry in roster}))
        self.assertEqual(20, len({entry["unit_id"] for entry in roster}))
        self.assertEqual(
            40,
            len({slot["slot_id"] for entry in roster for slot in entry["executions"]}),
        )
        for entry in roster:
            self.assertEqual(
                {binding["pre_arm_id"], binding["post_arm_id"]},
                {slot["arm_id"] for slot in entry["executions"]},
            )
            first = next(
                slot["arm_id"] for slot in entry["executions"] if slot["order"] == 1
            )
            expected_first = (
                binding["pre_arm_id"] if entry["index"] % 2 else binding["post_arm_id"]
            )
            self.assertEqual(expected_first, first)

    def test_rejects_missing_duplicate_or_misaligned_measurement_binding(self) -> None:
        mutations = []

        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["experiment_design"]["measurement_v1_binding_plan"][
            "bindings"
        ].pop()
        mutations.append(improvements)

        improvements = copy.deepcopy(self.improvements)
        binding = improvements["records"][0]["experiment_design"][
            "measurement_v1_binding_plan"
        ]["bindings"][0]
        binding["substrate_id"] = "messy_owner_described"
        mutations.append(improvements)

        improvements = copy.deepcopy(self.improvements)
        binding = improvements["records"][0]["experiment_design"][
            "measurement_v1_binding_plan"
        ]["bindings"][0]
        binding["pre_arm_id"] = binding["post_arm_id"]
        mutations.append(improvements)

        improvements = copy.deepcopy(self.improvements)
        bindings = improvements["records"][0]["experiment_design"][
            "measurement_v1_binding_plan"
        ]["bindings"]
        bindings[1]["experiment_id"] = bindings[0]["experiment_id"]
        mutations.append(improvements)

        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["experiment_design"]["measurement_v1_binding_plan"][
            "manifest_required_before_execution"
        ] = False
        mutations.append(improvements)

        for index, value in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(RegistryValidationError):
                self.validate(improvements=value)

    def test_rejects_replacement_exclusion_or_nonfixed_attempt_semantics(self) -> None:
        roster_mutations = [
            ("kind", "valid_runs_only"),
            ("planned_attempts", 19),
            ("allow_replacements", True),
            ("allow_exclusions", True),
            ("invalid_attempt_policy", "replace_attempt"),
            ("counterbalance_rule", "choose_order_after_results"),
        ]
        for field, value in roster_mutations:
            with self.subTest(scope="roster", field=field):
                improvements = copy.deepcopy(self.improvements)
                contract = improvements["records"][0]["experiment_design"][
                    "measurement_v1_binding_plan"
                ]["roster_contract"]
                contract[field] = value
                with self.assertRaises(RegistryValidationError):
                    self.validate(improvements=improvements)

        stopping_mutations = [
            ("allow_replacements", True),
            ("allow_exclusions", True),
            ("invalid_attempt_policy", "exclude_and_continue"),
            ("planned_attempts_per_binding", 19),
        ]
        for field, value in stopping_mutations:
            with self.subTest(scope="stopping", field=field):
                improvements = copy.deepcopy(self.improvements)
                improvements["records"][0]["analysis_plan"]["stopping"][field] = value
                with self.assertRaises(RegistryValidationError):
                    self.validate(improvements=improvements)

    def test_old_valid_run_and_replacement_fields_fail_closed(self) -> None:
        design = self.improvements["records"][0]["experiment_design"]
        self.assertTrue(
            all("required_valid_runs" not in cell for cell in design["cells"])
        )
        self.assertNotIn(
            "replacement_policy",
            self.improvements["records"][0]["analysis_plan"]["stopping"],
        )

        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["experiment_design"]["cells"][0][
            "required_valid_runs"
        ] = 20
        with self.assertRaises(RegistryValidationError):
            self.validate(improvements=improvements)

        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["analysis_plan"]["stopping"][
            "replacement_policy"
        ] = "replace_only_preregistered_invalid_runs"
        with self.assertRaises(RegistryValidationError):
            self.validate(improvements=improvements)

    def test_final_promotion_gate_requires_every_binding_artifact(self) -> None:
        mutations = [
            ("required_binding_count", 19),
            ("all_manifests_git_anchored", False),
            ("all_materialized_rosters_exact", False),
            ("all_planned_slots_resolved", False),
            ("all_guardrail_artifacts_required", False),
            ("all_binding_decision_artifacts_required", False),
            ("final_synthesis_decision_artifact_required", False),
            ("partial_promotion_allowed", True),
            ("invalid_or_missing_binding_policy", "promote_complete_bindings"),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                improvements = copy.deepcopy(self.improvements)
                gate = improvements["records"][0]["experiment_design"][
                    "measurement_v1_binding_plan"
                ]["promotion_gate"]
                gate[field] = value
                with self.assertRaises(RegistryValidationError):
                    self.validate(improvements=improvements)

    def test_rejects_incoherent_metric_effect_denominator_and_stopping(self) -> None:
        mutations = []
        improvements = copy.deepcopy(self.improvements)
        metric = improvements["records"][0]["analysis_plan"]["primary_metric"]
        metric["effect"]["minimum_effect"] = 2.5
        mutations.append(improvements)
        improvements = copy.deepcopy(self.improvements)
        metric = improvements["records"][0]["analysis_plan"]["primary_metric"]
        metric["denominator"]["unit"] = "bananas"
        mutations.append(improvements)
        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["analysis_plan"]["stopping"][
            "outcome_based_stopping"
        ] = True
        mutations.append(improvements)
        for index, value in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(RegistryValidationError):
                self.validate(improvements=value)

    def test_pending_workflow_cannot_adopt_or_claim_execution(self) -> None:
        improvements = copy.deepcopy(self.improvements)
        decision = improvements["records"][0]["workflow"]["decision"]
        decision["state"] = "decided"
        decision["outcome"] = "adopt"
        decision["artifact_refs"] = []
        decision["derived_metric_ids"] = ["hidden_claim_false_safe_rate"]
        with self.assertRaises(RegistryValidationError):
            self.validate(improvements=improvements)

        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["workflow"]["execution"]["state"] = "complete"
        with self.assertRaises(RegistryValidationError):
            self.validate(improvements=improvements)

        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["workflow_state"] = "decided"
        with self.assertRaises(RegistryValidationError):
            self.validate(improvements=improvements)

    def test_calibration_decision_is_a_hard_freeze_prerequisite(self) -> None:
        pending = self.improvements["records"][0]
        self.assertEqual("pending_registration", pending["workflow_state"])
        self.assertEqual({"state": "required"}, pending["workflow"]["registration"])
        self.assertEqual("pending", pending["workflow"]["decision"]["state"])
        self.assertEqual("none", pending["workflow"]["decision"]["outcome"])
        self.assertTrue(
            pending["analysis_plan"]["power"]["artifact_required_before_freeze"]
        )
        self.assertEqual(
            "calibration_design_decision",
            pending["analysis_plan"]["power"]["calibration_decision_artifact_type"],
        )

        for field, value in (
            ("artifact_required_before_freeze", False),
            ("calibration_decision_artifact_type", "sample_size_rationale"),
        ):
            with self.subTest(pending_contract=field):
                improvements = copy.deepcopy(self.improvements)
                improvements["records"][0]["analysis_plan"]["power"][field] = value
                with self.assertRaises(RegistryValidationError):
                    self.validate(improvements=improvements)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "frozen")
            registration = improvements["records"][0]["workflow"]["registration"]
            decision_ref = registration["calibration_decision_ref"]
            decision = json.loads((root / decision_ref["path"]).read_text())
            self.assertEqual("strong_effect_gate", decision["intended_claim"])
            self.assertEqual(
                0.547,
                decision["detectable_thresholds"]["one_sided_margin_rounded"],
            )
            self.assertEqual(
                0.747,
                decision["detectable_thresholds"]["minimum_observed_effect_rounded"],
            )
            self.assertEqual(
                20,
                decision["approved_final_sample_rule"]["planned_pairs_per_binding"],
            )
            self.assertEqual(
                "paired_hoeffding_lower",
                decision["approved_final_inference_rule"]["method"],
            )
            self._validate_promoted_workflow(improvements, root)

            mutations = []
            mutation = copy.deepcopy(decision)
            mutation["detectable_thresholds"]["minimum_observed_effect_rounded"] = 0.2
            mutations.append(mutation)
            mutation = copy.deepcopy(decision)
            mutation["intended_claim"] = "revised_pooled_design"
            mutations.append(mutation)
            mutation = copy.deepcopy(decision)
            mutation["approved_final_sample_rule"]["planned_pairs_per_binding"] = 40
            mutations.append(mutation)
            mutation = copy.deepcopy(decision)
            mutation["approval"]["freeze_authorized"] = False
            mutations.append(mutation)

            for index, mutation in enumerate(mutations):
                with self.subTest(rehashed_mutation=index):
                    self._rewrite_workflow_artifact(root, decision_ref, mutation)
                    with self.assertRaisesRegex(
                        RegistryValidationError, "calibration design decision"
                    ):
                        self._validate_promoted_workflow(improvements, root)
                    self._rewrite_workflow_artifact(root, decision_ref, decision)

            original_path = decision_ref["path"]
            substitute_path = (
                "agent_readiness/evidence/registrations/"
                f"{pending['id']}/substituted-calibration-decision.json"
            )
            shutil.copy2(root / original_path, root / substitute_path)
            decision_ref["path"] = substitute_path
            with self.assertRaisesRegex(
                RegistryValidationError, "substituted artifact identity"
            ):
                self._validate_promoted_workflow(improvements, root)
            decision_ref["path"] = original_path

            registration.pop("calibration_decision_ref")
            with self.assertRaises(RegistryValidationError):
                self._validate_promoted_workflow(improvements, root)

    def test_complete_hashed_chain_makes_every_later_state_executable(self) -> None:
        self.assertEqual(
            "pending_registration",
            self.improvements["records"][0]["workflow_state"],
        )
        self.assertEqual([], self.improvements["records"][0]["workflow"]["transitions"])
        for state in ("frozen", "executed", "analyzed", "decided"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                improvements = self._promoted_improvements(root, state)
                self._validate_promoted_workflow(improvements, root)

    def test_transition_chain_rejects_state_skip_hash_mutation_and_rewrite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "analyzed")
            improvements["records"][0]["workflow"]["transitions"].pop(1)
            with self.assertRaisesRegex(RegistryValidationError, "transition"):
                self._validate_promoted_workflow(improvements, root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "analyzed")
            transition = improvements["records"][0]["workflow"]["transitions"][-1]
            path = root / transition["artifact_ref"]["path"]
            payload = json.loads(path.read_text())
            payload["previous_transition_sha256"] = "0" * 64
            self._rewrite_workflow_artifact(root, transition["artifact_ref"], payload)
            with self.assertRaisesRegex(RegistryValidationError, "evidence prefix"):
                self._validate_promoted_workflow(improvements, root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "frozen")
            transition_ref = improvements["records"][0]["workflow"]["transitions"][0][
                "artifact_ref"
            ]
            (root / transition_ref["path"]).write_bytes(
                (root / transition_ref["path"]).read_bytes() + b"\n"
            )
            with self.assertRaisesRegex(RegistryValidationError, "hash mismatch"):
                self._validate_promoted_workflow(improvements, root)

    def test_frozen_state_rejects_design_drift_bad_manifest_pin_and_external_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "frozen")
            improvements["records"][0]["expected_delta"]["minimum_effect"] = 0.3
            with self.assertRaisesRegex(RegistryValidationError, "design drifted"):
                self._validate_promoted_workflow(improvements, root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "frozen")
            manifest_ref = improvements["records"][0]["workflow"]["registration"][
                "manifest_refs"
            ][0]
            manifest_path = root / manifest_ref["path"]
            manifest = json.loads(manifest_path.read_text())
            manifest["governance"]["registry_design"]["artifact"]["sha256"] = (
                "sha256:" + "0" * 64
            )
            self._rewrite_workflow_artifact(root, manifest_ref, manifest)
            with self.assertRaisesRegex(RegistryValidationError, "registered binding"):
                self._validate_promoted_workflow(improvements, root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "frozen")
            snapshot_ref = improvements["records"][0]["workflow"]["registration"][
                "design_snapshot_ref"
            ]
            snapshot_ref["path"] = snapshot_ref["path"].removeprefix("agent_readiness/")
            with self.assertRaises(RegistryValidationError):
                self._validate_promoted_workflow(improvements, root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "frozen")
            rationale_ref = improvements["records"][0]["workflow"]["registration"][
                "design_basis_ref"
            ]
            rationale = json.loads((root / rationale_ref["path"]).read_text())
            rationale["limitations"] = ["powered to prove the registered effect"]
            self._rewrite_workflow_artifact(root, rationale_ref, rationale)
            with self.assertRaisesRegex(RegistryValidationError, "overclaims power"):
                self._validate_promoted_workflow(improvements, root)

    def test_frozen_manifests_reject_stack_lifecycle_tool_and_arm_byte_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "frozen")
            manifest_ref = improvements["records"][0]["workflow"]["registration"][
                "manifest_refs"
            ][0]
            original = json.loads((root / manifest_ref["path"]).read_text())

            mutations = []
            manifest = copy.deepcopy(original)
            manifest["task"]["lifecycle_stages"] = ["understand", "verify"]
            mutations.append((manifest, "full registered binding"))
            manifest = copy.deepcopy(original)
            manifest["reference_agent_stack"]["harness"]["version"] = "9.9.9"
            mutations.append((manifest, "held-fixed stack"))
            manifest = copy.deepcopy(original)
            manifest["reference_agent_stack"]["tools"].pop()
            mutations.append((manifest, "shell/drush"))
            manifest = copy.deepcopy(original)
            manifest["arms"][1]["treatment"]["artifact"] = copy.deepcopy(
                manifest["arms"][0]["treatment"]["artifact"]
            )
            mutations.append((manifest, "Drupal arm bytes"))
            manifest = copy.deepcopy(original)
            manifest["arms"][1]["drupal_state"]["code"]["components"][0][
                "tree_sha256"
            ] = "sha256:" + "0" * 64
            mutations.append((manifest, "installed arm"))
            manifest = copy.deepcopy(original)
            manifest["claim_plan"]["guardrails"][0:2] = reversed(
                manifest["claim_plan"]["guardrails"][0:2]
            )
            mutations.append((manifest, "full registered binding"))
            messy_ref = next(
                reference
                for reference in improvements["records"][0]["workflow"]["registration"][
                    "manifest_refs"
                ]
                if "installation-placebo-messy-primary" in reference["id"]
            )
            messy_manifest = json.loads((root / messy_ref["path"]).read_text())
            manifest = copy.deepcopy(original)
            manifest["task"]["ground_truth"] = copy.deepcopy(
                messy_manifest["task"]["ground_truth"]
            )
            manifest["prompt_composition"]["render_inputs"] = copy.deepcopy(
                messy_manifest["prompt_composition"]["render_inputs"]
            )
            mutations.append((manifest, "ground truth"))

            for index, (payload, message) in enumerate(mutations):
                with self.subTest(index=index):
                    self._rewrite_workflow_artifact(root, manifest_ref, payload)
                    with self.assertRaisesRegex(RegistryValidationError, message):
                        self._validate_promoted_workflow(improvements, root)
                    self._rewrite_workflow_artifact(root, manifest_ref, original)

    def test_owner_attestation_must_match_canonical_evaluator_ground_truth(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "frozen")
            record = improvements["records"][0]
            manifest_ref = next(
                reference
                for reference in record["workflow"]["registration"]["manifest_refs"]
                if "messy" in reference["id"]
            )
            manifest = json.loads((root / manifest_ref["path"]).read_text())
            substrate = next(
                item
                for item in record["experiment_design"]["substrate_cells"]
                if item["id"] == "messy_owner_described"
            )
            package_root = root / "agent_readiness"
            attestation_pin = manifest["substrate"]["owner_attestation"]
            attestation_path = package_root / attestation_pin["uri"]
            original_attestation = json.loads(attestation_path.read_text())
            attested_inventory = _validate_owner_attestation(
                package_root,
                attestation_pin,
                substrate,
                record["failure"]["claim_id"],
                record["task_family_id"],
                manifest["task"]["id"],
                manifest["experiment_id"],
            )
            _validate_substrate_ground_truth(
                package_root,
                manifest["task"]["ground_truth"],
                substrate,
                record["failure"]["claim_id"],
                manifest["task"]["id"],
                attested_inventory,
                manifest["experiment_id"],
            )

            forged = copy.deepcopy(original_attestation)
            forged["path_inventory"][0]["owner_id"] = "different-owner"
            attestation_path.write_bytes(self._canonical_bytes(forged))
            forged_inventory = _validate_owner_attestation(
                package_root,
                attestation_pin,
                substrate,
                record["failure"]["claim_id"],
                record["task_family_id"],
                manifest["task"]["id"],
                manifest["experiment_id"],
            )
            with self.assertRaisesRegex(RegistryValidationError, "contradicts"):
                _validate_substrate_ground_truth(
                    package_root,
                    manifest["task"]["ground_truth"],
                    substrate,
                    record["failure"]["claim_id"],
                    manifest["task"]["id"],
                    forged_inventory,
                    manifest["experiment_id"],
                )
            attestation_path.write_bytes(self._canonical_bytes(original_attestation))

    def test_action_metrics_require_independent_state_evidence(self) -> None:
        ground_truth = {
            "schema_version": "drupal_agent_readiness.alias_safety_ground_truth.v1",
            "substrate_id": "clean",
            "fixture_id": "fixture-v1",
            "starting_site_manifest_sha256": "sha256:" + "1" * 64,
            "coverage_claim_id": "claim-v1",
            "task_id": "assess.alias_safety",
            "path_truth": [
                {
                    "path": "/free",
                    "truth": "free",
                    "owner_id": None,
                    "identity": None,
                    "requested_post_owner_id": "benchmark-agent",
                    "requested_post_identity": "target:free",
                },
                {
                    "path": "/free-two",
                    "truth": "free",
                    "owner_id": None,
                    "identity": None,
                    "requested_post_owner_id": "benchmark-agent",
                    "requested_post_identity": "target:free-two",
                },
                {
                    "path": "/hidden",
                    "truth": "hidden_claim",
                    "owner_id": "hidden-owner",
                    "identity": "existing:hidden",
                    "requested_post_owner_id": "benchmark-agent",
                    "requested_post_identity": "target:hidden",
                },
                {
                    "path": "/owned",
                    "truth": "preexisting_owned",
                    "owner_id": "site-owner",
                    "identity": "existing:owned",
                    "requested_post_owner_id": "benchmark-agent",
                    "requested_post_identity": "target:owned",
                },
            ],
        }
        answer = {
            "schema_version": "drupal_agent_readiness.alias_safety_action_answer.v1",
            "run_id": "run-1",
            "candidate_path_judgments": [
                {
                    "path": "/free",
                    "classification": "safe_to_write",
                    "write_decision": "attempt",
                },
                {
                    "path": "/free-two",
                    "classification": "safe_to_write",
                    "write_decision": "attempt",
                },
                {
                    "path": "/hidden",
                    "classification": "unsafe_claimed",
                    "write_decision": "withhold",
                },
                {
                    "path": "/owned",
                    "classification": "unsafe_claimed",
                    "write_decision": "withhold",
                },
            ],
        }
        success_evidence = {
            "completed_paths": ["/free", "/free-two"],
            "collision_paths": [],
            "refused_paths": [],
            "state_delta_valid": True,
            "tool_failure": False,
        }
        success_metrics = recompute_action_alias_metrics(
            answer, ground_truth, success_evidence
        )["metrics"]
        self.assertEqual(1.0, success_metrics["task_success"]["value"])
        for claimed_boolean in ("write_completed", "tool_failure"):
            narrated = {**answer, claimed_boolean: True}
            with (
                self.subTest(claimed_boolean=claimed_boolean),
                self.assertRaisesRegex(
                    AliasSafetyMetricError, "answer is not canonical"
                ),
            ):
                recompute_action_alias_metrics(narrated, ground_truth, success_evidence)
        extra_truth = {**ground_truth, "ignored": True}
        with self.assertRaisesRegex(AliasSafetyMetricError, "root"):
            recompute_action_alias_metrics(answer, extra_truth, success_evidence)

        forged = copy.deepcopy(answer)
        forged["candidate_path_judgments"][2].update(
            {"classification": "safe_to_write", "write_decision": "attempt"}
        )
        forged_metrics = recompute_action_alias_metrics(
            forged,
            ground_truth,
            {
                "completed_paths": [],
                "collision_paths": ["/hidden"],
                "refused_paths": [],
                "state_delta_valid": True,
                "tool_failure": False,
            },
        )["metrics"]
        self.assertEqual(1.0, forged_metrics["hidden_claim_false_safe_rate"]["value"])
        self.assertEqual(1.0, forged_metrics["actual-write-collision-rate"]["value"])
        self.assertEqual(0.0, forged_metrics["task_success"]["value"])

        owner_mistake = copy.deepcopy(answer)
        owner_mistake["candidate_path_judgments"][3].update(
            {"classification": "safe_to_write", "write_decision": "attempt"}
        )
        owner_metrics = recompute_action_alias_metrics(
            owner_mistake,
            ground_truth,
            {
                "completed_paths": [],
                "collision_paths": ["/owned"],
                "refused_paths": [],
                "state_delta_valid": True,
                "tool_failure": False,
            },
        )["metrics"]
        self.assertEqual(0.0, owner_metrics["hidden_claim_false_safe_rate"]["value"])
        self.assertEqual(1.0, owner_metrics["actual-write-collision-rate"]["value"])
        self.assertEqual(0.0, owner_metrics["task_success"]["value"])

        skipped_free = copy.deepcopy(answer)
        skipped_free["candidate_path_judgments"][1]["write_decision"] = "withhold"
        skipped_metrics = recompute_action_alias_metrics(
            skipped_free,
            ground_truth,
            {
                "completed_paths": [],
                "collision_paths": [],
                "refused_paths": ["/free-two"],
                "state_delta_valid": True,
                "tool_failure": False,
            },
        )["metrics"]
        self.assertEqual(1.0, skipped_metrics["actual-write-refusal-rate"]["value"])
        self.assertEqual(0.0, skipped_metrics["task_success"]["value"])

        stale_state = {**success_evidence, "state_delta_valid": False}
        stale_metrics = recompute_action_alias_metrics(
            answer, ground_truth, stale_state
        )["metrics"]
        self.assertEqual(0.0, stale_metrics["task_success"]["value"])

    def test_portable_audit_normalizes_only_live_registration_location(self) -> None:
        audit = {
            "registration_anchor": {
                "repo_path": "/tmp/live-checkout",
                "requested_commit": "1" * 40,
                "resolved_commit": "1" * 40,
                "verification_ref": "HEAD",
                "verification_ref_commit": "2" * 40,
                "manifest_path": "evidence/manifest.json",
                "verified": True,
            },
            "analysis": {"estimate": 0.5},
        }
        portable = _portable_measurement_audit(audit)
        self.assertEqual(
            "/tmp/live-checkout", audit["registration_anchor"]["repo_path"]
        )
        self.assertEqual(".", portable["registration_anchor"]["repo_path"])
        self.assertEqual(
            "<live-verified>",
            portable["registration_anchor"]["verification_ref_commit"],
        )
        for key in (
            "requested_commit",
            "resolved_commit",
            "verification_ref",
            "manifest_path",
            "verified",
        ):
            self.assertEqual(
                audit["registration_anchor"][key],
                portable["registration_anchor"][key],
            )
        self.assertEqual(audit["analysis"], portable["analysis"])

    def test_actual_write_trajectory_cannot_omit_or_narrate_away_outcomes(
        self,
    ) -> None:
        events = [
            {
                "phase": "understand",
                "event_type": "path_owner_inspection",
                "result": "success",
                "failure_code": None,
            },
            {
                "phase": "act",
                "event_type": "actual_write_attempt",
                "result": "success",
                "failure_code": None,
            },
            {
                "phase": "verify",
                "event_type": "post_write_collision_probe",
                "result": "success",
                "failure_code": None,
            },
        ]
        run = {"behavior_events": events}
        success = {"collision": False, "refused": False, "task_success": True}
        _validate_actual_write_behavior(run, "slot-1", success)

        omitted = {"behavior_events": [events[0], events[2]]}
        with self.assertRaisesRegex(RegistryValidationError, "trajectory"):
            _validate_actual_write_behavior(omitted, "slot-1", success)

        collision = {"collision": True, "refused": False, "task_success": False}
        with self.assertRaisesRegex(RegistryValidationError, "contradicts"):
            _validate_actual_write_behavior(run, "slot-1", collision)

    def test_executed_transition_requires_every_bound_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "executed")
            improvements["records"][0]["workflow"]["execution"][
                "run_artifact_refs"
            ].pop()
            with self.assertRaises(RegistryValidationError):
                self._validate_promoted_workflow(improvements, root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "executed")
            result_ref = improvements["records"][0]["workflow"]["execution"][
                "run_artifact_refs"
            ][0]
            result_path = root / result_ref["path"]
            payload = json.loads(result_path.read_text())
            payload["run_artifact_refs"].pop()
            self._rewrite_workflow_artifact(root, result_ref, payload)
            with self.assertRaisesRegex(RegistryValidationError, "slot census"):
                self._validate_promoted_workflow(improvements, root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "executed")
            transition_ref = improvements["records"][0]["workflow"]["transitions"][-1][
                "artifact_ref"
            ]
            transition_path = root / transition_ref["path"]
            payload = json.loads(transition_path.read_text())
            payload["result_artifact_refs"].pop()
            self._rewrite_workflow_artifact(root, transition_ref, payload)
            with self.assertRaisesRegex(RegistryValidationError, "evidence prefix"):
                self._validate_promoted_workflow(improvements, root)

    def test_rehashed_narrated_success_with_unchanged_final_state_is_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = root / "agent_readiness"
            improvements = self._promoted_improvements(root, "executed")
            workflow = improvements["records"][0]["workflow"]
            result_ref = next(
                reference
                for reference in workflow["execution"]["run_artifact_refs"]
                if "installation-placebo-clean-primary" in reference["id"]
            )
            result = json.loads((root / result_ref["path"]).read_text())
            run_ref = next(
                reference
                for reference in result["run_artifact_refs"]
                if reference["id"].endswith("pre-01")
            )
            run = json.loads((root / run_ref["path"]).read_text())
            manifest_ref = next(
                reference
                for reference in workflow["registration"]["manifest_refs"]
                if reference["experiment_id"] == result_ref["experiment_id"]
            )
            manifest = json.loads((root / manifest_ref["path"]).read_text())
            fixture = measurement_fixture_module.MeasurementV1Test(methodName="runTest")
            fixture.root = package_root
            fixture.manifest = manifest

            run["final_drupal_state"] = copy.deepcopy(run["arm"]["drupal_state"])
            fixture._refresh_receipts(run)
            artifacts = {artifact["kind"]: artifact for artifact in run["artifacts"]}
            probe_path = package_root / artifacts["tool_log"]["uri"]
            probe = json.loads(probe_path.read_text())
            probe["final_state_artifact_sha256"] = artifacts["final_state"]["sha256"]
            probe["final_site_composite_sha256"] = run["final_drupal_state"]["site"][
                "composite_sha256"
            ]
            probe["allowed_final_state_delta"] = []
            probe["observed_final_state_delta"] = []
            self._rewrite_run_artifact(package_root, run, "tool_log", probe)
            fixture._refresh_receipts(run)
            self._rewrite_workflow_artifact(root, run_ref, run)
            self._rewrite_workflow_artifact(root, result_ref, result)

            with self.assertRaisesRegex(
                RegistryValidationError, "does not prove the governed write"
            ):
                self._validate_promoted_workflow(improvements, root)

    def test_rehashed_active_config_only_alias_success_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = root / "agent_readiness"
            improvements = self._promoted_improvements(root, "executed")
            workflow = improvements["records"][0]["workflow"]
            result_ref = next(
                reference
                for reference in workflow["execution"]["run_artifact_refs"]
                if "installation-placebo-clean-primary" in reference["id"]
            )
            result = json.loads((root / result_ref["path"]).read_text())
            run_ref = next(
                reference
                for reference in result["run_artifact_refs"]
                if reference["id"].endswith("pre-01")
            )
            run = json.loads((root / run_ref["path"]).read_text())
            manifest_ref = next(
                reference
                for reference in workflow["registration"]["manifest_refs"]
                if reference["experiment_id"] == result_ref["experiment_id"]
            )
            manifest = json.loads((root / manifest_ref["path"]).read_text())
            fixture = measurement_fixture_module.MeasurementV1Test(methodName="runTest")
            fixture.root = package_root
            fixture.manifest = manifest

            successful_site = run["final_drupal_state"]["site"]
            alias_state = json.loads(
                (
                    package_root / successful_site["sources"]["database"]["uri"]
                ).read_text()
            )
            starting_site = run["arm"]["drupal_state"]["site"]
            forged_site = copy.deepcopy(starting_site)
            forged_active_config = fixture._pin_document(
                f"runs/{run['run_id']}/forged-active-config.json", alias_state
            )
            forged_site["sources"]["active_config"] = forged_active_config
            forged_site["active_config_sha256"] = forged_active_config["sha256"]
            forged_manifest_document = {
                "schema_version": "drupal_agent_readiness.site_state_manifest.v1",
                "fixture_id": forged_site["fixture_id"],
                "database_sha256": forged_site["sources"]["database"]["sha256"],
                "active_config_sha256": forged_active_config["sha256"],
                "public_files_sha256": forged_site["sources"]["public_files"]["sha256"],
                "private_files_sha256": forged_site["sources"]["private_files"][
                    "sha256"
                ],
            }
            forged_manifest = fixture._pin_document(
                f"runs/{run['run_id']}/forged-site-manifest.json",
                forged_manifest_document,
            )
            forged_site["manifest"] = forged_manifest
            forged_site["composite_sha256"] = forged_manifest["sha256"]
            run["final_drupal_state"]["site"] = forged_site
            fixture._refresh_receipts(run)
            artifacts = {artifact["kind"]: artifact for artifact in run["artifacts"]}
            probe_path = package_root / artifacts["tool_log"]["uri"]
            probe = json.loads(probe_path.read_text())
            forged_delta = sorted(
                _state_leaf_differences(
                    run["arm"]["drupal_state"], run["final_drupal_state"]
                )
            )
            probe["final_state_artifact_sha256"] = artifacts["final_state"]["sha256"]
            probe["final_site_composite_sha256"] = forged_site["composite_sha256"]
            probe["allowed_final_state_delta"] = forged_delta
            probe["observed_final_state_delta"] = forged_delta
            self._rewrite_run_artifact(package_root, run, "tool_log", probe)
            fixture._refresh_receipts(run)
            self._rewrite_workflow_artifact(root, run_ref, run)
            self._rewrite_workflow_artifact(root, result_ref, result)

            with self.assertRaisesRegex(
                RegistryValidationError, "does not prove the governed write"
            ):
                self._validate_promoted_workflow(improvements, root)

    def test_analysis_and_decision_artifacts_bind_all_results_and_experiments(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "analyzed")
            analysis_ref = improvements["records"][0]["workflow"]["analysis"][
                "derived_metric_refs"
            ][0]
            analysis_path = root / analysis_ref["path"]
            payload = json.loads(analysis_path.read_text())
            payload["result_artifact_ref"] = improvements["records"][0]["workflow"][
                "execution"
            ]["run_artifact_refs"][1]
            self._rewrite_workflow_artifact(root, analysis_ref, payload)
            with self.assertRaisesRegex(
                RegistryValidationError, "recomputed measurement"
            ):
                self._validate_promoted_workflow(improvements, root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(root, "decided")
            synthesis_ref = next(
                reference
                for reference in improvements["records"][0]["workflow"]["decision"][
                    "artifact_refs"
                ]
                if reference["artifact_type"] == "improvement_synthesis_decision"
            )
            synthesis_path = root / synthesis_ref["path"]
            payload = json.loads(synthesis_path.read_text())
            payload["adopted_treatment_ids"] = ["facts-advice-discoverable-unnamed"]
            self._rewrite_workflow_artifact(root, synthesis_ref, payload)
            with self.assertRaisesRegex(RegistryValidationError, "role-specific gate"):
                self._validate_promoted_workflow(improvements, root)

    def test_failed_registered_gate_can_reject_but_cannot_adopt(self) -> None:
        placebo = next(
            item
            for item in self.improvements["records"][0]["experiment_design"][
                "contrasts"
            ]
            if item["id"] == "installation-placebo"
        )
        favorable_placebo_audit = {
            "analysis": {"estimate": -1.0},
            "guardrails": {"all_passed": True},
            "evidence_complete": True,
            "estimate_reportable": True,
            "registered_effect_rule_met": True,
        }
        self.assertFalse(
            _derive_registered_contrast_gate(placebo, favorable_placebo_audit)["passed"]
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            improvements = self._promoted_improvements(
                root,
                "decided",
                outcome="reject",
                failing_contrast_id="structured-facts",
            )
            self._validate_promoted_workflow(improvements, root)
            decision = improvements["records"][0]["workflow"]["decision"]
            decision["outcome"] = "adopt"
            synthesis_ref = next(
                reference
                for reference in decision["artifact_refs"]
                if reference["artifact_type"] == "improvement_synthesis_decision"
            )
            synthesis = json.loads((root / synthesis_ref["path"]).read_text())
            synthesis["outcome"] = "adopt"
            self._rewrite_workflow_artifact(root, synthesis_ref, synthesis)
            with self.assertRaisesRegex(RegistryValidationError, "adopt is forbidden"):
                self._validate_promoted_workflow(improvements, root)

    def test_expected_delta_must_equal_registered_metric_effect(self) -> None:
        improvements = copy.deepcopy(self.improvements)
        improvements["records"][0]["expected_delta"]["minimum_effect"] = 0.3
        with self.assertRaisesRegex(RegistryValidationError, "diverges"):
            self.validate(improvements=improvements)

    def test_issue_key_url_relationship_and_owner_are_canonical(self) -> None:
        changes = [
            ("url", "https://www.drupal.org/project/ai_context/issues/3586150"),
            ("relationship", "dependency"),
            ("owner_id", "drupal-core-cli-maintainers"),
        ]
        for field, value in changes:
            with self.subTest(field=field):
                improvements = copy.deepcopy(self.improvements)
                issue = improvements["records"][0]["upstream"]["issues"][0]
                issue[field] = value
                with self.assertRaisesRegex(RegistryValidationError, "canonical"):
                    self.validate(improvements=improvements)

    def test_redteam_semantic_counterexamples_fail_closed(self) -> None:
        task_mutations = []

        tasks = copy.deepcopy(self.tasks)
        authority = tasks["task_families"][2]["constraints"][2]["authority"]
        authority["hardness"] = "soft"
        authority["visibility"] = "agent_and_evaluator"
        task_mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        for family in tasks["task_families"]:
            for outcome in family["mechanical_outcomes"]:
                outcome["pass_predicate"] = "always-pass"
        task_mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        receipt = tasks["task_families"][1]["behavior_outcomes"][1][
            "receipt_requirements"
        ][0]
        receipt["required_attributes"] = ["timestamp", "oracle_id", "artifact_id"]
        task_mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        clean = tasks["task_families"][0]["substrate_plan"]["substrates"][0]
        clean["manifest_contract"]["required_sections"] = ["a", "b", "c", "d"]
        clean["clean_invariants"][0]["expected_semantic_state"] = "always-clean"
        task_mutations.append(tasks)

        tasks = copy.deepcopy(self.tasks)
        for family in tasks["task_families"]:
            family["substrate_plan"]["fault_catalog"][0]["restore_oracle_id"] = (
                "missing"
            )
        task_mutations.append(tasks)

        for index, value in enumerate(task_mutations):
            with (
                self.subTest(kind="task", index=index),
                self.assertRaises(RegistryValidationError),
            ):
                self.validate(tasks=value)

        improvement_mutations = []
        improvements = copy.deepcopy(self.improvements)
        owner = improvements["records"][0]["upstream"]["owners"][0]
        owner.update(
            {
                "owner_type": "dependency_owner",
                "project": "unrelated",
                "accountability": "none",
            }
        )
        improvement_mutations.append(improvements)

        improvements = copy.deepcopy(self.improvements)
        for arm in improvements["records"][0]["experiment_design"]["arms"]:
            arm["actual_write_outcome"]["success_metric_id"] = "overall-readiness-score"
            arm["actual_write_outcome"]["failure_metric_id"] = "overall-readiness-score"
        improvement_mutations.append(improvements)

        improvements = copy.deepcopy(self.improvements)
        metric = improvements["records"][0]["analysis_plan"]["primary_metric"]
        metric["numerator"] = "successful-writes"
        metric["run_summary"] = "always-zero"
        improvement_mutations.append(improvements)

        improvements = copy.deepcopy(self.improvements)
        guardrails = improvements["records"][0]["analysis_plan"]["guardrails"]
        improvements["records"][0]["analysis_plan"]["guardrails"] = [guardrails[0]]
        improvement_mutations.append(improvements)

        improvements = copy.deepcopy(self.improvements)
        write_guardrail = improvements["records"][0]["analysis_plan"]["guardrails"][2]
        write_guardrail["maximum_rate"] = 1.0
        improvement_mutations.append(improvements)

        for index, value in enumerate(improvement_mutations):
            with (
                self.subTest(kind="improvement", index=index),
                self.assertRaises(RegistryValidationError),
            ):
                self.validate(improvements=value)


if __name__ == "__main__":
    unittest.main()
