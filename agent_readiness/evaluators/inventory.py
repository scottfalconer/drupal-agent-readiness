from typing import Any

from agent_readiness.evaluators.common import (
    add_contains_failures,
    add_equal_failure,
    add_unexpected_failures,
    command_runner_from_state,
    get_path,
)
from agent_readiness.evaluators.result import EvaluationResult


REQUIRED_PATHS = ["/blog", "/node", "/home"]


def evaluate(state: dict[str, Any], answer: dict[str, Any]) -> EvaluationResult:
    failures: list[str] = []
    expected_runner = command_runner_from_state(state)
    if expected_runner and answer.get("command_runner") != expected_runner:
        failures.append("command_runner")

    for path in [
        "provenance.project_name",
        "provenance.project_version",
        "provenance.site_template",
        "provenance.active_config_source",
        "provenance.config_sync_status",
    ]:
        add_equal_failure(failures, state, answer, path)

    for path in REQUIRED_PATHS:
        state_path = f"paths.{path}"
        answer_path = f"paths.{path}"
        if get_path(answer, answer_path) is None:
            failures.append(answer_path)
            continue
        for field in ["claimed", "owner_kind"]:
            add_equal_failure(failures, state, answer, f"{state_path}.{field}")
        state_entity_type = get_path(state, f"{state_path}.entity_type")
        if state_entity_type:
            add_equal_failure(failures, state, answer, f"{state_path}.entity_type")
        elif get_path(answer, f"{answer_path}.entity_type") is not None:
            failures.append(f"{answer_path}.entity_type.unexpected")

    # Canvas page count must match exactly: under-counting misses surfaces,
    # over-counting hallucinates them. Both are errors.
    state_page_count = _as_int(get_path(state, "canvas.page_count")) or 0
    if _as_int(get_path(answer, "canvas.page_count")) != state_page_count:
        failures.append("canvas.page_count")

    # List fields are graded as sets: missing real surfaces AND reporting
    # surfaces that do not exist both fail.
    expected_listings = _normalize_embedded_listings(get_path(state, "canvas.embedded_listings") or [])
    answer_listings = _normalize_embedded_listings(get_path(answer, "canvas.embedded_listings") or [])
    add_contains_failures(failures, expected_listings, answer_listings, "canvas.embedded_listings")
    add_unexpected_failures(failures, expected_listings, answer_listings, "canvas.embedded_listings")

    expected_bundles = _normalize_bundles(get_path(state, "content_model.bundles") or [])
    answer_bundles = _normalize_bundles(get_path(answer, "content_model.bundles") or [])
    add_contains_failures(failures, expected_bundles, answer_bundles, "content_model.bundles")
    add_unexpected_failures(failures, expected_bundles, answer_bundles, "content_model.bundles")

    add_equal_failure(failures, state, answer, "content_model.moderation_enabled")
    add_equal_failure(failures, state, answer, "pathauto.enabled")

    expected_patterns = _normalize_pathauto_patterns(get_path(state, "pathauto.patterns") or [])
    answer_patterns = _normalize_pathauto_patterns(get_path(answer, "pathauto.patterns") or [])
    add_contains_failures(failures, expected_patterns, answer_patterns, "pathauto.patterns")
    add_unexpected_failures(failures, expected_patterns, answer_patterns, "pathauto.patterns")

    return EvaluationResult(passed=not failures, failures=failures)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_embedded_listings(items: list[Any]) -> list[str]:
    normalized: list[str] = []
    for item in items:
        if isinstance(item, str):
            normalized.append(item)
        elif isinstance(item, dict):
            view = item.get("view") or item.get("view_id")
            display = item.get("display") or item.get("display_id")
            if view and display:
                normalized.append(f"{view}:{display}")
    return sorted(set(normalized))


def _normalize_bundles(items: list[Any]) -> list[str]:
    normalized: list[str] = []
    for item in items:
        if isinstance(item, str):
            normalized.append(item)
        elif isinstance(item, dict) and item.get("bundle"):
            normalized.append(str(item["bundle"]))
    return sorted(set(normalized))


def _normalize_pathauto_patterns(items: list[Any]) -> list[str]:
    normalized: list[str] = []
    for item in items:
        if isinstance(item, str):
            normalized.append(item)
        elif isinstance(item, dict) and item.get("pattern"):
            normalized.append(str(item["pattern"]))
    return sorted(set(normalized))
