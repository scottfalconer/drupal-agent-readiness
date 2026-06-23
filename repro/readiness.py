from typing import Any
import json

from agent_readiness.baseline_gate import audit_inventory_baseline
from agent_readiness.publishing import audit_publication_package


CLAIM_SCOPE = "constrained_v0_mechanical_evidence_loop"

# Completed in v0.2: the inventory prompt is de-leaked (discovery required), a
# failing run is retained, and the assess.alias_safety A/B has been run across two
# models (claude-haiku-4-5, claude-opus-4-8), three Drupal starting sites, and three prompt
# framings (finding: live self-description prevents latent-path collisions for
# lightly-prompted/weaker agents; see experiments/alias-safety-SYNTHESIS.md). The
# remaining actions below still gate any broad readiness claim.
V0_HARDENING_ACTIONS = [
    "Repeat the non-Claude alias-safety run at n=10 and add another non-Claude stack before making a claim across model providers.",
    "Repeat act.event_jsonapi and recover.event_jsonapi runs, not only inventory.read_only.",
    "Add token cost alongside elapsed time in the public scorecard when token data is available.",
    "Raise n on the remaining Drupal starting sites (core, Convivial) for the condition where the agent is not told the hidden risk; stock Haven is done at n=10 (haiku 80% / opus 70% hidden-claim flags vs 100% with site self-description).",
    "Grow the task set before making any aggregate Drupal readiness claim.",
]

# What the readiness flags do NOT certify. Surface these wherever the flags are
# shown so an external reader does not over-read a green light.
PROVENANCE_CAVEATS = [
    "Metrics (elapsed_seconds, tool_calls) for the inventory/event/recovery runs are operator-supplied, not harness-instrumented; only the v0.2 de-leaked inventory run and the alias-safety runs are instrumented.",
    "'Independent' status is asserted via free-text agent metadata (name/model), not cryptographically bound to the answer; the gate trusts that metadata.",
    "These flags certify the evidence-loop method plus N genuine evaluator passes on a fixed Drupal starting site — not a blinded or statistically-powered benchmark.",
]


def audit_readiness(
    base_dir,
    run_results: list[dict[str, Any]],
    *,
    public_required_passes: int = 1,
    numeric_required_passes: int = 3,
) -> dict[str, Any]:
    publication_errors = audit_publication_package(base_dir, run_results)
    public_errors = audit_inventory_baseline(run_results, required_passes=public_required_passes)
    numeric_errors = audit_inventory_baseline(run_results, required_passes=numeric_required_passes)
    smoke_runs = [
        run["run_id"]
        for run in run_results
        if _is_smoke_run(run)
    ]
    independent_runs = [
        run["run_id"]
        for run in run_results
        if _is_independent_pass(run)
    ]
    independent_inventory_passes = [
        run["run_id"]
        for run in run_results
        if _is_independent_inventory_pass(run)
    ]
    independent_event_passes = [
        run["run_id"]
        for run in run_results
        if _is_independent_task_pass(run, "act.event_jsonapi")
    ]
    independent_recovery_passes = [
        run["run_id"]
        for run in run_results
        if _is_independent_task_pass(run, "recover.event_jsonapi")
    ]
    return {
        "claim_scope": CLAIM_SCOPE,
        "private_circulation_ready": not publication_errors,
        "public_v0_package_ready": not publication_errors and not public_errors,
        "numeric_claim_ready": not publication_errors and not numeric_errors,
        "publication_errors": publication_errors,
        "public_v0_package_errors": public_errors,
        "numeric_claim_errors": numeric_errors,
        "smoke_runs": smoke_runs,
        "independent_runs": independent_runs,
        "independent_inventory_passes": independent_inventory_passes,
        "independent_event_passes": independent_event_passes,
        "independent_recovery_passes": independent_recovery_passes,
        "provenance_caveats": PROVENANCE_CAVEATS,
        "next_actions": _next_actions(publication_errors, public_errors, numeric_errors),
    }


def write_readiness_json(base_dir, run_results: list[dict[str, Any]], output_path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(audit_readiness(base_dir, run_results), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _next_actions(
    publication_errors: list[str],
    public_errors: list[str],
    numeric_errors: list[str],
) -> list[str]:
    actions: list[str] = []
    if publication_errors:
        actions.append("Fix publication package errors and regenerate public assets.")
    if public_errors:
        actions.append("Run one fresh independent inventory.read_only task with no human rescue and capture it with scripts/capture_run.py.")
    elif numeric_errors:
        actions.append("Repeat independent inventory.read_only until there are three no-rescue constrained evaluator passes before making constrained v0 mechanical-pass claims.")
    actions.extend(V0_HARDENING_ACTIONS)
    return actions


def _is_independent_pass(run: dict[str, Any]) -> bool:
    if not run.get("evaluator", {}).get("passed"):
        return False
    if int(run.get("metrics", {}).get("human_rescues", 0)) != 0:
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
