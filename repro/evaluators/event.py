from typing import Any

from agent_readiness.evaluators.common import get_path
from agent_readiness.evaluators.result import EvaluationResult


def _event_related_alias(alias: str) -> bool:
    normalized = alias.lower()
    return "event" in normalized or "agent-readiness" in normalized


def evaluate(state: dict[str, Any], answer: dict[str, Any]) -> EvaluationResult:
    failures: list[str] = []
    bundles = get_path(state, "content_model.bundles") or []
    if "event" not in bundles:
        failures.append("content_model.bundles.event")
    if not get_path(answer, "event.bundle_created"):
        failures.append("event.bundle_created")

    required_state = get_path(state, "content_model.event_required_fields") or []
    required_answer = get_path(answer, "event.required_fields") or []
    for field_name in required_state:
        if field_name not in required_answer:
            failures.append(f"event.required_fields.{field_name}")

    if int(get_path(state, "content.published_event_sample_count") or 0) < 1:
        failures.append("content.published_event_sample_count")
    if not get_path(answer, "event.published_sample_created"):
        failures.append("event.published_sample_created")

    if not get_path(state, "jsonapi.event_resource_available"):
        failures.append("jsonapi.event_resource_available")
    if not get_path(answer, "jsonapi.verified"):
        failures.append("jsonapi.verified")
    if get_path(answer, "jsonapi.sample_fetch_status") != 200:
        failures.append("jsonapi.sample_fetch_status")

    baseline_bundles = get_path(state, "baseline.bundles")
    if baseline_bundles is not None:
        current_without_event = sorted(bundle for bundle in bundles if bundle != "event")
        if sorted(baseline_bundles) != current_without_event:
            failures.append("blast_radius.unrelated_bundles_changed")

    baseline_views = get_path(state, "baseline.views")
    current_views = get_path(state, "views")
    if baseline_views is not None and current_views is not None and sorted(baseline_views) != sorted(current_views):
        failures.append("blast_radius.unrelated_views_changed")

    baseline_aliases = get_path(state, "baseline.aliases")
    current_aliases = get_path(state, "aliases")
    if baseline_aliases is not None and current_aliases is not None:
        baseline_alias_set = set(baseline_aliases)
        current_alias_set = set(current_aliases)
        unrelated_removed = baseline_alias_set - current_alias_set
        unrelated_added = {
            alias
            for alias in current_alias_set - baseline_alias_set
            if not _event_related_alias(alias)
        }
        if unrelated_removed or unrelated_added:
            failures.append("blast_radius.unrelated_aliases_changed")

    baseline_permissions = get_path(state, "baseline.role_permissions")
    current_permissions = get_path(state, "permissions.role_permissions")
    if baseline_permissions is not None and current_permissions is not None and baseline_permissions != current_permissions:
        failures.append("blast_radius.unrelated_permissions_changed")
    if get_path(state, "permissions.event_permissions_granted"):
        failures.append("blast_radius.unrelated_permissions_changed")

    if get_path(state, "routes.event_add_route_available") is False:
        failures.append("routes.event_add_route_available")

    for key in [
        "unrelated_bundles_changed",
        "unrelated_views_changed",
        "unrelated_aliases_changed",
        "unrelated_permissions_changed",
    ]:
        if get_path(answer, f"blast_radius.{key}"):
            failures.append(f"blast_radius.{key}")

    return EvaluationResult(passed=not failures, failures=failures)
