from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = REPO_ROOT / "evidence" / "external-evals"
DEFAULT_REFERENCE_DIR = REPO_ROOT / "method" / "eval-references"
DEFAULT_RUN_SCHEMA_PATH = (
    REPO_ROOT / "method" / "schema" / "external-eval-run-v1.schema.json"
)
DEFAULT_SOURCE_VALIDATION_SCHEMA_PATH = (
    REPO_ROOT / "method" / "schema" / "external-eval-source-validation-v1.schema.json"
)
DEFAULT_JSON_OUTPUT = REPO_ROOT / "docs" / "external-eval-results.json"
DEFAULT_MARKDOWN_OUTPUT = REPO_ROOT / "docs" / "external-eval-results.md"
AI_BEST_PRACTICES_AUDITED_COMMIT = "c45117130a4de1fe7d03d3fe225e3f09b8e4e803"
ABP_B01_APPROVED_TRACE_SHA256 = (
    "f6efef30de423403ac9b9ebb1627c876d26d77a65c21544ff5294aa3b0bb9531"
)
ABP_B01_REQUIRED_TOKENS = ["#cache", "'tags'", "'contexts'"]
ABP_B01_FORBIDDEN_TOKENS = [
    "new Response(",
    "new HtmlResponse(",
    "return '<",
]
ABP_B01_PROMPT = (
    "Write a Drupal page controller method that displays a list of the 10 most "
    "recent published articles. The page is visible to any user with the 'access "
    "content' permission."
)
ABP_B01_TEACHING = (
    "A controller method that returns a render array (NOT a Response object or raw "
    "HTML string) with cache metadata including cache tags (node_list) and cache "
    "contexts (user.permissions)."
)
ABP_B01_AGENT = {
    "provider": "openai",
    "agent_id": "codex",
    "agent_version": "0.142.5",
    "model_id": "gpt-5.4",
}
ABP_STATIC_COMMAND_TARGETS = {
    "default-discovery": None,
    "nested-a11y-fapi": "drupal-accessibility/drupal-a11y-fapi",
    "nested-a11y-dom": "drupal-accessibility/drupal-a11y-dom",
    "nested-a11y-dynamic": "drupal-accessibility/drupal-a11y-dynamic",
    "nested-a11y-qa": "drupal-accessibility/drupal-a11y-qa",
}
ABP_STATIC_DEFAULT_HEADINGS = [
    "drupal-accessibility",
    "drupal-automated-testing",
    "drupal-configuration",
    "drupal-expert-corrections",
    "drupal-gitlab",
    "drupal-render-pipeline",
    "drupal-skill-authoring",
    "drupal-writing-documentation",
]

PUBLICATION_POLICY = {
    "purpose": "publish_bounded_maintainer_local_external_eval_records",
    "registry_listing_is_execution_authority": False,
    "agent_runs_are_general_model_scores": False,
    "source_validations_are_agent_performance_results": False,
    "manifest_only_records_are_auditable_evidence": False,
    "scorecard_effect": "none",
    "coverage_effect": "none",
}


class ExternalEvalResultError(ValueError):
    """Raised when trusted-local external evaluation evidence is invalid."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExternalEvalResultError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalEvalResultError(f"cannot load JSON from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExternalEvalResultError(f"expected a JSON object in {path}")
    return payload


def _resolve_local_ref(
    root_schema: Mapping[str, Any], reference: str
) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise ExternalEvalResultError(
            f"unsupported non-local schema reference: {reference}"
        )
    current: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or part not in current:
            raise ExternalEvalResultError(f"unresolvable schema reference: {reference}")
        current = current[part]
    if not isinstance(current, Mapping):
        raise ExternalEvalResultError(f"schema reference is not an object: {reference}")
    return current


def _schema_error(path: str, message: str) -> None:
    raise ExternalEvalResultError(f"{path}: {message}")


def _validate_instance(
    value: Any,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    path: str = "$",
) -> None:
    """Validate the closed JSON-Schema subset used by the evidence envelopes."""

    if "$ref" in schema:
        _validate_instance(
            value, _resolve_local_ref(root_schema, schema["$ref"]), root_schema, path
        )
        return
    if "if" in schema:
        condition = schema["if"]
        if not isinstance(condition, Mapping):
            raise ExternalEvalResultError(
                f"schema if clause must be an object at {path}"
            )
        try:
            _validate_instance(value, condition, root_schema, path)
        except ExternalEvalResultError:
            selected = schema.get("else")
        else:
            selected = schema.get("then")
        if selected is not None:
            if not isinstance(selected, Mapping):
                raise ExternalEvalResultError(
                    f"schema conditional branch must be an object at {path}"
                )
            _validate_instance(value, selected, root_schema, path)
    if "const" in schema and value != schema["const"]:
        _schema_error(path, f"must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        _schema_error(path, f"must be one of {schema['enum']!r}")

    expected_type = schema.get("type")
    type_matches = {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }
    if expected_type is not None:
        if expected_type not in type_matches:
            raise ExternalEvalResultError(
                f"unsupported schema type {expected_type!r} at {path}"
            )
        if not type_matches[expected_type]:
            _schema_error(path, f"must be {expected_type}")

    if isinstance(value, Mapping):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                _schema_error(path, f"missing required property {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                _schema_error(path, f"unknown properties {extras!r}")
        for key, child in value.items():
            child_schema = properties.get(key)
            if child_schema is not None:
                _validate_instance(child, child_schema, root_schema, f"{path}.{key}")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            _schema_error(path, f"must have at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            _schema_error(path, f"must have at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            rendered = [json.dumps(item, sort_keys=True) for item in value]
            if len(rendered) != len(set(rendered)):
                _schema_error(path, "items must be unique")
        prefix_items = schema.get("prefixItems", [])
        for index, child_schema in enumerate(prefix_items):
            if index < len(value):
                _validate_instance(
                    value[index], child_schema, root_schema, f"{path}[{index}]"
                )
        if "items" in schema:
            for index, item in enumerate(value):
                _validate_instance(
                    item, schema["items"], root_schema, f"{path}[{index}]"
                )

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            _schema_error(path, f"must have length at least {schema['minLength']}")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            _schema_error(path, f"must match pattern {pattern!r}")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                _schema_error(path, "must be an ISO-8601 date-time")
            if parsed.tzinfo is None:
                _schema_error(path, "date-time must include a timezone")

    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and "minimum" in schema
        and value < schema["minimum"]
    ):
        _schema_error(path, f"must be at least {schema['minimum']}")

    for child_schema in schema.get("allOf", []):
        if not isinstance(child_schema, Mapping):
            raise ExternalEvalResultError(
                f"schema allOf entries must be objects at {path}"
            )
        _validate_instance(value, child_schema, root_schema, path)


def _validate_with_schema(
    payload: Mapping[str, Any], schema: Mapping[str, Any], *, label: str
) -> None:
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ExternalEvalResultError(f"{label} schema must declare draft 2020-12")
    _validate_instance(payload, schema, schema)


def _closed_object(
    value: Any,
    *,
    path: str,
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExternalEvalResultError(f"{path}: must be an object")
    missing = sorted(set(required) - set(value))
    if missing:
        raise ExternalEvalResultError(f"{path}: missing fields {missing!r}")
    extras = sorted(set(value) - set(required) - set(optional))
    if extras:
        raise ExternalEvalResultError(f"{path}: unknown fields {extras!r}")
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ExternalEvalResultError(f"{path}: must be an integer >= {minimum}")
    return value


def _number(value: Any, path: str, *, minimum: float = 0) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < minimum
    ):
        raise ExternalEvalResultError(f"{path}: must be a number >= {minimum}")
    return float(value)


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExternalEvalResultError(f"{path}: must be a non-empty string")
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ExternalEvalResultError(f"{path}: must be boolean")
    return value


def _string_list(value: Any, path: str, *, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ExternalEvalResultError(
            f"{path}: must be a list with at least {minimum} items"
        )
    for index, item in enumerate(value):
        _string(item, f"{path}[{index}]")
    if len(value) != len(set(value)):
        raise ExternalEvalResultError(f"{path}: values must be unique")
    return value


def _source_and_record_directory(path: Path, evidence_dir: Path) -> tuple[str, str]:
    try:
        relative = path.relative_to(evidence_dir)
    except ValueError as exc:
        raise ExternalEvalResultError(
            f"record {path} is outside evidence directory {evidence_dir}"
        ) from exc
    if len(relative.parts) != 3:
        raise ExternalEvalResultError(
            f"record {path} must be <source-id>/<record-id>/<filename>"
        )
    return relative.parts[0], relative.parts[1]


def _artifact_path(value: str, repo_root: Path) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ExternalEvalResultError(
            f"artifact path must be repository-relative without '..': {value}"
        )
    resolved = (repo_root / relative).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ExternalEvalResultError(
            f"artifact path escapes repository: {value}"
        ) from exc
    return resolved


def _record_artifact_path(
    value: str,
    repo_root: Path,
    *,
    source_id: str,
    record_id: str,
) -> Path:
    """Resolve one canonical artifact path confined to its evidence record."""

    relative = Path(value)
    if relative.as_posix() != value:
        raise ExternalEvalResultError(
            f"artifact path must use canonical POSIX form: {value}"
        )
    expected_relative_directory = (
        Path("evidence") / "external-evals" / source_id / record_id
    )
    try:
        relative.relative_to(expected_relative_directory)
    except ValueError as exc:
        raise ExternalEvalResultError(
            f"artifact path must remain inside its evidence record directory: {value}"
        ) from exc

    resolved = _artifact_path(value, repo_root)
    expected_resolved_directory = (repo_root / expected_relative_directory).resolve()
    try:
        resolved.relative_to(expected_resolved_directory)
    except ValueError as exc:
        raise ExternalEvalResultError(
            f"artifact path resolves outside its evidence record directory: {value}"
        ) from exc
    return resolved


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _markdown_text(value: Any) -> str:
    """Escape record prose before placing it in generated Markdown."""

    text = str(value).replace("\r", " ").replace("\n", " ")
    text = html_escape(text, quote=False)
    for character in ("\\", "`", "*", "_", "[", "]", "(", ")", "#", ">", "|"):
        text = text.replace(character, f"\\{character}")
    return text


def _inline_code(value: Any) -> str:
    """Render arbitrary record text in a non-breakable CommonMark code span."""

    text = str(value).replace("\r", " ").replace("\n", " ")
    backtick_runs = [len(match.group(0)) for match in re.finditer(r"`+", text)]
    delimiter = "`" * (max(backtick_runs, default=0) + 1)
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{delimiter}{padding}{text}{padding}{delimiter}"


def load_reference_index(
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Load inert pointer IDs only; never import their execution-independent validator."""

    index: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(reference_dir.glob("*.json")):
        reference = _load_json(path)
        source_id = _string(reference.get("id"), f"{path}.id")
        artifacts = reference.get("artifacts")
        if not isinstance(artifacts, list):
            raise ExternalEvalResultError(f"{path}.artifacts: must be a list")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise ExternalEvalResultError(
                    f"{path}.artifacts: entries must be objects"
                )
            artifact_id = _string(artifact.get("id"), f"{path}.artifacts.id")
            key = (source_id, artifact_id)
            if key in index:
                raise ExternalEvalResultError(
                    f"duplicate inert registry pointer: {key}"
                )
            index[key] = artifact
    if not index:
        raise ExternalEvalResultError(
            f"no inert registry pointers found in {reference_dir}"
        )
    return index


