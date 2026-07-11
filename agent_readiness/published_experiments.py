"""Normalize published experiment evidence into one auditable data plane.

The historical experiments in this repository predate the v1 measurement
contract and use different result shapes.  This module does not upgrade their
evidence class.  It verifies their registered source hashes, normalizes only the
facts present in those sources, and makes reports consume those facts instead of
copying headline numbers into prose.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from agent_readiness.alias_safety_metrics import (
    AliasSafetyMetricError,
    validate_retained_alias_safety_results,
)
from agent_readiness.benchmark_registries_v1 import (
    RegistryValidationError,
    load_default_registries,
    portable_measurement_audit,
    validated_improvement_projections,
)
from agent_readiness.measurement_v1 import (
    GitRegistrationAnchor,
    audit_measurement_v1,
    canonical_json_bytes,
)

SCHEMA_VERSION = "drupal_agent_readiness.published_experiments.v1"
REGISTRY_SCHEMA_VERSION = "drupal_agent_readiness.experiment_registry.v1"
DEFAULT_REGISTRY = Path("experiments/published-experiments-v1.json")


class PublishedExperimentError(ValueError):
    """Raised when published evidence cannot be tied to its registered source."""


def load_published_experiments(
    base_dir: Path,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Load, hash-check, and normalize every registered public experiment."""
    base_dir = base_dir.resolve()
    registry_path = (registry_path or (base_dir / DEFAULT_REGISTRY)).resolve()
    try:
        registry_path.relative_to(base_dir)
    except ValueError as exc:
        raise PublishedExperimentError(
            f"registry escapes package root: {registry_path}"
        ) from exc
    registry = _load_json(registry_path)
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise PublishedExperimentError(
            f"{registry_path}: expected schema_version {REGISTRY_SCHEMA_VERSION!r}"
        )
    entries = registry.get("experiments")
    if not isinstance(entries, list) or not entries:
        raise PublishedExperimentError(f"{registry_path}: experiments must be a non-empty list")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    action_registry_cache: dict[str, Any] = {}
    for entry in entries:
        experiment_id = str(entry.get("experiment_id", ""))
        if not experiment_id:
            raise PublishedExperimentError("experiment entry missing experiment_id")
        if experiment_id in seen:
            raise PublishedExperimentError(f"duplicate experiment_id: {experiment_id}")
        seen.add(experiment_id)
        adapter = entry.get("adapter")
        if adapter == "alias_safety_v0":
            normalized.append(_normalize_alias_safety(base_dir, entry))
        elif adapter == "intent_behavior_summary_v0":
            normalized.append(_normalize_intent_behavior(base_dir, entry))
        elif adapter == "measurement_v1":
            normalized.append(
                _normalize_measurement_v1(
                    base_dir,
                    entry,
                    action_registry_cache,
                )
            )
        else:
            raise PublishedExperimentError(
                f"{experiment_id}: unsupported adapter {adapter!r}"
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "registry": str(registry_path.relative_to(base_dir)),
        "experiments": normalized,
    }


def render_experiment_markdown(bundle: dict[str, Any]) -> list[str]:
    """Render all public experiment numbers strictly from normalized evidence."""
    lines: list[str] = []
    for experiment in bundle.get("experiments", []):
        if experiment["adapter"] == "alias_safety_v0":
            lines.extend(_render_alias_safety(experiment))
        elif experiment["adapter"] == "intent_behavior_summary_v0":
            lines.extend(_render_intent_behavior(experiment))
        elif experiment["adapter"] == "measurement_v1":
            lines.extend(_render_measurement_v1(experiment))
    if not lines:
        return ["No registered experiment evidence was supplied."]
    return lines


