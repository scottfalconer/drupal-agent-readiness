"""Independent recomputation for retained alias-safety workflow evidence."""

from __future__ import annotations

from typing import Any, Mapping


class AliasSafetyMetricError(ValueError):
    """Raised when raw, ground-truth, and derived alias evidence diverge."""


def reason_recognizes_latent(reason: str) -> bool:
    normalized = (reason or "").lower()
    return "disabl" in normalized or "latent" in normalized


def recompute_alias_safety_metrics(
    raw_workflow: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute canonical run and arm metrics from raw answers and truth."""

    result = raw_workflow.get("result", raw_workflow)
    items = list(result.get("told") or []) + list(result.get("blind") or [])
    if not items:
        raise AliasSafetyMetricError("raw workflow contains no runs")
    if not ground_truth or any(
        not isinstance(path, str)
        or not path.startswith("/")
        or not isinstance(truth, Mapping)
        or not isinstance(truth.get("safe"), bool)
        or "blocker_kind" not in truth
        for path, truth in ground_truth.items()
    ):
        raise AliasSafetyMetricError("ground truth is not a typed candidate map")
    latent_paths = sorted(
        path
        for path, truth in ground_truth.items()
        if truth.get("blocker_kind") == "latent_disabled_view"
    )
    if not latent_paths:
        raise AliasSafetyMetricError("ground truth has no latent disabled-View paths")

    cells: dict[str, dict[str, Any]] = {}
    seen_runs: set[tuple[str, str, str, int]] = set()
    candidate_paths = set(ground_truth)
    for item in items:
        model = item.get("model")
        condition = item.get("condition")
        arm = item.get("arm")
        attempt = item.get("n")
        if (
            not isinstance(model, str)
            or condition not in {"blind", "told"}
            or arm not in {"raw", "equipped"}
            or not isinstance(attempt, int)
            or attempt < 1
        ):
            raise AliasSafetyMetricError("raw workflow run identity is invalid")
        identity = (model, condition, arm, attempt)
        if identity in seen_runs:
            raise AliasSafetyMetricError(f"duplicate raw workflow run {identity}")
        seen_runs.add(identity)
        answer = item.get("answer") or {}
        assessments = answer.get("assessments")
        if not isinstance(assessments, Mapping) or set(assessments) != candidate_paths:
            raise AliasSafetyMetricError(
                f"raw workflow run {identity} has a different candidate unit"
            )

        failures: list[str] = []
        verdict_correct = 0
        latent_correct = 0
        latent_reasoned = 0
        for path, truth in ground_truth.items():
            assessment = assessments.get(path)
            if not isinstance(assessment, Mapping) or not isinstance(
                assessment.get("safe"), bool
            ):
                raise AliasSafetyMetricError(
                    f"raw workflow run {identity} has an untyped answer for {path}"
                )
            answer_safe = assessment["safe"]
            if answer_safe == truth["safe"]:
                verdict_correct += 1
            else:
                failures.append(f"{path}.safe")
            if path in latent_paths and answer_safe is False:
                latent_correct += 1
                if condition == "blind" and reason_recognizes_latent(
                    str(assessment.get("reason") or "")
                ):
                    latent_reasoned += 1

        command_count = answer.get("command_count")
        if not isinstance(command_count, int) or command_count < 0:
            raise AliasSafetyMetricError(
                f"raw workflow run {identity} has invalid command_count"
            )
        cell_id = f"ab-{model}-{condition}"
        cell = cells.setdefault(
            cell_id,
            {"model": model, "condition": condition, "runs": []},
        )
        cell["runs"].append(
            {
                "run_id": f"{arm}-{attempt}",
                "arm": arm,
                "passed": not failures,
                "failures": failures,
                "latent_total": len(latent_paths),
                "latent_correct": latent_correct,
                "latent_reasoned": latent_reasoned,
                "verdict_correct": verdict_correct,
                "command_count": command_count,
            }
        )

    for cell in cells.values():
        cell["runs"].sort(key=lambda run: (run["arm"], _run_number(run["run_id"])))
    summary = {
        cell_id: {
            "model": cell["model"],
            "condition": cell["condition"],
            "raw_drush": _arm_stats(cell["runs"], "raw", len(candidate_paths)),
            "site_architecture": _arm_stats(
                cell["runs"], "equipped", len(candidate_paths)
            ),
        }
        for cell_id, cell in sorted(cells.items())
    }
    return {
        "latent_paths": latent_paths,
        "cells": cells,
        "summary": summary,
    }


def validate_retained_alias_safety_results(
    raw_workflow: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
    retained_results: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute and require exact retained run and summary metric equality."""

    canonical = recompute_alias_safety_metrics(raw_workflow, ground_truth)
    if retained_results.get("latent_paths") != canonical["latent_paths"]:
        raise AliasSafetyMetricError(
            "retained latent path set differs from ground truth"
        )
    retained_cells = retained_results.get("cells")
    retained_summary = retained_results.get("summary")
    raw_models = {cell["model"] for cell in canonical["cells"].values()}
    model_ids = retained_results.get("model_ids")
    if (
        not isinstance(model_ids, Mapping)
        or set(model_ids) != raw_models
        or any(not isinstance(value, str) or not value for value in model_ids.values())
    ):
        raise AliasSafetyMetricError(
            "retained model IDs do not bind every raw workflow model label"
        )
    if not isinstance(retained_cells, Mapping) or set(retained_cells) != set(
        canonical["cells"]
    ):
        raise AliasSafetyMetricError("retained cell set differs from raw workflow")
    if not isinstance(retained_summary, Mapping) or set(retained_summary) != set(
        canonical["summary"]
    ):
        raise AliasSafetyMetricError("retained summary cells differ from raw workflow")

    for cell_id, expected_cell in canonical["cells"].items():
        observed_cell = retained_cells[cell_id]
        if (
            observed_cell.get("model") != expected_cell["model"]
            or observed_cell.get("condition") != expected_cell["condition"]
            or observed_cell.get("model_id") != model_ids[expected_cell["model"]]
        ):
            raise AliasSafetyMetricError(
                f"retained cell identity differs for {cell_id}"
            )
        observed_runs = sorted(
            observed_cell.get("runs") or [],
            key=lambda run: (run.get("arm", ""), _run_number(run.get("run_id", "-0"))),
        )
        if observed_runs != expected_cell["runs"]:
            raise AliasSafetyMetricError(
                f"retained run metrics do not recompute for {cell_id}"
            )

        observed_summary = retained_summary[cell_id]
        expected_summary = canonical["summary"][cell_id]
        for identity_key in ("model", "condition"):
            if observed_summary.get(identity_key) != expected_summary[identity_key]:
                raise AliasSafetyMetricError(
                    f"retained summary identity differs for {cell_id}"
                )
        if observed_summary.get("model_id") != model_ids[expected_summary["model"]]:
            raise AliasSafetyMetricError(
                f"retained summary model ID differs for {cell_id}"
            )
        for arm_key in ("raw_drush", "site_architecture"):
            if observed_summary.get(arm_key) != expected_summary[arm_key]:
                raise AliasSafetyMetricError(
                    f"retained summary metrics do not recompute for {cell_id}.{arm_key}"
                )
    return canonical


def recompute_action_alias_metrics(
    answer: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
    write_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute action metrics from judgments and independently derived state evidence."""

    if (
        set(answer)
        != {
            "schema_version",
            "run_id",
            "candidate_path_judgments",
        }
        or answer.get("schema_version")
        != "drupal_agent_readiness.alias_safety_action_answer.v1"
        or not isinstance(answer.get("run_id"), str)
        or not answer["run_id"]
    ):
        raise AliasSafetyMetricError("action answer is not canonical")
    if set(ground_truth) != {
        "schema_version",
        "substrate_id",
        "fixture_id",
        "starting_site_manifest_sha256",
        "coverage_claim_id",
        "task_id",
        "path_truth",
    } or ground_truth.get("schema_version") != (
        "drupal_agent_readiness.alias_safety_ground_truth.v1"
    ):
        raise AliasSafetyMetricError("action ground truth root is not canonical")
    path_truth = ground_truth.get("path_truth")
    judgments = answer.get("candidate_path_judgments")
    if not isinstance(path_truth, list) or not isinstance(judgments, list):
        raise AliasSafetyMetricError("action answer or ground truth lacks path units")
    truth_by_path: dict[str, Mapping[str, Any]] = {}
    for item in path_truth:
        if (
            not isinstance(item, Mapping)
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
            raise AliasSafetyMetricError("action ground truth path unit is invalid")
        truth_by_path[item["path"]] = item
    judgment_by_path: dict[str, Mapping[str, Any]] = {}
    for item in judgments:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"path", "classification", "write_decision"}
            or item.get("path") not in truth_by_path
            or item["path"] in judgment_by_path
            or item.get("classification") not in {"safe_to_write", "unsafe_claimed"}
            or item.get("write_decision") not in {"attempt", "withhold"}
        ):
            raise AliasSafetyMetricError("action answer path judgment is invalid")
        judgment_by_path[item["path"]] = item
    if set(judgment_by_path) != set(truth_by_path):
        raise AliasSafetyMetricError(
            "action answer does not cover the exact path census"
        )

    hidden_claim_paths = {
        path
        for path, truth in truth_by_path.items()
        if truth["truth"] == "hidden_claim"
    }
    free_paths = {
        path for path, truth in truth_by_path.items() if truth["truth"] == "free"
    }
    if not hidden_claim_paths or not free_paths:
        raise AliasSafetyMetricError(
            "action metric requires at least one hidden-claim and one free path"
        )
    hidden_false_safe = sum(
        judgment_by_path[path]["classification"] == "safe_to_write"
        for path in hidden_claim_paths
    )
    free_false_unsafe = sum(
        judgment_by_path[path]["classification"] == "unsafe_claimed"
        for path in free_paths
    )
    expected_collision_paths = {
        path
        for path in set(truth_by_path) - free_paths
        if judgment_by_path[path]["write_decision"] == "attempt"
    }
    expected_refused_paths = {
        path
        for path in free_paths
        if judgment_by_path[path]["write_decision"] == "withhold"
    }
    if set(write_evidence) != {
        "completed_paths",
        "collision_paths",
        "refused_paths",
        "state_delta_valid",
        "tool_failure",
    }:
        raise AliasSafetyMetricError("write evidence root is not canonical")

    def path_set(field: str) -> set[str]:
        value = write_evidence.get(field)
        if (
            not isinstance(value, list)
            or len(value) != len(set(value))
            or any(path not in truth_by_path for path in value)
        ):
            raise AliasSafetyMetricError(f"write evidence {field} is invalid")
        return set(value)

    completed_paths = path_set("completed_paths")
    collision_paths = path_set("collision_paths")
    refused_paths = path_set("refused_paths")
    if not isinstance(write_evidence.get("state_delta_valid"), bool):
        raise AliasSafetyMetricError("write evidence state delta verdict is invalid")
    if not isinstance(write_evidence.get("tool_failure"), bool):
        raise AliasSafetyMetricError("write evidence tool failure verdict is invalid")
    tool_failure = write_evidence["tool_failure"]
    if collision_paths != expected_collision_paths:
        raise AliasSafetyMetricError(
            "write probe collision paths contradict the answer"
        )
    if refused_paths != expected_refused_paths:
        raise AliasSafetyMetricError("write probe refusal paths contradict the answer")
    expected_completed_paths = (
        set()
        if collision_paths or refused_paths or tool_failure
        else {
            path
            for path in free_paths
            if judgment_by_path[path]["write_decision"] == "attempt"
        }
    )
    if completed_paths != expected_completed_paths:
        raise AliasSafetyMetricError(
            "completed writes do not match final-state evidence"
        )
    collision = bool(collision_paths)
    refusal = bool(refused_paths)
    exact_candidate_census = all(
        judgment_by_path[path]["classification"]
        == ("safe_to_write" if truth["truth"] == "free" else "unsafe_claimed")
        and judgment_by_path[path]["write_decision"]
        == ("attempt" if truth["truth"] == "free" else "withhold")
        for path, truth in truth_by_path.items()
    )
    task_success = bool(
        exact_candidate_census
        and not tool_failure
        and not refusal
        and not collision
        and write_evidence["state_delta_valid"]
        and completed_paths == free_paths
    )

    def metric(numerator: int, denominator: int = 1) -> dict[str, Any]:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": float(numerator / denominator),
        }

    return {
        "metrics": {
            "hidden_claim_false_safe_rate": metric(
                hidden_false_safe, len(hidden_claim_paths)
            ),
            "free-path-false-unsafe-rate": metric(free_false_unsafe, len(free_paths)),
            "valid-run-tool-failure-rate": metric(int(tool_failure)),
            "actual-write-collision-rate": metric(int(collision)),
            "actual-write-refusal-rate": metric(int(refusal)),
            "task_success": metric(int(task_success)),
        },
        "write_outcome": {
            "collision": collision,
            "refused": refusal,
            "task_success": task_success,
            "completed_paths": sorted(completed_paths),
            "collision_paths": sorted(collision_paths),
            "refused_paths": sorted(refused_paths),
        },
    }


def _run_number(run_id: str) -> int:
    try:
        return int(run_id.rsplit("-", 1)[1])
    except (AttributeError, IndexError, ValueError) as exc:
        raise AliasSafetyMetricError(f"invalid retained run id {run_id!r}") from exc


def _arm_stats(
    runs: list[dict[str, Any]], arm: str, candidate_count: int
) -> dict[str, Any]:
    arm_runs = [run for run in runs if run["arm"] == arm]
    latent_total = sum(run["latent_total"] for run in arm_runs)
    latent_correct = sum(run["latent_correct"] for run in arm_runs)
    latent_reasoned = sum(run["latent_reasoned"] for run in arm_runs)
    verdict_correct = sum(run["verdict_correct"] for run in arm_runs)
    commands = [run["command_count"] for run in arm_runs]
    return {
        "n": len(arm_runs),
        "passes": sum(1 for run in arm_runs if run["passed"]),
        "latent_total": latent_total,
        "latent_correct": latent_correct,
        "latent_accuracy": round(latent_correct / latent_total, 3)
        if latent_total
        else None,
        "latent_reasoned": latent_reasoned,
        "latent_reasoned_accuracy": round(latent_reasoned / latent_total, 3)
        if latent_total
        else None,
        "verdict_correct": verdict_correct,
        "verdict_total": len(arm_runs) * candidate_count,
        "avg_commands": round(sum(commands) / len(commands), 1) if commands else None,
    }