def _validate_source_pointer(
    source: Mapping[str, Any],
    reference_index: Mapping[tuple[str, str], Mapping[str, Any]],
) -> None:
    key = (source["source_id"], source["artifact_id"])
    if key not in reference_index:
        raise ExternalEvalResultError(
            f"source pointer {key[0]}:{key[1]} does not exist in the inert registry"
        )
    registry_artifact = reference_index[key]
    registry_revision = registry_artifact.get("upstream_revision")
    if not isinstance(registry_revision, Mapping):
        raise ExternalEvalResultError(f"inert registry pointer {key} has no revision")
    expected = {
        "kind": registry_revision.get("kind"),
        "value": registry_revision.get("value"),
    }
    if source["registry_revision"] != expected:
        raise ExternalEvalResultError(
            f"source registry_revision does not match inert pointer {key[0]}:{key[1]}"
        )
    if expected["kind"] == "commit" and source["upstream_commit"] != expected["value"]:
        raise ExternalEvalResultError(
            f"source upstream_commit does not match immutable inert pointer {key[0]}:{key[1]}"
        )


def _validate_abp_run(run: dict[str, Any], repo_root: Path) -> None:
    if (run["source"]["source_id"], run["source"]["artifact_id"]) != (
        "ai-best-practices",
        "skill-eval-cases",
    ):
        raise ExternalEvalResultError(
            "ai_best_practices_run_evals_v1 requires ai-best-practices:skill-eval-cases"
        )
    if run["source"]["upstream_commit"] != AI_BEST_PRACTICES_AUDITED_COMMIT:
        raise ExternalEvalResultError(
            "ABP run upstream_commit must match the adapter's audited commit"
        )
    if (
        run["suite"]["id"] != "drupal-render-pipeline"
        or run["suite"]["case_ids"] != ["B01"]
        or run["suite"]["cases_selected"] != 1
    ):
        raise ExternalEvalResultError(
            "ABP adapter is bounded to the drupal-render-pipeline B01 case"
        )
    if run["treatment"] != {
        "condition_id": "skill_injected",
        "comparison_design": "single_condition_no_ab",
    }:
        raise ExternalEvalResultError(
            "ABP B01 adapter requires the retained single skill-injected condition"
        )
    if run["agent"] != ABP_B01_AGENT:
        raise ExternalEvalResultError(
            "ABP B01 agent identity must match the approved provider, CLI, version, and model"
        )
    data = _closed_object(
        run["adapter_data"],
        path="$.adapter_data",
        required=(
            "runner",
            "substrate",
            "evaluator",
            "result",
            "upstream_artifact_pins",
        ),
    )
    runner = _closed_object(
        data["runner"],
        path="$.adapter_data.runner",
        required=(
            "upstream_runner",
            "added_cli_arguments",
            "trace_capture",
            "other_changes",
            "non_upstream_behavior_changes",
        ),
    )
    _string(runner["upstream_runner"], "$.adapter_data.runner.upstream_runner")
    if runner["added_cli_arguments"] != ["--ignore-user-config", "--ephemeral"]:
        raise ExternalEvalResultError(
            "$.adapter_data.runner.added_cli_arguments: only the two audited isolation flags are allowed"
        )
    trace_capture = _closed_object(
        runner["trace_capture"],
        path="$.adapter_data.runner.trace_capture",
        required=(
            "omitted_from_trace",
            "retained_elsewhere_in_package",
            "unretained",
            "reconstructed_prompt_artifact_path",
            "prompt_reconstruction_method",
        ),
    )
    if (
        trace_capture["omitted_from_trace"]
        != [
            "full_injected_skill_prompt",
            "final_codex_cli_argv",
        ]
        or trace_capture["retained_elsewhere_in_package"]
        != ["full_injected_skill_prompt"]
        or trace_capture["unretained"] != ["final_codex_cli_argv"]
    ):
        raise ExternalEvalResultError(
            "$.adapter_data.runner.trace_capture: must distinguish trace omissions, retained reconstruction, and unretained argv"
        )
    prompt_artifact_path = _string(
        trace_capture["reconstructed_prompt_artifact_path"],
        "$.adapter_data.runner.trace_capture.reconstructed_prompt_artifact_path",
    )
    _string(
        trace_capture["prompt_reconstruction_method"],
        "$.adapter_data.runner.trace_capture.prompt_reconstruction_method",
    )
    if (
        runner["other_changes"] != []
        or runner["non_upstream_behavior_changes"] is not False
    ):
        raise ExternalEvalResultError(
            "$.adapter_data.runner: unaudited behavior changes are not allowed"
        )

    substrate = _closed_object(
        data["substrate"],
        path="$.adapter_data.substrate",
        required=(
            "working_directory",
            "git_repository",
            "drupal_runtime",
            "real_drupal_site",
        ),
    )
    working_directory = _string(
        substrate["working_directory"], "$.adapter_data.substrate.working_directory"
    )
    if not working_directory.startswith("/private/tmp/"):
        raise ExternalEvalResultError(
            "$.adapter_data.substrate.working_directory: must be an isolated temp path"
        )
    if substrate["git_repository"] is not True:
        raise ExternalEvalResultError("ABP run substrate must be a Git repository")
    if (
        substrate["drupal_runtime"] is not False
        or substrate["real_drupal_site"] is not False
    ):
        raise ExternalEvalResultError(
            "ABP prompt-only run cannot claim a Drupal runtime"
        )
    if run["substrate"]["real_target_runtime"] is not False:
        raise ExternalEvalResultError(
            "ABP prompt-only envelope cannot claim a real runtime"
        )

    evaluator = _closed_object(
        data["evaluator"],
        path="$.adapter_data.evaluator",
        required=(
            "kind",
            "upstream_assertions",
            "php_lint",
            "oracle_required_tokens",
        ),
    )
    if evaluator != {
        "kind": "upstream_deterministic_assertions",
        "upstream_assertions": True,
        "php_lint": True,
        "oracle_required_tokens": ABP_B01_REQUIRED_TOKENS,
    }:
        raise ExternalEvalResultError(
            "$.adapter_data.evaluator: unexpected ABP evaluator contract"
        )
    adapter_result = _closed_object(
        data["result"],
        path="$.adapter_data.result",
        required=("php_blocks_linted", "php_blocks_failed_lint"),
    )
    php_linted = _integer(
        adapter_result["php_blocks_linted"],
        "$.adapter_data.result.php_blocks_linted",
    )
    php_failed = _integer(
        adapter_result["php_blocks_failed_lint"],
        "$.adapter_data.result.php_blocks_failed_lint",
    )
    if php_failed > php_linted:
        raise ExternalEvalResultError("PHP lint failures cannot exceed linted blocks")

    expected_pins = [
        {
            "path": "skills/drupal-render-pipeline/SKILL.md",
            "sha256": "841e49e40c4010919fe5e0df724f0e4be6c960d45838a89d7355f1b47d0cc7d1",
        },
        {
            "path": "evals/drupal-render-pipeline/evals.json",
            "sha256": "f53855f341f09912decfe85603718927902a70e1ee0a8f0fe119b87436afa891",
        },
        {
            "path": "evals/run-evals.py",
            "sha256": "edf8cf73d0d5734539834c26ea74068d929b201d000c11750fab2ce9e5a5a217",
        },
        {
            "path": "evals/providers.py",
            "sha256": "62b430e8492424b84cf11f36c11d803ddf4e547ffd71b01241307827519f7597",
        },
    ]
    if data["upstream_artifact_pins"] != expected_pins:
        raise ExternalEvalResultError(
            "$.adapter_data.upstream_artifact_pins: must match the audited upstream inputs"
        )

    result = run["result"]
    if result["cases_failed"] > 0:
        if (
            result["published_outcome"]
            != "upstream_oracle_fail_manual_adjudication_required"
            or result["manual_adjudication_status"] != "required_unresolved"
        ):
            raise ExternalEvalResultError(
                "an ABP oracle failure must remain manual-adjudication-required"
            )
    elif (
        result["published_outcome"] != "upstream_oracle_pass"
        or result["manual_adjudication_status"] != "not_required"
    ):
        raise ExternalEvalResultError(
            "an ABP oracle pass must remain an upstream-oracle pass without adjudication"
        )

    trace_passed = 0
    trace_failed = 0
    trace_php_linted = 0
    trace_php_failed = 0
    traces: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    reconstructed_prompt: tuple[Mapping[str, Any], str] | None = None
    for artifact in run["artifacts"]:
        if artifact["kind"] == "reconstructed_full_prompt":
            if (
                artifact["media_type"] != "text/plain"
                or artifact["path"] != prompt_artifact_path
            ):
                raise ExternalEvalResultError(
                    "ABP reconstructed prompt artifact does not match trace-capture provenance"
                )
            if reconstructed_prompt is not None:
                raise ExternalEvalResultError(
                    "ABP run must retain exactly one reconstructed full prompt"
                )
            prompt_path = Path(artifact["path"])
            if prompt_path.parent.name != "prompts" or not prompt_path.name.endswith(
                "-full-injected.txt"
            ):
                raise ExternalEvalResultError(
                    "ABP reconstructed prompt must use prompts/<case-id>-full-injected.txt"
                )
            try:
                prompt_text = _artifact_path(artifact["path"], repo_root).read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeDecodeError) as exc:
                raise ExternalEvalResultError(
                    "ABP reconstructed prompt must be readable UTF-8 text"
                ) from exc
            reconstructed_prompt = (artifact, prompt_text)
            continue
        if (
            artifact["kind"] != "upstream_trace"
            or artifact["media_type"] != "application/json"
        ):
            raise ExternalEvalResultError(
                "ABP run contains an unsupported artifact kind"
            )
        trace = _load_json(_artifact_path(artifact["path"], repo_root))
        trace = _closed_object(
            trace,
            path=f"trace:{artifact['path']}",
            required=(
                "id",
                "teaching",
                "provider",
                "model",
                "prompt",
                "response",
                "assertions",
                "passed",
                "detail",
                "elapsed",
                "input_tokens",
                "output_tokens",
                "cost_usd",
                "timestamp",
            ),
        )
        _string(trace["id"], f"trace:{artifact['path']}.id")
        for field in (
            "teaching",
            "provider",
            "model",
            "prompt",
            "response",
            "detail",
            "timestamp",
        ):
            _string(trace[field], f"trace:{artifact['path']}.{field}")
        if trace["id"] != "B01":
            raise ExternalEvalResultError("ABP adapter is bounded to trace B01")
        if trace["prompt"] != ABP_B01_PROMPT or trace["teaching"] != ABP_B01_TEACHING:
            raise ExternalEvalResultError(
                "ABP B01 prompt and teaching must match the audited case"
            )
        _boolean(trace["passed"], f"trace:{artifact['path']}.passed")
        _number(trace["elapsed"], f"trace:{artifact['path']}.elapsed")
        _integer(trace["input_tokens"], f"trace:{artifact['path']}.input_tokens")
        _integer(trace["output_tokens"], f"trace:{artifact['path']}.output_tokens")
        _number(trace["cost_usd"], f"trace:{artifact['path']}.cost_usd")
        assertions = _closed_object(
            trace["assertions"],
            path=f"trace:{artifact['path']}.assertions",
            required=(
                "must_contain_any",
                "found",
                "must_not_contain",
                "found_bad",
                "php_lint",
                "markdown_structure",
            ),
        )
        if (
            _string_list(
                assertions["must_contain_any"],
                f"trace:{artifact['path']}.assertions.must_contain_any",
                minimum=1,
            )
            != ABP_B01_REQUIRED_TOKENS
        ):
            raise ExternalEvalResultError(
                "ABP trace oracle tokens do not match the audited evaluator contract"
            )
        found = _string_list(
            assertions["found"], f"trace:{artifact['path']}.assertions.found"
        )
        prohibited = _string_list(
            assertions["must_not_contain"],
            f"trace:{artifact['path']}.assertions.must_not_contain",
            minimum=1,
        )
        if prohibited != ABP_B01_FORBIDDEN_TOKENS:
            raise ExternalEvalResultError(
                "ABP trace forbidden tokens do not match the audited B01 oracle"
            )
        found_bad = _string_list(
            assertions["found_bad"],
            f"trace:{artifact['path']}.assertions.found_bad",
        )
        response_lower = trace["response"].lower()
        expected_found = [
            token
            for token in ABP_B01_REQUIRED_TOKENS
            if token.lower() in response_lower
        ]
        expected_found_bad = [
            token
            for token in ABP_B01_FORBIDDEN_TOKENS
            if token.lower() in response_lower
        ]
        if found != expected_found:
            raise ExternalEvalResultError(
                "ABP trace required-token findings do not match its response"
            )
        if found_bad != expected_found_bad:
            raise ExternalEvalResultError(
                "ABP trace forbidden-token findings do not match its response"
            )
        lint_detail = _string(
            assertions["php_lint"],
            f"trace:{artifact['path']}.assertions.php_lint",
        )
        php_block_count = len(
            re.findall(r"```php[^\n]*\n(.*?)```", trace["response"], re.DOTALL)
        )
        lint_success = re.fullmatch(
            r"([0-9]+) PHP block\(s\) pass syntax check", lint_detail
        )
        if lint_detail == "No PHP code blocks to lint":
            if php_block_count != 0:
                raise ExternalEvalResultError(
                    "ABP trace PHP-lint detail contradicts its response"
                )
            lint_passed = True
            lint_failed_count = 0
        elif lint_success is not None:
            if int(lint_success.group(1)) != php_block_count:
                raise ExternalEvalResultError(
                    "ABP trace PHP-lint block count contradicts its response"
                )
            lint_passed = True
            lint_failed_count = 0
        else:
            failure_indexes = [
                int(index)
                for index in re.findall(r"(?:^|; )Block ([0-9]+):", lint_detail)
            ]
            if (
                lint_detail == "php not available, skipping lint"
                or not failure_indexes
                or len(failure_indexes) != len(set(failure_indexes))
                or any(
                    index < 1 or index > php_block_count for index in failure_indexes
                )
            ):
                raise ExternalEvalResultError(
                    "ABP trace PHP-lint detail is not an auditable upstream result"
                )
            lint_passed = False
            lint_failed_count = len(failure_indexes)
        trace_php_linted += php_block_count
        trace_php_failed += lint_failed_count
        if assertions["markdown_structure"] is not None:
            raise ExternalEvalResultError(
                "ABP render-pipeline trace must not contain a Markdown-structure result"
            )
        expected_passed = (
            bool(expected_found) and not expected_found_bad and lint_passed
        )
        expected_detail_parts = [
            (
                f"found: {expected_found}"
                if expected_found
                else f"missing all of: {ABP_B01_REQUIRED_TOKENS}"
            ),
        ]
        if expected_found_bad:
            expected_detail_parts.append(f"unwanted: {expected_found_bad}")
        expected_detail_parts.append(f"php-lint: {lint_detail}")
        expected_detail = "; ".join(expected_detail_parts)
        if trace["detail"] != expected_detail:
            raise ExternalEvalResultError(
                "ABP trace detail does not match its recomputed oracle result"
            )
        if trace["passed"] is not expected_passed:
            raise ExternalEvalResultError(
                "ABP trace verdict does not match its recomputed oracle result"
            )
        if artifact["sha256"] != ABP_B01_APPROVED_TRACE_SHA256:
            raise ExternalEvalResultError(
                "ABP B01 trace must match the approved byte-exact artifact hash"
            )
        if trace["provider"] != run["agent"]["agent_id"]:
            raise ExternalEvalResultError("ABP trace provider does not match run agent")
        if trace["model"] != run["agent"]["model_id"]:
            raise ExternalEvalResultError("ABP trace model does not match run model")
        if trace["timestamp"] != run["recorded_at"]:
            raise ExternalEvalResultError(
                "ABP trace timestamp does not match run timestamp"
            )
        trace_passed += int(expected_passed)
        trace_failed += int(not expected_passed)
        traces.append((artifact, trace))

    trace_ids = [trace["id"] for _, trace in traces]
    declared_case_ids = run["suite"]["case_ids"]
    if len(trace_ids) != len(set(trace_ids)):
        raise ExternalEvalResultError("ABP run must retain one unique trace per case")
    if set(trace_ids) != set(declared_case_ids) or len(trace_ids) != len(
        declared_case_ids
    ):
        raise ExternalEvalResultError(
            "ABP trace case-id set must exactly match the declared suite cases"
        )
    for artifact, trace in traces:
        trace_path = Path(artifact["path"])
        if (
            trace_path.parent.name != "traces"
            or trace_path.name != f"{trace['id']}.json"
        ):
            raise ExternalEvalResultError(
                "ABP trace must use traces/<case-id>.json matching its content"
            )
    if (trace_passed, trace_failed) != (
        result["cases_passed"],
        result["cases_failed"],
    ):
        raise ExternalEvalResultError("ABP trace flags must match result counts")
    if (trace_php_linted, trace_php_failed) != (php_linted, php_failed):
        raise ExternalEvalResultError(
            "ABP trace PHP-lint totals must match adapter result totals"
        )
    if reconstructed_prompt is None:
        raise ExternalEvalResultError(
            "ABP run must retain exactly one reconstructed full prompt"
        )
    prompt_artifact, prompt_text = reconstructed_prompt
    prompt_case_id = Path(prompt_artifact["path"]).name.removesuffix(
        "-full-injected.txt"
    )
    trace_by_id = {trace["id"]: trace for _, trace in traces}
    if prompt_case_id not in trace_by_id:
        raise ExternalEvalResultError(
            "ABP reconstructed prompt filename must name a declared trace case"
        )
    separator = "\n\n---\n\n"
    if separator not in prompt_text:
        raise ExternalEvalResultError(
            "ABP reconstructed prompt does not match the upstream concatenation shape"
        )
    skill_text, task_prompt = prompt_text.rsplit(separator, 1)
    expected_skill_sha256 = next(
        item["sha256"]
        for item in expected_pins
        if item["path"] == "skills/drupal-render-pipeline/SKILL.md"
    )
    if _sha256(skill_text.encode("utf-8")) != expected_skill_sha256:
        raise ExternalEvalResultError(
            "ABP reconstructed prompt skill content does not match the audited pin"
        )
    if task_prompt != trace_by_id[prompt_case_id]["prompt"]:
        raise ExternalEvalResultError(
            "ABP reconstructed prompt task does not match its retained trace"
        )