def _normalize_alias_safety(base_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    metrics: list[dict[str, Any]] = []
    source_groups = entry.get("sources")
    if not isinstance(source_groups, dict) or set(source_groups) != {"headline", "breadth"}:
        raise PublishedExperimentError(
            f"{entry['experiment_id']}: alias sources must contain headline and breadth"
        )
    for source_class in ("headline", "breadth"):
        group = source_groups[source_class]
        if not isinstance(group, dict) or set(group) != {"raw", "ground_truth", "derived"}:
            raise PublishedExperimentError(
                f"{entry['experiment_id']}: {source_class} must pin raw, ground_truth, and derived"
            )
        raw = _load_registered_pointer(
            base_dir,
            group["raw"],
            f"{entry['experiment_id']}.{source_class}.raw",
        )
        ground_truth = _load_registered_pointer(
            base_dir,
            group["ground_truth"],
            f"{entry['experiment_id']}.{source_class}.ground_truth",
        )
        derived = _load_registered_pointer(
            base_dir,
            group["derived"],
            f"{entry['experiment_id']}.{source_class}.derived",
        )
        try:
            validate_retained_alias_safety_results(raw, ground_truth, derived)
        except AliasSafetyMetricError as exc:
            raise PublishedExperimentError(
                f"{entry['experiment_id']}: {source_class} metrics do not recompute: {exc}"
            ) from exc
        summary = derived.get("summary")
        if not isinstance(summary, dict) or not summary:
            raise PublishedExperimentError(
                f"{entry['experiment_id']}: {source_class} source missing summary cells"
            )
        for cell_id, cell in sorted(summary.items()):
            model_id = cell.get("model_id")
            source_cell = derived.get("cells", {}).get(cell_id, {})
            source_runs = source_cell.get("runs")
            if not isinstance(source_runs, list):
                raise PublishedExperimentError(
                    f"{entry['experiment_id']}: {cell_id} source runs missing"
                )
            for arm_key, arm_name, source_arm in (
                ("raw_drush", "raw_drush", "raw"),
                ("site_architecture", "site_architecture", "equipped"),
            ):
                arm = cell.get(arm_key)
                if not isinstance(arm, dict):
                    raise PublishedExperimentError(
                        f"{entry['experiment_id']}: {cell_id}.{arm_key} missing"
                    )
                arm_runs = [run for run in source_runs if run.get("arm") == source_arm]
                expected_runs = _required_int(arm, "n", entry["experiment_id"])
                if len(arm_runs) != expected_runs:
                    raise PublishedExperimentError(
                        f"{entry['experiment_id']}: {cell_id}.{arm_key} run census differs from summary"
                    )
                runs_all_hidden_correct = sum(
                    1
                    for run in arm_runs
                    if run.get("latent_correct") == run.get("latent_total")
                    and type(run.get("latent_total")) is int
                    and run["latent_total"] > 0
                )
                metrics.append({
                    "source_class": source_class,
                    "cell_id": cell_id,
                    "condition": cell.get("condition"),
                    "model_id": model_id,
                    "arm": arm_name,
                    "runs": expected_runs,
                    "passes": _required_int(arm, "passes", entry["experiment_id"]),
                    "runs_all_hidden_correct": runs_all_hidden_correct,
                    "latent_correct": _required_int(arm, "latent_correct", entry["experiment_id"]),
                    "latent_total": _required_int(arm, "latent_total", entry["experiment_id"]),
                    "latent_reasoned": _required_int(arm, "latent_reasoned", entry["experiment_id"]),
                    "avg_commands_self_reported": arm.get("avg_commands"),
                })

    return _base_normalized(entry, metrics)


def _normalize_intent_behavior(base_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    source = _load_registered_source(base_dir, entry, "summary")
    arms = source.get("by_arm")
    if not isinstance(arms, list) or not arms:
        raise PublishedExperimentError(f"{entry['experiment_id']}: summary missing by_arm")
    metrics: list[dict[str, Any]] = []
    selected = _required_int(source, "selected_run_count", entry["experiment_id"])
    completed = _required_int(source, "completed_run_count", entry["experiment_id"])
    if completed > selected:
        raise PublishedExperimentError(
            f"{entry['experiment_id']}: completed_run_count exceeds selected_run_count"
        )
    for arm in arms:
        metrics.append({
            "arm": str(arm.get("arm", "")),
            "runs": _required_int(arm, "runs", entry["experiment_id"]),
            "preserved_all_4": _required_int(arm, "M1_preserved_all_4", entry["experiment_id"]),
            "target_considered_before_write": _required_int(
                arm, "M2_target_considered_before_write", entry["experiment_id"]
            ),
            "completion": _required_int(arm, "M4_completion", entry["experiment_id"]),
        })
    normalized = _base_normalized(entry, metrics)
    normalized["selected_run_count"] = selected
    normalized["completed_run_count"] = completed
    normalized["source_status"] = source.get("status")
    return normalized


def _normalize_measurement_v1(
    base_dir: Path,
    entry: dict[str, Any],
    action_registry_cache: dict[str, Any],
) -> dict[str, Any]:
    allowed_fields = {
        "experiment_id",
        "adapter",
        "sources",
        "artifact_root",
        "registration_commit",
    }
    unexpected = sorted(set(entry) - allowed_fields)
    missing = sorted(allowed_fields - set(entry))
    if missing or unexpected:
        raise PublishedExperimentError(
            f"{entry.get('experiment_id', '<unknown>')}: measurement_v1 registry fields "
            f"must be source-only; missing={missing!r}, unexpected={unexpected!r}"
        )
    experiment_id = str(entry["experiment_id"])
    sources = entry["sources"]
    if not isinstance(sources, dict) or set(sources) != {"manifest", "runs"}:
        raise PublishedExperimentError(
            f"{experiment_id}: measurement_v1 sources must contain only manifest and runs"
        )
    manifest_path, manifest = _load_measurement_source(
        base_dir, sources["manifest"], f"{experiment_id}.manifest"
    )
    run_pointers = sources["runs"]
    if not isinstance(run_pointers, list) or not run_pointers:
        raise PublishedExperimentError(
            f"{experiment_id}: measurement_v1 runs must be a non-empty source list"
        )
    runs = [
        _load_measurement_source(base_dir, pointer, f"{experiment_id}.runs[{index}]")[1]
        for index, pointer in enumerate(run_pointers)
    ]
    if manifest.get("experiment_id") != experiment_id:
        raise PublishedExperimentError(
            f"{experiment_id}: manifest experiment_id does not match registry identity"
        )
    runs = _order_measurement_runs_by_registered_roster(manifest, runs)

    artifact_root = _resolve_package_path(
        base_dir, entry["artifact_root"], f"{experiment_id}.artifact_root"
    )
    if not artifact_root.is_dir():
        raise PublishedExperimentError(
            f"{experiment_id}: artifact_root is not a directory: {entry['artifact_root']}"
        )
    commit = str(entry["registration_commit"])
    if re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", commit) is None:
        raise PublishedExperimentError(
            f"{experiment_id}: registration_commit must be a full Git object ID"
        )
    repo_root = _git_repository_root(base_dir, experiment_id)
    manifest_git_path = manifest.get("registration", {}).get("manifest_path")
    if not isinstance(manifest_git_path, str):
        raise PublishedExperimentError(
            f"{experiment_id}: manifest registration path is missing"
        )
    anchored_manifest_path = (repo_root / manifest_git_path).resolve()
    if manifest_path != anchored_manifest_path:
        raise PublishedExperimentError(
            f"{experiment_id}: registered manifest source is not the Git-anchored manifest path"
        )
    audit = audit_measurement_v1(
        manifest,
        runs,
        artifact_root=artifact_root,
        registration_anchor=GitRegistrationAnchor(
            repo_path=repo_root,
            commit=commit,
            manifest_path=manifest_git_path,
        ),
    )
    audit = portable_measurement_audit(audit)
    estimate_reportable = audit["estimate_reportable"] is True
    fixed_estimate_reportable = (
        estimate_reportable and audit["lane"] == "fixed_regression"
    )
    registered_effect_rule_met = audit["registered_effect_rule_met"] is True
    evidence_complete = audit["evidence_complete"] is True
    action_registry_binding = _audit_action_registry_binding(
        base_dir,
        artifact_root,
        manifest,
        audit,
        sources,
        action_registry_cache,
    )
    return {
        "experiment_id": experiment_id,
        "task_id": manifest.get("task", {}).get("id"),
        "adapter": "measurement_v1",
        "lane": audit["lane"],
        "evidence_class": (
            "measurement_v1_estimate_reportable"
            if estimate_reportable
            else "measurement_v1_ineligible"
        ),
        "claim_boundary": (
            "Audited measurement-v1 estimate; improvement_ready additionally requires "
            "this exact primary-efficacy source set in a fully verified and adopted "
            "canonical action synthesis."
        ),
        "artifacts_complete": bool(
            audit["artifacts_verified"] and audit["artifact_semantics_verified"]
        ),
        "pins_complete": bool(
            audit["contract_valid"] and audit["registration_anchor"]["verified"]
        ),
        "evidence_complete": evidence_complete,
        "estimate_reportable": estimate_reportable,
        "fixed_estimate_reportable": fixed_estimate_reportable,
        "registered_effect_rule_met": registered_effect_rule_met,
        "action_registry_binding": action_registry_binding,
        "improvement_ready": bool(
            registered_effect_rule_met and action_registry_binding["verified"]
        ),
        "metrics": [],
        "sources": sources,
        "artifact_root": str(Path(str(entry["artifact_root"]))),
        "registration_commit": commit.lower(),
        "audit": audit,
    }


def _order_measurement_runs_by_registered_roster(
    manifest: dict[str, Any],
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Canonicalize valid run order without hiding duplicates or unknown slots."""
    slot_order: dict[str, int] = {}
    for attempt in manifest.get("execution_plan", {}).get("attempt_roster", []):
        for execution in attempt.get("executions", []):
            slot_id = execution.get("slot_id")
            if isinstance(slot_id, str) and slot_id not in slot_order:
                slot_order[slot_id] = len(slot_order)
    fallback = len(slot_order)
    indexed_runs = list(enumerate(runs))
    indexed_runs.sort(
        key=lambda item: (
            slot_order.get(
                item[1].get("attempt", {}).get("roster_slot_id"),
                fallback,
            ),
            item[0],
        )
    )
    return [run for _, run in indexed_runs]


def _base_normalized(entry: dict[str, Any], metrics: list[dict[str, Any]]) -> dict[str, Any]:
    required = [
        "experiment_id",
        "task_id",
        "lane",
        "evidence_class",
        "claim_boundary",
        "artifacts_complete",
        "pins_complete",
    ]
    missing = [field for field in required if field not in entry]
    if missing:
        raise PublishedExperimentError(
            f"{entry.get('experiment_id', '<unknown>')}: missing registry fields {missing}"
        )
    if entry["lane"] != "frontier_observation":
        raise PublishedExperimentError(
            f"{entry['experiment_id']}: historical adapters must remain frontier_observation"
        )
    for field in ("artifacts_complete", "pins_complete"):
        if not isinstance(entry[field], bool):
            raise PublishedExperimentError(
                f"{entry['experiment_id']}: {field} must be a boolean"
            )
    if entry["artifacts_complete"] or entry["pins_complete"]:
        raise PublishedExperimentError(
            f"{entry['experiment_id']}: historical adapters cannot self-promote to claim-grade"
        )
    return {
        "experiment_id": entry["experiment_id"],
        "task_id": entry["task_id"],
        "adapter": entry["adapter"],
        "lane": entry["lane"],
        "evidence_class": entry["evidence_class"],
        "claim_boundary": entry["claim_boundary"],
        "artifacts_complete": False,
        "pins_complete": False,
        "claim_grade": False,
        "metrics": metrics,
        "sources": entry["sources"],
    }


def _audit_action_registry_binding(
    base_dir: Path,
    artifact_root: Path,
    manifest: dict[str, Any],
    audit: dict[str, Any],
    sources: dict[str, Any],
    action_registry_cache: dict[str, Any],
) -> dict[str, Any]:
    """Bind one published result to its fully validated canonical action lineage."""
    governance = manifest.get("governance")
    result = {
        "verified": False,
        "coverage_claim_id": None,
        "task_family_id": None,
        "improvement_record_id": None,
        "workflow_state": None,
        "decision_outcome": None,
        "decision_role": None,
        "decision_rule": None,
        "registered_gate_passed": False,
        "guardrails_passed": False,
        "source_census_verified": False,
        "synthesis_verified": False,
        "adopted_treatment_id": None,
        "adopted_treatment_code_hashes": None,
        "errors": [],
    }
    errors: list[str] = result["errors"]
    if not isinstance(governance, dict):
        errors.append("measurement manifest has no governance object")
        return result
    for field in ("coverage_claim_id", "task_family_id", "improvement_record_id"):
        value = governance.get(field)
        result[field] = value
        if not isinstance(value, str) or not value:
            errors.append(f"governance.{field} is missing")
    projections, registry_error = _validated_action_registry_projection_cache(
        base_dir,
        action_registry_cache,
    )
    if registry_error is not None:
        errors.append(registry_error)
        return result

    experiment_id = manifest.get("experiment_id")
    projection = projections.get(experiment_id)
    if projection is None:
        errors.append("measurement experiment is not registered in the action binding plan")
        return result

    for field in ("coverage_claim_id", "task_family_id", "improvement_record_id"):
        if result[field] != projection[field]:
            errors.append(f"governance.{field} does not match the canonical action binding")

    result["workflow_state"] = projection["workflow_state"]
    result["decision_outcome"] = projection["decision_outcome"]
    binding = projection["binding"]
    result["decision_role"] = binding["decision_role"]
    result["decision_rule"] = binding["decision_rule"]

    manifest_ref = projection["manifest_artifact_ref"]
    expected_manifest_pointer = (
        _published_pointer_from_artifact_ref(manifest_ref)
        if manifest_ref is not None
        else None
    )
    actual_manifest_pointer = _normalized_published_pointer(sources.get("manifest"))
    manifest_source_matches = (
        expected_manifest_pointer is not None
        and actual_manifest_pointer == expected_manifest_pointer
    )
    if not manifest_source_matches:
        errors.append(
            "published measurement manifest is not the lifecycle-custodied manifest source"
        )

    expected_run_pointers = [
        _published_pointer_from_artifact_ref(reference)
        for reference in projection["run_artifact_refs"]
    ]
    actual_run_pointers = [
        _normalized_published_pointer(pointer)
        for pointer in sources.get("runs", [])
    ]
    run_sources_match = (
        len(actual_run_pointers) == len(expected_run_pointers)
        and sorted(actual_run_pointers, key=lambda item: (item["path"], item["sha256"]))
        == sorted(expected_run_pointers, key=lambda item: (item["path"], item["sha256"]))
    )
    if not run_sources_match:
        errors.append(
            "published measurement runs are not the exact lifecycle-custodied run census"
        )
    if artifact_root != base_dir:
        errors.append("published measurement artifact_root is not the canonical package root")
    result["source_census_verified"] = bool(
        manifest_source_matches and run_sources_match and artifact_root == base_dir
    )

    analysis = projection["analysis"]
    if not isinstance(analysis, dict):
        errors.append("canonical action binding has no completed analysis artifact")
    else:
        if analysis.get("measurement_audit") != audit:
            errors.append(
                "published measurement audit differs from the lifecycle-custodied analysis"
            )
        result["registered_gate_passed"] = (
            analysis.get("registered_gate_passed") is True
        )
        result["guardrails_passed"] = analysis.get("guardrails_passed") is True

    binding_decision = projection["binding_decision"]
    if not isinstance(binding_decision, dict):
        errors.append("canonical action binding has no completed binding decision")
    else:
        if binding_decision.get("decision_role") != binding["decision_role"]:
            errors.append("binding decision role differs from the registered action role")
        if binding_decision.get("decision_rule") != binding["decision_rule"]:
            errors.append("binding decision rule differs from the registered action rule")
        if binding_decision.get("registered_gate_passed") is not True:
            errors.append("binding decision registered gate is not satisfied")
        if binding_decision.get("guardrails_passed") is not True:
            errors.append("binding decision guardrails are not satisfied")
        if binding_decision.get("eligible_for_synthesis") is not True:
            errors.append("binding decision is not eligible for the canonical synthesis")

    synthesis = projection["synthesis"]
    if not isinstance(synthesis, dict):
        errors.append("canonical action record has no complete synthesis decision")
    else:
        if synthesis.get("all_registered_gates_passed") is not True:
            errors.append("canonical action synthesis did not pass every registered gate")
        if projection["decision_outcome"] != "adopt" or synthesis.get("outcome") != "adopt":
            errors.append("canonical action synthesis does not adopt the change")
        adopted_primary_ids = synthesis.get(
            "adopted_primary_efficacy_experiment_ids", []
        )
        if experiment_id not in adopted_primary_ids:
            errors.append(
                "experiment is not an adopted primary-efficacy result in the canonical synthesis"
            )
        treatment_id = binding["post_arm_id"]
        if treatment_id not in synthesis.get("adopted_treatment_ids", []):
            errors.append("experiment treatment is not in the adopted treatment scope")
        else:
            result["adopted_treatment_id"] = treatment_id
        treatment_hashes = synthesis.get("adopted_treatment_code_hashes", {}).get(
            treatment_id
        )
        if not isinstance(treatment_hashes, dict):
            errors.append("adopted treatment code hashes are missing from the synthesis")
        else:
            result["adopted_treatment_code_hashes"] = treatment_hashes
        result["synthesis_verified"] = not any(
            error.startswith("canonical action synthesis")
            or error.startswith("experiment is not an adopted")
            or error.startswith("experiment treatment")
            or error.startswith("adopted treatment")
            for error in errors
        )

    if binding["decision_role"] != "primary_efficacy":
        errors.append("action binding decision_role is not primary_efficacy")
    if audit.get("registered_effect_rule_met") is not True:
        errors.append("measurement registered effect rule is not met")

    result["verified"] = not errors
    return result


def _validated_action_registry_projection_cache(
    base_dir: Path,
    cache: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], str | None]:
    if cache.get("loaded") is True:
        return cache.get("projections", {}), cache.get("error")
    cache["loaded"] = True
    repo_root = base_dir.parent.resolve() if base_dir.name == "agent_readiness" else base_dir
    required = [
        repo_root / relative
        for relative in (
            "method/benchmark-coverage-v1.json",
            "method/task-families-v1.json",
            "method/improvement-registry-v1.json",
            "method/schema/benchmark-coverage-v1.schema.json",
            "method/schema/task-families-v1.schema.json",
            "method/schema/improvement-registry-v1.schema.json",
        )
    ]
    if not all(path.is_file() for path in required):
        cache["projections"] = {}
        cache["error"] = "canonical benchmark/action registries are not packaged"
        return {}, cache["error"]
    try:
        coverage, tasks, improvements = load_default_registries(repo_root)
        projections = validated_improvement_projections(
            coverage,
            tasks,
            improvements,
            repo_root=repo_root,
        )
    except (OSError, ValueError, RegistryValidationError) as exc:
        cache["projections"] = {}
        cache["error"] = f"canonical benchmark/action registries are invalid: {exc}"
        return {}, cache["error"]
    cache["projections"] = projections
    cache["error"] = None
    return projections, None


def _published_pointer_from_artifact_ref(reference: dict[str, Any]) -> dict[str, str]:
    prefix = "agent_readiness/"
    path = str(reference["path"])
    if not path.startswith(prefix):
        raise PublishedExperimentError(
            f"canonical lifecycle artifact is outside the package: {path}"
        )
    return {
        "path": path.removeprefix(prefix),
        "sha256": str(reference["sha256"]).removeprefix("sha256:"),
    }


def _normalized_published_pointer(pointer: Any) -> dict[str, str]:
    if not isinstance(pointer, dict):
        return {"path": "", "sha256": ""}
    return {
        "path": str(pointer.get("path", "")),
        "sha256": str(pointer.get("sha256", "")).removeprefix("sha256:"),
    }


def _load_registered_source(
    base_dir: Path,
    entry: dict[str, Any],
    source_name: str,
) -> dict[str, Any]:
    source = entry.get("sources", {}).get(source_name)
    if not isinstance(source, dict):
        raise PublishedExperimentError(
            f"{entry.get('experiment_id', '<unknown>')}: missing source {source_name!r}"
        )
    return _load_registered_pointer(
        base_dir,
        source,
        f"{entry.get('experiment_id', '<unknown>')}.{source_name}",
    )


def _load_registered_pointer(
    base_dir: Path,
    source: Any,
    context: str,
) -> dict[str, Any]:
    if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
        raise PublishedExperimentError(
            f"{context}: source pointers contain only path and sha256"
        )
    relative = Path(str(source.get("path", "")))
    path = (base_dir / relative).resolve()
    try:
        path.relative_to(base_dir)
    except ValueError as exc:
        raise PublishedExperimentError(
            f"{context}: source escapes package root: {relative}"
        ) from exc
    if not path.is_file():
        raise PublishedExperimentError(
            f"{context}: source missing: {relative}"
        )
    expected = str(source.get("sha256", ""))
    actual = _sha256(path)
    if not expected or actual != expected:
        raise PublishedExperimentError(
            f"{context}: source hash mismatch: {relative}"
        )
    return _load_json(path)


def _load_measurement_source(
    base_dir: Path,
    pointer: Any,
    context: str,
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(pointer, dict) or set(pointer) != {"path", "sha256"}:
        raise PublishedExperimentError(
            f"{context}: source pointers contain only path and sha256"
        )
    path = _resolve_package_path(base_dir, pointer["path"], context)
    if not path.is_file():
        raise PublishedExperimentError(f"{context}: source missing: {pointer['path']}")
    expected = str(pointer["sha256"]).removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise PublishedExperimentError(f"{context}: sha256 must be 64 lowercase hex digits")
    actual = _sha256(path)
    if actual != expected:
        raise PublishedExperimentError(
            f"{context}: source hash mismatch: {pointer['path']}"
        )
    document = _load_json(path)
    try:
        canonical = canonical_json_bytes(document)
    except (TypeError, ValueError) as exc:
        raise PublishedExperimentError(
            f"{context}: source is outside canonical JSON: {exc}"
        ) from exc
    if path.read_bytes() != canonical:
        raise PublishedExperimentError(
            f"{context}: measurement source must use exact canonical JSON bytes"
        )
    return path, document


def _resolve_package_path(base_dir: Path, relative_value: Any, context: str) -> Path:
    if not isinstance(relative_value, str) or not relative_value:
        raise PublishedExperimentError(f"{context}: path must be a non-empty string")
    if "\\" in relative_value:
        raise PublishedExperimentError(
            f"{context}: path escapes package root: {relative_value}"
        )
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise PublishedExperimentError(
            f"{context}: path escapes package root: {relative}"
        )
    candidate = base_dir
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise PublishedExperimentError(
                f"{context}: path contains a symlink: {relative}"
            )
    path = candidate.resolve()
    try:
        path.relative_to(base_dir)
    except ValueError as exc:
        raise PublishedExperimentError(
            f"{context}: path escapes package root: {relative}"
        ) from exc
    return path


def _git_repository_root(base_dir: Path, experiment_id: str) -> Path:
    try:
        completed = subprocess.run(
            ["git", "-C", str(base_dir), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublishedExperimentError(
            f"{experiment_id}: cannot locate Git registration repository: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise PublishedExperimentError(
            f"{experiment_id}: cannot locate Git registration repository"
        )
    return Path(completed.stdout.strip()).resolve()


def _render_alias_safety(experiment: dict[str, Any]) -> list[str]:
    headline = [m for m in experiment["metrics"] if m["source_class"] == "headline"]
    breadth = [m for m in experiment["metrics"] if m["source_class"] == "breadth"]
    lines = [
        "### Alias safety: named decision helper",
        "",
        "This historical frontier observation compares a Drush-only condition with a bundled condition whose prompt names a verdict-bearing path helper. It does not isolate tool discovery, installation, prompt guidance, facts-only output, or an end-to-end write, and its original pins are incomplete.",
        "",
        "The run is the analysis unit. Hidden-path judgments are nested within a run and are shown only as supporting detail.",
        "",
        "| Model | Arm | Runs with all hidden judgments correct | Nested hidden judgments correct | Nested reasons naming hidden layer |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for metric in headline + breadth:
        lines.append(
            f"| {metric['model_id']} | {metric['arm']} | "
            f"{metric['runs_all_hidden_correct']}/{metric['runs']} | "
            f"{metric['latent_correct']}/{metric['latent_total']} | "
            f"{metric['latent_reasoned']}/{metric['latent_total']} |"
        )
    lines.extend([
        "",
        f"Claim boundary: {experiment['claim_boundary']}",
        f"Evidence class: `{experiment['evidence_class']}`; claim-grade: `{str(experiment['claim_grade']).lower()}`.",
        "",
    ])
    return lines


def _render_intent_behavior(experiment: dict[str, Any]) -> list[str]:
    lines = [
        "### Intent behavior: preservation-only null",
        "",
        "The retained summary reports whether the four SEO editor widgets survived. That is not a complete measure of appropriate authority/conflict handling, so this result is published as a preservation-only null rather than evidence that intent did or did not help generally.",
        "",
        "| Arm | Runs | Preserved all four | Target considered before write | Task completion |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for metric in experiment["metrics"]:
        lines.append(
            f"| {metric['arm']} | {metric['runs']} | {metric['preserved_all_4']}/{metric['runs']} | "
            f"{metric['target_considered_before_write']}/{metric['runs']} | "
            f"{metric['completion']}/{metric['runs']} |"
        )
    lines.extend([
        "",
        f"Claim boundary: {experiment['claim_boundary']}",
        f"Evidence class: `{experiment['evidence_class']}`; claim-grade: `{str(experiment['claim_grade']).lower()}`.",
        "",
    ])
    return lines


def _render_measurement_v1(experiment: dict[str, Any]) -> list[str]:
    audit = experiment["audit"]
    decision = audit["decision"]
    analysis = audit.get("analysis") or {}
    confidence = analysis.get("confidence") or {}
    guardrails = audit.get("guardrails") or {}
    binding = experiment["action_registry_binding"]
    lines = [
        f"### Measurement v1: {experiment['experiment_id']}",
        "",
        f"- Lane: {experiment['lane']}",
        f"- Claim class: {audit.get('claim_class')}",
        f"- Evidence complete: {str(experiment['evidence_complete']).lower()}",
        f"- Estimate reportable: {str(experiment['estimate_reportable']).lower()}",
        f"- Fixed-regression estimate: {str(experiment['fixed_estimate_reportable']).lower()}",
        f"- Registered effect rule met: {str(experiment['registered_effect_rule_met']).lower()}",
        f"- Action-registry decision bound: {str(binding['verified']).lower()}",
        f"- Improvement ready: {str(experiment['improvement_ready']).lower()}",
        f"- Primary metric: {analysis.get('primary_metric_id')}",
        f"- N / sample unit: {analysis.get('n')} / {analysis.get('sample_unit')}",
        f"- Estimate: {analysis.get('estimate')}",
        f"- Favorable-direction estimate: {analysis.get('favorable_direction_estimate')}",
        f"- Confidence method / level / tail: {confidence.get('method')} / {confidence.get('level')} / {confidence.get('tail')}",
        f"- Favorable lower bound: {confidence.get('favorable_direction_lower_bound')}",
        f"- Registered minimum favorable effect: {decision.get('minimum_favorable_effect')}",
        f"- Guardrails passed: {str(guardrails.get('all_passed') is True).lower()}",
        f"- Registered decision: {decision['reason']}",
        f"- Inference scope: {analysis.get('inference_scope')}",
        f"- Sampling design: {analysis.get('sampling_design')}",
        "",
        "These fields are derived by reloading hashed sources and rerunning the "
        "measurement-v1 audit. A measurement effect rule is not a final improvement "
        "decision unless the canonical action registry also resolves and passes.",
        "",
    ]
    if analysis.get("assumptions"):
        lines.append("Assumptions:")
        lines.extend(f"- {item}" for item in analysis["assumptions"])
        lines.append("")
    if analysis.get("limitations") or audit.get("limitations") or binding["errors"]:
        lines.append("Limitations:")
        lines.extend(f"- {item}" for item in analysis.get("limitations", []))
        lines.extend(f"- {item}" for item in audit.get("limitations", []))
        lines.extend(f"- Action registry: {item}" for item in binding["errors"])
        lines.append("")
    return lines


def _required_int(data: dict[str, Any], key: str, experiment_id: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PublishedExperimentError(
            f"{experiment_id}: {key} must be a non-negative integer"
        )
    return value


def _load_json(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PublishedExperimentError(
                    f"{path}: duplicate JSON object key {key!r}"
                )
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> Any:
        raise PublishedExperimentError(
            f"{path}: non-finite JSON number {value!r} is prohibited"
        )

    try:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishedExperimentError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PublishedExperimentError(f"{path}: expected a JSON object")
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
