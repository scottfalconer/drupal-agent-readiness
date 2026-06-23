from typing import Any


def audit_inventory_baseline(run_results: list[dict[str, Any]], required_passes: int = 1) -> list[str]:
    errors: list[str] = []
    passing = [
        run
        for run in run_results
        if _is_independent_inventory_pass(run)
    ]
    if len(passing) < required_passes:
        errors.append(f"independent inventory passes: {len(passing)}/{required_passes}")
    return errors


def _is_independent_inventory_pass(run: dict[str, Any]) -> bool:
    if run.get("task_id") != "inventory.read_only":
        return False
    if not run.get("evaluator", {}).get("passed"):
        return False
    if int(run.get("metrics", {}).get("human_rescues", 0)) != 0:
        return False
    return not _is_tooling_smoke(run)


def _is_tooling_smoke(run: dict[str, Any]) -> bool:
    agent = run.get("agent", {})
    run_id = run.get("run_id", "")
    return (
        agent.get("name") == "Tooling smoke"
        or agent.get("model") == "none"
        or "tooling-smoke" in run_id
    )