def _validate_abp_static(record: dict[str, Any], repo_root: Path) -> None:
    if (record["source"]["source_id"], record["source"]["artifact_id"]) != (
        "ai-best-practices",
        "skill-eval-cases",
    ):
        raise ExternalEvalResultError(
            "ai_best_practices_static_v1 requires ai-best-practices:skill-eval-cases"
        )
    if record["source"]["upstream_commit"] != AI_BEST_PRACTICES_AUDITED_COMMIT:
        raise ExternalEvalResultError(
            "ABP static upstream_commit must match the adapter's audited commit"
        )
    validation = record["validation"]
    if validation["outcome_model"] != "aggregate_checks":
        raise ExternalEvalResultError(
            "ai_best_practices_static_v1 requires aggregate_checks"
        )
    data = _closed_object(
        validation["adapter_data"],
        path="$.validation.adapter_data",
        required=(
            "commands",
            "commands_total",
            "default_discovery_checks",
            "nested_explicit_checks",
            "discovery_note",
        ),
    )
    if record["evidence"]["support_grade"] != "retained_artifacts":
        raise ExternalEvalResultError(
            "ai_best_practices_static_v1 requires retained-artifact support"
        )

    artifacts_by_id: dict[str, Mapping[str, Any]] = {}
    for artifact in record["artifacts"]:
        artifact_id = _string(artifact["id"], "$.artifacts[].id")
        if artifact_id in artifacts_by_id:
            raise ExternalEvalResultError(
                f"duplicate source artifact id: {artifact_id}"
            )
        if (
            artifact["kind"] != "static_check_stdout"
            or artifact["media_type"] != "text/plain"
        ):
            raise ExternalEvalResultError(
                "ABP static artifacts must be text/plain static_check_stdout"
            )
        expected_suffix = f"artifacts/{artifact_id}.stdout.txt"
        if not artifact["path"].endswith(expected_suffix):
            raise ExternalEvalResultError(
                "ABP static artifact path must match its artifact id"
            )
        artifacts_by_id[artifact_id] = artifact

    commands = data["commands"]
    if not isinstance(commands, list) or not commands:
        raise ExternalEvalResultError(
            "$.validation.adapter_data.commands: must be non-empty"
        )
    command_id_order = [
        command.get("id") if isinstance(command, Mapping) else None
        for command in commands
    ]
    if command_id_order != list(ABP_STATIC_COMMAND_TARGETS):
        raise ExternalEvalResultError(
            "ABP static validation must retain the five approved commands in order"
        )
    if _integer(
        data["commands_total"], "$.validation.adapter_data.commands_total", minimum=1
    ) != len(commands):
        raise ExternalEvalResultError("ABP commands_total must equal commands length")
    _string(data["discovery_note"], "$.validation.adapter_data.discovery_note")

    command_ids: set[str] = set()
    total = passed = failed = default_total = 0
    for index, command_value in enumerate(commands):
        path = f"$.validation.adapter_data.commands[{index}]"
        command = _closed_object(
            command_value,
            path=path,
            required=(
                "id",
                "environment",
                "argv",
                "artifact_id",
                "default_discovery",
                "exit_code",
                "checks_total",
                "checks_passed",
                "checks_failed",
            ),
        )
        command_id = _string(command["id"], f"{path}.id")
        if command_id in command_ids:
            raise ExternalEvalResultError(f"{path}.id: duplicate command id")
        command_ids.add(command_id)
        artifact_id = _string(command["artifact_id"], f"{path}.artifact_id")
        if artifact_id != command_id or artifact_id not in artifacts_by_id:
            raise ExternalEvalResultError(
                f"{path}.artifact_id: must bind the command to its retained stdout"
            )
        environment = _closed_object(
            command["environment"],
            path=f"{path}.environment",
            required=("PYTHONPYCACHEPREFIX",),
        )
        pycache = _string(
            environment["PYTHONPYCACHEPREFIX"],
            f"{path}.environment.PYTHONPYCACHEPREFIX",
        )
        if not pycache.startswith("/private/tmp/"):
            raise ExternalEvalResultError(f"{path}.environment: must use /private/tmp")
        argv = _string_list(command["argv"], f"{path}.argv", minimum=4)
        runner_argv = ["python3", "-B", "evals/run-evals.py", "--static"]
        if argv[:4] != runner_argv:
            raise ExternalEvalResultError(f"{path}.argv: unexpected ABP static runner")
        is_default = _boolean(command["default_discovery"], f"{path}.default_discovery")
        expected_target = ABP_STATIC_COMMAND_TARGETS[command_id]
        expected_argv = (
            runner_argv
            if expected_target is None
            else [*runner_argv, "--skill", expected_target]
        )
        if argv != expected_argv or is_default != (expected_target is None):
            raise ExternalEvalResultError(
                f"{path}: argv and discovery metadata must match the approved static target"
            )
        if command["exit_code"] != 0:
            raise ExternalEvalResultError(
                f"{path}.exit_code: passing validation must exit 0"
            )
        command_total = _integer(
            command["checks_total"], f"{path}.checks_total", minimum=1
        )
        command_passed = _integer(command["checks_passed"], f"{path}.checks_passed")
        command_failed = _integer(command["checks_failed"], f"{path}.checks_failed")
        if command_passed + command_failed != command_total:
            raise ExternalEvalResultError(f"{path}: result counts do not sum")

        artifact = artifacts_by_id[artifact_id]
        retained_path = _record_artifact_path(
            artifact["path"],
            repo_root,
            source_id=record["source"]["source_id"],
            record_id=record["validation_id"],
        )
        try:
            stdout = retained_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ExternalEvalResultError(
                f"ABP static stdout is not readable UTF-8: {artifact['path']}"
            ) from exc
        stdout_headings = re.findall(
            r"^=== ([^=\r\n]+) ===\s*$", stdout, flags=re.MULTILINE
        )
        expected_headings = (
            ABP_STATIC_DEFAULT_HEADINGS
            if expected_target is None
            else [expected_target]
        )
        if stdout_headings != expected_headings:
            raise ExternalEvalResultError(
                f"{path}: retained stdout headings do not match the approved static target"
            )
        score_pairs = [
            (int(match.group(1)), int(match.group(2)))
            for match in re.finditer(
                r"^\s*Score:\s*(\d+)/(\d+)\s*$", stdout, flags=re.MULTILINE
            )
        ]
        stdout_passed = sum(pair[0] for pair in score_pairs)
        stdout_total = sum(pair[1] for pair in score_pairs)
        pass_markers = len(re.findall(r"^\s*\[PASS\]", stdout, flags=re.MULTILINE))
        fail_markers = len(re.findall(r"^\s*\[FAIL\]", stdout, flags=re.MULTILINE))
        if not score_pairs or (stdout_total, stdout_passed, fail_markers) != (
            command_total,
            command_passed,
            command_failed,
        ):
            raise ExternalEvalResultError(
                f"{path}: retained stdout does not support the reported counts"
            )
        if pass_markers != command_passed:
            raise ExternalEvalResultError(
                f"{path}: retained stdout PASS markers do not match the report"
            )
        total += command_total
        passed += command_passed
        failed += command_failed
        default_total += command_total if is_default else 0

    if (total, passed, failed) != (
        validation["checks_total"],
        validation["checks_passed"],
        validation["checks_failed"],
    ):
        raise ExternalEvalResultError(
            "ABP static aggregate counts do not match commands"
        )
    if data["default_discovery_checks"] != default_total:
        raise ExternalEvalResultError(
            "ABP default_discovery_checks does not match commands"
        )
    if data["nested_explicit_checks"] != total - default_total:
        raise ExternalEvalResultError(
            "ABP nested_explicit_checks does not match commands"
        )
    if set(artifacts_by_id) != command_ids:
        raise ExternalEvalResultError(
            "ABP static artifacts must map one-to-one to the reported commands"
        )


