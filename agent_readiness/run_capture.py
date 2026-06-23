import json
from pathlib import Path
from typing import Any

from agent_readiness.evaluators.common import collect_live_state, load_json
from agent_readiness.evaluators.event import evaluate as evaluate_event
from agent_readiness.evaluators.inventory import evaluate as evaluate_inventory
from agent_readiness.evaluators.recovery import evaluate as evaluate_recovery
from agent_readiness.run_artifacts import failure_labels_for_failures


EVALUATORS = {
    "inventory.read_only": evaluate_inventory,
    "act.event_jsonapi": evaluate_event,
    "recover.event_jsonapi": evaluate_recovery,
}


def capture_run(
    *,
    run_id: str,
    task_id: str,
    answer_json: Path,
    transcript: Path,
    runs_dir: Path,
    source_path: str,
    run_site_path: str,
    prompt_version: str,
    agent: dict[str, Any],
    metrics: dict[str, Any],
    state: dict[str, Any] | None = None,
    site_root: Path | None = None,
    baseline_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if task_id not in EVALUATORS:
        raise ValueError(f"Unsupported task_id: {task_id}")
    if state is None:
        if site_root is None:
            raise ValueError("Either state or site_root is required")
        state = collect_live_state(site_root)
    if baseline_state is not None:
        state = dict(state)
        state["baseline"] = _baseline_projection(baseline_state)

    answer = load_json(answer_json)
    evaluator = EVALUATORS[task_id](state, answer).to_dict()
    run_dir = runs_dir / run_id
    if run_dir.exists():
        raise FileExistsError(f"Run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)

    artifacts = {
        "answer_json": f"runs/{run_id}/answer.json",
        "transcript": f"runs/{run_id}/transcript.md",
        "state_json": f"runs/{run_id}/state.json",
        "evaluator_json": f"runs/{run_id}/evaluator.json",
    }
    run_result = {
        "run_id": run_id,
        "task_id": task_id,
        "prompt_version": prompt_version,
        "substrate": {
            "id": "haven-clean-install",
            "source_path": source_path,
            "run_site_path": run_site_path,
        },
        "agent": agent,
        "metrics": {
            "elapsed_seconds": metrics["elapsed_seconds"],
            "tool_calls": metrics["tool_calls"],
            "human_rescues": metrics["human_rescues"],
        },
        "evaluator": {
            "passed": evaluator["passed"],
            "failures": evaluator["failures"],
            "warnings": evaluator["warnings"],
        },
        "failure_labels": failure_labels_for_failures(evaluator["failures"]),
        "artifacts": artifacts,
    }

    _write_json(run_dir / "answer.json", answer)
    _write_json(run_dir / "state.json", state)
    _write_json(run_dir / "evaluator.json", evaluator)
    _write_json(run_dir / "run-result.json", run_result)
    (run_dir / "transcript.md").write_text(transcript.read_text(encoding="utf-8"), encoding="utf-8")
    return run_result


def _baseline_projection(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundles": state.get("content_model", {}).get("bundles", []),
        "views": state.get("views", []),
        "aliases": state.get("aliases", []),
        "role_permissions": state.get("permissions", {}).get("role_permissions", {}),
        "event_add_route_available": state.get("routes", {}).get("event_add_route_available", False),
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
