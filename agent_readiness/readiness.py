from typing import Any
import json
from pathlib import Path

from agent_readiness.baseline_gate import audit_inventory_baseline
from agent_readiness.published_experiments import (
    DEFAULT_REGISTRY,
    load_published_experiments,
)
from agent_readiness.publishing import (
    audit_legacy_run_evidence,
    audit_publication_package,
)


CLAIM_SCOPE = "evidence_package_plus_named_measurement_v1_gates"

# Completed in v0.2: the inventory prompt is de-leaked (discovery required), a
# failing run is retained, and the assess.alias_safety A/B has been run across two
# models (claude-haiku-4-5, claude-opus-4-8), three Drupal starting sites, and three prompt
# framings (retained judgments differed between a Drush-only condition and a
# bundled condition whose prompt named a verdict-bearing helper; see
# experiments/alias-safety-SYNTHESIS.md). The
# remaining actions below still gate any broad readiness claim.
V0_HARDENING_ACTIONS = [
    "Factor decision helpers into discovery, facts-only, advice, and actual-write conditions.",
    "Measure intent authority/conflict handling rather than treating preservation as sufficient.",
    "Exercise the Drupal lifecycle on clean and messy substrates, including recovery and handoff.",
    "Capture harness-derived token, timing, tool, rescue, invalid-attempt, and trajectory evidence.",
    "Keep fixed-agent regression and frontier-observation lanes separate and defer an aggregate readiness score.",
]

# What the readiness flags do NOT certify. Surface these wherever the flags are
# shown so an external reader does not over-read a green light.
PROVENANCE_CAVEATS = [
    "Outcome judgments for the v0.2 inventory and alias-safety examples can be mechanically re-scored from retained answers and ground truth. Tool invocation, token/cost, and complete trajectory evidence are not independently instrumented or retained; legacy timing and tool counts may be operator-supplied or self-reported.",
    "Legacy non-smoke status is inferred from run metadata; it does not establish independence, complete pinning, or longitudinal comparability.",
    "Evidence-package flags certify packaging and evaluator examples only. Estimate and fixed-estimate flags require a separately audited measurement-v1 experiment; improvement additionally requires a compatible decided canonical action-registry record.",
]


def audit_readiness(
    base_dir,
    run_results: list[dict[str, Any]],
    *,
    public_required_passes: int = 1,
    legacy_example_required_passes: int = 3,
) -> dict[str, Any]:
    _validate_readiness_thresholds(
        public_required_passes,
        legacy_example_required_passes,
    )
    base_dir = Path(base_dir).resolve()
    publication_errors = audit_publication_package(base_dir, run_results)
    audited_bundle = _load_experiment_bundle(base_dir)
    verified_legacy_run_ids = {
        run["run_id"]
        for run in run_results
        if isinstance(run, dict)
        and isinstance(run.get("run_id"), str)
        and not audit_legacy_run_evidence(base_dir, run)
    }
    return derive_readiness_report(
        run_results,
        audited_bundle,
        publication_errors=publication_errors,
        public_required_passes=public_required_passes,
        legacy_example_required_passes=legacy_example_required_passes,
        verified_legacy_run_ids=verified_legacy_run_ids,
    )