def _validate_ai_agents_drupal_cms_codebase_preflight(
    record: dict[str, Any], repo_root: Path
) -> None:
    del repo_root
    if (record["source"]["source_id"], record["source"]["artifact_id"]) != (
        "ai-agents-test",
        "drupal-cms-agent-test-suites",
    ):
        raise ExternalEvalResultError(
            "ai_agents_test_drupal_cms_codebase_preflight_v1 requires "
            "ai-agents-test:drupal-cms-agent-test-suites"
        )
    validation = record["validation"]
    if validation["kind"] != "drupal_cms_codebase_standard_profile_preflight":
        raise ExternalEvalResultError(
            "ai_agents_test_drupal_cms_codebase_preflight_v1 requires the "
            "Drupal-CMS-codebase Standard-profile preflight"
        )
    if validation["outcome_model"] != "structured_observations":
        raise ExternalEvalResultError(
            "ai_agents_test_drupal_cms_codebase_preflight_v1 requires "
            "structured_observations"
        )
    if record["evidence"]["support_grade"] != "manifest_only_unverified":
        raise ExternalEvalResultError(
            "AI Agents preflight must remain manifest-only and unverified"
        )
    if record["artifacts"]:
        raise ExternalEvalResultError(
            "AI Agents manifest-only preflight cannot claim retained artifacts"
        )
    data = _closed_object(
        validation["adapter_data"],
        path="$.validation.adapter_data",
        required=("substrate", "observations", "retention"),
    )
    expected_substrate = {
        "lifecycle": "temporary_local_copy",
        "substrate_label": "Drupal CMS 2.1.1 codebase with the Standard install profile",
        "codebase_project": "Drupal CMS",
        "codebase_version": "2.1.1",
        "drupal_version": "11.3.8",
        "install_profile": "standard",
        "drupal_cms_install_profile_used": False,
        "runtime": "DDEV",
        "containers_stopped_after": True,
    }
    substrate = _closed_object(
        data["substrate"],
        path="$.validation.adapter_data.substrate",
        required=tuple(expected_substrate),
    )
    if substrate != expected_substrate:
        raise ExternalEvalResultError(
            "$.validation.adapter_data.substrate: unexpected codebase/profile substrate"
        )

    expected_observations = [
        {
            "id": "php-lint",
            "outcome": "validated_clean",
            "evidence_support": "manifest_only_unverified",
            "command_exit_code": 0,
            "facts": {"scope": "all_upstream_php_files", "lint_failures": 0},
        },
        {
            "id": "yaml-catalog-parse",
            "outcome": "parsed",
            "evidence_support": "manifest_only_unverified",
            "command_exit_code": 0,
            "facts": {"yaml_groups": 11, "cases_counted": 81},
        },
        {
            "id": "standard-profile-site-install",
            "outcome": "installed",
            "evidence_support": "manifest_only_unverified",
            "command_exit_code": 0,
            "facts": {"install_profile": "standard"},
        },
        {
            "id": "drupal-cms-ai-recipe",
            "outcome": "externally_blocked_partial",
            "evidence_support": "manifest_only_unverified",
            "command_exit_code": 173,
            "facts": {
                "recipe": "drupal_cms_ai",
                "external_service": "amazee_trial_provisioning",
                "http_status": 429,
                "default_chat_with_tools_provider_after": False,
            },
        },
        {
            "id": "module-enable",
            "outcome": "enabled",
            "evidence_support": "manifest_only_unverified",
            "command_exit_code": 0,
            "facts": {"module": "ai_agents_test"},
        },
        {
            "id": "content-type-group-import",
            "outcome": "imported",
            "evidence_support": "manifest_only_unverified",
            "command_exit_code": 0,
            "facts": {"group": "content-type", "cases_imported": 9},
        },
        {
            "id": "real-test-1-no-provider",
            "outcome": "blocked_missing_precondition",
            "evidence_support": "manifest_only_unverified",
            "command_exit_code": 1,
            "facts": {
                "test_id": 1,
                "error": "No default AI provider set for chat with tools",
                "real_model_invoked": False,
            },
        },
        {
            "id": "unsupported-echo-mock-smoke",
            "outcome": "presentation_result_disagreement",
            "evidence_support": "manifest_only_unverified",
            "command_exit_code": 0,
            "facts": {
                "provider": "internal_unsupported_echo_mock",
                "drush_summary": "Success",
                "attempts": [
                    {
                        "uid": 0,
                        "observed_result_entity_status": "failure",
                        "error_category": "permission_error",
                    },
                    {
                        "uid": 1,
                        "observed_result_entity_status": "failure",
                        "error_category": "tool_output_type_error",
                    },
                ],
            },
        },
    ]
    observations = data["observations"]
    if observations != expected_observations:
        raise ExternalEvalResultError(
            "$.validation.adapter_data.observations: preflight manifest differs "
            "from the audited adapter contract"
        )

    retention = _closed_object(
        data["retention"],
        path="$.validation.adapter_data.retention",
        required=(
            "raw_stdout_retained",
            "database_dump_retained",
            "result_entity_export_retained",
            "manifest_only",
            "note",
        ),
    )
    if (
        retention["raw_stdout_retained"] is not False
        or retention["database_dump_retained"] is not False
        or retention["result_entity_export_retained"] is not False
        or retention["manifest_only"] is not True
    ):
        raise ExternalEvalResultError(
            "$.validation.adapter_data.retention: this record must remain manifest-only"
        )
    _string(retention["note"], "$.validation.adapter_data.retention.note")


