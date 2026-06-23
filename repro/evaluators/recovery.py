from typing import Any

from agent_readiness.evaluators.common import get_path
from agent_readiness.evaluators.result import EvaluationResult


def evaluate(state: dict[str, Any], answer: dict[str, Any]) -> EvaluationResult:
    failures: list[str] = []
    bundles = get_path(state, "content_model.bundles") or []
    if "event" in bundles:
        failures.append("content_model.bundles.event")
    if get_path(state, "content_model.event_required_fields"):
        failures.append("content_model.event_required_fields")
    if int(get_path(state, "content.event_sample_count") or 0) != 0:
        failures.append("content.event_sample_count")
    if get_path(state, "jsonapi.event_resource_available"):
        failures.append("jsonapi.event_resource_available")

    baseline_bundles = get_path(state, "baseline.bundles")
    if baseline_bundles is not None and sorted(baseline_bundles) != sorted(bundles):
        failures.append("blast_radius.unrelated_bundles_changed")

    baseline_views = get_path(state, "baseline.views")
    current_views = get_path(state, "views")
    if baseline_views is not None and current_views is not None and sorted(baseline_views) != sorted(current_views):
        failures.append("blast_radius.unrelated_views_changed")

    baseline_aliases = get_path(state, "baseline.aliases")
    current_aliases = get_path(state, "aliases")
    if baseline_aliases is not None and current_aliases is not None and sorted(baseline_aliases) != sorted(current_aliases):
        failures.append("blast_radius.unrelated_aliases_changed")

    baseline_permissions = get_path(state, "baseline.role_permissions")
    current_permissions = get_path(state, "permissions.role_permissions")
    if baseline_permissions is not None and current_permissions is not None and baseline_permissions != current_permissions:
        failures.append("blast_radius.unrelated_permissions_changed")
    if get_path(state, "permissions.event_permissions_granted"):
        failures.append("permissions.event_permissions_granted")

    if get_path(state, "routes.event_add_route_available"):
        failures.append("routes.event_add_route_available")

    for key in [
        "event_removed",
        "event_content_removed",
        "jsonapi_removed",
    ]:
        if not answer.get(key):
            failures.append(key)

    for key in [
        "unrelated_bundles_changed",
        "unrelated_views_changed",
        "unrelated_aliases_changed",
        "unrelated_permissions_changed",
        "unexpected_routes_remaining",
    ]:
        if get_path(state, f"blast_radius.{key}") or get_path(answer, f"blast_radius.{key}"):
            failures.append(f"blast_radius.{key}")

    return EvaluationResult(passed=not failures, failures=failures)
