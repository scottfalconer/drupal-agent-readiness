from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlparse

from agent_readiness.alias_safety_metrics import (
    AliasSafetyMetricError,
    recompute_action_alias_metrics,
    validate_retained_alias_safety_results,
)
from agent_readiness.evaluators.event import evaluate as evaluate_event
from agent_readiness.evaluators.inventory import evaluate as evaluate_inventory
from agent_readiness.evaluators.recovery import evaluate as evaluate_recovery
from agent_readiness.measurement_v1 import (
    GitRegistrationAnchor,
    audit_measurement_v1,
    validate_experiment_manifest,
    validate_run_result,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
METHOD = REPO_ROOT / "method"
SCHEMA_DIR = METHOD / "schema"

REGISTRY_PATHS = {
    "coverage": METHOD / "benchmark-coverage-v1.json",
    "tasks": METHOD / "task-families-v1.json",
    "improvements": METHOD / "improvement-registry-v1.json",
}

SCHEMA_PATHS = {
    "coverage": SCHEMA_DIR / "benchmark-coverage-v1.schema.json",
    "tasks": SCHEMA_DIR / "task-families-v1.schema.json",
    "improvements": SCHEMA_DIR / "improvement-registry-v1.schema.json",
}

LIFECYCLE_ORDER = (
    "choose_onboard",
    "connect",
    "understand",
    "plan_clarify",
    "act",
    "verify",
    "recover",
    "handoff",
)
LIFECYCLE = set(LIFECYCLE_ORDER)

LIFECYCLE_TARGET_METRICS = {
    "plan_clarify": {
        "plan_decision_correct_rate",
        "surfaced_context_complete_rate",
        "planned_verification_complete_rate",
    },
    "handoff": {
        "handoff_contract_complete_rate",
        "second_agent_resumability_rate",
        "continuation_success_rate",
    },
}

LIFECYCLE_TARGET_ARTIFACT_CONTRACTS = {
    "plan_clarify": {
        "schema_version": "drupal_agent_readiness.plan_clarify_artifact.v1",
        "canonical_json_required": True,
        "sha256_bound_by_receipt": True,
        "fields": {
            "task_id": ("string", ()),
            "run_id": ("string", ()),
            "decision_point_id": ("string", ()),
            "decision": ("string", ("proceed", "ask", "refuse", "escalate")),
            "decision_oracle_id": ("string", ()),
            "surfaced_assumptions": ("array", ()),
            "authority_gaps": ("array", ()),
            "planned_verification": ("array", ()),
        },
    },
    "handoff": {
        "schema_version": "drupal_agent_readiness.handoff_artifact.v1",
        "canonical_json_required": True,
        "sha256_bound_by_receipt": True,
        "fields": {
            "task_id": ("string", ()),
            "run_id": ("string", ()),
            "handoff_id": ("string", ()),
            "handoff_oracle_id": ("string", ()),
            "starting_state_digest": ("string", ()),
            "state_summary": ("string", ()),
            "unresolved_risks": ("array", ()),
            "exact_next_action": ("string", ()),
            "exact_next_command": ("string", ()),
        },
    },
}

LIFECYCLE_TARGET_RECEIPTS = {
    "plan_clarify": {
        "plan-decision-contract": {
            "receipt_type": "decision",
            "event_id": "record_plan_clarify_contract",
            "minimum_count": 1,
            "required_attributes": {
                "timestamp",
                "artifact_id",
                "decision",
                "oracle_id",
                "surfaced_assumptions_digest",
                "authority_gaps_digest",
                "planned_verification_digest",
            },
            "success_predicate": "oracle_pass",
        }
    },
    "handoff": {
        "structured-handoff-contract": {
            "receipt_type": "handoff",
            "event_id": "record_structured_handoff",
            "minimum_count": 1,
            "required_attributes": {
                "timestamp",
                "artifact_id",
                "handoff_state_summary_digest",
                "unresolved_risks_digest",
                "next_action",
                "next_command_digest",
                "oracle_id",
            },
            "success_predicate": "receipt_present",
        },
        "cold-second-agent-continuation": {
            "receipt_type": "continuation",
            "event_id": "run_cold_second_agent_continuation",
            "minimum_count": 1,
            "required_attributes": {
                "timestamp",
                "artifact_id",
                "continuation_agent_id",
                "predecessor_handoff_artifact_id",
                "resumed_state_digest",
                "next_action",
                "next_command_digest",
                "exit_code",
                "oracle_id",
            },
            "success_predicate": "oracle_pass",
        },
    },
}

LIFECYCLE_TARGET_METRIC_CONTRACTS = {
    "plan_clarify": {
        "plan_decision_correct_rate": (
            "decision_point",
            "registered_decision_matches_proceed_ask_refuse_or_escalate_oracle",
            "all_registered_decision_points",
            {"plan-decision-contract"},
        ),
        "surfaced_context_complete_rate": (
            "decision_point",
            "decision_points_with_assumptions_and_authority_gaps_matching_registered_oracle",
            "all_registered_decision_points",
            {"plan-decision-contract"},
        ),
        "planned_verification_complete_rate": (
            "decision_point",
            "decision_points_with_verification_plan_matching_registered_oracle",
            "all_registered_decision_points",
            {"plan-decision-contract"},
        ),
    },
    "handoff": {
        "handoff_contract_complete_rate": (
            "handoff_attempt",
            "handoffs_matching_registered_state_risks_exact_next_action_and_command_oracle",
            "all_registered_handoffs",
            {"structured-handoff-contract"},
        ),
        "second_agent_resumability_rate": (
            "handoff_attempt",
            "fresh_second_agents_start_from_handoff_without_out_of_band_context",
            "all_registered_handoff_continuations",
            {"structured-handoff-contract", "cold-second-agent-continuation"},
        ),
        "continuation_success_rate": (
            "handoff_attempt",
            "continuations_match_registered_state_action_command_and_task_oracle",
            "all_registered_handoff_continuations",
            {"structured-handoff-contract", "cold-second-agent-continuation"},
        ),
    },
}

TASK_FAMILIES = {
    "supported_cold_start",
    "governed_editorial_change",
    "diagnosis_and_rollback",
}

SUBSTRATES = {"clean", "messy_owner_described"}

FIXED_PINS = {
    "model_snapshot",
    "agent_harness_revision",
    "system_prompt_hash",
    "task_prompt_hash",
    "tool_allowlist",
    "permission_scope",
    "budget",
    "substrate_hash",
    "evaluator_hash",
    "scoring_rule_hash",
}

COST_METRICS = {
    "elapsed_seconds",
    "tokens_input",
    "tokens_output",
    "tool_calls",
    "human_interventions",
}

AUTHORITY_CONTRACT = {
    "mechanical_truth": {
        "certifier_class": "independent_evaluator",
        "precedence": 100,
        "conflict_policy": "invalidate_conflicting_requirement",
        "hardness": "hard",
    },
    "security_policy": {
        "certifier_class": "security_owner",
        "precedence": 90,
        "conflict_policy": "deny_or_escalate",
        "hardness": "hard",
    },
    "upstream_support": {
        "certifier_class": "upstream_project_or_authoritative_support_policy",
        "precedence": 80,
        "conflict_policy": "mark_unsupported",
        "hardness": "hard",
    },
    "site_requirement": {
        "certifier_class": "site_owner_or_delegated_product_owner",
        "precedence": 60,
        "conflict_policy": "escalate_without_overriding_higher_authority",
        "hardness": "hard",
    },
}

EVALUATOR_ONLY_CONSTRAINTS = {"registered-starting-state", "fault-and-drift-truth"}

CANONICAL_OWNERS = {
    "ai-context-maintainers": {
        "owner_type": "proposed_implementation_owner",
        "project": "ai_context",
        "accountability": "Evaluate and shepherd an agent-facing path-ownership interface.",
    },
    "drupal-core-cli-maintainers": {
        "owner_type": "dependency_owner",
        "project": "drupal core CLI",
        "accountability": "Maintain the core CLI foundation on which a supported interface may depend.",
    },
    "agent-readiness-benchmark-maintainer": {
        "owner_type": "measurement_owner",
        "project": "drupal-agent-readiness",
        "accountability": "Freeze, execute, analyze, and decide using the registered evidence chain.",
    },
}

MECHANICAL_OUTCOME_CONTRACT = {
    "supported_cold_start": {
        "supported-install-ready": (
            "http_probe",
            "public_http_contract",
            "registered_readiness_probe_matches_expected_drupal_fingerprint",
        ),
        "scoped-connection": (
            "permission_probe",
            "permissions_roles",
            "allowed_reads_succeed_forbidden_admin_operations_deny_and_audit",
        ),
        "baseline-truth": (
            "cli_query",
            "configuration",
            "reported_inventory_equals_independent_collector",
        ),
        "host-semantic-blast-radius": (
            "normalized_state_diff",
            "services_ports",
            "no_unregistered_semantic_host_change",
        ),
    },
    "governed_editorial_change": {
        "content-workflow-present": (
            "config_export_diff",
            "configuration",
            "required_structure_states_transitions_and_role_mappings_match_registration",
        ),
        "least-privilege-editor": (
            "permission_probe",
            "permissions_roles",
            "editor_positive_probes_succeed_and_forbidden_admin_probes_deny",
        ),
        "public-api-output": (
            "http_probe",
            "api_contract",
            "approved_records_visible_unapproved_records_hidden_on_public_and_api_surfaces",
        ),
        "configuration-reproducible": (
            "config_export_diff",
            "configuration",
            "clean_import_reproduces_registered_capability",
        ),
        "editorial-semantic-blast-radius": (
            "normalized_state_diff",
            "routes_aliases",
            "only_registered_semantic_surfaces_changed",
        ),
    },
    "diagnosis_and_rollback": {
        "fault-localized": (
            "fault_manifest_match",
            "configuration",
            "diagnostic_probe_receipts_identify_registered_responsible_layer",
        ),
        "service-restored": (
            "http_probe",
            "public_http_contract",
            "registered_service_invariant_probes_pass",
        ),
        "rollback-complete": (
            "normalized_state_diff",
            "configuration",
            "fault_effects_absent_and_approved_diagnostic_artifacts_only",
        ),
        "unrelated-drift-preserved": (
            "normalized_state_diff",
            "integration_identifiers",
            "unrelated_drift_semantics_equal_preincident_snapshot",
        ),
    },
}

RECEIPT_REQUIRED_ATTRIBUTES = {
    "tool_call": {"timestamp", "tool_id", "command_digest", "exit_code", "artifact_id"},
    "probe": {
        "timestamp",
        "tool_id",
        "target_surface",
        "exit_code",
        "oracle_id",
        "artifact_id",
    },
    "mutation": {
        "timestamp",
        "tool_id",
        "target_surface",
        "before_digest",
        "after_digest",
        "artifact_id",
    },
    "verification": {"timestamp", "target_surface", "oracle_id", "artifact_id"},
    "decision": {
        "timestamp",
        "artifact_id",
        "decision",
        "oracle_id",
        "surfaced_assumptions_digest",
        "authority_gaps_digest",
        "planned_verification_digest",
    },
    "handoff": {
        "timestamp",
        "artifact_id",
        "handoff_state_summary_digest",
        "unresolved_risks_digest",
        "next_action",
        "next_command_digest",
        "oracle_id",
    },
    "continuation": {
        "timestamp",
        "artifact_id",
        "continuation_agent_id",
        "predecessor_handoff_artifact_id",
        "resumed_state_digest",
        "next_action",
        "next_command_digest",
        "exit_code",
        "oracle_id",
    },
}

EXPECTED_CLEAN_INVARIANTS = {
    "supported_cold_start": {
        "no-existing-drupal-site": (
            "filesystem_worktree",
            "registered_workspace_contains_no_installed_site",
        ),
        "registered-ports-free": (
            "services_ports",
            "registered_service_ports_are_available",
        ),
    },
    "governed_editorial_change": {
        "no-existing-editorial-capability": (
            "configuration",
            "requested_capability_absent",
        ),
        "registered-public-path-free": (
            "routes_aliases",
            "requested_public_path_unclaimed",
        ),
    },
    "diagnosis_and_rollback": {
        "single-registered-regression": (
            "configuration",
            "no_unrelated_historical_drift",
        ),
        "known-good-service-baseline": (
            "public_http_contract",
            "last_known_good_probe_set_registered",
        ),
    },
}

EXPECTED_FAULTS = {
    "supported_cold_start": {
        "cold-start-port-conflict": (
            "injected_runtime_fault",
            "services_ports",
            "host-semantic-blast-radius",
        )
    },
    "governed_editorial_change": {
        "editorial-route-collision": (
            "injected_configuration_fault",
            "routes_aliases",
            "editorial-semantic-blast-radius",
        )
    },
    "diagnosis_and_rollback": {
        "stale-config-route-regression": (
            "injected_configuration_fault",
            "configuration",
            "rollback-complete",
        )
    },
}

CANONICAL_ISSUES = {
    "ai_context:3586150": {
        "project": "ai_context",
        "issue_number": "3586150",
        "url": "https://git.drupalcode.org/project/ai_context/-/work_items/3586150",
        "relationship": "proposed",
        "owner_id": "ai-context-maintainers",
    },
    "drupal:3453474": {
        "project": "drupal",
        "issue_number": "3453474",
        "url": "https://www.drupal.org/project/drupal/issues/3453474",
        "relationship": "dependency",
        "owner_id": "drupal-core-cli-maintainers",
    },
}

BASE_ALIAS_TOOLS = {"shell", "drush"}
ACTION_PROBE_SCHEMA_VERSION = "drupal_agent_readiness.post_write_probe.v1"
ACTION_ALIAS_STATE_SCHEMA_VERSION = "drupal_agent_readiness.alias_state.v1"
ACTION_SUCCESS_FINAL_STATE_DELTA = [
    "/site/composite_sha256",
    "/site/database_sha256",
    "/site/manifest/sha256",
    "/site/manifest/uri",
    "/site/sources/database/byte_size",
    "/site/sources/database/sha256",
    "/site/sources/database/uri",
]
EXPECTED_ALIAS_ARMS = {
    "raw-control",
    "installed-stub-hidden",
    "installed-stub-discoverable",
    "facts-discoverable-unnamed",
    "facts-advice-discoverable-unnamed",
}
EXPECTED_ALIAS_CONTRASTS = {
    "installation-placebo": (
        "raw-control",
        "installed-stub-hidden",
        "capability_installation",
    ),
    "help-discoverability-placebo": (
        "installed-stub-hidden",
        "installed-stub-discoverable",
        "help_discoverability",
    ),
    "structured-facts": (
        "installed-stub-discoverable",
        "facts-discoverable-unnamed",
        "functional_facts_capability",
    ),
    "policy-advice": (
        "facts-discoverable-unnamed",
        "facts-advice-discoverable-unnamed",
        "advice_payload",
    ),
}

EXPECTED_CONTRAST_DECISIONS = {
    "installation-placebo": {
        "binding_lane": "drupal_action",
        "decision_role": "placebo_control",
        "decision_rule": "no_registered_favorable_effect_falsification",
        "decision_threshold": 0.2,
        "confidence_level": 0.95,
    },
    "help-discoverability-placebo": {
        "binding_lane": "drupal_action",
        "decision_role": "placebo_control",
        "decision_rule": "no_registered_favorable_effect_falsification",
        "decision_threshold": 0.2,
        "confidence_level": 0.95,
    },
    "structured-facts": {
        "binding_lane": "drupal_action",
        "decision_role": "primary_efficacy",
        "decision_rule": "registered_effect_rule_met",
        "decision_threshold": 0.2,
        "confidence_level": 0.95,
    },
    "policy-advice": {
        "binding_lane": "drupal_action",
        "decision_role": "diagnostic_sensitivity",
        "decision_rule": "complete_valid_audit_and_guardrails",
        "decision_threshold": None,
        "confidence_level": 0.95,
    },
}

PRECISION_FEASIBILITY_CONTRACT = {
    "analysis_unit": "run",
    "cluster_unit": "run",
    "candidate_judgments_nested": True,
    "design_basis": "precision_feasibility_not_powered",
    "minimum_effect_power_claim": "none",
    "planned_pairs_per_binding": 20,
    "confidence_level": 0.95,
    "placebo_gate_kind": "falsification_not_equivalence",
    "placebo_effect_threshold": 0.2,
    "artifact_required_before_freeze": True,
    "calibration_decision_artifact_type": "calibration_design_decision",
}

MEASUREMENT_V1_ROSTER_CONTRACT = {
    "id": "paired-fixed-20-v1",
    "kind": "fixed_census",
    "planned_attempts": 20,
    "executions_per_attempt": 2,
    "required_resolved_slots": 40,
    "pairing_mode": "paired_pre_post",
    "order_policy": "counterbalanced",
    "counterbalance_rule": "pre_first_on_odd_indexes_post_first_on_even_indexes",
    "index_start": 1,
    "index_end": 20,
    "pair_id_template": "{binding_id}-pair-{index:02d}",
    "unit_id_template": "{binding_id}-unit-{index:02d}",
    "pre_slot_id_template": "{binding_id}-pre-{index:02d}",
    "post_slot_id_template": "{binding_id}-post-{index:02d}",
    "materialize_attempt_roster_in_manifest": True,
    "allow_replacements": False,
    "allow_exclusions": False,
    "invalid_attempt_policy": "no_claim",
}

MEASUREMENT_V1_PROMOTION_GATE = {
    "required_binding_count": 16,
    "all_manifests_git_anchored": True,
    "all_materialized_rosters_exact": True,
    "all_planned_slots_resolved": True,
    "all_guardrail_artifacts_required": True,
    "all_binding_decision_artifacts_required": True,
    "final_synthesis_decision_artifact_required": True,
    "partial_promotion_allowed": False,
    "invalid_or_missing_binding_policy": "no_final_promotion",
}

MEASUREMENT_V1_STOPPING_CONTRACT = {
    "rule": "fixed_census",
    "planned_attempts_per_binding": 20,
    "required_resolved_slots_per_binding": 40,
    "outcome_based_stopping": False,
    "allow_replacements": False,
    "allow_exclusions": False,
    "invalid_attempt_policy": "no_claim",
}

WORKFLOW_STATES = (
    "pending_registration",
    "frozen",
    "executed",
    "analyzed",
    "decided",
)
DESIGN_SNAPSHOT_SCHEMA_VERSION = "drupal_agent_readiness.improvement_design_snapshot.v1"
SAMPLE_SIZE_RATIONALE_SCHEMA_VERSION = (
    "drupal_agent_readiness.precision_feasibility_rationale.v2"
)
CALIBRATION_DECISION_SCHEMA_VERSION = (
    "drupal_agent_readiness.calibration_design_decision.v1"
)
CALIBRATION_DECISION_ARTIFACT_TYPE = "calibration_design_decision"
CALIBRATION_CLAIM_OPTIONS = ["strong_effect_gate", "revised_pooled_design"]
TRANSITION_SCHEMA_VERSION = "drupal_agent_readiness.improvement_transition.v1"
BOUND_RESULT_SCHEMA_VERSION = "drupal_agent_readiness.bound_experiment_result.v1"
BOUND_ANALYSIS_SCHEMA_VERSION = "drupal_agent_readiness.bound_experiment_analysis.v1"
BINDING_DECISION_SCHEMA_VERSION = "drupal_agent_readiness.binding_decision.v1"
SYNTHESIS_DECISION_SCHEMA_VERSION = "drupal_agent_readiness.synthesis_decision.v1"
PACKAGE_EVIDENCE_ROOT = "agent_readiness/evidence"
PRIORITIZATION_DIMENSIONS = (
    "occurrence",
    "consequence",
    "lifecycle_reach",
    "owner_site_reach",
    "delivery_effort",
    "strategic_fit",
)
PRIORITIZATION_STATES = (
    "unranked_insufficient_evidence",
    "unranked_owner_decision_pending",
    "ranked",
)
PRIORITIZATION_SCHEMA_VERSION = (
    "drupal_agent_readiness.improvement_prioritization.v1"
)
PRIORITIZATION_OWNER_DECISION_SCHEMA_VERSION = (
    "drupal_agent_readiness.improvement_prioritization_owner_decision.v1"
)
PRIORITIZATION_OWNER_DECISION_ARTIFACT_TYPE = (
    "improvement_prioritization_owner_decision"
)
PRIORITIZATION_CONTRACT = {
    "schema_version": PRIORITIZATION_SCHEMA_VERSION,
    "states": list(PRIORITIZATION_STATES),
    "dimensions": list(PRIORITIZATION_DIMENSIONS),
    "score_minimum": 1,
    "score_maximum": 5,
    "score_direction": "higher_is_more_priority",
    "delivery_effort_score_direction": "higher_means_lower_delivery_effort",
    "ranking_method": "owner_decision_without_automatic_composite",
    "rank_requires_complete_dimensions": True,
    "rank_requires_owner_decision_artifact": True,
    "owner_decision_schema_version": (
        PRIORITIZATION_OWNER_DECISION_SCHEMA_VERSION
    ),
}


class RegistryValidationError(ValueError):
    """Raised when a registry fails schema, evidence, or semantic validation."""


class SchemaValidationError(RegistryValidationError):
    """Raised when a registry violates the checked JSON Schema subset."""


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_default_registries(
    repo_root: Path = REPO_ROOT,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    method = repo_root / "method"
    return (
        load_json(method / "benchmark-coverage-v1.json"),
        load_json(method / "task-families-v1.json"),
        load_json(method / "improvement-registry-v1.json"),
    )


def validate_default_registries(repo_root: Path = REPO_ROOT) -> dict[str, int | bool]:
    coverage, tasks, improvements = load_default_registries(repo_root)
    validate_registries(coverage, tasks, improvements, repo_root=repo_root)
    return {
        "valid": True,
        "lifecycle_stages": len(coverage["lifecycle"]),
        "evidence_records": len(coverage["evidence_records"]),
        "published_claims": len(coverage["published_claims"]),
        "task_families": len(tasks["task_families"]),
        "improvement_records": len(improvements["records"]),
    }


def validate_registries(
    coverage: dict[str, Any],
    tasks: dict[str, Any],
    improvements: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
) -> None:
    schemas = {
        "coverage": load_json(
            repo_root / "method/schema/benchmark-coverage-v1.schema.json"
        ),
        "tasks": load_json(repo_root / "method/schema/task-families-v1.schema.json"),
        "improvements": load_json(
            repo_root / "method/schema/improvement-registry-v1.schema.json"
        ),
    }
    for name, instance in {
        "coverage": coverage,
        "tasks": tasks,
        "improvements": improvements,
    }.items():
        validate_schema_instance(instance, schemas[name])

    evidence = _validate_coverage(coverage, repo_root)
    lifecycle_targets = _validate_lifecycle_target_contracts(tasks)
    families = _validate_tasks(tasks, lifecycle_targets)
    _validate_target_links(coverage, families, lifecycle_targets)
    _validate_improvements(coverage, improvements, evidence, families, repo_root)


def validated_improvement_projections(
    coverage: dict[str, Any],
    tasks: dict[str, Any],
    improvements: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
) -> dict[str, dict[str, Any]]:
    """Return trusted per-experiment lifecycle bindings after one full audit.

    Publication consumers need the exact manifest/run/analysis/decision lineage,
    but should not duplicate the registry's semantic validator or re-audit the
    complete action product once for every published experiment. This function
    validates the registries exactly once, then exposes only artifacts whose
    hashes, canonical bytes, complete censuses, and cross-document semantics
    were accepted by that audit.
    """
    repo_root = repo_root.resolve()
    validate_registries(
        coverage,
        tasks,
        improvements,
        repo_root=repo_root,
    )
    projections: dict[str, dict[str, Any]] = {}
    for record in improvements["records"]:
        workflow = record["workflow"]
        state = record["workflow_state"]
        state_index = WORKFLOW_STATES.index(state)
        binding_plan = record["experiment_design"]["measurement_v1_binding_plan"]
        bindings = {
            binding["experiment_id"]: binding for binding in binding_plan["bindings"]
        }

        manifest_refs: dict[str, dict[str, Any]] = {}
        if state_index >= WORKFLOW_STATES.index("frozen"):
            manifest_refs = {
                reference["experiment_id"]: reference
                for reference in workflow["registration"]["manifest_refs"]
            }

        result_refs: dict[str, dict[str, Any]] = {}
        results: dict[str, dict[str, Any]] = {}
        if state_index >= WORKFLOW_STATES.index("executed"):
            result_refs = {
                reference["experiment_id"]: reference
                for reference in workflow["execution"]["run_artifact_refs"]
            }
            results = {
                experiment_id: _load_canonical_workflow_json(
                    _resolve_workflow_artifact(
                        repo_root,
                        reference,
                        "measurement_v1_result",
                        require_experiment=True,
                    ),
                    f"validated projection result {experiment_id}",
                )
                for experiment_id, reference in result_refs.items()
            }

        analysis_refs: dict[str, dict[str, Any]] = {}
        analyses: dict[str, dict[str, Any]] = {}
        if state_index >= WORKFLOW_STATES.index("analyzed"):
            analysis_refs = {
                reference["experiment_id"]: reference
                for reference in workflow["analysis"]["derived_metric_refs"]
            }
            analyses = {
                experiment_id: _load_canonical_workflow_json(
                    _resolve_workflow_artifact(
                        repo_root,
                        reference,
                        "measurement_v1_analysis",
                        require_experiment=True,
                    ),
                    f"validated projection analysis {experiment_id}",
                )
                for experiment_id, reference in analysis_refs.items()
            }

        binding_decision_refs: dict[str, dict[str, Any]] = {}
        binding_decisions: dict[str, dict[str, Any]] = {}
        synthesis_ref: dict[str, Any] | None = None
        synthesis: dict[str, Any] | None = None
        if state == "decided":
            for reference in workflow["decision"]["artifact_refs"]:
                if reference["artifact_type"] == "measurement_v1_binding_decision":
                    binding_decision_refs[reference["experiment_id"]] = reference
                elif reference["artifact_type"] == "improvement_synthesis_decision":
                    synthesis_ref = reference
            binding_decisions = {
                experiment_id: _load_canonical_workflow_json(
                    _resolve_workflow_artifact(
                        repo_root,
                        reference,
                        "measurement_v1_binding_decision",
                        require_experiment=True,
                    ),
                    f"validated projection binding decision {experiment_id}",
                )
                for experiment_id, reference in binding_decision_refs.items()
            }
            if synthesis_ref is not None:
                synthesis = _load_canonical_workflow_json(
                    _resolve_workflow_artifact(
                        repo_root,
                        synthesis_ref,
                        "improvement_synthesis_decision",
                        require_experiment=False,
                    ),
                    "validated projection synthesis decision",
                )

        for experiment_id, binding in bindings.items():
            result = results.get(experiment_id)
            projections[experiment_id] = {
                "registry_id": improvements["registry_id"],
                "registry_version": improvements["schema_version"],
                "coverage_claim_id": record["failure"]["claim_id"],
                "task_family_id": record["task_family_id"],
                "improvement_record_id": record["id"],
                "workflow_state": state,
                "decision_outcome": workflow["decision"]["outcome"],
                "binding": binding,
                "manifest_artifact_ref": manifest_refs.get(experiment_id),
                "result_artifact_ref": result_refs.get(experiment_id),
                "run_artifact_refs": (
                    result["run_artifact_refs"] if result is not None else []
                ),
                "analysis_artifact_ref": analysis_refs.get(experiment_id),
                "analysis": analyses.get(experiment_id),
                "binding_decision_artifact_ref": binding_decision_refs.get(
                    experiment_id
                ),
                "binding_decision": binding_decisions.get(experiment_id),
                "synthesis_artifact_ref": synthesis_ref,
                "synthesis": synthesis,
            }
    return projections


def validate_schema_instance(instance: Any, schema: dict[str, Any]) -> None:
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise SchemaValidationError(
            "registry schema must declare JSON Schema draft 2020-12"
        )
    _validate_schema_node(instance, schema, schema, "$")


def resolve_hashed_artifact(
    repo_root: Path,
    reference: dict[str, Any],
    *,
    allowed_roots: Iterable[str],
) -> Path:
    raw_path = reference["path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise RegistryValidationError("artifact path must be a non-empty POSIX path")
    if "\\" in raw_path:
        raise RegistryValidationError(
            f"artifact path uses a non-POSIX separator: {raw_path}"
        )
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise RegistryValidationError(
            f"artifact path escapes the repository: {raw_path}"
        )
    if not any(
        pure == PurePosixPath(root) or PurePosixPath(root) in pure.parents
        for root in allowed_roots
    ):
        raise RegistryValidationError(
            f"artifact path is outside allowed evidence roots: {raw_path}"
        )

    root = repo_root.resolve(strict=True)
    candidate = root
    for part in pure.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise RegistryValidationError(
                f"artifact path contains a symlink: {raw_path}"
            )
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RegistryValidationError(f"artifact does not exist: {raw_path}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RegistryValidationError(
            f"artifact resolves outside repository: {raw_path}"
        ) from exc
    if not resolved.is_file():
        raise RegistryValidationError(f"artifact is not a regular file: {raw_path}")

    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if digest != reference["sha256"]:
        raise RegistryValidationError(
            f"artifact hash mismatch for {raw_path}: expected {reference['sha256']}, got {digest}"
        )
    return resolved


def _validate_coverage(
    coverage: dict[str, Any], repo_root: Path
) -> dict[str, dict[str, Any]]:
    evidence = _index_unique(coverage["evidence_records"], "id", "evidence record")
    resolved_evidence: dict[str, Path] = {}
    for evidence_id, record in evidence.items():
        if not record["current_observation"] or record["target_method"]:
            raise RegistryValidationError(
                f"current evidence {evidence_id} is marked as target methodology"
            )
        resolved_evidence[evidence_id] = resolve_hashed_artifact(
            repo_root,
            record,
            allowed_roots=("evidence/runs", "evidence/experiments"),
        )
    for evidence_id, record in evidence.items():
        _validate_evidence_payload(
            evidence_id,
            record,
            resolved_evidence[evidence_id],
            evidence,
            resolved_evidence,
            repo_root,
        )
    _validate_alias_evidence_coherence(evidence, resolved_evidence)

    stages = _index_unique(coverage["lifecycle"], "id", "lifecycle stage")
    if (
        set(stages) != LIFECYCLE
        or [stage["id"] for stage in coverage["lifecycle"]]
        != list(LIFECYCLE_ORDER)
    ):
        raise RegistryValidationError("coverage must contain the exact lifecycle spine")
    expected_status = {
        "choose_onboard": "not_covered",
        "connect": "not_covered",
        "understand": "constrained",
        "plan_clarify": "not_covered",
        "act": "constrained",
        "verify": "constrained",
        "recover": "constrained",
        "handoff": "not_covered",
    }
    for stage_id, stage in stages.items():
        if stage["current_status"] != expected_status[stage_id]:
            raise RegistryValidationError(
                f"coverage v1 current status drifted for {stage_id}"
            )
        evidence_ids = stage["current_evidence_ids"]
        if stage["current_status"] == "not_covered" and evidence_ids:
            raise RegistryValidationError(
                f"uncovered lifecycle stage {stage_id} has current evidence"
            )
        if stage["current_status"] != "not_covered" and not evidence_ids:
            raise RegistryValidationError(
                f"covered lifecycle stage {stage_id} has no current evidence"
            )
        for evidence_id in evidence_ids:
            if evidence_id not in evidence:
                raise RegistryValidationError(
                    f"lifecycle stage {stage_id} references unknown evidence {evidence_id}"
                )
            if stage_id not in evidence[evidence_id]["lifecycle_stages"]:
                raise RegistryValidationError(
                    f"evidence {evidence_id} is not typed for lifecycle stage {stage_id}"
                )

    claims = _index_unique(coverage["published_claims"], "id", "published claim")
    for claim_id, claim in claims.items():
        if (
            claim["evidence_lane"] != "historical_frontier_observation"
            or claim["claim_grade"]
            or claim["causal_attribution"]
        ):
            raise RegistryValidationError(
                f"current claim {claim_id} overstates historical frontier evidence"
            )
        scope = claim["scope"]
        if (
            scope["output_level"] != "task_metric"
            or scope["analysis_unit"] != "run"
            or scope["aggregation"] != "within_task_only"
            or scope["cross_task_inference"]
            or scope["readiness_output"]
        ):
            raise RegistryValidationError(f"claim {claim_id} has aggregate scope")
        if claim["task_id"] != scope["task_id"]:
            raise RegistryValidationError(
                f"claim {claim_id} task scope is inconsistent"
            )
        if claim["observed_outcome"]["metric_id"] not in scope["metric_ids"]:
            raise RegistryValidationError(
                f"claim {claim_id} metric scope is inconsistent"
            )
        evidence_roles: set[str] = set()
        for evidence_id in claim["evidence_ids"]:
            if evidence_id not in evidence:
                raise RegistryValidationError(
                    f"claim {claim_id} references unknown evidence {evidence_id}"
                )
            record = evidence[evidence_id]
            if record["task_id"] != claim["task_id"]:
                raise RegistryValidationError(
                    f"claim {claim_id} uses evidence from task {record['task_id']}"
                )
            if not set(scope["metric_ids"]).issubset(set(record["metric_ids"])):
                raise RegistryValidationError(
                    f"claim {claim_id} uses evidence without its metric semantics"
                )
            evidence_roles.add(record["evidence_role"])
        required_roles = {"raw_runs", "mechanical_ground_truth", "derived_metrics"}
        if claim[
            "claim_type"
        ] == "bounded_observed_difference" and not required_roles.issubset(
            evidence_roles
        ):
            raise RegistryValidationError(
                f"bounded comparison {claim_id} lacks raw, ground-truth, or derived evidence"
            )
        for stage_id in claim["lifecycle_stages"]:
            if stages[stage_id]["current_status"] == "not_covered":
                raise RegistryValidationError(
                    f"claim {claim_id} names uncovered lifecycle stage {stage_id}"
                )
            if not set(claim["evidence_ids"]).issubset(
                set(stages[stage_id]["current_evidence_ids"])
            ):
                raise RegistryValidationError(
                    f"claim {claim_id} evidence is not registered for {stage_id}"
                )
    return evidence


def _validate_evidence_payload(
    evidence_id: str,
    record: dict[str, Any],
    path: Path,
    evidence: dict[str, dict[str, Any]],
    resolved_evidence: dict[str, Path],
    repo_root: Path,
) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryValidationError(
            f"evidence {evidence_id} is not valid JSON bytes"
        ) from exc
    binding = record["semantic_binding"]
    binding_contract = {
        "embedded_task_id": ("run_result", "run"),
        "companion_run_result": ("evaluator_output", "run"),
        "legacy_recomputed_run": ("recomputed_run_result", "run"),
        "alias_raw_runs": ("raw_runs", "experiment_run_set"),
        "alias_ground_truth": ("mechanical_ground_truth", "candidate_path"),
        "alias_derived_metrics": ("derived_metrics", "experiment_run_set"),
    }
    expected_role, expected_unit = binding_contract[binding]
    if (
        record["evidence_role"] != expected_role
        or record["claim_unit"] != expected_unit
    ):
        raise RegistryValidationError(
            f"evidence {evidence_id} role or claim unit conflicts with its byte binding"
        )

    if binding == "embedded_task_id":
        if not isinstance(payload, dict) or payload.get("task_id") != record["task_id"]:
            raise RegistryValidationError(
                f"evidence {evidence_id} bytes do not embed task {record['task_id']}"
            )
        if not isinstance(payload.get("run_id"), str) or not isinstance(
            payload.get("evaluator"), dict
        ):
            raise RegistryValidationError(
                f"evidence {evidence_id} is not a typed run-result payload"
            )
        return

    if binding == "legacy_recomputed_run":
        _validate_legacy_run_bundle(evidence_id, record, payload, path, repo_root)
        return

    if binding == "companion_run_result":
        companion_id = record["companion_evidence_id"]
        if companion_id not in evidence:
            raise RegistryValidationError(
                f"evidence {evidence_id} references missing companion {companion_id}"
            )
        companion = evidence[companion_id]
        if (
            companion["semantic_binding"] != "embedded_task_id"
            or companion["task_id"] != record["task_id"]
            or resolved_evidence[companion_id].parent != path.parent
        ):
            raise RegistryValidationError(
                f"evidence {evidence_id} companion does not bind the same run and task"
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("passed"), bool):
            raise RegistryValidationError(
                f"evidence {evidence_id} is not an evaluator output"
            )
        return

    if record["task_id"] != "assess.alias_safety" or record["metric_ids"] != [
        "hidden_claim_false_safe_rate"
    ]:
        raise RegistryValidationError(
            f"alias evidence {evidence_id} has inconsistent task or metric semantics"
        )
    if binding == "alias_raw_runs":
        runs = (
            payload.get("result", {}).get("blind")
            if isinstance(payload, dict)
            else None
        )
        if not isinstance(runs, list) or not runs:
            raise RegistryValidationError(
                f"evidence {evidence_id} lacks raw alias runs"
            )
        candidate_sets: set[tuple[str, ...]] = set()
        for run in runs:
            assessments = run.get("answer", {}).get("assessments")
            if (
                run.get("arm") not in {"raw", "equipped"}
                or not isinstance(run.get("model"), str)
                or not isinstance(assessments, dict)
                or not assessments
                or any(
                    not isinstance(item.get("safe"), bool)
                    for item in assessments.values()
                )
            ):
                raise RegistryValidationError(
                    f"evidence {evidence_id} contains an untyped alias run"
                )
            candidate_sets.add(tuple(sorted(assessments)))
        if len(candidate_sets) != 1:
            raise RegistryValidationError(
                f"evidence {evidence_id} raw runs use inconsistent candidate units"
            )
        return
    if binding == "alias_ground_truth":
        if (
            not isinstance(payload, dict)
            or not payload
            or any(
                not isinstance(candidate, str)
                or not candidate.startswith("/")
                or not isinstance(item, dict)
                or not isinstance(item.get("safe"), bool)
                or "blocker_kind" not in item
                for candidate, item in payload.items()
            )
        ):
            raise RegistryValidationError(
                f"evidence {evidence_id} is not mechanical alias ground truth"
            )
        return
    if binding == "alias_derived_metrics":
        cells = payload.get("cells") if isinstance(payload, dict) else None
        summary = payload.get("summary") if isinstance(payload, dict) else None
        if not isinstance(cells, dict) or not cells or not isinstance(summary, dict):
            raise RegistryValidationError(
                f"evidence {evidence_id} lacks cell-level alias metrics"
            )
        for cell in cells.values():
            runs = cell.get("runs") if isinstance(cell, dict) else None
            if not isinstance(runs, list) or not runs:
                raise RegistryValidationError(
                    f"evidence {evidence_id} has an empty derived-metric cell"
                )
            for run in runs:
                if (
                    not isinstance(run.get("run_id"), str)
                    or run.get("arm") not in {"raw", "equipped"}
                    or not isinstance(run.get("latent_total"), int)
                    or not isinstance(run.get("latent_correct"), int)
                ):
                    raise RegistryValidationError(
                        f"evidence {evidence_id} has an untyped run-level metric"
                    )
        return
    raise RegistryValidationError(f"unsupported evidence binding {binding}")


def _validate_legacy_run_bundle(
    evidence_id: str,
    record: dict[str, Any],
    run_result: dict[str, Any],
    run_result_path: Path,
    repo_root: Path,
) -> None:
    evaluators = {
        "inventory.read_only": (
            evaluate_inventory,
            "agent_readiness/evaluators/inventory.py",
            ["inventory_mechanical_pass"],
        ),
        "act.event_jsonapi": (
            evaluate_event,
            "agent_readiness/evaluators/event.py",
            ["event_mechanical_pass", "event_blast_radius_pass"],
        ),
        "recover.event_jsonapi": (
            evaluate_recovery,
            "agent_readiness/evaluators/recovery.py",
            ["recovery_mechanical_pass", "recovery_blast_radius_pass"],
        ),
    }
    if record["task_id"] not in evaluators:
        raise RegistryValidationError(
            f"legacy evidence {evidence_id} has no production evaluator binding"
        )
    evaluator, evaluator_source, metric_ids = evaluators[record["task_id"]]
    if (
        record["evidence_class"] != "constrained_legacy_run_bundle"
        or set(record["legacy_limitations"])
        != {
            "evaluator_version_not_registered_at_run_time",
            "agent_stack_pins_incomplete",
        }
        or record["metric_ids"] != metric_ids
    ):
        raise RegistryValidationError(
            f"legacy evidence {evidence_id} overstates its class or metric binding"
        )
    companion_paths: dict[str, Path] = {}
    for role, reference in record["companions"].items():
        allowed_roots = (
            ("agent_readiness/evaluators",)
            if role == "evaluator_source"
            else ("evidence/runs",)
        )
        companion_paths[role] = resolve_hashed_artifact(
            repo_root,
            reference,
            allowed_roots=allowed_roots,
        )
    if record["companions"]["evaluator_source"]["path"] != evaluator_source:
        raise RegistryValidationError(
            f"legacy evidence {evidence_id} points at the wrong evaluator source"
        )
    loaded_source = Path(inspect.getsourcefile(evaluator) or "")
    if (
        not loaded_source.is_file()
        or hashlib.sha256(loaded_source.read_bytes()).hexdigest()
        != record["companions"]["evaluator_source"]["sha256"]
    ):
        raise RegistryValidationError(
            f"legacy evidence {evidence_id} evaluator source hash does not match loaded production code"
        )
    if any(
        companion_paths[role].parent != run_result_path.parent
        for role in ("answer", "state", "evaluator")
    ):
        raise RegistryValidationError(
            f"legacy evidence {evidence_id} companions are not from the same run"
        )
    if run_result.get("task_id") != record["task_id"] or not isinstance(
        run_result.get("run_id"), str
    ):
        raise RegistryValidationError(
            f"legacy evidence {evidence_id} run result does not bind its task"
        )
    for artifact_key, role in (
        ("answer_json", "answer"),
        ("state_json", "state"),
        ("evaluator_json", "evaluator"),
    ):
        declared = run_result.get("artifacts", {}).get(artifact_key)
        actual = record["companions"][role]["path"].removeprefix("evidence/")
        if declared != actual:
            raise RegistryValidationError(
                f"legacy evidence {evidence_id} run result does not reference {role} bytes"
            )
    try:
        state = json.loads(companion_paths["state"].read_text(encoding="utf-8"))
        answer = json.loads(companion_paths["answer"].read_text(encoding="utf-8"))
        retained_evaluator = json.loads(
            companion_paths["evaluator"].read_text(encoding="utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryValidationError(
            f"legacy evidence {evidence_id} has a non-JSON companion"
        ) from exc
    recomputed = evaluator(state, answer).to_dict()
    if retained_evaluator != recomputed:
        raise RegistryValidationError(
            f"legacy evidence {evidence_id} retained evaluator differs from recomputation"
        )
    embedded = run_result.get("evaluator")
    embedded_projection = {
        key: recomputed[key] for key in ("passed", "failures", "warnings")
    }
    if embedded != embedded_projection:
        raise RegistryValidationError(
            f"legacy evidence {evidence_id} embedded evaluator differs from recomputation"
        )


def _validate_alias_evidence_coherence(
    evidence: dict[str, dict[str, Any]], resolved_evidence: dict[str, Path]
) -> None:
    alias_records = [
        (evidence_id, record)
        for evidence_id, record in evidence.items()
        if record["task_id"] == "assess.alias_safety"
    ]
    by_binding = {
        record["semantic_binding"]: evidence_id for evidence_id, record in alias_records
    }
    required = {"alias_raw_runs", "alias_ground_truth", "alias_derived_metrics"}
    if len(alias_records) != 3 or set(by_binding) != required:
        raise RegistryValidationError(
            "alias evidence must contain one raw, ground-truth, and derived artifact"
        )
    raw = json.loads(resolved_evidence[by_binding["alias_raw_runs"]].read_text())
    ground = json.loads(resolved_evidence[by_binding["alias_ground_truth"]].read_text())
    derived = json.loads(
        resolved_evidence[by_binding["alias_derived_metrics"]].read_text()
    )
    try:
        validate_retained_alias_safety_results(raw, ground, derived)
    except AliasSafetyMetricError as exc:
        raise RegistryValidationError(
            f"alias derived metrics do not independently recompute: {exc}"
        ) from exc


def _validate_lifecycle_target_contracts(
    tasks: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    contracts = _index_unique(
        tasks["lifecycle_target_contracts"],
        "lifecycle_stage",
        "lifecycle target contract",
    )
    if set(contracts) != set(LIFECYCLE_TARGET_METRICS):
        raise RegistryValidationError(
            "task registry must contain the exact unexecuted plan and handoff targets"
        )

    for stage_id, contract in contracts.items():
        if (
            contract["measurement_state"] != "target_not_executed"
            or contract["private_reasoning_required"]
            or set(contract["task_family_ids"]) != TASK_FAMILIES
        ):
            raise RegistryValidationError(
                f"{stage_id} target is presented as evidence or lacks full task-family scope"
            )

        if stage_id == "plan_clarify":
            if contract.get("decision_options") != [
                "proceed",
                "ask",
                "refuse",
                "escalate",
            ] or "continuation_context_policy" in contract:
                raise RegistryValidationError(
                    "plan_clarify must freeze proceed/ask/refuse/escalate outcomes"
                )
        elif (
            contract.get("continuation_context_policy")
            != "registered_task_and_handoff_artifact_only"
            or "decision_options" in contract
        ):
            raise RegistryValidationError(
                "handoff must use a cold second agent without out-of-band context"
            )

        artifact = contract["artifact_contract"]
        expected_artifact = LIFECYCLE_TARGET_ARTIFACT_CONTRACTS[stage_id]
        fields = _index_unique(
            artifact["fields"],
            "name",
            f"{stage_id} target artifact field",
        )
        observed_fields = {
            name: (field["type"], tuple(field.get("allowed_values", [])))
            for name, field in fields.items()
        }
        if (
            artifact["schema_version"] != expected_artifact["schema_version"]
            or artifact["canonical_json_required"]
            != expected_artifact["canonical_json_required"]
            or artifact["sha256_bound_by_receipt"]
            != expected_artifact["sha256_bound_by_receipt"]
            or observed_fields != expected_artifact["fields"]
        ):
            raise RegistryValidationError(
                f"{stage_id} structured artifact contract drifted"
            )

        receipts = _index_unique(
            contract["receipt_requirements"],
            "id",
            f"{stage_id} target receipt",
        )
        expected_receipts = LIFECYCLE_TARGET_RECEIPTS[stage_id]
        if set(receipts) != set(expected_receipts):
            raise RegistryValidationError(f"{stage_id} target receipt set drifted")
        for receipt_id, expected in expected_receipts.items():
            receipt = receipts[receipt_id]
            observed = {
                "receipt_type": receipt["receipt_type"],
                "event_id": receipt["event_id"],
                "minimum_count": receipt["minimum_count"],
                "required_attributes": set(receipt["required_attributes"]),
                "success_predicate": receipt["success_predicate"],
            }
            if observed != expected or receipt["source"] != "harness_event_log":
                raise RegistryValidationError(
                    f"{stage_id} receipt {receipt_id} is not mechanically observable"
                )
            if not RECEIPT_REQUIRED_ATTRIBUTES[receipt["receipt_type"]].issubset(
                set(receipt["required_attributes"])
            ):
                raise RegistryValidationError(
                    f"{stage_id} receipt {receipt_id} lacks observable attributes"
                )

        metrics = _index_unique(
            contract["metric_contracts"],
            "id",
            f"{stage_id} target metric",
        )
        expected_metrics = LIFECYCLE_TARGET_METRIC_CONTRACTS[stage_id]
        if set(metrics) != LIFECYCLE_TARGET_METRICS[stage_id]:
            raise RegistryValidationError(f"{stage_id} target metric set drifted")
        for metric_id, expected in expected_metrics.items():
            metric = metrics[metric_id]
            observed = (
                metric["analysis_unit"],
                metric["numerator_predicate"],
                metric["denominator_predicate"],
                set(metric["required_receipt_ids"]),
            )
            if (
                observed != expected
                or metric["evidence_source"]
                != "independent_evaluator_over_retained_receipts"
                or metric["zero_denominator"] != "invalid_run"
            ):
                raise RegistryValidationError(
                    f"{stage_id} metric {metric_id} is not mechanically derived"
                )
            if not set(metric["required_receipt_ids"]).issubset(receipts):
                raise RegistryValidationError(
                    f"{stage_id} metric {metric_id} names an unknown receipt"
                )
    return contracts


def _validate_tasks(
    tasks: dict[str, Any],
    lifecycle_targets: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    families = _index_unique(tasks["task_families"], "id", "task family")
    if set(families) != TASK_FAMILIES:
        raise RegistryValidationError(
            "the three required task families must appear exactly once"
        )

    for family_id, family in families.items():
        if family["measurement_state"] != "target_not_executed":
            raise RegistryValidationError(
                f"target task family {family_id} is presented as executed evidence"
            )
        stages = set(family["lifecycle_stages"])
        if not stages.issubset(LIFECYCLE):
            raise RegistryValidationError(f"{family_id} has an unknown lifecycle stage")
        stage_positions = [
            LIFECYCLE_ORDER.index(stage_id)
            for stage_id in family["lifecycle_stages"]
        ]
        if stage_positions != sorted(stage_positions):
            raise RegistryValidationError(
                f"{family_id} lifecycle stages are not in canonical order"
            )

        constraints = _index_unique(
            family["constraints"], "id", f"{family_id} constraint"
        )
        for constraint in constraints.values():
            authority = constraint["authority"]
            expected = AUTHORITY_CONTRACT[authority["class"]]
            for key, value in expected.items():
                if authority[key] != value:
                    raise RegistryValidationError(
                        f"{family_id} authority {authority['class']} cannot be certified as {authority['certifier_class']}"
                    )
            if (
                constraint["id"] in EVALUATOR_ONLY_CONSTRAINTS
                and authority["visibility"] != "evaluator_only"
            ):
                raise RegistryValidationError(
                    f"{family_id} hidden mechanical truth {constraint['id']} leaked to the agent"
                )
            attestation = authority["attestation"]
            if not all(
                (
                    attestation["required_before_registration"],
                    attestation["versioned"],
                    attestation["sha256_required"],
                )
            ):
                raise RegistryValidationError(
                    f"{family_id} constraint {constraint['id']} lacks versioned attestation"
                )

        mechanical = _index_unique(
            family["mechanical_outcomes"], "id", f"{family_id} mechanical outcome"
        )
        if set(mechanical) != set(MECHANICAL_OUTCOME_CONTRACT[family_id]):
            raise RegistryValidationError(f"{family_id} mechanical outcome set drifted")
        for outcome_id, outcome in mechanical.items():
            observed = (
                outcome["oracle"],
                outcome["target_surface"],
                outcome["pass_predicate"],
            )
            if observed != MECHANICAL_OUTCOME_CONTRACT[family_id][outcome_id]:
                raise RegistryValidationError(
                    f"{family_id} mechanical outcome {outcome_id} is not bound to its oracle"
                )
        behavior = _index_unique(
            family["behavior_outcomes"], "id", f"{family_id} behavior outcome"
        )
        behavior_stages = {item["lifecycle_stage"] for item in behavior.values()}
        shared_target_stages = {
            stage_id
            for stage_id, contract in lifecycle_targets.items()
            if family_id in contract["task_family_ids"]
        }
        if behavior_stages & shared_target_stages:
            raise RegistryValidationError(
                f"{family_id} duplicates a shared lifecycle target contract"
            )
        if behavior_stages | shared_target_stages != stages:
            raise RegistryValidationError(
                f"{family_id} must collect observable receipts in every named lifecycle stage"
            )
        for outcome in behavior.values():
            if (
                outcome["private_reasoning_required"]
                or not outcome["receipt_requirements"]
            ):
                raise RegistryValidationError(
                    f"{family_id} behavior outcome {outcome['id']} is not receipt-based"
                )
            _index_unique(
                outcome["receipt_requirements"],
                "id",
                f"{family_id} behavior receipt",
            )
            for receipt in outcome["receipt_requirements"]:
                if not RECEIPT_REQUIRED_ATTRIBUTES[receipt["receipt_type"]].issubset(
                    set(receipt["required_attributes"])
                ):
                    raise RegistryValidationError(
                        f"{family_id} receipt {receipt['id']} lacks observable attributes"
                    )

        if set(family["cost"]["metrics"]) != COST_METRICS:
            raise RegistryValidationError(f"{family_id} cost contract is incomplete")

        substrate_plan = family["substrate_plan"]
        substrates = _index_unique(
            substrate_plan["substrates"], "id", f"{family_id} substrate"
        )
        if set(substrates) != SUBSTRATES:
            raise RegistryValidationError(
                f"{family_id} must define clean and messy owner-described substrates"
            )
        if substrates["clean"]["inject_inventory"]:
            raise RegistryValidationError(
                f"{family_id} clean substrate contains injections"
            )
        if not substrates["clean"]["clean_invariants"]:
            raise RegistryValidationError(
                f"{family_id} clean substrate lacks invariants"
            )
        _index_unique(
            substrates["clean"]["clean_invariants"],
            "id",
            f"{family_id} clean invariant",
        )
        clean_invariants = {
            item["id"]: (item["surface"], item["expected_semantic_state"])
            for item in substrates["clean"]["clean_invariants"]
        }
        if clean_invariants != EXPECTED_CLEAN_INVARIANTS[family_id]:
            raise RegistryValidationError(
                f"{family_id} clean invariants are not the registered semantic baseline"
            )
        if len(substrates["messy_owner_described"]["inject_inventory"]) < 2:
            raise RegistryValidationError(
                f"{family_id} messy substrate lacks inject inventory"
            )
        _index_unique(
            substrates["messy_owner_described"]["inject_inventory"],
            "id",
            f"{family_id} messy inject",
        )
        for substrate in substrates.values():
            manifest = substrate["manifest_contract"]
            reset = substrate["reset_proof_contract"]
            if not all(
                (
                    manifest["required_before_registration"],
                    manifest["sha256_required"],
                    reset["required_before_registration"],
                    reset["before_hash_required"],
                    reset["after_hash_required"],
                )
            ):
                raise RegistryValidationError(
                    f"{family_id} substrate {substrate['id']} is not executable before registration"
                )
            expected_sections = (
                {
                    "platform_versions",
                    "starting_state",
                    "clean_invariants",
                    "volatile_surface_allowlist",
                }
                if substrate["kind"] == "clean"
                else {
                    "platform_versions",
                    "starting_state",
                    "inject_inventory",
                    "owner_attestations",
                    "volatile_surface_allowlist",
                }
            )
            if set(manifest["required_sections"]) != expected_sections:
                raise RegistryValidationError(
                    f"{family_id} substrate {substrate['id']} manifest sections drifted"
                )

        faults = _index_unique(
            substrate_plan["fault_catalog"], "id", f"{family_id} fault"
        )
        observed_faults = {
            fault_id: (
                fault["kind"],
                fault["target_surface"],
                fault["restore_oracle_id"],
            )
            for fault_id, fault in faults.items()
        }
        if observed_faults != EXPECTED_FAULTS[family_id]:
            raise RegistryValidationError(f"{family_id} fault contract drifted")
        if any(
            fault["restore_oracle_id"] not in mechanical for fault in faults.values()
        ):
            raise RegistryValidationError(f"{family_id} fault has no restore oracle")
        cases = _index_unique(
            substrate_plan["case_matrix"], "id", f"{family_id} fault case"
        )
        expected_cases = {
            (substrate, fault_mode)
            for substrate in SUBSTRATES
            for fault_mode in {"no_fault", "fault"}
        }
        actual_cases = {
            (case["substrate_id"], case["fault_mode"]) for case in cases.values()
        }
        if actual_cases != expected_cases:
            raise RegistryValidationError(
                f"{family_id} must cross clean/messy with no-fault/fault cases"
            )
        for case in cases.values():
            if case["fault_mode"] == "fault" and case["fault_id"] not in faults:
                raise RegistryValidationError(
                    f"{family_id} case {case['id']} references unknown fault"
                )
            if case["fault_mode"] == "no_fault" and case["fault_id"] != "none":
                raise RegistryValidationError(
                    f"{family_id} no-fault case {case['id']} has a fault"
                )
        recovery = family["recovery_contract"]
        if not set(recovery["fault_ids"]).issubset(set(faults)):
            raise RegistryValidationError(
                f"{family_id} recovery references unknown faults"
            )
        if not set(recovery["restore_outcome_ids"]).issubset(set(mechanical)):
            raise RegistryValidationError(
                f"{family_id} recovery references unknown outcomes"
            )

        blast = family["semantic_blast_radius"]
        _require_unique_values(blast["surfaces"], f"{family_id} blast-radius surface")
        _require_unique_values(
            blast["volatile_surface_allowlist"], f"{family_id} volatile surface"
        )
        if (
            blast["byte_stability_required"]
            or blast["comparison"] != "normalized_semantic_snapshot"
        ):
            raise RegistryValidationError(
                f"{family_id} blast radius uses volatile byte stability"
            )

        proof = family["proof_contract"]
        expected_target_metrics = set().union(
            *(
                LIFECYCLE_TARGET_METRICS[stage_id]
                for stage_id in shared_target_stages
            )
        )
        if (
            proof["output_level"] != "task_run"
            or proof["task_family_id"] != family_id
            or proof["cross_task_aggregation"]
            or proof["readiness_output"]
            or proof["generalization"] != "none"
            or not set(proof["outcome_ids"]).issubset(set(mechanical))
            or set(proof["target_metric_ids"]) != expected_target_metrics
        ):
            raise RegistryValidationError(f"{family_id} proof contract is overbroad")

        fixed = family["fixed_regression_lane"]
        variants = _index_unique(fixed["variants"], "id", f"{family_id} fixed variant")
        expected_variants = {
            (substrate, role)
            for substrate in SUBSTRATES
            for role in {"control", "candidate"}
        }
        if {
            (variant["substrate_id"], variant["intervention_role"])
            for variant in variants.values()
        } != expected_variants:
            raise RegistryValidationError(f"{family_id} fixed matrix is incomplete")
        if set(fixed["pin_requirements"]) != FIXED_PINS:
            raise RegistryValidationError(f"{family_id} fixed lane is not fully pinned")
        _validate_comparison_scope(fixed["comparison_scope"], family_id)

        frontier = family["frontier_lane"]
        frontier_variants = _index_unique(
            frontier["variants"], "id", f"{family_id} frontier variant"
        )
        if {
            variant["substrate_id"] for variant in frontier_variants.values()
        } != SUBSTRATES:
            raise RegistryValidationError(f"{family_id} frontier matrix is incomplete")
        _validate_comparison_scope(frontier["reporting_scope"], family_id)
    return families


def _validate_target_links(
    coverage: dict[str, Any],
    families: dict[str, dict[str, Any]],
    lifecycle_targets: dict[str, dict[str, Any]],
) -> None:
    for stage in coverage["lifecycle"]:
        for family_id in stage["target_task_family_ids"]:
            if family_id not in families:
                raise RegistryValidationError(
                    f"{stage['id']} targets unknown task family {family_id}"
                )
            if stage["id"] not in families[family_id]["lifecycle_stages"]:
                raise RegistryValidationError(
                    f"{stage['id']} is not exercised by target family {family_id}"
                )
        if stage["id"] in lifecycle_targets:
            contract = lifecycle_targets[stage["id"]]
            if set(stage["target_task_family_ids"]) != set(
                contract["task_family_ids"]
            ) or set(stage["target"].get("required_metric_ids", [])) != set(
                LIFECYCLE_TARGET_METRICS[stage["id"]]
            ):
                raise RegistryValidationError(
                    f"{stage['id']} coverage does not bind its executable target metrics"
                )
        elif "required_metric_ids" in stage["target"]:
            raise RegistryValidationError(
                f"{stage['id']} cannot claim the unexecuted lifecycle target metrics"
            )


def _prioritization_snapshot(prioritization: dict[str, Any]) -> dict[str, Any]:
    """Return the decision-bound prioritization fields without its own reference."""

    return {
        "state": prioritization["state"],
        "dimensions": {
            dimension: prioritization[dimension]
            for dimension in PRIORITIZATION_DIMENSIONS
        },
        "evidence_ids": prioritization["evidence_ids"],
        "rank": prioritization["rank"],
    }


def _prioritization_snapshot_sha256(prioritization: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_workflow_json_bytes(_prioritization_snapshot(prioritization))
    ).hexdigest()


def _validate_prioritization(
    record: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    owners: dict[str, dict[str, Any]],
    repo_root: Path,
) -> int | None:
    """Validate an improvement's evidence-backed, owner-decided priority state."""

    prioritization = record["prioritization"]
    record_id = record["id"]
    complete_dimensions: list[str] = []
    dimension_evidence: set[str] = set()
    for dimension in PRIORITIZATION_DIMENSIONS:
        value = prioritization[dimension]
        evidence_ids = value["evidence_ids"]
        if evidence_ids != sorted(evidence_ids):
            raise RegistryValidationError(
                f"improvement {record_id} prioritization {dimension} evidence is not sorted"
            )
        unknown_evidence = sorted(set(evidence_ids) - set(evidence))
        if unknown_evidence:
            raise RegistryValidationError(
                f"improvement {record_id} prioritization {dimension} references "
                f"unknown evidence {unknown_evidence}"
            )
        if value["status"] == "insufficient_evidence":
            if value["score"] is not None or evidence_ids:
                raise RegistryValidationError(
                    f"improvement {record_id} prioritization {dimension} must remain "
                    "unscored without evidence"
                )
            continue
        score = value["score"]
        if (
            not isinstance(score, int)
            or isinstance(score, bool)
            or not 1 <= score <= 5
            or not evidence_ids
        ):
            raise RegistryValidationError(
                f"improvement {record_id} prioritization {dimension} is not "
                "evidence-complete with a 1-5 score"
            )
        complete_dimensions.append(dimension)
        dimension_evidence.update(evidence_ids)

    expected_evidence_ids = sorted(dimension_evidence)
    if prioritization["evidence_ids"] != expected_evidence_ids:
        raise RegistryValidationError(
            f"improvement {record_id} prioritization evidence_ids must be the "
            "sorted union of dimension evidence"
        )

    state = prioritization["state"]
    all_dimensions_complete = len(complete_dimensions) == len(
        PRIORITIZATION_DIMENSIONS
    )
    decision_ref = prioritization["owner_decision_artifact"]
    rank = prioritization["rank"]
    if state == "unranked_insufficient_evidence":
        if all_dimensions_complete:
            raise RegistryValidationError(
                f"improvement {record_id} cannot claim insufficient prioritization "
                "evidence when every dimension is complete"
            )
        if decision_ref is not None or rank is not None:
            raise RegistryValidationError(
                f"improvement {record_id} cannot rank before evidence is complete"
            )
        return None
    if state == "unranked_owner_decision_pending":
        if not all_dimensions_complete:
            raise RegistryValidationError(
                f"improvement {record_id} cannot await an owner decision until every "
                "prioritization dimension is complete"
            )
        if decision_ref is not None or rank is not None:
            raise RegistryValidationError(
                f"improvement {record_id} owner-decision-pending state cannot carry a rank"
            )
        return None
    if state != "ranked":
        raise RegistryValidationError(
            f"improvement {record_id} has unknown prioritization state {state}"
        )
    if not all_dimensions_complete:
        missing = sorted(set(PRIORITIZATION_DIMENSIONS) - set(complete_dimensions))
        raise RegistryValidationError(
            f"improvement {record_id} cannot rank without complete prioritization "
            f"dimensions: {missing}"
        )
    if (
        not isinstance(rank, int)
        or isinstance(rank, bool)
        or rank < 1
        or not isinstance(decision_ref, dict)
    ):
        raise RegistryValidationError(
            f"improvement {record_id} rank requires a positive integer and owner decision"
        )

    expected_ref_id = f"{record_id}-prioritization-owner-decision-v1"
    expected_ref_path = (
        f"{PACKAGE_EVIDENCE_ROOT}/decisions/{record_id}/"
        "prioritization-owner-decision-v1.json"
    )
    if (
        decision_ref["id"] != expected_ref_id
        or decision_ref["path"] != expected_ref_path
        or decision_ref["artifact_type"]
        != PRIORITIZATION_OWNER_DECISION_ARTIFACT_TYPE
    ):
        raise RegistryValidationError(
            f"improvement {record_id} owner decision reference is not deterministic"
        )
    owner_ids = decision_ref["owner_ids"]
    if owner_ids != sorted(owner_ids):
        raise RegistryValidationError(
            f"improvement {record_id} owner decision owner_ids are not sorted"
        )
    if any(owner_id not in owners for owner_id in owner_ids):
        raise RegistryValidationError(
            f"improvement {record_id} owner decision names an unknown upstream owner"
        )
    if not any(
        owners[owner_id]["owner_type"] != "measurement_owner"
        for owner_id in owner_ids
    ):
        raise RegistryValidationError(
            f"improvement {record_id} rank lacks a non-measurement upstream owner"
        )

    decision_path = resolve_hashed_artifact(
        repo_root,
        decision_ref,
        allowed_roots=(f"{PACKAGE_EVIDENCE_ROOT}/decisions",),
    )
    decision = _load_canonical_workflow_json(
        decision_path, f"prioritization owner decision {record_id}"
    )
    expected_decision = {
        "schema_version": PRIORITIZATION_OWNER_DECISION_SCHEMA_VERSION,
        "improvement_record_id": record_id,
        "decision": "rank",
        "rank": rank,
        "owner_ids": owner_ids,
        "dimension_scores": {
            dimension: prioritization[dimension]["score"]
            for dimension in PRIORITIZATION_DIMENSIONS
        },
        "evidence_ids": prioritization["evidence_ids"],
        "prioritization_snapshot_sha256": _prioritization_snapshot_sha256(
            prioritization
        ),
    }
    if decision != expected_decision:
        raise RegistryValidationError(
            f"improvement {record_id} owner decision does not bind the registered "
            "prioritization"
        )
    return rank


def _validate_prioritization_ranks(ranks: list[int]) -> None:
    if len(ranks) != len(set(ranks)):
        raise RegistryValidationError("ranked improvements contain duplicate ranks")
    if sorted(ranks) != list(range(1, len(ranks) + 1)):
        raise RegistryValidationError(
            "ranked improvement ranks must be contiguous beginning at 1"
        )


def _validate_improvements(
    coverage: dict[str, Any],
    improvements: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    families: dict[str, dict[str, Any]],
    repo_root: Path,
) -> None:
    if (
        improvements["workflow_contract"]["prioritization_contract"]
        != PRIORITIZATION_CONTRACT
    ):
        raise RegistryValidationError("improvement prioritization contract drifted")
    claims = _index_unique(coverage["published_claims"], "id", "published claim")
    records = _index_unique(improvements["records"], "id", "improvement record")
    records_by_claim: dict[str, list[dict[str, Any]]] = {}
    ranked_priorities: list[int] = []
    for record in records.values():
        failure = record["failure"]
        if failure["claim_id"] not in claims:
            raise RegistryValidationError(
                f"improvement {record['id']} is orphaned from claim {failure['claim_id']}"
            )
        records_by_claim.setdefault(failure["claim_id"], []).append(record)
        family = families.get(record["task_family_id"])
        if family is None:
            raise RegistryValidationError(
                f"improvement {record['id']} references unknown task family "
                f"{record['task_family_id']}"
            )
        claim = claims[failure["claim_id"]]
        if not set(claim["lifecycle_stages"]).issubset(set(family["lifecycle_stages"])):
            raise RegistryValidationError(
                f"improvement {record['id']} task family does not exercise its "
                "claim lifecycle"
            )
        for evidence_id in (
            failure["evidence_ids"] + record["diagnosis"]["evidence_ids"]
        ):
            if evidence_id not in evidence:
                raise RegistryValidationError(
                    f"improvement {record['id']} references unknown evidence {evidence_id}"
                )

        upstream = record["upstream"]
        owners = _index_unique(upstream["owners"], "id", "upstream owner")
        if set(owners) != set(CANONICAL_OWNERS):
            raise RegistryValidationError("alias improvement owner set drifted")
        for owner_id, owner in owners.items():
            if owner != {"id": owner_id, **CANONICAL_OWNERS[owner_id]}:
                raise RegistryValidationError(
                    f"owner {owner_id} does not match its canonical accountability"
                )
        issues = _index_unique(upstream["issues"], "key", "upstream issue")
        if set(issues) != set(CANONICAL_ISSUES):
            raise RegistryValidationError(
                "alias improvement has non-canonical issue keys"
            )
        for issue_key, issue in issues.items():
            if issue != {"key": issue_key, **CANONICAL_ISSUES[issue_key]}:
                raise RegistryValidationError(
                    f"issue {issue_key} does not match its canonical URL/relationship/owner"
                )
            if issue["owner_id"] not in owners:
                raise RegistryValidationError(
                    f"issue {issue_key} references missing owner {issue['owner_id']}"
                )

        rank = _validate_prioritization(record, evidence, owners, repo_root)
        if rank is not None:
            ranked_priorities.append(rank)

        design = record["experiment_design"]
        arms = _index_unique(design["arms"], "id", "alias experiment arm")
        model_cells = _index_unique(design["model_cells"], "id", "model cell")
        substrate_cells = _index_unique(
            design["substrate_cells"], "id", "substrate cell"
        )
        _validate_alias_arms(
            arms, design["base_tool_allowlist"], record["workflow_state"]
        )
        _validate_design_cell_pins(
            record["workflow_state"], model_cells, substrate_cells
        )
        cells = _index_unique(design["cells"], "id", "alias experiment cell")
        expected_cells = {
            (arm_id, substrate, model_id)
            for arm_id in arms
            for substrate in SUBSTRATES
            for model_id in model_cells
        }
        actual_cells = {
            (cell["arm_id"], cell["substrate_id"], cell["model_cell_id"])
            for cell in cells.values()
        }
        if actual_cells != expected_cells:
            raise RegistryValidationError(
                "alias experiment cells must be the full arm by substrate by model product"
            )
        contrasts = _index_unique(design["contrasts"], "id", "alias contrast")
        if set(contrasts) != set(EXPECTED_ALIAS_CONTRASTS):
            raise RegistryValidationError(
                "alias rerun lacks the orthogonal contrast set"
            )
        for contrast_id, contrast in contrasts.items():
            if (
                contrast["left_arm_id"] not in arms
                or contrast["right_arm_id"] not in arms
            ):
                raise RegistryValidationError(
                    f"contrast {contrast['id']} references an unknown arm"
                )
            observed = (
                contrast["left_arm_id"],
                contrast["right_arm_id"],
                contrast["primary_factor"],
            )
            if observed != EXPECTED_ALIAS_CONTRASTS[contrast_id]:
                raise RegistryValidationError(
                    f"contrast {contrast_id} does not isolate its registered factor"
                )
            decision = {
                key: contrast[key]
                for key in (
                    "binding_lane",
                    "decision_role",
                    "decision_rule",
                    "decision_threshold",
                    "confidence_level",
                )
            }
            if decision != EXPECTED_CONTRAST_DECISIONS[contrast_id]:
                raise RegistryValidationError(
                    f"contrast {contrast_id} has the wrong registered decision role"
                )
        if design["non_action_diagnostics"] != [
            {
                "id": "prompt-naming",
                "status": "not_executed",
                "registration_requirement": "separate_registration_required",
                "domain": "non_drupal_prompt_sensitivity",
                "held_fixed_drupal_arm_id": "facts-discoverable-unnamed",
                "adoption_effect": "cannot_support_or_block_drupal_action_adoption",
            }
        ]:
            raise RegistryValidationError(
                "prompt naming must remain a separate unexecuted non-Drupal diagnostic"
            )

        binding_plan = design["measurement_v1_binding_plan"]
        _validate_measurement_v1_binding_plan(
            binding_plan,
            contrasts,
            model_cells,
        )

        plan = record["analysis_plan"]
        _validate_analysis_plan(plan, binding_plan)
        expected_delta = record["expected_delta"]
        effect = plan["primary_metric"]["effect"]
        if expected_delta != {
            "metric_id": plan["primary_metric"]["id"],
            "analysis_unit": plan["analysis_unit"],
            "direction": effect["direction"],
            "effect_kind": effect["kind"],
            "effect_unit": effect["unit"],
            "minimum_effect": effect["minimum_effect"],
            "cross_task_inference": False,
            "readiness_output": False,
        }:
            raise RegistryValidationError(
                f"improvement {record['id']} expected delta diverges from analysis plan"
            )
        metric_ids = (
            {plan["primary_metric"]["id"]}
            | {item["id"] for item in plan["guardrails"]}
            | {plan["task_completion_guardrail"]["id"]}
            | {item["id"] for item in plan["measurement_integrity_guardrails"]}
        )
        _validate_workflow_state(
            record,
            repo_root,
            cells,
            metric_ids,
            binding_plan,
            improvements["registry_id"],
            improvements["schema_version"],
            failure["claim_id"],
            record["task_family_id"],
            claim["task_id"],
            contrasts,
            model_cells,
            substrate_cells,
        )

    _validate_prioritization_ranks(ranked_priorities)
    for claim_id, claim in claims.items():
        count = len(records_by_claim.get(claim_id, []))
        if claim["action_required"] and count != 1:
            raise RegistryValidationError(
                f"actionable claim {claim_id} must have exactly one improvement record"
            )


def _validate_alias_arms(
    arms: dict[str, dict[str, Any]],
    base_tool_allowlist: list[str],
    workflow_state: str,
) -> None:
    if set(arms) != EXPECTED_ALIAS_ARMS:
        raise RegistryValidationError(
            "alias rerun arm set is incomplete or substituted"
        )
    if set(base_tool_allowlist) != BASE_ALIAS_TOOLS:
        raise RegistryValidationError("alias base tool allowlist drifted")
    factor_vectors: set[tuple[Any, ...]] = set()
    for arm_id, arm in arms.items():
        mode = arm["capability_mode"]
        installed = arm["capability_installed"]
        facts = arm["facts_available"]
        advice = arm["advice_available"]
        help_discoverable = arm["help_discoverable"]
        if mode == "absent" and any((installed, facts, advice, help_discoverable)):
            raise RegistryValidationError(f"absent arm {arm_id} exposes the capability")
        if mode == "stub" and (not installed or facts or advice):
            raise RegistryValidationError(f"stub arm {arm_id} exposes facts or advice")
        if mode == "functional" and (not installed or not facts):
            raise RegistryValidationError(f"functional arm {arm_id} lacks facts")
        if advice and not facts:
            raise RegistryValidationError(f"advice arm {arm_id} lacks facts")
        if set(arm["tool_allowlist"]) != set(base_tool_allowlist):
            raise RegistryValidationError(
                f"arm {arm_id} changes the held-fixed agent tool allowlist"
            )
        write = arm["actual_write_outcome"]
        if (
            not write["required"]
            or write["oracle"] != "post_write_path_ownership_probe"
            or write["success_metric_id"] != "requested_write_safe"
            or write["failure_metric_id"] != "write_collision_or_unjustified_refusal"
        ):
            raise RegistryValidationError(f"arm {arm_id} lacks an actual-write oracle")
        vector = (
            mode,
            help_discoverable,
            arm["prompt_named"],
            facts,
            advice,
        )
        if vector in factor_vectors:
            raise RegistryValidationError(
                f"arm {arm_id} duplicates another factor vector"
            )
        factor_vectors.add(vector)

    if workflow_state == "pending_registration":
        if any(
            arm["implementation_pin_state"] != "required_before_freeze"
            or arm["drupal_code_tree_sha256"] is not None
            or arm["capability_component_tree_sha256"] is not None
            or arm["treatment_artifact_sha256"] is not None
            for arm in arms.values()
        ):
            raise RegistryValidationError(
                "pending action arms must remain honestly unresolved"
            )
        return

    if any(
        arm["implementation_pin_state"] != "frozen"
        or re.fullmatch(r"[0-9a-f]{64}", arm["drupal_code_tree_sha256"] or "") is None
        or re.fullmatch(r"[0-9a-f]{64}", arm["treatment_artifact_sha256"] or "") is None
        for arm in arms.values()
    ):
        raise RegistryValidationError(
            "promoted action arms lack frozen Drupal code and treatment pins"
        )
    for arm_id, arm in arms.items():
        component_pin = arm["capability_component_tree_sha256"]
        if arm["capability_installed"]:
            if re.fullmatch(r"[0-9a-f]{64}", component_pin or "") is None:
                raise RegistryValidationError(
                    f"installed arm {arm_id} lacks an exact capability component-tree pin"
                )
        elif component_pin is not None:
            raise RegistryValidationError(
                f"raw arm {arm_id} cannot pin an absent capability component"
            )
    action_arm_ids = {
        arm_id
        for contrast_id, (
            left_arm_id,
            right_arm_id,
            _,
        ) in EXPECTED_ALIAS_CONTRASTS.items()
        if EXPECTED_CONTRAST_DECISIONS[contrast_id]["binding_lane"] == "drupal_action"
        for arm_id in (left_arm_id, right_arm_id)
    }
    action_identities = {
        (
            arms[arm_id]["drupal_code_tree_sha256"],
            arms[arm_id]["capability_component_tree_sha256"],
            arms[arm_id]["treatment_artifact_sha256"],
        )
        for arm_id in action_arm_ids
    }
    if len(action_identities) != len(action_arm_ids):
        raise RegistryValidationError(
            "distinct Drupal action arms reuse the same implementation/treatment pins"
        )


def _validate_design_cell_pins(
    workflow_state: str,
    model_cells: dict[str, dict[str, Any]],
    substrate_cells: dict[str, dict[str, Any]],
) -> None:
    expected_model_flags = {
        "fixed-model-primary": False,
        "fixed-model-replication": True,
    }
    if (
        set(model_cells) != set(expected_model_flags)
        or set(substrate_cells) != SUBSTRATES
    ):
        raise RegistryValidationError("model or substrate cell set drifted")
    for model_id, independent in expected_model_flags.items():
        model = model_cells[model_id]
        if (
            not model["snapshot_required_before_registration"]
            or model["independent_provider_cell"] is not independent
        ):
            raise RegistryValidationError(f"model cell {model_id} changed its role")

    if workflow_state == "pending_registration":
        for model in model_cells.values():
            if model != {
                "id": model["id"],
                "snapshot_required_before_registration": True,
                "independent_provider_cell": expected_model_flags[model["id"]],
                "pin_state": "required_before_freeze",
                "provider": None,
                "model_id": None,
                "snapshot": None,
                "inference_parameters_sha256": None,
                "held_fixed_stack_sha256": None,
            }:
                raise RegistryValidationError(
                    "pending model cells must remain honestly unresolved"
                )
        for substrate in substrate_cells.values():
            if substrate != {
                "id": substrate["id"],
                "pin_state": "required_before_freeze",
                "fixture_id": None,
                "starting_site_manifest_sha256": None,
                "owner_attestation_sha256": None,
            }:
                raise RegistryValidationError(
                    "pending substrate cells must remain honestly unresolved"
                )
        return

    if any(
        model["pin_state"] != "frozen"
        or not all(
            isinstance(model[field], str) and model[field]
            for field in (
                "provider",
                "model_id",
                "snapshot",
                "inference_parameters_sha256",
                "held_fixed_stack_sha256",
            )
        )
        for model in model_cells.values()
    ):
        raise RegistryValidationError("promoted model cells lack exact frozen pins")
    model_identities = {
        (
            model["provider"],
            model["model_id"],
            model["snapshot"],
            model["inference_parameters_sha256"],
            model["held_fixed_stack_sha256"],
        )
        for model in model_cells.values()
    }
    if len(model_identities) != len(model_cells):
        raise RegistryValidationError(
            "primary and replication model cells reuse the same frozen model pins"
        )
    if (
        model_cells["fixed-model-primary"]["provider"]
        == model_cells["fixed-model-replication"]["provider"]
    ):
        raise RegistryValidationError(
            "independent replication model cell must use a distinct provider"
        )
    if any(
        substrate["pin_state"] != "frozen"
        or not isinstance(substrate["fixture_id"], str)
        or not substrate["fixture_id"]
        or not isinstance(substrate["starting_site_manifest_sha256"], str)
        for substrate in substrate_cells.values()
    ):
        raise RegistryValidationError("promoted substrate cells lack exact frozen pins")
    if substrate_cells["clean"]["owner_attestation_sha256"] is not None:
        raise RegistryValidationError(
            "clean substrate must not carry a messy-owner attestation"
        )
    messy_attestation = substrate_cells["messy_owner_described"][
        "owner_attestation_sha256"
    ]
    if (
        not isinstance(messy_attestation, str)
        or re.fullmatch(r"[0-9a-f]{64}", messy_attestation) is None
    ):
        raise RegistryValidationError(
            "messy substrate lacks a frozen owner-attestation pin"
        )
    substrate_identities = {
        (substrate["fixture_id"], substrate["starting_site_manifest_sha256"])
        for substrate in substrate_cells.values()
    }
    if len(substrate_identities) != len(substrate_cells):
        raise RegistryValidationError(
            "clean and messy substrate cells reuse the same frozen seed pins"
        )


def _validate_measurement_v1_binding_plan(
    plan: dict[str, Any],
    contrasts: dict[str, dict[str, Any]],
    model_cells: dict[str, dict[str, Any]],
) -> None:
    if (
        plan["schema_version"]
        != "drupal_agent_readiness.benchmark_action_binding_plan.v1"
        or plan["manifest_schema_version"]
        != "drupal_agent_readiness.benchmark_experiment.v1"
        or plan["manifest_lane"] != "fixed_regression"
        or not plan["manifest_required_before_execution"]
        or plan["binding_axes"] != ["contrast", "substrate", "model_cell"]
    ):
        raise RegistryValidationError(
            "alias measurement-v1 binding plan has the wrong contract"
        )
    roster_contract = plan["roster_contract"]
    if roster_contract != MEASUREMENT_V1_ROSTER_CONTRACT:
        raise RegistryValidationError(
            "alias measurement-v1 roster allows replacement, exclusion, or drift"
        )
    if plan["promotion_gate"] != MEASUREMENT_V1_PROMOTION_GATE:
        raise RegistryValidationError(
            "alias final promotion gate does not require every binding artifact"
        )

    bindings = _index_unique(plan["bindings"], "id", "measurement-v1 manifest binding")
    action_contrast_ids = {
        contrast_id
        for contrast_id, contrast in contrasts.items()
        if contrast["binding_lane"] == "drupal_action"
    }
    expected_product = {
        (contrast_id, substrate_id, model_cell_id)
        for contrast_id in action_contrast_ids
        for substrate_id in SUBSTRATES
        for model_cell_id in model_cells
    }
    actual_product = {
        (
            binding["contrast_id"],
            binding["substrate_id"],
            binding["model_cell_id"],
        )
        for binding in bindings.values()
    }
    if actual_product != expected_product or len(bindings) != 16:
        raise RegistryValidationError(
            "alias action registry must bind every Drupal action contrast by substrate by model cell"
        )

    experiment_ids: set[str] = set()
    for binding in bindings.values():
        contrast_id = binding["contrast_id"]
        substrate_id = binding["substrate_id"]
        model_cell_id = binding["model_cell_id"]
        contrast = contrasts[contrast_id]
        if contrast["binding_lane"] != "drupal_action":
            raise RegistryValidationError(
                f"binding {binding['id']} uses a non-Drupal diagnostic contrast"
            )
        substrate_label = "clean" if substrate_id == "clean" else "messy"
        model_label = {
            "fixed-model-primary": "primary",
            "fixed-model-replication": "replication",
        }.get(model_cell_id)
        if model_label is None:
            raise RegistryValidationError(
                f"binding {binding['id']} uses an unregistered model cell"
            )
        expected_binding_id = f"{contrast_id}-{substrate_label}-{model_label}"
        expected_experiment_id = f"alias-{expected_binding_id}@v1"
        if binding != {
            "id": expected_binding_id,
            "contrast_id": contrast_id,
            "substrate_id": substrate_id,
            "model_cell_id": model_cell_id,
            "experiment_id": expected_experiment_id,
            "pre_arm_id": contrast["left_arm_id"],
            "post_arm_id": contrast["right_arm_id"],
            "roster_contract_id": MEASUREMENT_V1_ROSTER_CONTRACT["id"],
            "decision_role": contrast["decision_role"],
            "decision_rule": contrast["decision_rule"],
        }:
            raise RegistryValidationError(
                f"binding {binding['id']} does not match its two-arm fixed-regression contrast"
            )
        if binding["experiment_id"] in experiment_ids:
            raise RegistryValidationError(
                f"duplicate measurement-v1 experiment id {binding['experiment_id']}"
            )
        experiment_ids.add(binding["experiment_id"])
        roster = _materialize_binding_attempt_roster(binding, roster_contract)
        if (
            len(roster) != roster_contract["planned_attempts"]
            or sum(len(entry["executions"]) for entry in roster)
            != roster_contract["required_resolved_slots"]
            or len({entry["pair_id"] for entry in roster}) != len(roster)
            or len({entry["unit_id"] for entry in roster}) != len(roster)
            or len(
                {slot["slot_id"] for entry in roster for slot in entry["executions"]}
            )
            != roster_contract["required_resolved_slots"]
        ):
            raise RegistryValidationError(
                f"binding {binding['id']} does not materialize a fixed complete roster"
            )


def _materialize_binding_attempt_roster(
    binding: dict[str, Any], roster_contract: dict[str, Any]
) -> list[dict[str, Any]]:
    roster: list[dict[str, Any]] = []
    for index in range(
        roster_contract["index_start"], roster_contract["index_end"] + 1
    ):
        values = {"binding_id": binding["id"], "index": index}
        pre = {
            "slot_id": roster_contract["pre_slot_id_template"].format(**values),
            "arm_id": binding["pre_arm_id"],
            "order": 1 if index % 2 else 2,
        }
        post = {
            "slot_id": roster_contract["post_slot_id_template"].format(**values),
            "arm_id": binding["post_arm_id"],
            "order": 2 if index % 2 else 1,
        }
        roster.append(
            {
                "index": index,
                "pair_id": roster_contract["pair_id_template"].format(**values),
                "unit_id": roster_contract["unit_id_template"].format(**values),
                "executions": [pre, post],
            }
        )
    return roster


def _validate_analysis_plan(plan: dict[str, Any], binding_plan: dict[str, Any]) -> None:
    metric = plan["primary_metric"]
    if plan["analysis_unit"] != "run" or metric["analysis_unit"] != "run":
        raise RegistryValidationError("alias analysis unit must be the run")
    if metric["nested_observation"] != "candidate_path_judgment":
        raise RegistryValidationError("candidate judgments must be nested within runs")
    if metric["value_type"] == "proportion":
        if metric["bounds"] != {"minimum": 0.0, "maximum": 1.0}:
            raise RegistryValidationError(
                "proportion metric must be bounded from zero to one"
            )
        effect = metric["effect"]
        if (
            effect["kind"] != "absolute_difference"
            or effect["unit"] != "proportion"
            or not 0.0 <= effect["minimum_effect"] <= 1.0
        ):
            raise RegistryValidationError(
                "proportion metric has an incompatible effect"
            )
    else:
        raise RegistryValidationError("alias primary metric must be a proportion")
    if metric["denominator"]["unit"] != "eligible_hidden_claim_judgments_within_run":
        raise RegistryValidationError("alias primary metric denominator is not typed")
    if (
        metric["numerator"] != "hidden_claim_false_safe_judgments_within_run"
        or metric["run_summary"]
        != "false_safe_judgments_divided_by_eligible_hidden_claim_judgments"
    ):
        raise RegistryValidationError("alias primary metric formula is not registered")
    if plan["stratification"] != ["arm", "substrate", "model_cell"]:
        raise RegistryValidationError(
            "analysis must retain arm by substrate by model cells"
        )
    guardrails = _index_unique(plan["guardrails"], "id", "analysis guardrail")
    expected_guardrails = {
        "free-path-false-unsafe-rate": (0.05, 0.05),
        "valid-run-tool-failure-rate": (0.05, 0.05),
        "actual-write-collision-rate": (0.0, 0.0),
        "actual-write-refusal-rate": (0.0, 0.0),
    }
    if set(guardrails) != set(expected_guardrails) or any(
        guardrail["value_type"] != "proportion"
        or guardrail["bounds"] != {"minimum": 0.0, "maximum": 1.0}
        or (
            guardrail["maximum_absolute_increase"],
            guardrail["maximum_rate"],
        )
        != expected_guardrails[guardrail_id]
        for guardrail_id, guardrail in guardrails.items()
    ):
        raise RegistryValidationError(
            "alias guardrail contract is incomplete or changed"
        )
    expected_write_policy = {
        "placebo_control": 1.0,
        "primary_efficacy": 0.0,
        "diagnostic_sensitivity": 0.0,
    }
    if any(
        guardrails[guardrail_id].get("post_rate_policy_by_role")
        != expected_write_policy
        for guardrail_id in (
            "actual-write-collision-rate",
            "actual-write-refusal-rate",
        )
    ) or any(
        "post_rate_policy_by_role" in guardrails[guardrail_id]
        for guardrail_id in (
            "free-path-false-unsafe-rate",
            "valid-run-tool-failure-rate",
        )
    ):
        raise RegistryValidationError(
            "actual-write guardrails lack role-specific placebo handling"
        )
    if plan["task_completion_guardrail"] != {
        "id": "task-success-retention",
        "metric_id": "task_success",
        "minimum_post_rate_by_role": {
            "placebo_control": 0.0,
            "primary_efficacy": 0.95,
            "diagnostic_sensitivity": 0.95,
        },
        "minimum_post_minus_pre": 0.0,
    }:
        raise RegistryValidationError(
            "task completion is not protected by the role-specific adoption guardrail"
        )
    if plan["measurement_integrity_guardrails"] != [
        {
            "id": "zero-human-interventions",
            "source_kind": "cost",
            "metric_id": "human_interventions",
            "statistic": "maximum_all",
            "operator": "at_most",
            "threshold": 0,
        },
        {
            "id": "bounded-latency-regression",
            "source_kind": "cost",
            "metric_id": "wall_time_ms",
            "statistic": "mean_post_minus_pre",
            "operator": "at_most",
            "threshold": 1000,
        },
    ]:
        raise RegistryValidationError(
            "measurement integrity guardrails are incomplete or changed"
        )
    if plan["power"] != PRECISION_FEASIBILITY_CONTRACT:
        raise RegistryValidationError(
            "sample-size basis overclaims power or lacks the frozen feasibility contract"
        )
    stopping = plan["stopping"]
    if (
        stopping != MEASUREMENT_V1_STOPPING_CONTRACT
        or stopping["planned_attempts_per_binding"]
        != binding_plan["roster_contract"]["planned_attempts"]
        or stopping["required_resolved_slots_per_binding"]
        != binding_plan["roster_contract"]["required_resolved_slots"]
    ):
        raise RegistryValidationError(
            "alias stopping rule is not the fixed fail-closed binding roster"
        )


def _validate_workflow_state(
    record: dict[str, Any],
    repo_root: Path,
    cells: dict[str, dict[str, Any]],
    metric_ids: set[str],
    binding_plan: dict[str, Any],
    registry_id: str,
    registry_version: str,
    coverage_claim_id: str,
    task_family_id: str,
    claim_task_id: str,
    contrasts: dict[str, dict[str, Any]],
    model_cells: dict[str, dict[str, Any]],
    substrate_cells: dict[str, dict[str, Any]],
) -> None:
    workflow = record["workflow"]
    state = record["workflow_state"]
    pending = {
        "registration": {"state": "required"},
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
    if state == "pending_registration":
        if workflow != pending:
            raise RegistryValidationError(
                "pending workflow contains promotion, execution, analysis, or decision state"
            )
        return

    if state not in WORKFLOW_STATES:
        raise RegistryValidationError(f"unsupported improvement workflow state {state}")
    state_index = WORKFLOW_STATES.index(state)
    if state_index == 0:
        raise RegistryValidationError(
            "pending workflow state was not handled fail closed"
        )

    registration = workflow["registration"]
    if registration["state"] != "frozen":
        raise RegistryValidationError(
            "promoted workflow has no frozen design registration"
        )
    snapshot_ref = registration["design_snapshot_ref"]
    snapshot_path = _resolve_workflow_artifact(
        repo_root,
        snapshot_ref,
        "improvement_design_snapshot",
        require_experiment=False,
    )
    design_sha256 = registration["design_snapshot_sha256"]
    if design_sha256 != snapshot_ref["sha256"]:
        raise RegistryValidationError(
            "frozen design hash differs from its immutable snapshot artifact"
        )
    snapshot = _load_canonical_workflow_json(snapshot_path, "design snapshot")
    expected_snapshot = _immutable_design_snapshot(record)
    if snapshot != expected_snapshot:
        raise RegistryValidationError(
            "current improvement design drifted from its preregistered immutable snapshot"
        )

    design_basis_ref = registration["design_basis_ref"]
    design_basis_path = _resolve_workflow_artifact(
        repo_root,
        design_basis_ref,
        "sample_size_rationale",
        require_experiment=False,
    )
    design_basis = _load_canonical_workflow_json(
        design_basis_path, "precision and feasibility rationale"
    )
    if design_basis != _expected_precision_rationale(record, design_sha256):
        raise RegistryValidationError(
            "sample-size rationale is missing, drifted, or overclaims power"
        )
    design_basis_pin = {
        "uri": design_basis_ref["path"].removeprefix("agent_readiness/"),
        "sha256": f"sha256:{design_basis_ref['sha256']}",
        "media_type": "application/json",
        "byte_size": design_basis_path.stat().st_size,
    }

    calibration_ref = registration["calibration_decision_ref"]
    expected_calibration_identity = {
        "id": f"{record['id']}-calibration-design-decision",
        "path": (
            "agent_readiness/evidence/registrations/"
            f"{record['id']}/calibration-design-decision.json"
        ),
    }
    if any(
        calibration_ref.get(field) != value
        for field, value in expected_calibration_identity.items()
    ):
        raise RegistryValidationError(
            "calibration design decision has a substituted artifact identity"
        )
    calibration_path = _resolve_workflow_artifact(
        repo_root,
        calibration_ref,
        CALIBRATION_DECISION_ARTIFACT_TYPE,
        require_experiment=False,
    )
    calibration = _load_canonical_workflow_json(
        calibration_path, "calibration design decision"
    )
    if calibration != _expected_calibration_decision(record, design_sha256):
        raise RegistryValidationError(
            "calibration design decision is missing, unapproved, or inconsistent with the frozen design"
        )

    bindings = binding_plan["bindings"]
    bindings_by_experiment = {binding["experiment_id"]: binding for binding in bindings}
    bound_experiment_ids = sorted(bindings_by_experiment)
    manifest_refs = _index_workflow_refs_by_experiment(
        repo_root,
        registration["manifest_refs"],
        "measurement_v1_manifest",
        bound_experiment_ids,
    )
    snapshot_pin = {
        "uri": snapshot_ref["path"].removeprefix("agent_readiness/"),
        "sha256": f"sha256:{design_sha256}",
        "media_type": "application/json",
        "byte_size": snapshot_path.stat().st_size,
    }
    manifests_by_experiment: dict[str, dict[str, Any]] = {}
    arms_by_id = {arm["id"]: arm for arm in record["experiment_design"]["arms"]}
    held_fixed_projection_by_model: dict[str, dict[str, Any]] = {}
    context_projection_by_cell: dict[tuple[str, str], dict[str, Any]] = {}
    context_hashes_by_model: dict[str, set[str]] = {}
    ground_truth_by_experiment: dict[str, dict[str, Any]] = {}
    for experiment_id, reference in manifest_refs.items():
        manifest = _load_canonical_workflow_json(
            _resolve_workflow_artifact(
                repo_root,
                reference,
                "measurement_v1_manifest",
                require_experiment=True,
            ),
            f"manifest {experiment_id}",
        )
        governance = manifest.get("governance", {})
        registry_design = governance.get("registry_design", {})
        binding = bindings_by_experiment[experiment_id]
        contrast = contrasts[binding["contrast_id"]]
        expected_roster = _materialize_binding_attempt_roster(
            binding, binding_plan["roster_contract"]
        )
        manifest_errors = [
            issue
            for issue in validate_experiment_manifest(manifest)
            if issue.severity == "error"
        ]
        if manifest_errors:
            codes = sorted({issue.code for issue in manifest_errors})
            raise RegistryValidationError(
                f"manifest {experiment_id} fails measurement-v1 validation: {codes}"
            )
        manifest_arms_by_role = {arm["role"]: arm for arm in manifest.get("arms", [])}
        manifest_arms = {
            role: arm["arm_id"] for role, arm in manifest_arms_by_role.items()
        }
        primary_metric = next(
            (
                metric
                for metric in manifest.get("outcome_metrics", [])
                if metric.get("metric_id")
                == record["analysis_plan"]["primary_metric"]["id"]
            ),
            None,
        )
        model = model_cells[binding["model_cell_id"]]
        substrate = substrate_cells[binding["substrate_id"]]
        if (
            manifest.get("schema_version") != binding_plan["manifest_schema_version"]
            or manifest.get("experiment_id") != experiment_id
            or manifest.get("lane") != binding_plan["manifest_lane"]
            or governance.get("coverage_claim_id") != coverage_claim_id
            or governance.get("task_family_id") != task_family_id
            or governance.get("improvement_record_id") != record["id"]
            or manifest.get("task", {}).get("id") != claim_task_id
            or manifest.get("task", {}).get("lifecycle_stages")
            != ["understand", "act", "verify"]
            or manifest.get("registration", {}).get("manifest_path")
            != reference["path"]
            or registry_design
            != {
                "id": registry_id,
                "version": registry_version,
                "artifact": snapshot_pin,
            }
            or manifest_arms
            != {"pre": binding["pre_arm_id"], "post": binding["post_arm_id"]}
            or manifest.get("comparison", {}).get("pre_arm_id") != binding["pre_arm_id"]
            or manifest.get("comparison", {}).get("post_arm_id")
            != binding["post_arm_id"]
            or manifest.get("execution_plan", {}).get("attempt_roster")
            != expected_roster
            or manifest.get("execution_plan", {}).get("stopping_rule")
            != {
                "kind": "fixed_census",
                "required_resolved_slots": 40,
                "allow_replacements": False,
                "on_exclusion": "no_claim",
            }
            or manifest.get("claim_plan", {}).get("primary_metric_id")
            != record["analysis_plan"]["primary_metric"]["id"]
            or manifest.get("claim_plan", {}).get("minimum_favorable_effect")
            != record["expected_delta"]["minimum_effect"]
            or manifest.get("claim_plan", {}).get("planned_denominator") != 20
            or manifest.get("claim_plan", {}).get("sample_size_rationale")
            != design_basis_pin
            or manifest.get("outcome_metrics")
            != _expected_measurement_outcome_metrics(record)
            or manifest.get("claim_plan", {}).get("guardrails")
            != _expected_measurement_guardrails(record, binding["decision_role"])
            or manifest.get("evaluation", {}).get("verdict_metric_id") != "task_success"
            or primary_metric is None
            or primary_metric.get("direction")
            != {"decrease": "lower_is_better"}[record["expected_delta"]["direction"]]
            or manifest.get("reference_agent_stack", {})
            .get("model", {})
            .get("provider")
            != model["provider"]
            or manifest.get("reference_agent_stack", {}).get("model", {}).get("id")
            != model["model_id"]
            or manifest.get("reference_agent_stack", {})
            .get("model", {})
            .get("snapshot")
            != model["snapshot"]
            or manifest.get("reference_agent_stack", {})
            .get("model", {})
            .get("inference_parameters", {})
            .get("sha256")
            != f"sha256:{model['inference_parameters_sha256']}"
            or manifest.get("substrate", {}).get("substrate_id")
            != binding["substrate_id"]
            or manifest.get("substrate", {})
            .get("starting_site_seed", {})
            .get("fixture_id")
            != substrate["fixture_id"]
            or manifest.get("substrate", {})
            .get("starting_site_seed", {})
            .get("manifest", {})
            .get("sha256")
            != f"sha256:{substrate['starting_site_manifest_sha256']}"
            or (
                binding["substrate_id"] == "clean"
                and manifest.get("substrate", {}).get("owner_attestation") is not None
            )
            or (
                binding["substrate_id"] == "messy_owner_described"
                and manifest.get("substrate", {})
                .get("owner_attestation", {})
                .get("sha256")
                != f"sha256:{substrate['owner_attestation_sha256']}"
            )
            or binding["decision_role"] != contrast["decision_role"]
            or binding["decision_rule"] != contrast["decision_rule"]
        ):
            raise RegistryValidationError(
                f"manifest {experiment_id} does not match its full registered binding"
            )
        for role, arm_id in (
            ("pre", binding["pre_arm_id"]),
            ("post", binding["post_arm_id"]),
        ):
            manifest_arm = manifest_arms_by_role[role]
            registered_arm = arms_by_id[arm_id]
            if (
                manifest_arm["drupal_state"]["code"]["codebase_tree_sha256"]
                != f"sha256:{registered_arm['drupal_code_tree_sha256']}"
                or manifest_arm["treatment"]["id"] != arm_id
                or manifest_arm["treatment"]["artifact"]["sha256"]
                != f"sha256:{registered_arm['treatment_artifact_sha256']}"
            ):
                raise RegistryValidationError(
                    f"manifest {experiment_id} swaps or reuses registered Drupal arm bytes"
                )
            capability_components = [
                component
                for component in manifest_arm["drupal_state"]["code"]["components"]
                if component.get("kind") == "module"
                and component.get("name") == "site_architecture"
            ]
            if registered_arm["capability_installed"]:
                if (
                    len(capability_components) != 1
                    or capability_components[0].get("tree_sha256")
                    != "sha256:" + registered_arm["capability_component_tree_sha256"]
                ):
                    raise RegistryValidationError(
                        f"manifest {experiment_id} installed arm {arm_id} lacks its exact capability component tree"
                    )
            elif capability_components:
                raise RegistryValidationError(
                    f"manifest {experiment_id} raw arm {arm_id} contains the capability component"
                )
            _verify_package_artifact_pin(
                repo_root / "agent_readiness",
                manifest_arm["treatment"]["artifact"],
                f"sha256:{registered_arm['treatment_artifact_sha256']}",
                f"manifest {experiment_id} {role} treatment",
            )
        capability_tool_ids = [
            tool.get("id")
            for tool in manifest.get("reference_agent_stack", {}).get("tools", [])
            if tool.get("id") != "execution-environment-policy"
        ]
        if (
            len(capability_tool_ids) != len(set(capability_tool_ids))
            or set(capability_tool_ids) != BASE_ALIAS_TOOLS
        ):
            raise RegistryValidationError(
                f"manifest {experiment_id} changes the held-fixed shell/drush tool stack"
            )
        projection = _held_fixed_stack_projection(manifest)
        projection_sha256 = hashlib.sha256(
            _canonical_workflow_json_bytes(projection)
        ).hexdigest()
        if projection_sha256 != model["held_fixed_stack_sha256"]:
            raise RegistryValidationError(
                f"manifest {experiment_id} drifts from its preregistered full held-fixed stack"
            )
        previous_projection = held_fixed_projection_by_model.setdefault(
            binding["model_cell_id"], projection
        )
        if projection != previous_projection:
            raise RegistryValidationError(
                f"manifests in model cell {binding['model_cell_id']} do not share the full held-fixed stack"
            )
        context_projection = _substrate_context_projection(manifest)
        context_key = (binding["model_cell_id"], binding["substrate_id"])
        previous_context = context_projection_by_cell.setdefault(
            context_key, context_projection
        )
        if context_projection != previous_context:
            raise RegistryValidationError(
                f"manifests in cell {context_key} drift their substrate context"
            )
        context_hashes_by_model.setdefault(binding["model_cell_id"], set()).add(
            hashlib.sha256(
                _canonical_workflow_json_bytes(context_projection)
            ).hexdigest()
        )
        _verify_package_artifact_pin(
            repo_root / "agent_readiness",
            manifest["reference_agent_stack"]["model"]["inference_parameters"],
            f"sha256:{model['inference_parameters_sha256']}",
            f"manifest {experiment_id} model inference parameters",
        )
        _verify_package_artifact_pin(
            repo_root / "agent_readiness",
            manifest["substrate"]["starting_site_seed"]["manifest"],
            f"sha256:{substrate['starting_site_manifest_sha256']}",
            f"manifest {experiment_id} substrate state manifest",
        )
        attested_inventory: list[dict[str, Any]] = []
        if binding["substrate_id"] == "messy_owner_described":
            _verify_package_artifact_pin(
                repo_root / "agent_readiness",
                manifest["substrate"]["owner_attestation"],
                f"sha256:{substrate['owner_attestation_sha256']}",
                f"manifest {experiment_id} owner attestation",
            )
            attested_inventory = _validate_owner_attestation(
                repo_root / "agent_readiness",
                manifest["substrate"]["owner_attestation"],
                substrate,
                coverage_claim_id,
                task_family_id,
                claim_task_id,
                experiment_id,
            )
        ground_truth_by_experiment[experiment_id] = _validate_substrate_ground_truth(
            repo_root / "agent_readiness",
            manifest["task"]["ground_truth"],
            substrate,
            coverage_claim_id,
            claim_task_id,
            attested_inventory,
            experiment_id,
        )
        manifests_by_experiment[experiment_id] = manifest

    if any(
        len(context_hashes) != len(SUBSTRATES)
        for context_hashes in context_hashes_by_model.values()
    ):
        raise RegistryValidationError(
            "clean and messy substrates must freeze distinct evaluator/context projections"
        )

    execution = workflow["execution"]
    if state_index >= WORKFLOW_STATES.index("executed"):
        if execution["state"] != "complete":
            raise RegistryValidationError(
                "executed workflow lacks a complete run census"
            )
        result_refs = _index_workflow_refs_by_experiment(
            repo_root,
            execution["run_artifact_refs"],
            "measurement_v1_result",
            bound_experiment_ids,
        )
        results_by_experiment: dict[str, dict[str, Any]] = {}
        audits_by_experiment: dict[str, dict[str, Any]] = {}
        for experiment_id, reference in result_refs.items():
            result = _load_canonical_workflow_json(
                _resolve_workflow_artifact(
                    repo_root,
                    reference,
                    "measurement_v1_result",
                    require_experiment=True,
                ),
                f"result {experiment_id}",
            )
            _require_workflow_payload(
                result,
                {
                    "schema_version": BOUND_RESULT_SCHEMA_VERSION,
                    "improvement_record_id": record["id"],
                    "experiment_id": experiment_id,
                    "design_snapshot_sha256": design_sha256,
                    "manifest_artifact_ref": manifest_refs[experiment_id],
                    "result_status": "complete",
                    "planned_slots": binding_plan["roster_contract"][
                        "required_resolved_slots"
                    ],
                    "resolved_slots": binding_plan["roster_contract"][
                        "required_resolved_slots"
                    ],
                },
                f"result {experiment_id}",
            )
            expected_slot_ids = [
                slot["slot_id"]
                for attempt in _materialize_binding_attempt_roster(
                    bindings_by_experiment[experiment_id],
                    binding_plan["roster_contract"],
                )
                for slot in attempt["executions"]
            ]
            raw_run_refs = result.get("run_artifact_refs")
            if not isinstance(raw_run_refs, list):
                raise RegistryValidationError(
                    f"result {experiment_id} has no hashed run artifact census"
                )
            run_refs = _index_unique(
                raw_run_refs, "id", f"{experiment_id} benchmark run artifact"
            )
            if set(run_refs) != set(expected_slot_ids):
                raise RegistryValidationError(
                    f"result {experiment_id} does not contain the exact planned slot census"
                )
            manifest = manifests_by_experiment[experiment_id]
            runs: list[dict[str, Any]] = []
            for slot_id in expected_slot_ids:
                run_ref = run_refs[slot_id]
                run = _load_canonical_workflow_json(
                    _resolve_workflow_artifact(
                        repo_root,
                        run_ref,
                        "measurement_v1_run",
                        require_experiment=True,
                    ),
                    f"benchmark run {experiment_id} {slot_id}",
                )
                run_errors = [
                    issue
                    for issue in validate_run_result(run, manifest)
                    if issue.severity == "error"
                ]
                if (
                    run_ref.get("experiment_id") != experiment_id
                    or run.get("experiment_id") != experiment_id
                    or run.get("attempt", {}).get("roster_slot_id") != slot_id
                    or run_errors
                ):
                    codes = sorted({issue.code for issue in run_errors})
                    raise RegistryValidationError(
                        f"run {slot_id} does not bind its manifest and slot: {codes}"
                    )
                mechanical = _validate_action_metric_recomputation(
                    repo_root / "agent_readiness",
                    run,
                    ground_truth_by_experiment[experiment_id],
                    slot_id,
                )
                _validate_actual_write_behavior(
                    run, slot_id, mechanical["write_outcome"]
                )
                runs.append(run)
            audit = audit_measurement_v1(
                manifest,
                runs,
                artifact_root=repo_root / "agent_readiness",
                registration_anchor=GitRegistrationAnchor(
                    repo_path=repo_root,
                    commit=registration["git_commit"],
                    manifest_path=manifest["registration"]["manifest_path"],
                ),
            )
            portable_audit = _portable_measurement_audit(audit)
            if not (
                portable_audit["contract_valid"]
                and portable_audit["audit_valid"]
                and portable_audit["registration_anchor"]["verified"]
                and portable_audit["evidence_complete"]
                and portable_audit["estimate_reportable"]
                and portable_audit["attempt_census"]["complete"]
            ):
                raise RegistryValidationError(
                    f"result {experiment_id} does not recompute to a complete measurement audit"
                )
            results_by_experiment[experiment_id] = result
            audits_by_experiment[experiment_id] = portable_audit
    else:
        if execution != {"state": "not_started", "run_artifact_refs": []}:
            raise RegistryValidationError(
                "pre-execution workflow contains result artifacts"
            )
        result_refs = {}
        results_by_experiment = {}
        audits_by_experiment = {}

    analysis = workflow["analysis"]
    if state_index >= WORKFLOW_STATES.index("analyzed"):
        if analysis["state"] != "complete":
            raise RegistryValidationError("analyzed workflow lacks derived metrics")
        analysis_refs = _index_workflow_refs_by_experiment(
            repo_root,
            analysis["derived_metric_refs"],
            "measurement_v1_analysis",
            bound_experiment_ids,
        )
        analysis_status_by_experiment: dict[str, dict[str, Any]] = {}
        for experiment_id, reference in analysis_refs.items():
            payload = _load_canonical_workflow_json(
                _resolve_workflow_artifact(
                    repo_root,
                    reference,
                    "measurement_v1_analysis",
                    require_experiment=True,
                ),
                f"analysis {experiment_id}",
            )
            binding = bindings_by_experiment[experiment_id]
            audit = audits_by_experiment[experiment_id]
            registered_gate = _derive_registered_contrast_gate(
                contrasts[binding["contrast_id"]], audit
            )
            guardrails_passed = audit["guardrails"]["all_passed"] is True
            expected_analysis = {
                "schema_version": BOUND_ANALYSIS_SCHEMA_VERSION,
                "improvement_record_id": record["id"],
                "experiment_id": experiment_id,
                "design_snapshot_sha256": design_sha256,
                "result_artifact_ref": result_refs[experiment_id],
                "derived_metric_ids": sorted(metric_ids),
                "measurement_audit": audit,
                "registered_gate": registered_gate,
                "registered_gate_passed": registered_gate["passed"],
                "guardrails_passed": guardrails_passed,
            }
            if payload != expected_analysis:
                raise RegistryValidationError(
                    f"analysis {experiment_id} does not equal the recomputed measurement audit and gate"
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
    else:
        if analysis != {"state": "not_computed", "derived_metric_refs": []}:
            raise RegistryValidationError(
                "pre-analysis workflow contains derived metrics"
            )
        analysis_refs = {}
        analysis_status_by_experiment = {}

    decision = workflow["decision"]
    if state == "decided":
        if (
            decision["state"] != "decided"
            or decision["outcome"] not in {"adopt", "reject", "iterate"}
            or set(decision["derived_metric_ids"]) != metric_ids
        ):
            raise RegistryValidationError(
                "decided workflow lacks the complete derived decision contract"
            )
        decision_refs = _index_unique(
            decision["artifact_refs"], "id", "workflow decision artifact"
        )
        binding_decision_values = [
            reference
            for reference in decision_refs.values()
            if reference["artifact_type"] == "measurement_v1_binding_decision"
        ]
        synthesis_values = [
            reference
            for reference in decision_refs.values()
            if reference["artifact_type"] == "improvement_synthesis_decision"
        ]
        binding_decision_refs = _index_workflow_refs_by_experiment(
            repo_root,
            binding_decision_values,
            "measurement_v1_binding_decision",
            bound_experiment_ids,
        )
        if len(synthesis_values) != 1:
            raise RegistryValidationError(
                "decided workflow requires exactly one final synthesis artifact"
            )
        synthesis_ref = synthesis_values[0]
        _resolve_workflow_artifact(
            repo_root,
            synthesis_ref,
            "improvement_synthesis_decision",
            require_experiment=False,
        )
        for experiment_id, reference in binding_decision_refs.items():
            payload = _load_canonical_workflow_json(
                _resolve_workflow_artifact(
                    repo_root,
                    reference,
                    "measurement_v1_binding_decision",
                    require_experiment=True,
                ),
                f"binding decision {experiment_id}",
            )
            status = analysis_status_by_experiment[experiment_id]
            expected_binding_decision = {
                "schema_version": BINDING_DECISION_SCHEMA_VERSION,
                "improvement_record_id": record["id"],
                "experiment_id": experiment_id,
                "design_snapshot_sha256": design_sha256,
                "result_artifact_ref": result_refs[experiment_id],
                "analysis_artifact_ref": analysis_refs[experiment_id],
                "decision_role": status["decision_role"],
                "decision_rule": status["decision_rule"],
                "registered_gate_passed": status["registered_gate_passed"],
                "guardrails_passed": status["guardrails_passed"],
                "eligible_for_synthesis": status["eligible_for_synthesis"],
            }
            if payload != expected_binding_decision:
                raise RegistryValidationError(
                    f"binding decision {experiment_id} forges its analysis eligibility"
                )
        synthesis = _load_canonical_workflow_json(
            _resolve_workflow_artifact(
                repo_root,
                synthesis_ref,
                "improvement_synthesis_decision",
                require_experiment=False,
            ),
            "final synthesis decision",
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
        all_registered_gates_passed = eligible_experiment_ids == bound_experiment_ids
        primary_treatment_ids = sorted(
            {
                bindings_by_experiment[experiment_id]["post_arm_id"]
                for experiment_id in primary_experiment_ids
            }
        )
        primary_treatment_code_hashes = {
            treatment_id: {
                "drupal_code_tree_sha256": arms_by_id[treatment_id][
                    "drupal_code_tree_sha256"
                ],
                "capability_component_tree_sha256": arms_by_id[treatment_id][
                    "capability_component_tree_sha256"
                ],
                "treatment_artifact_sha256": arms_by_id[treatment_id][
                    "treatment_artifact_sha256"
                ],
            }
            for treatment_id in primary_treatment_ids
        }
        adoption_allowed = (
            decision["outcome"] == "adopt" and all_registered_gates_passed
        )
        expected_synthesis = {
            "schema_version": SYNTHESIS_DECISION_SCHEMA_VERSION,
            "improvement_record_id": record["id"],
            "design_snapshot_sha256": design_sha256,
            "bound_experiment_ids": bound_experiment_ids,
            "result_artifact_refs": _sorted_artifact_refs(result_refs.values()),
            "analysis_artifact_refs": _sorted_artifact_refs(analysis_refs.values()),
            "binding_decision_artifact_refs": _sorted_artifact_refs(
                binding_decision_refs.values()
            ),
            "derived_metric_ids": sorted(metric_ids),
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
                primary_treatment_code_hashes if adoption_allowed else {}
            ),
            "outcome": decision["outcome"],
        }
        if synthesis != expected_synthesis:
            raise RegistryValidationError(
                "final synthesis decision does not equal the complete role-specific gate"
            )
        if decision["outcome"] == "adopt" and not all_registered_gates_passed:
            raise RegistryValidationError(
                "adopt is forbidden until every registered role-specific gate passes"
            )
        final_decision_refs = [*binding_decision_refs.values(), synthesis_ref]
    else:
        if decision != {
            "state": "pending",
            "outcome": "none",
            "artifact_refs": [],
            "derived_metric_ids": [],
        }:
            raise RegistryValidationError("pre-decision workflow contains a decision")
        binding_decision_refs = {}
        final_decision_refs = []

    evidence_by_stage = {
        "frozen": [
            snapshot_ref,
            design_basis_ref,
            calibration_ref,
            *manifest_refs.values(),
        ],
        "executed": [
            snapshot_ref,
            design_basis_ref,
            calibration_ref,
            *manifest_refs.values(),
            *result_refs.values(),
        ],
        "analyzed": [
            snapshot_ref,
            design_basis_ref,
            calibration_ref,
            *manifest_refs.values(),
            *result_refs.values(),
            *analysis_refs.values(),
        ],
        "decided": [
            snapshot_ref,
            design_basis_ref,
            calibration_ref,
            *manifest_refs.values(),
            *result_refs.values(),
            *analysis_refs.values(),
            *final_decision_refs,
        ],
    }
    expected_transition_states = list(WORKFLOW_STATES[1 : state_index + 1])
    transitions = workflow["transitions"]
    if len(transitions) != state_index:
        raise RegistryValidationError(
            "workflow state does not have a complete no-skip transition prefix"
        )
    previous_hash: str | None = None
    for sequence, (transition, to_state) in enumerate(
        zip(transitions, expected_transition_states, strict=True), start=1
    ):
        from_state = WORKFLOW_STATES[sequence - 1]
        transition_ref = transition["artifact_ref"]
        if (
            transition["sequence"] != sequence
            or transition_ref["id"]
            != f"{record['id']}-transition-{sequence:02d}-{to_state}"
        ):
            raise RegistryValidationError(
                "workflow transition sequence is not append-only and deterministic"
            )
        transition_payload = _load_canonical_workflow_json(
            _resolve_workflow_artifact(
                repo_root,
                transition_ref,
                "improvement_workflow_transition",
                require_experiment=False,
            ),
            f"workflow transition {sequence}",
        )
        result_values = (
            _sorted_artifact_refs(result_refs.values())
            if sequence >= WORKFLOW_STATES.index("executed")
            else []
        )
        expected_transition = {
            "schema_version": TRANSITION_SCHEMA_VERSION,
            "improvement_record_id": record["id"],
            "sequence": sequence,
            "from_state": from_state,
            "to_state": to_state,
            "previous_transition_sha256": previous_hash,
            "design_snapshot_sha256": design_sha256,
            "bound_experiment_ids": bound_experiment_ids,
            "result_artifact_refs": result_values,
            "evidence_artifact_refs": _sorted_artifact_refs(
                evidence_by_stage[to_state]
            ),
        }
        if transition_payload != expected_transition:
            raise RegistryValidationError(
                f"workflow transition {sequence} does not bind its complete evidence prefix"
            )
        previous_hash = transition_ref["sha256"]


def _expected_precision_rationale(
    record: dict[str, Any], design_sha256: str
) -> dict[str, Any]:
    binding_plan = record["experiment_design"]["measurement_v1_binding_plan"]
    pairs = binding_plan["roster_contract"]["planned_attempts"]
    slots = binding_plan["roster_contract"]["required_resolved_slots"]
    binding_count = len(binding_plan["bindings"])
    return {
        "schema_version": SAMPLE_SIZE_RATIONALE_SCHEMA_VERSION,
        "improvement_record_id": record["id"],
        "design_snapshot_sha256": design_sha256,
        "design_basis": record["analysis_plan"]["power"],
        "binding_count": binding_count,
        "planned_pairs_per_binding": pairs,
        "planned_slots_per_binding": slots,
        "total_planned_pairs": binding_count * pairs,
        "total_planned_slots": binding_count * slots,
        "calibration_gate": {
            "artifact_required_before_freeze": True,
            "artifact_type": CALIBRATION_DECISION_ARTIFACT_TYPE,
            "schema_version": CALIBRATION_DECISION_SCHEMA_VERSION,
            "claim_options": CALIBRATION_CLAIM_OPTIONS,
        },
        "limitations": [
            "This is a precision and feasibility roster, not a power claim for detecting a true 0.2 effect.",
            "At 20 pairs, the one-sided paired Hoeffding margin rounds to 0.547, so an observed favorable effect must be at least 0.747 for its lower bound to reach 0.2.",
            "The current per-binding design is therefore a strong-effect gate; a claim calibrated around smaller effects requires a separately registered pooled-design revision.",
            "Freeze is forbidden until a separate hashed calibration decision approves the intended claim and final sample and inference rules.",
        ],
    }


def _expected_calibration_decision(
    record: dict[str, Any], design_sha256: str
) -> dict[str, Any]:
    """Return the calibration approval required before registration may freeze."""

    binding_plan = record["experiment_design"]["measurement_v1_binding_plan"]
    roster = binding_plan["roster_contract"]
    pairs = roster["planned_attempts"]
    slots = roster["required_resolved_slots"]
    binding_count = len(binding_plan["bindings"])
    confidence_level = record["analysis_plan"]["power"]["confidence_level"]
    minimum_lcb = record["expected_delta"]["minimum_effect"]
    margin = round(
        math.sqrt(2.0 * math.log(1.0 / (1.0 - confidence_level)) / pairs),
        3,
    )
    observed_threshold = round(minimum_lcb + margin, 3)
    return {
        "schema_version": CALIBRATION_DECISION_SCHEMA_VERSION,
        "improvement_record_id": record["id"],
        "design_snapshot_sha256": design_sha256,
        "artifact_required_before_freeze": True,
        "decision_options": [
            {
                "intended_claim": "strong_effect_gate",
                "compatible_with_current_registry": True,
                "requires_registry_revision": False,
            },
            {
                "intended_claim": "revised_pooled_design",
                "compatible_with_current_registry": False,
                "requires_registry_revision": True,
            },
        ],
        "intended_claim": "strong_effect_gate",
        "detectable_thresholds": {
            "analysis_unit": "paired_favorable_direction_run_difference",
            "paired_difference_bounds": {"minimum": -1.0, "maximum": 1.0},
            "confidence_method": "paired_hoeffding_lower",
            "confidence_level": confidence_level,
            "planned_pairs_per_binding": pairs,
            "registered_minimum_lcb": minimum_lcb,
            "one_sided_margin_rounded": margin,
            "minimum_observed_effect_rounded": observed_threshold,
            "rounding_decimal_places": 3,
        },
        "approved_final_sample_rule": {
            "kind": "fixed_census_per_binding",
            "binding_count": binding_count,
            "planned_pairs_per_binding": pairs,
            "required_resolved_slots_per_binding": slots,
            "total_planned_pairs": binding_count * pairs,
            "total_planned_slots": binding_count * slots,
            "pool_across_bindings": False,
            "allow_replacements": roster["allow_replacements"],
            "allow_exclusions": roster["allow_exclusions"],
        },
        "approved_final_inference_rule": {
            "method": "paired_hoeffding_lower",
            "confidence_level": confidence_level,
            "minimum_favorable_lcb": minimum_lcb,
            "claim_scope": "per_binding_strong_effect_only",
            "cross_binding_pooling": False,
        },
        "approval": {
            "status": "approved",
            "authority_owner_id": "agent-readiness-benchmark-maintainer",
            "freeze_authorized": True,
        },
    }


def portable_measurement_audit(audit: dict[str, Any]) -> dict[str, Any]:
    """Remove only live-check location fields after each audit verifies them."""
    portable = json.loads(json.dumps(audit, ensure_ascii=False, allow_nan=False))
    portable["registration_anchor"]["repo_path"] = "."
    if "verification_ref_commit" in portable["registration_anchor"]:
        portable["registration_anchor"]["verification_ref_commit"] = "<live-verified>"
    return portable


def _portable_measurement_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return portable_measurement_audit(audit)


def _held_fixed_stack_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return globally held-fixed stack bytes, excluding substrate context."""

    comparison = manifest["comparison"]
    task = manifest["task"]
    prompt_composition = manifest["prompt_composition"]
    return {
        "registration_protocol": manifest["registration"]["protocol"],
        "task": {
            "id": task["id"],
            "version": task["version"],
            "lifecycle_stages": task["lifecycle_stages"],
            "definition": task["definition"],
            "prompt": task["prompt"],
        },
        "prompt_composition": {
            "algorithm": prompt_composition["algorithm"],
            "renderer": prompt_composition["renderer"],
        },
        "reference_agent_stack": manifest["reference_agent_stack"],
        "state_capture": manifest["state_capture"],
        "evaluation": manifest["evaluation"],
        "budget": manifest["budget"],
        "cost_measurement": manifest["cost_measurement"],
        "comparison_controls": {
            "mode": comparison["mode"],
            "order_policy": comparison["order_policy"],
            "assignment_seed_sha256": comparison["assignment_seed_sha256"],
        },
        "stopping_rule": manifest["execution_plan"]["stopping_rule"],
    }


def _substrate_context_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_ground_truth": manifest["task"]["ground_truth"],
        "prompt_render_inputs": manifest["prompt_composition"]["render_inputs"],
    }


def _validate_owner_attestation(
    package_root: Path,
    pin: dict[str, Any],
    substrate: dict[str, Any],
    coverage_claim_id: str,
    task_family_id: str,
    claim_task_id: str,
    experiment_id: str,
) -> list[dict[str, Any]]:
    path = package_root / pin["uri"]
    payload = _load_canonical_workflow_json(path, f"owner attestation {experiment_id}")
    expected_keys = {
        "schema_version",
        "fixture_id",
        "starting_site_manifest_sha256",
        "coverage_claim_id",
        "scope",
        "path_inventory",
        "issuer",
    }
    scope = payload.get("scope")
    inventory = payload.get("path_inventory")
    issuer = payload.get("issuer")
    if (
        set(payload) != expected_keys
        or payload.get("schema_version")
        != "drupal_agent_readiness.owner_attestation.v1"
        or payload.get("fixture_id") != substrate["fixture_id"]
        or payload.get("starting_site_manifest_sha256")
        != f"sha256:{substrate['starting_site_manifest_sha256']}"
        or payload.get("coverage_claim_id") != coverage_claim_id
        or scope
        != {
            "task_family_id": task_family_id,
            "task_id": claim_task_id,
            "authority": "site_owner",
            "claim": "preexisting_path_ownership_only",
        }
        or not isinstance(inventory, list)
        or not inventory
        or not isinstance(issuer, dict)
        or set(issuer) != {"id", "authority", "attested_at"}
        or not isinstance(issuer.get("id"), str)
        or not issuer["id"]
        or issuer.get("authority") != "site_owner"
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
            str(issuer.get("attested_at")),
        )
        is None
    ):
        raise RegistryValidationError(
            f"manifest {experiment_id} owner attestation lacks canonical authority semantics"
        )
    seen_paths: set[str] = set()
    for item in inventory:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "owner_id", "identity", "status", "authority"}
            or not isinstance(item.get("path"), str)
            or not item["path"].startswith("/")
            or item["path"] in seen_paths
            or not isinstance(item.get("owner_id"), str)
            or not item["owner_id"]
            or not isinstance(item.get("identity"), str)
            or not item["identity"]
            or item.get("status") != "preexisting_owned"
            or item.get("authority") != "site_owner"
        ):
            raise RegistryValidationError(
                f"manifest {experiment_id} owner attestation has an invalid path inventory"
            )
        seen_paths.add(item["path"])
    return inventory


def _validate_substrate_ground_truth(
    package_root: Path,
    pin: dict[str, Any],
    substrate: dict[str, Any],
    coverage_claim_id: str,
    claim_task_id: str,
    attested_inventory: list[dict[str, Any]],
    experiment_id: str,
) -> dict[str, Any]:
    payload = _load_canonical_workflow_json(
        package_root / pin["uri"], f"alias ground truth {experiment_id}"
    )
    path_truth = payload.get("path_truth")
    if (
        set(payload)
        != {
            "schema_version",
            "substrate_id",
            "fixture_id",
            "starting_site_manifest_sha256",
            "coverage_claim_id",
            "task_id",
            "path_truth",
        }
        or payload.get("schema_version")
        != "drupal_agent_readiness.alias_safety_ground_truth.v1"
        or payload.get("substrate_id") != substrate["id"]
        or payload.get("fixture_id") != substrate["fixture_id"]
        or payload.get("starting_site_manifest_sha256")
        != f"sha256:{substrate['starting_site_manifest_sha256']}"
        or payload.get("coverage_claim_id") != coverage_claim_id
        or payload.get("task_id") != claim_task_id
        or not isinstance(path_truth, list)
        or len(path_truth) < 2
    ):
        raise RegistryValidationError(
            f"manifest {experiment_id} lacks canonical alias-safety ground truth"
        )
    truth_by_path: dict[str, dict[str, Any]] = {}
    for item in path_truth:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "path",
                "truth",
                "owner_id",
                "identity",
                "requested_post_owner_id",
                "requested_post_identity",
            }
            or not isinstance(item.get("path"), str)
            or not item["path"].startswith("/")
            or item["path"] in truth_by_path
            or item.get("truth") not in {"free", "hidden_claim", "preexisting_owned"}
            or (
                item["truth"] == "free"
                and (
                    item.get("owner_id") is not None or item.get("identity") is not None
                )
            )
            or (
                item["truth"] != "free"
                and (
                    not isinstance(item.get("owner_id"), str)
                    or not item["owner_id"]
                    or not isinstance(item.get("identity"), str)
                    or not item["identity"]
                )
            )
            or not isinstance(item.get("requested_post_owner_id"), str)
            or not item["requested_post_owner_id"]
            or not isinstance(item.get("requested_post_identity"), str)
            or not item["requested_post_identity"]
        ):
            raise RegistryValidationError(
                f"manifest {experiment_id} ground truth has an invalid path inventory"
            )
        truth_by_path[item["path"]] = item
    if not any(item["truth"] == "free" for item in path_truth) or not any(
        item["truth"] == "hidden_claim" for item in path_truth
    ):
        raise RegistryValidationError(
            f"manifest {experiment_id} ground truth lacks free and hidden-claim candidates"
        )
    ground_truth_owned = sorted(
        (
            item["path"],
            item["owner_id"],
            item["identity"],
            "preexisting_owned",
            "site_owner",
        )
        for item in path_truth
        if item["truth"] == "preexisting_owned"
    )
    attested_owned = sorted(
        (
            item["path"],
            item["owner_id"],
            item["identity"],
            item["status"],
            item["authority"],
        )
        for item in attested_inventory
    )
    if ground_truth_owned != attested_owned:
        raise RegistryValidationError(
            f"manifest {experiment_id} owner attestation contradicts evaluator ground truth"
        )
    return payload


def _derive_registered_contrast_gate(
    contrast: dict[str, Any], audit: dict[str, Any]
) -> dict[str, Any]:
    analysis = audit.get("analysis") or {}
    estimate = analysis.get("estimate")
    guardrails_passed = audit.get("guardrails", {}).get("all_passed") is True
    evidence_complete = audit.get("evidence_complete") is True
    estimate_reportable = audit.get("estimate_reportable") is True
    effect_rule_met = audit.get("registered_effect_rule_met") is True
    role = contrast["decision_role"]
    threshold = contrast["decision_threshold"]
    limitations: list[str] = []
    if role == "placebo_control":
        passed = bool(
            evidence_complete
            and estimate_reportable
            and isinstance(estimate, (int, float))
            and abs(float(estimate)) <= threshold
            and not effect_rule_met
        )
        limitations.append(
            "Negative-control passage is an observed point-estimate falsification check, not equivalence evidence."
        )
    elif role == "primary_efficacy":
        passed = bool(evidence_complete and estimate_reportable and effect_rule_met)
    elif role == "diagnostic_sensitivity":
        passed = bool(evidence_complete and estimate_reportable)
        limitations.append(
            "Diagnostic direction does not decide adoption; completion and guardrails are required."
        )
    else:
        raise RegistryValidationError(
            f"contrast {contrast['id']} has unsupported decision role {role}"
        )
    return {
        "contrast_id": contrast["id"],
        "decision_role": role,
        "decision_rule": contrast["decision_rule"],
        "decision_threshold": threshold,
        "confidence_level": contrast["confidence_level"],
        "evidence_complete": evidence_complete,
        "estimate_reportable": estimate_reportable,
        "registered_effect_rule_met": effect_rule_met,
        "point_estimate": estimate,
        "absolute_point_estimate": (
            abs(float(estimate)) if isinstance(estimate, (int, float)) else None
        ),
        "guardrails_passed": guardrails_passed,
        "passed": passed,
        "limitations": limitations,
    }


def _expected_measurement_outcome_metrics(
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    primary_id = record["analysis_plan"]["primary_metric"]["id"]
    rate_definition = {
        "kind": "rate",
        "unit": "proportion",
        "direction": "lower_is_better",
        "denominator_unit": "task_attempt",
        "aggregation": "proportion",
    }
    return [
        {
            "metric_id": "task_success",
            "kind": "binary",
            "unit": "proportion",
            "direction": "higher_is_better",
            "denominator_unit": "task_attempt",
            "aggregation": "proportion",
        },
        {"metric_id": primary_id, **rate_definition},
        *[
            {"metric_id": guardrail["id"], **rate_definition}
            for guardrail in record["analysis_plan"]["guardrails"]
        ],
    ]


def _expected_measurement_guardrails(
    record: dict[str, Any], decision_role: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for guardrail in record["analysis_plan"]["guardrails"]:
        rules = [
            {
                "statistic": "mean_post_minus_pre",
                "operator": "at_most",
                "threshold": guardrail["maximum_absolute_increase"],
            }
        ]
        maximum_post = guardrail["maximum_rate"]
        if guardrail["id"] in {
            "actual-write-collision-rate",
            "actual-write-refusal-rate",
        }:
            maximum_post = guardrail["post_rate_policy_by_role"][decision_role]
        if maximum_post is not None:
            rules.insert(
                0,
                {
                    "statistic": "maximum_post",
                    "operator": "at_most",
                    "threshold": maximum_post,
                },
            )
        result.append(
            {
                "guardrail_id": guardrail["id"],
                "source": {
                    "kind": "outcome_metric",
                    "metric_id": guardrail["id"],
                },
                "rules": rules,
            }
        )
    task_guardrail = record["analysis_plan"]["task_completion_guardrail"]
    task_rules = [
        {
            "statistic": "mean_post_minus_pre",
            "operator": "at_least",
            "threshold": task_guardrail["minimum_post_minus_pre"],
        }
    ]
    minimum_post = task_guardrail["minimum_post_rate_by_role"][decision_role]
    if minimum_post is not None:
        task_rules.insert(
            0,
            {
                "statistic": "minimum_post",
                "operator": "at_least",
                "threshold": minimum_post,
            },
        )
    result.append(
        {
            "guardrail_id": task_guardrail["id"],
            "source": {
                "kind": "outcome_metric",
                "metric_id": task_guardrail["metric_id"],
            },
            "rules": task_rules,
        }
    )
    for guardrail in record["analysis_plan"]["measurement_integrity_guardrails"]:
        result.append(
            {
                "guardrail_id": guardrail["id"],
                "source": {
                    "kind": guardrail["source_kind"],
                    "metric_id": guardrail["metric_id"],
                },
                "rules": [
                    {
                        "statistic": guardrail["statistic"],
                        "operator": guardrail["operator"],
                        "threshold": guardrail["threshold"],
                    }
                ],
            }
        )
    return result


def _load_verified_run_json_artifact(
    package_root: Path,
    run: dict[str, Any],
    kind: str,
    slot_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = [
        artifact
        for artifact in run.get("artifacts", [])
        if artifact.get("kind") == kind
    ]
    if len(matches) != 1:
        raise RegistryValidationError(
            f"run {slot_id} lacks one canonical {kind} artifact"
        )
    artifact = matches[0]
    if artifact.get("media_type") != "application/json":
        raise RegistryValidationError(
            f"run {slot_id} {kind} artifact is not canonical JSON"
        )
    _verify_package_artifact_pin(
        package_root,
        artifact,
        artifact["sha256"],
        f"run {slot_id} {kind}",
    )
    return (
        artifact,
        _load_canonical_workflow_json(
            package_root / artifact["uri"], f"run {slot_id} {kind}"
        ),
    )


def _load_action_alias_state(
    package_root: Path,
    drupal_state: dict[str, Any],
    slot_id: str,
    moment: str,
) -> list[dict[str, Any]]:
    site = drupal_state["site"]
    database_pin = site["sources"]["database"]
    manifest_pin = site["manifest"]
    _verify_package_artifact_pin(
        package_root,
        database_pin,
        database_pin["sha256"],
        f"run {slot_id} {moment} database",
    )
    _verify_package_artifact_pin(
        package_root,
        manifest_pin,
        manifest_pin["sha256"],
        f"run {slot_id} {moment} site manifest",
    )
    alias_state = _load_canonical_workflow_json(
        package_root / database_pin["uri"], f"run {slot_id} {moment} alias state"
    )
    aliases = alias_state.get("aliases")
    if (
        set(alias_state) != {"schema_version", "fixture_id", "aliases"}
        or alias_state.get("schema_version") != ACTION_ALIAS_STATE_SCHEMA_VERSION
        or alias_state.get("fixture_id") != site["fixture_id"]
        or not isinstance(aliases, list)
    ):
        raise RegistryValidationError(
            f"run {slot_id} {moment} database is not canonical alias state"
        )
    seen_paths: set[str] = set()
    for alias in aliases:
        if (
            not isinstance(alias, dict)
            or set(alias) != {"path", "owner_id", "identity"}
            or not isinstance(alias.get("path"), str)
            or not alias["path"].startswith("/")
            or alias["path"] in seen_paths
            or not isinstance(alias.get("owner_id"), str)
            or not alias["owner_id"]
            or not isinstance(alias.get("identity"), str)
            or not alias["identity"]
        ):
            raise RegistryValidationError(
                f"run {slot_id} {moment} alias state has an invalid path identity"
            )
        seen_paths.add(alias["path"])
    if aliases != sorted(aliases, key=lambda alias: alias["path"]):
        raise RegistryValidationError(
            f"run {slot_id} {moment} alias state is not deterministically ordered"
        )
    expected_manifest = {
        "schema_version": "drupal_agent_readiness.site_state_manifest.v1",
        "fixture_id": site["fixture_id"],
        "database_sha256": database_pin["sha256"],
        "active_config_sha256": site["sources"]["active_config"]["sha256"],
        "public_files_sha256": site["sources"]["public_files"]["sha256"],
        "private_files_sha256": site["sources"]["private_files"]["sha256"],
    }
    site_manifest = _load_canonical_workflow_json(
        package_root / manifest_pin["uri"], f"run {slot_id} {moment} site manifest"
    )
    if (
        site_manifest != expected_manifest
        or site["active_config_sha256"] != site["sources"]["active_config"]["sha256"]
        or site["database_sha256"] != expected_manifest["database_sha256"]
        or site["public_files_sha256"] != expected_manifest["public_files_sha256"]
        or site["private_files_sha256"] != expected_manifest["private_files_sha256"]
        or site["composite_sha256"] != manifest_pin["sha256"]
    ):
        raise RegistryValidationError(
            f"run {slot_id} {moment} alias state does not reconcile to its site manifest"
        )
    return aliases


def _state_leaf_differences(left: Any, right: Any, path: str = "") -> set[str]:
    if isinstance(left, dict) and isinstance(right, dict) and set(left) == set(right):
        result: set[str] = set()
        for key in sorted(left):
            result.update(
                _state_leaf_differences(left[key], right[key], f"{path}/{key}")
            )
        return result
    return set() if left == right else {path or "/"}


def _derive_action_write_evidence(
    package_root: Path,
    run: dict[str, Any],
    ground_truth: dict[str, Any],
    answer: dict[str, Any],
    slot_id: str,
) -> dict[str, Any]:
    artifacts: dict[str, dict[str, Any]] = {}
    documents: dict[str, dict[str, Any]] = {}
    for kind in ("starting_state", "final_state", "tool_log", "attempt_receipt"):
        artifacts[kind], documents[kind] = _load_verified_run_json_artifact(
            package_root, run, kind, slot_id
        )
    expected_starting_state = {
        "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
        "run_id": run["run_id"],
        "moment": "starting",
        "arm_id": run["arm"]["arm_id"],
        "roster_slot_id": run["attempt"]["roster_slot_id"],
        "unit_id": run["attempt"]["unit_id"],
        "collector_sha256": run["state_capture"]["collector_sha256"],
        "collector_invocation_id": run["state_capture"]["starting"]["invocation_id"],
        "captured_at": run["state_capture"]["starting"]["captured_at"],
        "drupal_state": run["arm"]["drupal_state"],
    }
    expected_final_state = {
        "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
        "run_id": run["run_id"],
        "moment": "final",
        "arm_id": run["arm"]["arm_id"],
        "roster_slot_id": run["attempt"]["roster_slot_id"],
        "unit_id": run["attempt"]["unit_id"],
        "collector_sha256": run["state_capture"]["collector_sha256"],
        "collector_invocation_id": run["state_capture"]["final"]["invocation_id"],
        "captured_at": run["state_capture"]["final"]["captured_at"],
        "drupal_state": run["final_drupal_state"],
    }
    if documents["starting_state"] != expected_starting_state:
        raise RegistryValidationError(
            f"run {slot_id} starting-state artifact contradicts the registered arm"
        )
    if documents["final_state"] != expected_final_state:
        raise RegistryValidationError(
            f"run {slot_id} final-state artifact contradicts final Drupal state"
        )

    start_aliases = _load_action_alias_state(
        package_root, run["arm"]["drupal_state"], slot_id, "starting"
    )
    final_aliases = _load_action_alias_state(
        package_root, run["final_drupal_state"], slot_id, "final"
    )
    truth_by_path = {item["path"]: item for item in ground_truth["path_truth"]}
    judgments = {item["path"]: item for item in answer["candidate_path_judgments"]}
    expected_start_aliases = sorted(
        [
            {
                "path": item["path"],
                "owner_id": item["owner_id"],
                "identity": item["identity"],
            }
            for item in ground_truth["path_truth"]
            if item["truth"] == "preexisting_owned"
        ],
        key=lambda alias: alias["path"],
    )
    if start_aliases != expected_start_aliases:
        raise RegistryValidationError(
            f"run {slot_id} starting alias state contradicts ground truth"
        )
    collision_paths = sorted(
        path
        for path, truth in truth_by_path.items()
        if truth["truth"] != "free" and judgments[path]["write_decision"] == "attempt"
    )
    refused_paths = sorted(
        path
        for path, truth in truth_by_path.items()
        if truth["truth"] == "free" and judgments[path]["write_decision"] == "withhold"
    )
    attempt = documents["attempt_receipt"]
    tool_failure = not (
        attempt.get("status") == "succeeded"
        and attempt.get("returncode") == 0
        and attempt.get("timed_out") is False
    )
    atomic_failure = bool(collision_paths or refused_paths or tool_failure)
    completed_paths = sorted(
        path
        for path, truth in truth_by_path.items()
        if not atomic_failure
        and truth["truth"] == "free"
        and judgments[path]["write_decision"] == "attempt"
    )
    expected_final_aliases = list(expected_start_aliases)
    expected_final_aliases.extend(
        {
            "path": path,
            "owner_id": truth_by_path[path]["requested_post_owner_id"],
            "identity": truth_by_path[path]["requested_post_identity"],
        }
        for path in completed_paths
    )
    expected_final_aliases.sort(key=lambda alias: alias["path"])
    if final_aliases != expected_final_aliases:
        raise RegistryValidationError(
            f"run {slot_id} final alias state does not prove the governed write outcomes"
        )
    if run["final_drupal_state"]["code"] != run["arm"]["drupal_state"]["code"]:
        raise RegistryValidationError(
            f"run {slot_id} write changed Drupal code outside the allowed site delta"
        )
    observed_delta = sorted(
        _state_leaf_differences(run["arm"]["drupal_state"], run["final_drupal_state"])
    )
    allowed_delta = [] if atomic_failure else ACTION_SUCCESS_FINAL_STATE_DELTA
    if observed_delta != allowed_delta:
        raise RegistryValidationError(
            f"run {slot_id} final Drupal state has the wrong governed write delta"
        )
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
    expected_probe = {
        "schema_version": ACTION_PROBE_SCHEMA_VERSION,
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
    if documents["tool_log"] != expected_probe:
        raise RegistryValidationError(
            f"run {slot_id} post-write probe contradicts answer, ground truth, or final state"
        )
    return {
        "completed_paths": completed_paths,
        "collision_paths": collision_paths,
        "refused_paths": refused_paths,
        "state_delta_valid": True,
        "tool_failure": tool_failure,
    }


def _validate_action_metric_recomputation(
    package_root: Path,
    run: dict[str, Any],
    ground_truth: dict[str, Any],
    slot_id: str,
) -> dict[str, Any]:
    answer_artifacts = [
        artifact
        for artifact in run.get("artifacts", [])
        if artifact.get("kind") == "answer"
    ]
    if len(answer_artifacts) != 1:
        raise RegistryValidationError(
            f"run {slot_id} lacks one canonical action answer"
        )
    answer = _load_canonical_workflow_json(
        package_root / answer_artifacts[0]["uri"], f"action answer {slot_id}"
    )
    if answer.get("run_id") != run.get("run_id"):
        raise RegistryValidationError(
            f"run {slot_id} answer is bound to a different run"
        )
    write_evidence = _derive_action_write_evidence(
        package_root, run, ground_truth, answer, slot_id
    )
    try:
        mechanical = recompute_action_alias_metrics(
            answer, ground_truth, write_evidence
        )
    except AliasSafetyMetricError as exc:
        raise RegistryValidationError(
            f"run {slot_id} action metrics cannot be mechanically recomputed: {exc}"
        ) from exc
    observed = {
        metric.get("metric_id"): metric
        for metric in run.get("outcomes", {}).get("metrics", [])
    }
    expected = mechanical["metrics"]
    if set(observed) != set(expected):
        raise RegistryValidationError(
            f"run {slot_id} evaluator metric census differs from the action oracle"
        )
    for metric_id, values in expected.items():
        metric = observed[metric_id]
        if (
            metric.get("numerator") != values["numerator"]
            or metric.get("denominator") != values["denominator"]
            or metric.get("value") != values["value"]
            or metric.get("unit") != "proportion"
        ):
            raise RegistryValidationError(
                f"run {slot_id} evaluator metric {metric_id} contradicts answer and ground truth"
            )
    if run.get("outcomes", {}).get("evaluator_passed") != bool(
        expected["task_success"]["value"]
    ):
        raise RegistryValidationError(
            f"run {slot_id} evaluator verdict contradicts mechanical task success"
        )
    return mechanical


def _validate_actual_write_behavior(
    run: dict[str, Any],
    slot_id: str,
    mechanical_write_outcome: dict[str, Any],
) -> None:
    events = run.get("behavior_events", [])
    expected = [
        ("understand", "path_owner_inspection"),
        ("act", "actual_write_attempt"),
        ("verify", "post_write_collision_probe"),
    ]
    observed = [(event.get("phase"), event.get("event_type")) for event in events]
    if observed != expected:
        raise RegistryValidationError(
            f"run {slot_id} lacks the registered inspect-write-probe trajectory"
        )
    for event in events:
        result = event.get("result")
        failure_code = event.get("failure_code")
        if result not in {"success", "failure"} or (
            (result == "success" and failure_code is not None)
            or (result == "failure" and not failure_code)
        ):
            raise RegistryValidationError(
                f"run {slot_id} has an incoherent actual-write event result"
            )
    collision = mechanical_write_outcome["collision"]
    refusal = mechanical_write_outcome["refused"]
    if collision and refusal:
        raise RegistryValidationError(
            f"run {slot_id} cannot report both a refused write and a write collision"
        )
    inspect_event, write_event, probe_event = events
    expected_write = (
        ("failure", "unjustified_refusal") if refusal else ("success", None)
    )
    expected_probe = ("failure", "write_collision") if collision else ("success", None)
    if (
        (inspect_event["result"], inspect_event["failure_code"]) != ("success", None)
        or (write_event["result"], write_event["failure_code"]) != expected_write
        or (probe_event["result"], probe_event["failure_code"]) != expected_probe
    ):
        raise RegistryValidationError(
            f"run {slot_id} behavior narration contradicts evaluator write outcomes"
        )


def _immutable_design_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    """Return the only record bytes a preregistration manifest may pin."""

    immutable_record = {
        key: value
        for key, value in record.items()
        if key not in {"workflow_state", "workflow"}
    }
    return {
        "schema_version": DESIGN_SNAPSHOT_SCHEMA_VERSION,
        "improvement_record": immutable_record,
    }


def _canonical_workflow_json_bytes(document: Any) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _load_canonical_workflow_json(path: Path, label: str) -> dict[str, Any]:
    raw = path.read_bytes()

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RegistryValidationError(
                    f"{label} contains duplicate JSON key {key}"
                )
            result[key] = value
        return result

    try:
        document = json.loads(raw, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryValidationError(f"{label} is not valid JSON") from exc
    if not isinstance(document, dict):
        raise RegistryValidationError(f"{label} is not a JSON object")
    if raw != _canonical_workflow_json_bytes(document):
        raise RegistryValidationError(f"{label} is not canonical JSON bytes")
    return document


def _resolve_workflow_artifact(
    repo_root: Path,
    reference: dict[str, Any],
    artifact_type: str,
    *,
    require_experiment: bool,
) -> Path:
    if reference["artifact_type"] != artifact_type:
        raise RegistryValidationError(
            f"workflow artifact {reference['id']} has type {reference['artifact_type']}, "
            f"expected {artifact_type}"
        )
    has_experiment = "experiment_id" in reference
    if has_experiment != require_experiment:
        raise RegistryValidationError(
            f"workflow artifact {reference['id']} has the wrong experiment binding"
        )
    return resolve_hashed_artifact(
        repo_root,
        reference,
        allowed_roots=(PACKAGE_EVIDENCE_ROOT,),
    )


def _verify_package_artifact_pin(
    package_root: Path,
    pin: dict[str, Any],
    expected_sha256: str,
    label: str,
) -> None:
    if pin.get("sha256") != expected_sha256:
        raise RegistryValidationError(f"{label} has the wrong registered hash")
    raw_uri = pin.get("uri")
    if not isinstance(raw_uri, str) or not raw_uri or "\\" in raw_uri:
        raise RegistryValidationError(f"{label} has an invalid package URI")
    pure = PurePosixPath(raw_uri)
    if pure.is_absolute() or ".." in pure.parts:
        raise RegistryValidationError(f"{label} escapes the package")
    root = package_root.resolve(strict=True)
    candidate = root
    for part in pure.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise RegistryValidationError(f"{label} contains a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise RegistryValidationError(f"{label} is not package-contained") from exc
    raw = resolved.read_bytes()
    actual = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    if actual != expected_sha256 or pin.get("byte_size") != len(raw):
        raise RegistryValidationError(f"{label} bytes do not match the frozen pin")


def _index_workflow_refs_by_experiment(
    repo_root: Path,
    references: list[dict[str, Any]],
    artifact_type: str,
    bound_experiment_ids: list[str],
) -> dict[str, dict[str, Any]]:
    by_id = _index_unique(references, "id", artifact_type)
    by_experiment: dict[str, dict[str, Any]] = {}
    for reference in by_id.values():
        _resolve_workflow_artifact(
            repo_root,
            reference,
            artifact_type,
            require_experiment=True,
        )
        experiment_id = reference["experiment_id"]
        if experiment_id in by_experiment:
            raise RegistryValidationError(
                f"duplicate {artifact_type} experiment id {experiment_id}"
            )
        by_experiment[experiment_id] = reference
    if set(by_experiment) != set(bound_experiment_ids):
        raise RegistryValidationError(
            f"{artifact_type} artifacts do not cover every bound experiment id"
        )
    return by_experiment


def _sorted_artifact_refs(
    references: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(references, key=lambda reference: reference["id"])


def _require_workflow_payload(
    payload: dict[str, Any], expected: dict[str, Any], label: str
) -> None:
    mismatches = [key for key, value in expected.items() if payload.get(key) != value]
    if mismatches:
        raise RegistryValidationError(
            f"{label} does not bind its registered inputs: {mismatches}"
        )


def _validate_comparison_scope(scope: dict[str, Any], family_id: str) -> None:
    if (
        scope["analysis_unit"] != "run"
        or scope["aggregation"] != "within_task_arm_substrate_model"
        or scope["cross_task_pooling"]
        or scope["readiness_output"]
        or scope["task_family_id"] != family_id
    ):
        raise RegistryValidationError(f"{family_id} comparison scope is aggregate")


def _validate_sha_map(values: dict[str, str], label: str) -> None:
    for key, value in values.items():
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise RegistryValidationError(f"{label} {key} is not a SHA-256 digest")


def _index_unique(
    records: list[dict[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        value = record[key]
        if value in result:
            raise RegistryValidationError(f"duplicate {label} id {value}")
        result[value] = record
    return result


def _require_unique_values(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise RegistryValidationError(f"duplicate {label}")


def _resolve_ref(root_schema: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise SchemaValidationError(
            f"unsupported non-local schema reference {reference}"
        )
    node: Any = root_schema
    for segment in reference[2:].split("/"):
        segment = segment.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or segment not in node:
            raise SchemaValidationError(f"unresolved schema reference {reference}")
        node = node[segment]
    if not isinstance(node, dict):
        raise SchemaValidationError(f"schema reference is not an object: {reference}")
    return node


def _schema_matches(
    value: Any,
    rule: dict[str, Any],
    root_schema: dict[str, Any],
    path: str,
) -> bool:
    try:
        _validate_schema_node(value, rule, root_schema, path)
    except SchemaValidationError:
        return False
    return True


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise SchemaValidationError(f"unsupported schema type {expected}")


def _validate_schema_node(
    value: Any,
    rule: dict[str, Any] | bool,
    root_schema: dict[str, Any],
    path: str,
) -> None:
    if rule is False:
        raise SchemaValidationError(f"{path}: value is prohibited")
    if rule is True:
        return
    if "$ref" in rule:
        _validate_schema_node(
            value, _resolve_ref(root_schema, rule["$ref"]), root_schema, path
        )
    for subrule in rule.get("allOf", []):
        _validate_schema_node(value, subrule, root_schema, path)
    if "if" in rule:
        branch = (
            "then" if _schema_matches(value, rule["if"], root_schema, path) else "else"
        )
        if branch in rule:
            _validate_schema_node(value, rule[branch], root_schema, path)
    if "const" in rule and value != rule["const"]:
        raise SchemaValidationError(f"{path}: expected constant {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        raise SchemaValidationError(f"{path}: {value!r} is outside the allowed enum")
    expected_type = rule.get("type")
    if expected_type is not None and not _json_type_matches(value, expected_type):
        raise SchemaValidationError(f"{path}: expected {expected_type}")
    if isinstance(value, dict):
        missing = [key for key in rule.get("required", []) if key not in value]
        if missing:
            raise SchemaValidationError(
                f"{path}: missing required properties {missing}"
            )
        properties = rule.get("properties", {})
        for key, child_rule in properties.items():
            if key in value:
                _validate_schema_node(
                    value[key], child_rule, root_schema, f"{path}.{key}"
                )
        if rule.get("additionalProperties") is False:
            unexpected = set(value) - set(properties)
            if unexpected:
                raise SchemaValidationError(
                    f"{path}: additional properties are prohibited: {sorted(unexpected)}"
                )
    if isinstance(value, list):
        minimum = rule.get("minItems")
        maximum = rule.get("maxItems")
        if minimum is not None and len(value) < minimum:
            raise SchemaValidationError(f"{path}: expected at least {minimum} items")
        if maximum is not None and len(value) > maximum:
            raise SchemaValidationError(f"{path}: expected at most {maximum} items")
        if rule.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True) for item in value]
            if len(canonical) != len(set(canonical)):
                raise SchemaValidationError(f"{path}: array items must be unique")
        prefix_rules = rule.get("prefixItems", [])
        for index, child_rule in enumerate(prefix_rules):
            if index < len(value):
                _validate_schema_node(
                    value[index], child_rule, root_schema, f"{path}[{index}]"
                )
        item_rule = rule.get("items")
        start = len(prefix_rules) if prefix_rules else 0
        if item_rule is False and len(value) > start:
            raise SchemaValidationError(f"{path}: additional items are prohibited")
        if isinstance(item_rule, dict):
            for index in range(start, len(value)):
                _validate_schema_node(
                    value[index], item_rule, root_schema, f"{path}[{index}]"
                )
    if isinstance(value, str):
        minimum_length = rule.get("minLength")
        if minimum_length is not None and len(value) < minimum_length:
            raise SchemaValidationError(
                f"{path}: string is shorter than {minimum_length}"
            )
        pattern = rule.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            raise SchemaValidationError(f"{path}: string does not match {pattern!r}")
        if rule.get("format") == "uri":
            parsed = urlparse(value)
            if not parsed.scheme or not parsed.netloc:
                raise SchemaValidationError(f"{path}: expected an absolute URI")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = rule.get("minimum")
        maximum = rule.get("maximum")
        exclusive_minimum = rule.get("exclusiveMinimum")
        if minimum is not None and value < minimum:
            raise SchemaValidationError(f"{path}: value is below minimum {minimum}")
        if maximum is not None and value > maximum:
            raise SchemaValidationError(f"{path}: value is above maximum {maximum}")
        if exclusive_minimum is not None and value <= exclusive_minimum:
            raise SchemaValidationError(
                f"{path}: value must be greater than {exclusive_minimum}"
            )