RUN_ADAPTERS: dict[str, Callable[[dict[str, Any], Path], None]] = {
    "ai_best_practices_run_evals_v1": _validate_abp_run,
}
SOURCE_VALIDATION_ADAPTERS: dict[str, Callable[[dict[str, Any], Path], None]] = {
    "ai_best_practices_static_v1": _validate_abp_static,
    "ai_agents_test_drupal_cms_codebase_preflight_v1": (
        _validate_ai_agents_drupal_cms_codebase_preflight
    ),
}


def validate_run(
    run: dict[str, Any],
    schema: dict[str, Any],
    *,
    source_path: Path,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    repo_root: Path = REPO_ROOT,
    reference_index: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> None:
    _validate_with_schema(run, schema, label="external evaluation run")
    adapter = RUN_ADAPTERS.get(run["adapter_id"])
    if adapter is None:
        raise ExternalEvalResultError(
            f"unknown trusted run adapter: {run['adapter_id']}"
        )

    directory_source_id, directory_run_id = _source_and_record_directory(
        source_path, evidence_dir
    )
    if run["source"]["source_id"] != directory_source_id:
        raise ExternalEvalResultError(
            f"{source_path}: source directory must match source_id"
        )
    if run["run_id"] != directory_run_id:
        raise ExternalEvalResultError(f"{source_path}: run directory must match run_id")
    _validate_source_pointer(run["source"], reference_index or load_reference_index())
    if run["suite"]["cases_selected"] != len(run["suite"]["case_ids"]):
        raise ExternalEvalResultError("suite.cases_selected must equal case_ids length")
    result = run["result"]
    if result["cases_total"] != run["suite"]["cases_selected"]:
        raise ExternalEvalResultError("result.cases_total must equal cases_selected")
    if result["cases_passed"] + result["cases_failed"] != result["cases_total"]:
        raise ExternalEvalResultError("result counts must sum to cases_total")
    expected = (
        "passed"
        if result["cases_failed"] == 0
        else "failed"
        if result["cases_passed"] == 0
        else "mixed"
    )
    if result["automated_outcome"] != expected:
        raise ExternalEvalResultError(f"result.automated_outcome must be {expected!r}")

    seen_artifacts: set[str] = set()
    for artifact in run["artifacts"]:
        path_value = artifact["path"]
        if path_value in seen_artifacts:
            raise ExternalEvalResultError(f"duplicate artifact path: {path_value}")
        seen_artifacts.add(path_value)
        retained_path = _record_artifact_path(
            path_value,
            repo_root,
            source_id=run["source"]["source_id"],
            record_id=run["run_id"],
        )
        try:
            retained_bytes = retained_path.read_bytes()
        except OSError as exc:
            raise ExternalEvalResultError(
                f"cannot read retained artifact {retained_path}: {exc}"
            ) from exc
        if _sha256(retained_bytes) != artifact["sha256"]:
            raise ExternalEvalResultError(
                f"retained artifact checksum mismatch: {path_value}"
            )
    adapter(run, repo_root)


def validate_source_validation(
    record: dict[str, Any],
    schema: dict[str, Any],
    *,
    source_path: Path,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    repo_root: Path = REPO_ROOT,
    reference_index: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> None:
    _validate_with_schema(record, schema, label="external source validation")
    adapter = SOURCE_VALIDATION_ADAPTERS.get(record["adapter_id"])
    if adapter is None:
        raise ExternalEvalResultError(
            f"unknown trusted source-validation adapter: {record['adapter_id']}"
        )
    directory_source_id, directory_validation_id = _source_and_record_directory(
        source_path, evidence_dir
    )
    if record["source"]["source_id"] != directory_source_id:
        raise ExternalEvalResultError(
            f"{source_path}: source directory must match source_id"
        )
    if record["validation_id"] != directory_validation_id:
        raise ExternalEvalResultError(
            f"{source_path}: validation directory must match validation_id"
        )
    _validate_source_pointer(
        record["source"], reference_index or load_reference_index()
    )

    artifacts = record["artifacts"]
    support_grade = record["evidence"]["support_grade"]
    if support_grade == "retained_artifacts" and not artifacts:
        raise ExternalEvalResultError(
            "retained-artifact source validation must retain at least one artifact"
        )
    if support_grade == "manifest_only_unverified" and artifacts:
        raise ExternalEvalResultError(
            "manifest-only source validation cannot claim retained artifacts"
        )
    seen_artifact_ids: set[str] = set()
    seen_artifact_paths: set[str] = set()
    for artifact in artifacts:
        artifact_id = artifact["id"]
        path_value = artifact["path"]
        if artifact_id in seen_artifact_ids:
            raise ExternalEvalResultError(
                f"duplicate source artifact id: {artifact_id}"
            )
        if path_value in seen_artifact_paths:
            raise ExternalEvalResultError(
                f"duplicate source artifact path: {path_value}"
            )
        seen_artifact_ids.add(artifact_id)
        seen_artifact_paths.add(path_value)
        retained_path = _record_artifact_path(
            path_value,
            repo_root,
            source_id=record["source"]["source_id"],
            record_id=record["validation_id"],
        )
        try:
            retained_bytes = retained_path.read_bytes()
        except OSError as exc:
            raise ExternalEvalResultError(
                f"cannot read retained source artifact {retained_path}: {exc}"
            ) from exc
        if _sha256(retained_bytes) != artifact["sha256"]:
            raise ExternalEvalResultError(
                f"retained source artifact checksum mismatch: {path_value}"
            )

    validation = record["validation"]
    count_fields = ("checks_total", "checks_passed", "checks_failed")
    if validation["outcome_model"] == "aggregate_checks":
        missing = [field for field in count_fields if field not in validation]
        if missing:
            raise ExternalEvalResultError(
                f"aggregate source validation is missing count fields {missing!r}"
            )
        if (
            validation["checks_passed"] + validation["checks_failed"]
            != validation["checks_total"]
        ):
            raise ExternalEvalResultError(
                "source validation counts must sum to checks_total"
            )
    elif any(field in validation for field in count_fields):
        raise ExternalEvalResultError(
            "structured_observations must not be flattened into aggregate count fields"
        )
    adapter(record, repo_root)


def load_records(
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    run_schema_path: Path = DEFAULT_RUN_SCHEMA_PATH,
    source_validation_schema_path: Path = DEFAULT_SOURCE_VALIDATION_SCHEMA_PATH,
    *,
    repo_root: Path = REPO_ROOT,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    run_schema = _load_json(run_schema_path)
    source_validation_schema = _load_json(source_validation_schema_path)
    reference_index = load_reference_index(reference_dir)

    runs: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    for path in sorted(evidence_dir.glob("*/*/run.json")):
        run = _load_json(path)
        validate_run(
            run,
            run_schema,
            source_path=path,
            evidence_dir=evidence_dir,
            repo_root=repo_root,
            reference_index=reference_index,
        )
        if run["run_id"] in run_ids:
            raise ExternalEvalResultError(f"duplicate run id: {run['run_id']}")
        run_ids.add(run["run_id"])
        runs.append(run)

    validations: list[dict[str, Any]] = []
    validation_ids: set[str] = set()
    for path in sorted(evidence_dir.glob("*/*/source-validation.json")):
        record = _load_json(path)
        validate_source_validation(
            record,
            source_validation_schema,
            source_path=path,
            evidence_dir=evidence_dir,
            repo_root=repo_root,
            reference_index=reference_index,
        )
        if record["validation_id"] in validation_ids:
            raise ExternalEvalResultError(
                f"duplicate source validation id: {record['validation_id']}"
            )
        validation_ids.add(record["validation_id"])
        validations.append(record)

    if not runs and not validations:
        raise ExternalEvalResultError(
            f"no external evaluation evidence records found in {evidence_dir}"
        )
    return runs, validations


def build_results(
    runs: Sequence[dict[str, Any]], validations: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    ordered_runs = sorted(runs, key=lambda record: record["run_id"])
    ordered_validations = sorted(
        validations, key=lambda record: record["validation_id"]
    )
    if len({record["run_id"] for record in ordered_runs}) != len(ordered_runs):
        raise ExternalEvalResultError("cannot publish duplicate run ids")
    if len({record["validation_id"] for record in ordered_validations}) != len(
        ordered_validations
    ):
        raise ExternalEvalResultError("cannot publish duplicate source validation ids")
    return {
        "schema_version": "drupal_agent_readiness.external_eval_results.v1",
        "publication_policy": dict(PUBLICATION_POLICY),
        "counts": {
            "agent_performance_diagnostics": len(ordered_runs),
            "source_validations_not_agent_performance": len(ordered_validations),
        },
        "agent_performance_diagnostics": ordered_runs,
        "source_validations_not_agent_performance": ordered_validations,
    }


def _render_abp_run(run: Mapping[str, Any]) -> list[str]:
    source = run["source"]
    result = run["result"]
    adapter_data = run["adapter_data"]
    adapter_result = adapter_data["result"]
    adapter_substrate = adapter_data["substrate"]
    traces = sorted(
        (
            artifact
            for artifact in run["artifacts"]
            if artifact["kind"] == "upstream_trace"
        ),
        key=lambda artifact: artifact["path"],
    )
    prompts = sorted(
        (
            artifact
            for artifact in run["artifacts"]
            if artifact["kind"] == "reconstructed_full_prompt"
        ),
        key=lambda artifact: artifact["path"],
    )
    source_label = f"{source['source_id']}:{source['artifact_id']}"
    agent_label = f"{run['agent']['agent_id']} {run['agent']['agent_version']}"
    lines = [
        f"### {_inline_code(run['run_id'])}",
        "",
        f"- Source: {_inline_code(source_label)} at commit {_inline_code(source['upstream_commit'])}",
        f"- Adapter: {_inline_code(run['adapter_id'])}",
        f"- Suite/case: {_inline_code(run['suite']['id'])} / {_inline_code(', '.join(run['suite']['case_ids']))}",
        f"- Treatment: {_inline_code(run['treatment']['condition_id'])}; {_inline_code(run['treatment']['comparison_design'])}",
        f"- Agent: {_inline_code(agent_label)} with {_inline_code(run['agent']['model_id'])}",
        f"- Automated upstream oracle: **{result['cases_passed']}/{result['cases_total']} cases passed** ({result['cases_failed']} oracle failure)",
        f"- Published diagnostic status: {_inline_code(result['published_outcome'])}",
        f"- Manual adjudication: {_inline_code(result['manual_adjudication_status'])}",
        f"- PHP lint: {adapter_result['php_blocks_linted'] - adapter_result['php_blocks_failed_lint']}/{adapter_result['php_blocks_linted']} extracted blocks passed syntax lint",
        f"- Substrate: {_inline_code(run['substrate']['kind'])}; Drupal runtime {_inline_code(str(adapter_substrate['drupal_runtime']).lower())}; real Drupal site {_inline_code(str(adapter_substrate['real_drupal_site']).lower())}",
        f"- Runner change: upstream runner plus {_inline_code(', '.join(adapter_data['runner']['added_cli_arguments']))} only",
        f"- Evidence: {_inline_code(run['evidence']['classification'])}; scorecard eligible {_inline_code(str(run['evidence']['scorecard_eligible']).lower())}; coverage effect {_inline_code(run['evidence']['coverage_effect'])}",
    ]
    lines.extend(
        f"- Trace: {_inline_code(trace['path'])}; SHA-256 {_inline_code(trace['sha256'])}"
        for trace in traces
    )
    lines.extend(
        f"- Reconstructed prompt: {_inline_code(prompt['path'])}; SHA-256 {_inline_code(prompt['sha256'])}"
        for prompt in prompts
    )
    lines.extend(
        [
            "",
            _markdown_text(result["detail"]),
            "",
            f"Adjudication reason: {_markdown_text(result['manual_adjudication_reason'])}",
            "",
            "Manual observations:",
            "",
        ]
    )
    lines.extend(f"- {_markdown_text(item)}" for item in result["manual_observations"])
    lines.extend(["", "Claim boundaries:", ""])
    lines.extend(
        f"- {_markdown_text(item)}" for item in run["claim_boundary"]["limitations"]
    )
    lines.append("")
    return lines


def _render_abp_static(record: Mapping[str, Any]) -> list[str]:
    source = record["source"]
    validation = record["validation"]
    data = validation["adapter_data"]
    artifacts_by_id = {artifact["id"]: artifact for artifact in record["artifacts"]}
    source_label = f"{source['source_id']}:{source['artifact_id']}"
    lines = [
        f"### {_inline_code(record['validation_id'])}",
        "",
        f"- Source: {_inline_code(source_label)} at commit {_inline_code(source['upstream_commit'])}",
        f"- Adapter: {_inline_code(record['adapter_id'])}",
        f"- Aggregate: **{validation['checks_passed']}/{validation['checks_total']} static checks passed** across {data['commands_total']} commands",
        f"- Default discovery: {data['default_discovery_checks']} checks",
        f"- Explicit nested suites: {data['nested_explicit_checks']} checks",
        f"- Agent-performance result: {_inline_code(str(record['evidence']['agent_performance_result']).lower())}",
        f"- Evidence support: {_inline_code(record['evidence']['support_grade'])}",
        "",
        _markdown_text(data["discovery_note"]),
        "",
        "Commands:",
        "",
    ]
    for command in data["commands"]:
        environment = " ".join(
            f"{key}={value}" for key, value in command["environment"].items()
        )
        argv = " ".join(command["argv"])
        artifact = artifacts_by_id[command["artifact_id"]]
        lines.append(
            f"- {_inline_code(f'{environment} {argv}')} -> "
            f"{command['checks_passed']}/{command['checks_total']} passed, "
            f"exit {command['exit_code']}; stdout {_inline_code(artifact['path'])}; "
            f"SHA-256 {_inline_code(artifact['sha256'])}"
        )
    lines.extend(["", "Claim boundaries:", ""])
    lines.extend(
        f"- {_markdown_text(item)}" for item in record["claim_boundary"]["limitations"]
    )
    lines.append("")
    return lines


def _render_ai_agents_drupal_cms_codebase_preflight(
    record: Mapping[str, Any],
) -> list[str]:
    source = record["source"]
    validation = record["validation"]
    data = validation["adapter_data"]
    substrate = data["substrate"]
    source_label = f"{source['source_id']}:{source['artifact_id']}"
    substrate_label = substrate["substrate_label"]
    lines = [
        f"### {_inline_code(record['validation_id'])}",
        "",
        f"- Source: {_inline_code(source_label)} at commit {_inline_code(source['upstream_commit'])}",
        f"- Adapter: {_inline_code(record['adapter_id'])}",
        f"- Outcome model: {_inline_code('structured_observations')} — intentionally not flattened into suite pass/fail counts",
        f"- Substrate: temporary {_inline_code(substrate_label)} using Drupal "
        f"{_inline_code(substrate['drupal_version'])} and {_inline_code(substrate['runtime'])}; "
        f"Drupal CMS install profile used "
        f"{_inline_code(str(substrate['drupal_cms_install_profile_used']).lower())}; "
        f"containers stopped after "
        f"{_inline_code(str(substrate['containers_stopped_after']).lower())}",
        f"- Agent-performance result: {_inline_code(str(record['evidence']['agent_performance_result']).lower())}",
        f"- Evidence support: {_inline_code(record['evidence']['support_grade'])}",
        "",
        "Operator-recorded outcomes (manifest-only; independently unverified):",
        "",
    ]
    for observation in data["observations"]:
        facts = json.dumps(observation["facts"], sort_keys=True, ensure_ascii=False)
        lines.append(
            f"- {_inline_code(observation['id'])} — "
            f"{_inline_code(observation['outcome'])}, command exit "
            f"{_inline_code(observation['command_exit_code'])}, support "
            f"{_inline_code(observation['evidence_support'])}; facts: "
            f"{_inline_code(facts)}"
        )
    retention = data["retention"]
    lines.extend(
        [
            "",
            "Retention:",
            "",
            f"- Raw stdout retained: {_inline_code(str(retention['raw_stdout_retained']).lower())}",
            f"- Database dump retained: {_inline_code(str(retention['database_dump_retained']).lower())}",
            f"- Result entity export retained: {_inline_code(str(retention['result_entity_export_retained']).lower())}",
            f"- {_markdown_text(retention['note'])}",
            "",
            "Claim boundaries:",
            "",
        ]
    )
    lines.extend(
        f"- {_markdown_text(item)}" for item in record["claim_boundary"]["limitations"]
    )
    lines.append("")
    return lines


RUN_RENDERERS: dict[str, Callable[[Mapping[str, Any]], list[str]]] = {
    "ai_best_practices_run_evals_v1": _render_abp_run,
}
SOURCE_VALIDATION_RENDERERS: dict[str, Callable[[Mapping[str, Any]], list[str]]] = {
    "ai_best_practices_static_v1": _render_abp_static,
    "ai_agents_test_drupal_cms_codebase_preflight_v1": (
        _render_ai_agents_drupal_cms_codebase_preflight
    ),
}


def render_markdown(results: Mapping[str, Any]) -> str:
    lines = [
        "# Maintainer-local external evaluation records",
        "",
        "> These are bounded, maintainer-selected local records. Some retain auditable artifacts; others are explicitly unverified manifests. They do not make external registry entries executable, change Agent Readiness coverage, or enter the scorecard.",
        "",
        "Each record declares its substrate fidelity and claim boundary; the current ABP agent run is prompt-only. No record is a general model score or upstream project verdict. Source validations are listed separately because they are **not agent performance**.",
        "",
        "## Agent-performance diagnostics",
        "",
    ]
    runs = results["agent_performance_diagnostics"]
    if not runs:
        lines.extend(
            ["No trusted local agent-performance diagnostics are published.", ""]
        )
    for run in runs:
        lines.extend(RUN_RENDERERS[run["adapter_id"]](run))

    lines.extend(["## Source validation (not agent performance)", ""])
    validations = results["source_validations_not_agent_performance"]
    if not validations:
        lines.extend(["No external evaluation source validations are published.", ""])
    for record in validations:
        lines.extend(SOURCE_VALIDATION_RENDERERS[record["adapter_id"]](record))
    return "\n".join(lines).rstrip() + "\n"


def build_outputs(
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    run_schema_path: Path = DEFAULT_RUN_SCHEMA_PATH,
    source_validation_schema_path: Path = DEFAULT_SOURCE_VALIDATION_SCHEMA_PATH,
    *,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> tuple[str, str]:
    runs, validations = load_records(
        evidence_dir,
        run_schema_path,
        source_validation_schema_path,
        reference_dir=reference_dir,
    )
    results = build_results(runs, validations)
    return (
        json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        render_markdown(results),
    )


def write_outputs(
    json_output: Path = DEFAULT_JSON_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    *,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    run_schema_path: Path = DEFAULT_RUN_SCHEMA_PATH,
    source_validation_schema_path: Path = DEFAULT_SOURCE_VALIDATION_SCHEMA_PATH,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> None:
    json_text, markdown_text = build_outputs(
        evidence_dir,
        run_schema_path,
        source_validation_schema_path,
        reference_dir=reference_dir,
    )
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown_text, encoding="utf-8")


def check_outputs(
    json_output: Path = DEFAULT_JSON_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    *,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    run_schema_path: Path = DEFAULT_RUN_SCHEMA_PATH,
    source_validation_schema_path: Path = DEFAULT_SOURCE_VALIDATION_SCHEMA_PATH,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
) -> list[str]:
    expected_json, expected_markdown = build_outputs(
        evidence_dir,
        run_schema_path,
        source_validation_schema_path,
        reference_dir=reference_dir,
    )
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
