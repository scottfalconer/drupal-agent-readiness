from typing import Any


def audit_inventory_baseline(run_results: list[dict[str, Any]], required_passes: int = 1) -> list[str]:
    if type(required_passes) is not int or required_passes < 1:
        raise ValueError("required_passes must be an integer greater than or equal to 1")
    errors: list[str] = []
    passing_ids = {
        run.get("run_id")
        for run in run_results
        if _is_independent_inventory_pass(run)
        and isinstance(run.get("run_id"), str)
        and run["run_id"]
    }
    if len(passing_ids) < required_passes:
        errors.append(
            f"no-rescue non-smoke inventory examples: {len(passing_ids)}/{required_passes}"
        )
    return errors


def _is_independent_inventory_pass(run: dict[str, Any]) -> bool:
    if run.get("task_id") != "inventory.read_only":
        return False
    if run.get("evaluator", {}).get("passed") is not True:
        return False
    human_rescues = run.get("metrics", {}).get("human_rescues")
    if type(human_rescues) is not int or human_rescues != 0:
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
