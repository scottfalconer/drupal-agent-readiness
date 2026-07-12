from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from html import escape as html_escape
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = REPO_ROOT / "method" / "eval-references"
DEFAULT_SCHEMA_PATH = REPO_ROOT / "method" / "schema" / "eval-reference-v1.schema.json"
DEFAULT_JSON_OUTPUT = REPO_ROOT / "docs" / "eval-landscape.json"
DEFAULT_MARKDOWN_OUTPUT = REPO_ROOT / "docs" / "eval-landscape.md"

LIFECYCLE_ORDER = (
    "choose_onboard",
    "connect",
    "understand",
    "plan_clarify",
    "act",
    "verify",
    "recover",
    "handoff",
)
TASK_FAMILY_ORDER = (
    "supported_cold_start",
    "governed_editorial_change",
    "diagnosis_and_rollback",
)
DISPOSITION_ORDER = (
    "reference_only",
    "candidate_for_local_adaptation",
    "candidate_for_local_reproduction",
    "candidate_for_dataset_reuse",
    "candidate_for_evaluator_reuse",
    "candidate_for_substrate_reuse",
)
AGENT_CLASS_ORDER = (
    "external_coding_agent",
    "browser_agent",
    "drupal_native_agent",
    "model_only",
    "not_agent_specific",
)
# Defense in depth. The schema is closed, and this list prevents later schema
# changes from quietly turning a reference record into an integration manifest.
PROHIBITED_FIELD_TOKENS = frozenset(
    {
        "command",
        "commands",
        "script",
        "scripts",
        "install",
        "installation",
        "credential",
        "credentials",
        "secret",
        "secrets",
        "token",
        "tokens",
        "executable",
        "execution",
    }
)

REGISTRY_POLICY = {
    "purpose": "discovery_and_candidate_selection",
    "success_metric": "documented_downstream_conversion",
    "recorded_conversions": 0,
    "inventory_count_is_success": False,
    "intake_state": "open_pending_review",
    "listing_effect": "none",
    "trust_assumption": "none",
    "network_access": "none",
    "local_adoption_required": True,
    "external_results_are_evidence": False,
    "scorecard_eligibility_from_listing": False,
    "routine_curation_limit_hours_per_week": 1,
    "review_date": "2026-10-15",
    "freeze_if_no_conversion_by_review": True,
}


