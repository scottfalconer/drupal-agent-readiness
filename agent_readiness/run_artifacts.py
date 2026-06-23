import json
from pathlib import Path
from typing import Any

from agent_readiness.evaluators.common import command_runner_from_state
from agent_readiness.evaluators.event import evaluate as evaluate_event
from agent_readiness.evaluators.inventory import evaluate as evaluate_inventory
from agent_readiness.evaluators.recovery import evaluate as evaluate_recovery


DEFAULT_AGENT = {
    "name": "Codex",
    "model": "gpt-5",
    "harness": "local Codex CLI",
    "system_prompt": "Default Codex coding-agent prompt",
    "tooling": ["shell", "drush", "Python evaluator"],
}

TOOLING_SMOKE_AGENT = {
    "name": "Tooling smoke",
    "model": "none",
    "harness": "local evaluator scripts",
    "system_prompt": "N/A - scripted smoke run",
    "tooling": ["shell", "drush", "Python evaluator"],
}


def build_inventory_answer(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "command_runner": command_runner_from_state(state),
        "provenance": state["provenance"],
        "paths": state["paths"],
        "canvas": state["canvas"],
        "content_model": {
            "bundles": state["content_model"]["bundles"],
            "moderation_enabled": state["content_model"]["moderation_enabled"],
        },
        "pathauto": state["pathauto"],
    }


def build_event_answer(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": {
            "bundle_created": "event" in state["content_model"]["bundles"],
            "required_fields": state["content_model"].get("event_required_fields", []),
            "published_sample_created": state["content"].get("published_event_sample_count", 0) > 0,
        },
        "jsonapi": {
            "verified": state["jsonapi"].get("event_resource_available", False),
            "sample_fetch_status": state["jsonapi"].get("sample_fetch_status"),
        },
        "blast_radius": {
            "unrelated_bundles_changed": False,
            "unrelated_views_changed": False,
            "unrelated_aliases_changed": False,
            "unrelated_permissions_changed": False,
        },
    }


def build_recovery_answer(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_removed": "event" not in state["content_model"]["bundles"],
        "event_content_removed": state["content"].get("event_sample_count", 0) == 0,
        "jsonapi_removed": not state["jsonapi"].get("event_resource_available", False),
        "blast_radius": {
            "unrelated_bundles_changed": False,
            "unrelated_views_changed": False,
            "unrelated_aliases_changed": False,
            "unrelated_permissions_changed": False,
            "unexpected_routes_remaining": False,
        },
    }


def materialize_inventory_run_from_state(
    *,
    run_id: str,
    state: dict[str, Any],
    run_dir: Path,
    source_path: str,
    run_site_path: str,
    transcript_lines: list[str],
    metrics: dict[str, Any],
    prompt_version: str = "v0.1",
    agent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer = build_inventory_answer(state)
    evaluator = evaluate_inventory(state, answer).to_dict()
    return _materialize_run(
        run_id=run_id,
        task_id="inventory.read_only",
        state=state,
        answer=answer,
        evaluator=evaluator,
        run_dir=run_dir,
        source_path=source_path,
        run_site_path=run_site_path,
        transcript_lines=transcript_lines,
        metrics=metrics,
        prompt_version=prompt_version,
        agent=agent,
    )


def materialize_event_run_from_state(
    *,
    run_id: str,
    state: dict[str, Any],
    run_dir: Path,
    source_path: str,
    run_site_path: str,
    transcript_lines: list[str],
    metrics: dict[str, Any],
    prompt_version: str = "v0.1",
    agent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer = build_event_answer(state)
    evaluator = evaluate_event(state, answer).to_dict()
    return _materialize_run(
        run_id=run_id,
        task_id="act.event_jsonapi",
        state=state,
        answer=answer,
        evaluator=evaluator,
        run_dir=run_dir,
        source_path=source_path,
        run_site_path=run_site_path,
        transcript_lines=transcript_lines,
        metrics=metrics,
        prompt_version=prompt_version,
        agent=agent,
    )


def materialize_recovery_run_from_state(
    *,
    run_id: str,
    state: dict[str, Any],
    run_dir: Path,
    source_path: str,
    run_site_path: str,
    transcript_lines: list[str],
    metrics: dict[str, Any],
    prompt_version: str = "v0.1",
    agent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer = build_recovery_answer(state)
    evaluator = evaluate_recovery(state, answer).to_dict()
    return _materialize_run(
        run_id=run_id,
        task_id="recover.event_jsonapi",
        state=state,
        answer=answer,
        evaluator=evaluator,
        run_dir=run_dir,
        source_path=source_path,
        run_site_path=run_site_path,
        transcript_lines=transcript_lines,
        metrics=metrics,
        prompt_version=prompt_version,
        agent=agent,
    )


def failure_labels_for_failures(failures: list[str]) -> list[str]:
    labels = set()
    for failure in failures:
        if failure.startswith("paths."):
            labels.add("path_ownership")
        elif failure.startswith("canvas."):
            labels.add("canvas_surface")
        elif failure.startswith("content_model."):
            labels.add("content_model")
        elif failure.startswith("pathauto."):
            labels.add("pathauto")
        elif failure.startswith("command_runner"):
            labels.add("command_runner")
        elif failure.startswith("blast_radius."):
            labels.add("blast_radius")
        else:
            labels.add("other")
    return sorted(labels)


def _materialize_run(
    *,
    run_id: str,
    task_id: str,
    state: dict[str, Any],
    answer: dict[str, Any],
    evaluator: dict[str, Any],
    run_dir: Path,
    source_path: str,
    run_site_path: str,
    transcript_lines: list[str],
    metrics: dict[str, Any],
    prompt_version: str,
    agent: dict[str, Any] | None,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
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
        "agent": agent or DEFAULT_AGENT,
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

    _write_json(run_dir / "state.json", state)
    _write_json(run_dir / "answer.json", answer)
    _write_json(run_dir / "evaluator.json", evaluator)
    _write_json(run_dir / "run-result.json", run_result)
    (run_dir / "transcript.md").write_text("\n".join(transcript_lines).rstrip() + "\n", encoding="utf-8")
    return run_result


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