def derive_readiness_report(
    run_results: list[dict[str, Any]],
    audited_bundle: dict[str, Any],
    *,
    publication_errors: list[str],
    public_required_passes: int = 1,
    legacy_example_required_passes: int = 3,
    verified_legacy_run_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Derive flags from source-audited experiments and explicit package errors."""
    _validate_readiness_thresholds(
        public_required_passes,
        legacy_example_required_passes,
    )
    if verified_legacy_run_ids is None:
        verified_legacy_run_ids = {
            run.get("run_id")
            for run in run_results
            if isinstance(run, dict) and isinstance(run.get("run_id"), str)
        }
    ordered_runs = sorted(
        run_results,
        key=lambda item: str(item.get("run_id", "")),
    )
    verified_runs = [
        run for run in ordered_runs if run.get("run_id") in verified_legacy_run_ids
    ]
    public_errors = audit_inventory_baseline(verified_runs, required_passes=public_required_passes)
    legacy_example_errors = audit_inventory_baseline(
        verified_runs,
        required_passes=legacy_example_required_passes,
    )
    smoke_runs = [
        run["run_id"]
        for run in ordered_runs
        if _is_smoke_run(run)
    ]
    no_rescue_non_smoke_runs = [
        run["run_id"]
        for run in verified_runs
        if _is_independent_pass(run)
    ]
    no_rescue_non_smoke_inventory_passes = [
        run["run_id"]
        for run in verified_runs
        if _is_independent_inventory_pass(run)
    ]
    no_rescue_non_smoke_event_passes = [
        run["run_id"]
        for run in verified_runs
        if _is_independent_task_pass(run, "act.event_jsonapi")
    ]
    no_rescue_non_smoke_recovery_passes = [
        run["run_id"]
        for run in verified_runs
        if _is_independent_task_pass(run, "recover.event_jsonapi")
    ]
    experiments = audited_bundle.get("experiments", [])
    experiment_eligibility = [
        {
            "experiment_id": str(experiment.get("experiment_id", "<unknown>")),
            "adapter": experiment.get("adapter"),
            "lane": experiment.get("lane"),
            "evidence_complete": experiment.get("evidence_complete") is True,
            "estimate_reportable": experiment.get("estimate_reportable") is True,
            "fixed_estimate_reportable": (
                experiment.get("fixed_estimate_reportable") is True
            ),
            "registered_effect_rule_met": (
                experiment.get("registered_effect_rule_met") is True
            ),
            "action_registry_binding_verified": (
                experiment.get("action_registry_binding", {}).get("verified")
                is True
            ),
            "improvement_ready": experiment.get("improvement_ready") is True,
            "action_registry_errors": experiment.get(
                "action_registry_binding", {}
            ).get("errors", []),
            "audit_errors": experiment.get("audit", {}).get("errors", []),
        }
        for experiment in experiments
    ]
    estimate_experiments = [
        item["experiment_id"]
        for item in experiment_eligibility
        if item["estimate_reportable"]
    ]
    fixed_estimate_experiments = [
        item["experiment_id"]
        for item in experiment_eligibility
        if item["fixed_estimate_reportable"]
    ]
    effect_rule_experiments = [
        item["experiment_id"]
        for item in experiment_eligibility
        if item["registered_effect_rule_met"]
    ]
    improvement_experiments = [
        item["experiment_id"]
        for item in experiment_eligibility
        if item["improvement_ready"]
    ]
    estimate_errors = [] if estimate_experiments else [
        "no source-audited measurement_v1 experiment has a reportable estimate"
    ]
    fixed_estimate_errors = [] if fixed_estimate_experiments else [
        "no source-audited fixed_regression measurement_v1 estimate is reportable"
    ]
    improvement_errors = [] if improvement_experiments else [
        "no source-audited effect result is bound to a compatible decided canonical action-registry record"
    ]
    evidence_package_ready = not publication_errors and not public_errors
    return {
        "claim_scope": CLAIM_SCOPE,
        "private_circulation_ready": not publication_errors,
        "public_evidence_package_ready": evidence_package_ready,
        "public_v0_package_ready": evidence_package_ready,
        "legacy_example_count_gate_passed": (
            not publication_errors and not legacy_example_errors
        ),
        "estimate_ready": evidence_package_ready and not estimate_errors,
        "fixed_estimate_ready": evidence_package_ready and not fixed_estimate_errors,
        "improvement_ready": evidence_package_ready and not improvement_errors,
        "publication_errors": publication_errors,
        "public_v0_package_errors": public_errors,
        "legacy_example_count_errors": legacy_example_errors,
        "estimate_errors": estimate_errors,
        "fixed_estimate_errors": fixed_estimate_errors,
        "improvement_errors": improvement_errors,
        "experiment_eligibility": experiment_eligibility,
        "estimate_eligible_experiments": estimate_experiments,
        "fixed_estimate_eligible_experiments": fixed_estimate_experiments,
        "registered_effect_rule_met_experiments": effect_rule_experiments,
        "improvement_ready_experiments": improvement_experiments,
        "smoke_runs": smoke_runs,
        "no_rescue_non_smoke_runs": no_rescue_non_smoke_runs,
        "no_rescue_non_smoke_inventory_passes": no_rescue_non_smoke_inventory_passes,
        "no_rescue_non_smoke_event_passes": no_rescue_non_smoke_event_passes,
        "no_rescue_non_smoke_recovery_passes": no_rescue_non_smoke_recovery_passes,
        "provenance_caveats": PROVENANCE_CAVEATS,
        "next_actions": _next_actions(
            publication_errors,
            public_errors,
            legacy_example_errors,
            estimate_errors,
            fixed_estimate_errors,
            improvement_errors,
        ),
    }


def write_readiness_json(
    base_dir,
    run_results: list[dict[str, Any]],
    output_path,
) -> None:
    base_dir = Path(base_dir).resolve()
    audited_bundle = _load_experiment_bundle(base_dir)
    verified_legacy_run_ids = {
        run["run_id"]
        for run in run_results
        if isinstance(run, dict)
        and isinstance(run.get("run_id"), str)
        and not audit_legacy_run_evidence(base_dir, run)
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            derive_readiness_snapshot(
                run_results,
                audited_bundle,
                verified_legacy_run_ids=verified_legacy_run_ids,
            ),
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


def derive_readiness_snapshot(
    run_results: list[dict[str, Any]],
    audited_bundle: dict[str, Any],
    *,
    public_required_passes: int = 1,
    legacy_example_required_passes: int = 3,
    verified_legacy_run_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Render source gates without pretending to audit the live package tree.

    A generated file cannot attest to the files that contain it without a
    circular or post-build signature protocol.  The authoritative result is
    therefore the live ``audit_readiness`` output.  This checked-in snapshot
    deliberately leaves every package-dependent readiness flag unevaluated.
    """
    report = derive_readiness_report(
        run_results,
        audited_bundle,
        publication_errors=[],
        public_required_passes=public_required_passes,
        legacy_example_required_passes=legacy_example_required_passes,
        verified_legacy_run_ids=verified_legacy_run_ids,
    )
    snapshot = dict(report)
    snapshot.update({
        "artifact_kind": "drupal_agent_readiness.source_gate_snapshot.v1",
        "authoritative_package_audit": False,
        "package_audit": {
            "status": "not_run",
            "command": (
                "python3 -B agent_readiness/scripts/audit_readiness.py "
                "--base-dir agent_readiness --run-result <each-retained-run>"
            ),
        },
        "legacy_example_source_gate_met": report["legacy_example_count_gate_passed"],
        "estimate_source_gate_met": bool(report["estimate_eligible_experiments"]),
        "fixed_estimate_source_gate_met": bool(
            report["fixed_estimate_eligible_experiments"]
        ),
        "improvement_source_gate_met": bool(report["improvement_ready_experiments"]),
        "private_circulation_ready": None,
        "public_evidence_package_ready": None,
        "public_v0_package_ready": None,
        "legacy_example_count_gate_passed": None,
        "estimate_ready": None,
        "fixed_estimate_ready": None,
        "improvement_ready": None,
        "publication_errors": None,
        "public_v0_package_errors": None,
        "legacy_example_count_errors": None,
    })
    return snapshot


def _next_actions(
    publication_errors: list[str],
    public_errors: list[str],
    legacy_example_errors: list[str],
    estimate_errors: list[str],
    fixed_estimate_errors: list[str],
    improvement_errors: list[str],
) -> list[str]:
    actions: list[str] = []
    if publication_errors:
        actions.append("Fix publication package errors and regenerate public assets.")
    if public_errors:
        actions.append("Run one fresh non-smoke inventory.read_only task with no human rescue and capture it with scripts/capture_run.py; this checks the evidence loop, not independence.")
    elif legacy_example_errors:
        actions.append("Repeat non-smoke inventory.read_only until there are three no-rescue evaluator examples; this is an evidence-loop check, not a numeric-claim gate.")
    if estimate_errors:
        actions.append("Publish a measurement-v1 experiment with complete pins, attempt denominator, validity accounting, and retained artifacts before reporting a numeric estimate.")
    if fixed_estimate_errors:
        actions.append("Run a paired fixed_regression measurement-v1 experiment before reporting a comparable pre/post estimate.")
    if improvement_errors:
        actions.append("Meet the registered effect rule, pass guardrails, and bind the result to a compatible decided canonical action-registry record before claiming improvement.")
    actions.extend(V0_HARDENING_ACTIONS)
    return actions


def _validate_readiness_thresholds(
    public_required_passes: int,
    legacy_example_required_passes: int,
) -> None:
    if type(public_required_passes) is not int or public_required_passes < 1:
        raise ValueError("public_required_passes cannot be lower than 1")
    if (
        type(legacy_example_required_passes) is not int
        or legacy_example_required_passes < 3
    ):
        raise ValueError("legacy_example_required_passes cannot be lower than 3")


def _load_experiment_bundle(
    base_dir: Path,
) -> dict[str, Any]:
    registry_path = base_dir / DEFAULT_REGISTRY
    if not registry_path.is_file():
        return {
            "schema_version": "drupal_agent_readiness.published_experiments.v1",
            "registry": None,
            "experiments": [],
        }
    return load_published_experiments(base_dir, registry_path)


def _is_independent_pass(run: dict[str, Any]) -> bool:
    if run.get("evaluator", {}).get("passed") is not True:
        return False
    human_rescues = run.get("metrics", {}).get("human_rescues")
    if type(human_rescues) is not int or human_rescues != 0:
        return False
    return not _is_smoke_run(run)


def _is_independent_inventory_pass(run: dict[str, Any]) -> bool:
    return _is_independent_task_pass(run, "inventory.read_only")


def _is_independent_task_pass(run: dict[str, Any], task_id: str) -> bool:
    if run.get("task_id") != task_id:
        return False
    return _is_independent_pass(run)


def _is_smoke_run(run: dict[str, Any]) -> bool:
    agent = run.get("agent", {})
    return (
        "tooling-smoke" in run.get("run_id", "")
        or agent.get("name") == "Tooling smoke"
        or agent.get("model") == "none"
    )