class EvalReferenceError(ValueError):
    """Raised when an external evaluation reference is invalid."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvalReferenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalReferenceError(f"cannot load JSON from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvalReferenceError(f"expected a JSON object in {path}")
    return payload


def _resolve_local_ref(root_schema: Mapping[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise EvalReferenceError(
            f"schema uses unsupported non-local reference: {reference}"
        )
    current: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or part not in current:
            raise EvalReferenceError(f"schema reference does not resolve: {reference}")
        current = current[part]
    return current


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    raise EvalReferenceError(f"schema uses unsupported JSON type: {expected}")


def _value_is_unique(value: Any, prior: Sequence[Any]) -> bool:
    return not any(value == candidate for candidate in prior)


def _schema_errors(
    instance: Any,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    path: str,
) -> list[str]:
    """Validate the closed registry schema using a small stdlib-only subset."""

    if "$ref" in schema:
        target = _resolve_local_ref(root_schema, schema["$ref"])
        if not isinstance(target, Mapping):
            raise EvalReferenceError(
                f"schema reference is not an object: {schema['$ref']}"
            )
        return _schema_errors(instance, target, root_schema, path)

    errors: list[str] = []
    if "if" in schema:
        condition = schema["if"]
        if not isinstance(condition, Mapping):
            raise EvalReferenceError("schema if clause must be an object")
        condition_matches = not _schema_errors(instance, condition, root_schema, path)
        selected = schema.get("then" if condition_matches else "else")
        if selected is not None:
            if not isinstance(selected, Mapping):
                raise EvalReferenceError("schema conditional branch must be an object")
            errors.extend(_schema_errors(instance, selected, root_schema, path))

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} is not in the allowed enum")

    expected_type = schema.get("type")
    if expected_type is not None:
        if not isinstance(expected_type, str):
            raise EvalReferenceError("schema type must be a string")
        if not _matches_json_type(instance, expected_type):
            errors.append(f"{path}: expected {expected_type}")
            return errors

    if isinstance(instance, str):
        minimum_length = schema.get("minLength")
        if minimum_length is not None and len(instance) < minimum_length:
            errors.append(
                f"{path}: string is shorter than minimum length {minimum_length}"
            )
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, instance) is None:
            errors.append(f"{path}: string does not match pattern {pattern!r}")
        if schema.get("format") == "date":
            try:
                parsed_date = date.fromisoformat(instance)
            except ValueError:
                errors.append(f"{path}: value is not an ISO date")
            else:
                if parsed_date.isoformat() != instance:
                    errors.append(f"{path}: value is not a canonical ISO date")
        elif schema.get("format") == "uri":
            parsed = urlparse(instance)
            if not parsed.scheme:
                errors.append(f"{path}: value is not an absolute URI")

    if isinstance(instance, Mapping):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                errors.append(f"{path}: required property {key!r} is missing")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise EvalReferenceError("schema properties must be an object")
        if schema.get("additionalProperties") is False:
            for key in sorted(set(instance) - set(properties)):
                errors.append(f"{path}: additional property {key!r} is not allowed")
        for key, child_schema in properties.items():
            if key not in instance:
                continue
            if not isinstance(child_schema, Mapping):
                raise EvalReferenceError(f"schema property {key!r} must be an object")
            errors.extend(
                _schema_errors(
                    instance[key], child_schema, root_schema, f"{path}.{key}"
                )
            )

    if isinstance(instance, list):
        minimum_items = schema.get("minItems")
        if minimum_items is not None and len(instance) < minimum_items:
            errors.append(f"{path}: array has fewer than minimum {minimum_items} items")
        maximum_items = schema.get("maxItems")
        if maximum_items is not None and len(instance) > maximum_items:
            errors.append(f"{path}: array has more than maximum {maximum_items} items")
        if schema.get("uniqueItems") is True:
            prior: list[Any] = []
            for index, value in enumerate(instance):
                if not _value_is_unique(value, prior):
                    errors.append(f"{path}[{index}]: duplicate array item")
                prior.append(value)
        item_schema = schema.get("items")
        if item_schema is not None:
            if not isinstance(item_schema, Mapping):
                raise EvalReferenceError("schema items must be an object")
            for index, value in enumerate(instance):
                errors.extend(
                    _schema_errors(value, item_schema, root_schema, f"{path}[{index}]")
                )

    for child_schema in schema.get("allOf", []):
        if not isinstance(child_schema, Mapping):
            raise EvalReferenceError("schema allOf entries must be objects")
        errors.extend(_schema_errors(instance, child_schema, root_schema, path))
    return errors


def _validate_schema_instance(instance: Any, schema: Mapping[str, Any]) -> list[str]:
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise EvalReferenceError(
            "reference schema must declare JSON Schema draft 2020-12"
        )
    if schema.get("type") != "object" or not isinstance(schema.get("$defs"), Mapping):
        raise EvalReferenceError("reference schema must be a closed object with $defs")
    return sorted(_schema_errors(instance, schema, schema, "$"))


def _walk_field_names(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, key
            yield from _walk_field_names(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_field_names(child, f"{path}[{index}]")


def _validate_inert_fields(reference: Mapping[str, Any]) -> None:
    for path, key in _walk_field_names(reference):
        normalized_tokens = set(key.lower().replace("-", "_").split("_"))
        prohibited = normalized_tokens & PROHIBITED_FIELD_TOKENS
        if prohibited:
            token = sorted(prohibited)[0]
            raise EvalReferenceError(
                f"{path}: field token {token!r} is prohibited in pointer-only records"
            )


def _validate_https_url(value: str, path: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in value)
    ):
        raise EvalReferenceError(
            f"{path}: reference URLs must be credential-free HTTPS URLs"
        )
    try:
        parsed.port
    except ValueError as exc:
        raise EvalReferenceError(f"{path}: reference URL has an invalid port") from exc


def _validate_commit_pointer(artifact: Mapping[str, Any], path: str) -> None:
    revision = artifact["upstream_revision"]
    if revision["kind"] != "commit":
        return
    commit = revision["value"]
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise EvalReferenceError(
            f"{path}.upstream_revision.value: commit must be 40 lowercase hex characters"
        )
    if artifact["pointer_type"] in {
        "repository",
        "repository_tree",
        "repository_file",
    }:
        path_segments = urlparse(artifact["url"]).path.split("/")
        anchored = any(
            segment in {"tree", "blob", "commit", "commits"}
            and index + 1 < len(path_segments)
            and path_segments[index + 1] == commit
            for index, segment in enumerate(path_segments)
        )
        if not anchored:
            raise EvalReferenceError(
                f"{path}.url: repository commit pointer must anchor the commit after tree, blob, or commit"
            )


def _require_canonical_order(
    values: Sequence[str], order: Sequence[str], path: str
) -> None:
    order_index = {value: index for index, value in enumerate(order)}
    expected = sorted(values, key=order_index.__getitem__)
    if list(values) != expected:
        raise EvalReferenceError(
            f"{path}: values must use canonical order {list(order)!r}"
        )


def validate_reference(
    reference: dict[str, Any],
    schema: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> None:
    """Validate one pointer record without reading or calling its URLs."""

    _validate_inert_fields(reference)
    errors = _validate_schema_instance(reference, schema)
    if errors:
        raise EvalReferenceError("; ".join(errors))

    source_id = reference["id"]
    if source_path is not None and source_path.stem != source_id:
        raise EvalReferenceError(
            f"{source_path}: filename must match source id {source_id!r}"
        )

    _validate_https_url(reference["canonical_url"], "$.canonical_url")
    if "repository_url" in reference:
        _validate_https_url(reference["repository_url"], "$.repository_url")
    for index, url in enumerate(reference["provenance"]["source_urls"]):
        _validate_https_url(url, f"$.provenance.source_urls[{index}]")
    if reference["canonical_url"] not in reference["provenance"]["source_urls"]:
        raise EvalReferenceError(
            "$.provenance.source_urls must include the canonical source URL"
        )

    artifact_ids: set[str] = set()
    benchmark_plan_count = 0
    for index, artifact in enumerate(reference["artifacts"]):
        artifact_id = artifact["id"]
        if artifact_id in artifact_ids:
            raise EvalReferenceError(
                f"$.artifacts[{index}].id: duplicate artifact id {artifact_id!r}"
            )
        artifact_ids.add(artifact_id)
        if artifact["kind"] == "benchmark_plan":
            benchmark_plan_count += 1
        _validate_https_url(artifact["url"], f"$.artifacts[{index}].url")
        _validate_commit_pointer(artifact, f"$.artifacts[{index}]")
        if artifact["kind"] == "benchmark_plan" and (
            artifact["mapping_scope"] != "supporting_infrastructure"
            or artifact["disposition"] != "reference_only"
            or artifact["lifecycle_stages"]
            or artifact["candidate_task_family_ids"]
        ):
            raise EvalReferenceError(
                f"$.artifacts[{index}]: benchmark plans must remain reference-only "
                "supporting infrastructure without lifecycle or task-family mappings"
            )
        _require_canonical_order(
            artifact["lifecycle_stages"],
            LIFECYCLE_ORDER,
            f"$.artifacts[{index}].lifecycle_stages",
        )
        _require_canonical_order(
            artifact["candidate_task_family_ids"],
            TASK_FAMILY_ORDER,
            f"$.artifacts[{index}].candidate_task_family_ids",
        )
        if (
            "not_reported" in artifact["evaluator_types"]
            and len(artifact["evaluator_types"]) != 1
        ):
            raise EvalReferenceError(
                f"$.artifacts[{index}].evaluator_types: not_reported cannot be combined with reported evaluator types"
            )
        if (
            "not_agent_specific" in artifact["agent_classes"]
            and len(artifact["agent_classes"]) != 1
        ):
            raise EvalReferenceError(
                f"$.artifacts[{index}].agent_classes: not_agent_specific cannot be combined with concrete agent classes"
            )
        mapping_scope = artifact["mapping_scope"]
        lifecycle_stages = artifact["lifecycle_stages"]
        task_family_ids = artifact["candidate_task_family_ids"]
        if mapping_scope == "task_candidate":
            if not lifecycle_stages or not task_family_ids:
                raise EvalReferenceError(
                    f"$.artifacts[{index}]: task candidates require lifecycle and task-family mappings"
                )
            if artifact["evaluator_types"] == ["not_reported"]:
                raise EvalReferenceError(
                    f"$.artifacts[{index}]: task candidates require a reported evaluator type"
                )
        elif mapping_scope == "supporting_infrastructure":
            if lifecycle_stages or task_family_ids:
                raise EvalReferenceError(
                    f"$.artifacts[{index}]: supporting infrastructure cannot imply lifecycle or task-family coverage"
                )
        else:  # The schema should reject this first; retain a fail-closed guard.
            raise EvalReferenceError(
                f"$.artifacts[{index}].mapping_scope: unsupported value {mapping_scope!r}"
            )
    if benchmark_plan_count > 1:
        raise EvalReferenceError(
            "$.artifacts: a source may retain at most one benchmark plan"
        )


def load_references(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> list[dict[str, Any]]:
    """Load and validate all source JSON files; never dereference their URLs."""

    schema = _load_json(schema_path)
    paths = sorted(source_dir.glob("*.json"))
    if not paths:
        raise EvalReferenceError(f"no reference JSON files found in {source_dir}")

    references: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    global_artifact_ids: set[str] = set()
    for path in paths:
        reference = _load_json(path)
        validate_reference(reference, schema, source_path=path)
        source_id = reference["id"]
        if source_id in source_ids:
            raise EvalReferenceError(f"duplicate source id: {source_id}")
        source_ids.add(source_id)
        for artifact in reference["artifacts"]:
            global_id = f"{source_id}:{artifact['id']}"
            if global_id in global_artifact_ids:
                raise EvalReferenceError(f"duplicate global artifact id: {global_id}")
            global_artifact_ids.add(global_id)
        references.append(reference)
    return references


def build_landscape(references: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Build deterministic discovery views from already validated references."""

    ordered = sorted(references, key=lambda item: item["id"])
    source_ids = [reference["id"] for reference in ordered]
    if len(source_ids) != len(set(source_ids)):
        raise EvalReferenceError("cannot build landscape with duplicate source ids")

    artifacts: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for reference in ordered:
        for artifact in sorted(reference["artifacts"], key=lambda item: item["id"]):
            artifacts.append((reference, artifact))

    def grouped_view(keys: Sequence[str], selector: Any) -> list[dict[str, Any]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for reference, artifact in artifacts:
            for key in selector(artifact):
                grouped[key].append(f"{reference['id']}:{artifact['id']}")
        return [
            {
                "id": key,
                "references": sorted(grouped[key]),
            }
            for key in keys
        ]

    return {
        "schema_version": "drupal_agent_readiness.eval_landscape.v1",
        "registry_policy": dict(REGISTRY_POLICY),
        "counts": {
            "sources": len(ordered),
            "artifacts": len(artifacts),
            "task_candidates": sum(
                artifact["mapping_scope"] == "task_candidate"
                for _, artifact in artifacts
            ),
            "supporting_infrastructure": sum(
                artifact["mapping_scope"] == "supporting_infrastructure"
                for _, artifact in artifacts
            ),
            "plan_only_pointers": sum(
                artifact["kind"] == "benchmark_plan" for _, artifact in artifacts
            ),
        },
        "sources": ordered,
        "views": {
            "by_lifecycle_stage": grouped_view(
                LIFECYCLE_ORDER, lambda artifact: artifact["lifecycle_stages"]
            ),
            "by_task_family": grouped_view(
                TASK_FAMILY_ORDER,
                lambda artifact: artifact["candidate_task_family_ids"],
            ),
            "by_disposition": grouped_view(
                DISPOSITION_ORDER, lambda artifact: [artifact["disposition"]]
            ),
            "by_agent_class": grouped_view(
                AGENT_CLASS_ORDER, lambda artifact: artifact["agent_classes"]
            ),
        },
    }


def render_landscape_json(landscape: Mapping[str, Any]) -> str:
    return (
        json.dumps(
            landscape, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=False
        )
        + "\n"
    )


def _label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").title()


def _escape_markdown(value: Any) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = html_escape(text, quote=False)
    for character in ("\\", "`", "*", "_", "[", "]", "(", ")", "#", ">", "|"):
        text = text.replace(character, f"\\{character}")
    return text


def _markdown_url(value: str) -> str:
    # Angle-bracket destinations tolerate path punctuation; percent-encode the
    # delimiters that could terminate the destination and start new Markdown.
    encoded = quote(value, safe=":/?#[]@!$&'*+,;=%")
    return f"<{encoded}>"


def _artifact_lookup(landscape: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for source in landscape["sources"]:
        for artifact in source["artifacts"]:
            global_id = f"{source['id']}:{artifact['id']}"
            lookup[global_id] = {
                "source_name": source["name"],
                "artifact_name": artifact["name"],
                "url": artifact["url"],
            }
    return lookup


def _reference_links(
    group: Mapping[str, Any], lookup: Mapping[str, Mapping[str, str]]
) -> str:
    references = group["references"]
    if not references:
        return "None indexed"
    links: list[str] = []
    for reference_id in references:
        item = lookup[reference_id]
        links.append(
            f"[{_escape_markdown(item['source_name'])}: "
            f"{_escape_markdown(item['artifact_name'])}]"
            f"({_markdown_url(item['url'])})"
        )
    return "<br>".join(links)


def render_landscape_markdown(landscape: Mapping[str, Any]) -> str:
    counts = landscape["counts"]
    lookup = _artifact_lookup(landscape)
    lines = [
        "# External Drupal Agent Eval Landscape",
        "",
        (
            f"This generated discovery index contains {counts['sources']} sources and "
            f"{counts['artifacts']} indexed artifact pointers: "
            f"{counts['task_candidates']} task candidates and "
            f"{counts['supporting_infrastructure']} supporting-infrastructure references."
        ),
        "",
        "> Discovery only. Listing a source does not trust, fetch, run, validate, endorse, or import it. It has no effect on Agent Readiness claims, lifecycle coverage, results, or scorecard eligibility.",
        "",
        "This is consumer-side curation for Agent Readiness, intended to complement Eval Commons and upstream projects rather than act as a competing umbrella.",
        "",
        "Inventory counts describe scope, not success. Success is a documented downstream conversion; listing and running alone are not conversions.",
        "",
        "## Operating bounds",
        "",
        f"- Recorded conversions: {landscape['registry_policy']['recorded_conversions']}",
        f"- Routine curation cap: {landscape['registry_policy']['routine_curation_limit_hours_per_week']} maintainer-hour per week",
        f"- Intake state: {_label(landscape['registry_policy']['intake_state'])}",
        f"- Review date: {landscape['registry_policy']['review_date']}; if no conversion is recorded, freeze new intake and retain the registry as a read-only archive",
        f"- Plan-only pointer ratio: {counts['plan_only_pointers']}/{counts['artifacts']}",
        "",
        "## How this becomes evidence",
        "",
        "A maintainer may select a pointer, inspect and pin it, adapt or reproduce it on a controlled substrate, retain the local run evidence, and pass the normal Agent Readiness publication gates. Until that separate work happens, the entry remains only a reference.",
        "",
        "The generator performs no network access. It reads only the checked-in metadata files under `method/eval-references/`.",
        "",
        "## Lifecycle view",
        "",
        "| Lifecycle stage | Indexed references |",
        "| --- | --- |",
    ]
    for group in landscape["views"]["by_lifecycle_stage"]:
        lines.append(f"| {_label(group['id'])} | {_reference_links(group, lookup)} |")

    lines.extend(
        [
            "",
            "## Candidate task-family view",
            "",
            "These mappings identify candidates to inspect. They do not make a task family covered.",
            "",
            "| Task family | Indexed references |",
            "| --- | --- |",
        ]
    )
    for group in landscape["views"]["by_task_family"]:
        lines.append(f"| {_label(group['id'])} | {_reference_links(group, lookup)} |")

    lines.extend(["", "## Sources", ""])
    for source in landscape["sources"]:
        lines.extend(
            [
                f"### {_escape_markdown(source['name'])}",
                "",
                _escape_markdown(source["summary"]),
                "",
                f"- Source: [{_escape_markdown(source['canonical_url'])}]"
                f"({_markdown_url(source['canonical_url'])})",
                f"- Last reviewed: {_escape_markdown(source['last_reviewed_at'])}",
                f"- Roles: {', '.join(_label(role) for role in source['roles'])}",
                "- Registry effect: reference only; no claim or coverage effect",
                "",
            ]
        )
        for artifact in source["artifacts"]:
            revision = artifact["upstream_revision"]
            mutability = "immutable" if revision["immutable"] else "mutable pointer"
            lifecycle = (
                ", ".join(_label(stage) for stage in artifact["lifecycle_stages"])
                or "None (supporting infrastructure)"
            )
            task_families = (
                ", ".join(
                    _label(family) for family in artifact["candidate_task_family_ids"]
                )
                or "None (supporting infrastructure)"
            )
            lines.extend(
                [
                    f"#### [{_escape_markdown(artifact['name'])}]"
                    f"({_markdown_url(artifact['url'])})",
                    "",
                    f"- Kind: {_label(artifact['kind'])}",
                    f"- Mapping scope: {_label(artifact['mapping_scope'])}",
                    f"- Agent classes: {', '.join(_label(agent_class) for agent_class in artifact['agent_classes'])}",
                    f"- Substrate fidelity: {_label(artifact['substrate_fidelity'])}",
                    f"- Evaluator types: {', '.join(_label(evaluator_type) for evaluator_type in artifact['evaluator_types'])}",
                    f"- Question: {_escape_markdown(artifact['question_answered'])}",
                    f"- Lifecycle: {lifecycle}",
                    f"- Candidate families: {task_families}",
                    f"- Local disposition: {_label(artifact['disposition'])}",
                    f"- Upstream revision: {_label(revision['kind'])} "
                    f"{_escape_markdown(revision['value'])} ({mutability})",
                    f"- Mapping note: {_escape_markdown(artifact.get('mapping_note', 'None recorded'))}",
                    f"- Claim boundary: {_escape_markdown(artifact['claim_boundary'])}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def build_outputs(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> tuple[str, str]:
    references = load_references(source_dir, schema_path)
    landscape = build_landscape(references)
    return render_landscape_json(landscape), render_landscape_markdown(landscape)


def write_outputs(
    json_output: Path = DEFAULT_JSON_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> None:
    json_text, markdown_text = build_outputs(source_dir, schema_path)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown_text, encoding="utf-8")


def check_outputs(
    json_output: Path = DEFAULT_JSON_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> list[str]:
    expected_json, expected_markdown = build_outputs(source_dir, schema_path)
    failures: list[str] = []
    for path, expected in (
        (json_output, expected_json),
        (markdown_output, expected_markdown),
    ):
        try:
            actual = path.read_text(encoding="utf-8")
        except OSError:
            failures.append(f"missing generated output: {path}")
            continue
        if actual != expected:
            failures.append(f"stale generated output: {path}")
    return failures
