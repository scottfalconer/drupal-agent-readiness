"""Canonical, adversarially-auditable measurement contract for the benchmark.

The JSON schemas make individual documents portable.  This module enforces the
cross-document invariants a JSON schema cannot express: preregistration,
content-addressed pins, fixed-lane equality, paired comparability, trusted
instrumentation, denominator integrity, and exclusion timing.

The contract deliberately keeps two lanes separate:

* ``fixed_regression`` holds the agent and measurement stack fixed while a
  preregistered Drupal treatment changes.
* ``frontier_observation`` records the exact current stack, but never treats
  changes between mutable frontier stacks as evidence that Drupal improved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence


EXPERIMENT_SCHEMA_VERSION = "drupal_agent_readiness.benchmark_experiment.v1"
RUN_SCHEMA_VERSION = "drupal_agent_readiness.benchmark_run.v1"
SCHEMA_DIR = Path(__file__).resolve().parent / "schema"
EXPERIMENT_SCHEMA_PATH = SCHEMA_DIR / "benchmark-experiment-v1.schema.json"
RUN_SCHEMA_PATH = SCHEMA_DIR / "benchmark-run-v1.schema.json"


def _resolve_trusted_git_binary() -> Path | None:
    preferred = Path("/usr/bin/git")
    raw = str(preferred) if preferred.is_file() else shutil.which("git")
    if not raw:
        return None
    candidate = Path(raw).resolve()
    return candidate if candidate.is_file() else None


_TRUSTED_GIT_BINARY = _resolve_trusted_git_binary()

_MUTABLE_LABEL = re.compile(
    r"(?:^|[-_.:/@])(?:latest|current|default|stable|nightly|rolling|main|master|head|tip|auto)"
    r"(?:$|[-_.:/@])",
    re.IGNORECASE,
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_REQUIRED_ARTIFACT_KINDS = {
    "prompt",
    "render_inputs",
    "prompt_receipt",
    "model_identity_receipt",
    "execution_receipt",
    "transcript",
    "tool_log",
    "answer",
    "evaluator_output",
    "evaluator_receipt",
    "cost_trace",
    "behavior_trace",
    "validity_decision",
    "starting_state",
    "final_state",
    "attempt_receipt",
    "attempt_stdout",
    "attempt_stderr",
}
_ROLE_EXPECTATIONS = {
    "task_prompt": ("agent_visible", {"agent", "harness", "auditor"}),
    "system_prompt": ("agent_visible", {"agent", "harness", "auditor"}),
    "output_schema": ("agent_visible", {"agent", "harness", "auditor"}),
    "render_inputs": ("agent_visible", {"agent", "harness", "auditor"}),
    "ground_truth": ("withheld_from_agent", {"evaluator", "auditor"}),
    "evaluator_implementation": (
        "withheld_from_agent",
        {"harness", "evaluator", "auditor"},
    ),
    "evaluation_rubric": (
        "withheld_from_agent",
        {"harness", "evaluator", "auditor"},
    ),
    "scoring_implementation": (
        "withheld_from_agent",
        {"harness", "evaluator", "auditor"},
    ),
}
_COST_GUARDRAIL_METRICS = {
    "wall_time_ms",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "tool_calls",
    "human_interventions",
    "cost_microusd",
}
_TRUSTED_COST_SOURCES = {
    "harness_instrumentation",
    "provider_usage_api",
    "independent_observer",
}
_TRUSTED_EVENT_SOURCES = {"harness_trace", "tool_log", "independent_observer"}
_EVENT_SOURCE_ARTIFACT_KINDS = {
    "harness_trace": {"behavior_trace"},
    "tool_log": {"tool_log"},
    "independent_observer": {"behavior_trace"},
}
_LIFECYCLE_STAGES = (
    "choose_onboard",
    "connect",
    "understand",
    "plan_clarify",
    "act",
    "verify",
    "recover",
    "handoff",
)


@dataclass(frozen=True)
class ValidationIssue:
    """One stable, machine-readable audit finding."""

    severity: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class GitRegistrationAnchor:
    """External Git object used to anchor exact canonical manifest bytes."""

    repo_path: Path
    commit: str
    manifest_path: str


class _ListIdentityCollision(ValueError):
    pass


class CanonicalJSONError(ValueError):
    """Raised when source bytes are not one unambiguous canonical JSON document."""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalJSONError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def parse_canonical_json_bytes(payload: bytes) -> Any:
    """Decode canonical JSON while rejecting duplicate keys and byte ambiguity."""

    try:
        document = json.loads(
            payload,
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except UnicodeDecodeError as error:
        raise CanonicalJSONError(f"JSON is not valid UTF-8: {error}") from error
    except json.JSONDecodeError as error:
        raise CanonicalJSONError(f"invalid JSON: {error}") from error
    try:
        canonical = canonical_json_bytes(document)
    except (TypeError, ValueError) as error:
        raise CanonicalJSONError(f"JSON cannot be canonically encoded: {error}") from error
    if payload != canonical:
        raise CanonicalJSONError(
            "JSON source bytes must exactly equal the canonical UTF-8 serialization"
        )
    return document


def load_canonical_json_file(path: Path) -> Any:
    """Read one source document without normalizing attacker-controlled bytes."""

    return parse_canonical_json_bytes(path.read_bytes())


def canonical_json_bytes(document: Any) -> bytes:
    """Serialize a JSON document into the sole byte representation accepted by v1."""

    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def runtime_home_layout_document_valid(value: Any) -> bool:
    """Return whether an embedded runtime-home layout is canonical and hash-bound."""

    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "entries",
        "tree_sha256",
    }:
        return False
    entries = value.get("entries")
    if (
        value.get("schema_version")
        != "drupal_agent_readiness.runtime_home_layout.v1"
        or not isinstance(entries, list)
        or any(not isinstance(entry, Mapping) for entry in entries)
    ):
        return False
    paths: list[str] = []
    for entry in entries:
        path = entry.get("path")
        kind = entry.get("kind")
        mode = entry.get("mode")
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
            or kind not in {"file", "directory", "symlink"}
            or re.fullmatch(r"0o[0-7]{3,4}", str(mode)) is None
            or oct(int(str(mode), 8)) != mode
        ):
            return False
        paths.append(path)
        common = {"path", "kind", "mode"}
        if kind == "directory" and set(entry) != common:
            return False
        if kind == "file":
            required = common
            if path == "models_cache.json":
                required = common | {"byte_size", "sha256"}
            if (
                set(entry) != required
                or path == "models_cache.json"
                and (
                    type(entry.get("byte_size")) is not int
                    or entry["byte_size"] <= 0
                    or _SHA256.fullmatch(str(entry.get("sha256"))) is None
                )
            ):
                return False
        if kind == "symlink":
            role = entry.get("target_role")
            required = common | {"target_role", "target_path_sha256"}
            if role == "codex_binary":
                required.add("resolved_file_sha256")
            if (
                role not in {"credential_reference", "codex_binary"}
                or set(entry) != required
                or _SHA256.fullmatch(str(entry.get("target_path_sha256"))) is None
                or role == "codex_binary"
                and _SHA256.fullmatch(str(entry.get("resolved_file_sha256"))) is None
            ):
                return False
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        return False
    body = {
        "schema_version": value["schema_version"],
        "entries": entries,
    }
    return value.get("tree_sha256") == "sha256:" + hashlib.sha256(
        canonical_json_bytes(body)
    ).hexdigest()


_RUNTIME_HOME_DYNAMIC_TOP_LEVEL = frozenset(
    {
        "frontier-canary.config.toml",
        "goals_1.sqlite",
        "goals_1.sqlite-shm",
        "goals_1.sqlite-wal",
        "installation_id",
        "logs_2.sqlite",
        "logs_2.sqlite-shm",
        "logs_2.sqlite-wal",
        "memories_1.sqlite",
        "memories_1.sqlite-shm",
        "memories_1.sqlite-wal",
        "os-tmp",
        "skills",
        "state_5.sqlite",
        "state_5.sqlite-shm",
        "state_5.sqlite-wal",
        "tmp",
    }
)


def model_cache_contract_valid(value: Any) -> bool:
    """Validate the preregistered, behavior-affecting Codex model catalog pin."""

    return bool(
        isinstance(value, Mapping)
        and set(value)
        == {
            "schema_version",
            "file_sha256",
            "byte_size",
            "selected_model_selector",
            "selected_model_entry_sha256",
            "catalog_client_version",
            "catalog_fetched_at",
            "content_role",
            "bytes_retained",
        }
        and value.get("schema_version")
        == "drupal_agent_readiness.model_cache_contract.v1"
        and _SHA256.fullmatch(str(value.get("file_sha256"))) is not None
        and type(value.get("byte_size")) is int
        and value["byte_size"] > 0
        and isinstance(value.get("selected_model_selector"), str)
        and bool(value["selected_model_selector"])
        and _SHA256.fullmatch(str(value.get("selected_model_entry_sha256")))
        is not None
        and (
            value.get("catalog_client_version") is None
            or isinstance(value.get("catalog_client_version"), str)
            and bool(value["catalog_client_version"])
        )
        and (
            value.get("catalog_fetched_at") is None
            or isinstance(value.get("catalog_fetched_at"), str)
            and bool(value["catalog_fetched_at"])
        )
        and value.get("content_role") == "behavior_affecting_model_metadata"
        and value.get("bytes_retained") is False
    )


def runtime_home_layout_semantically_valid(
    value: Any,
    *,
    phase: str,
    system_manifest: Any,
    auth_target_path_sha256: str,
    codex_target_path_sha256: str,
    codex_file_sha256: str,
    model_cache_contract: Any = None,
) -> bool:
    """Validate the registered path/kind/mode contract, not merely its hash."""

    if phase not in {"before", "after"} or not runtime_home_layout_document_valid(value):
        return False
    if not isinstance(system_manifest, Mapping):
        return False
    directories = system_manifest.get("directories")
    files = system_manifest.get("files")
    if (
        set(system_manifest)
        != {"schema_version", "directories", "files", "tree_sha256"}
        or system_manifest.get("schema_version")
        != "drupal_agent_readiness.system_skills_manifest.v1"
        or not isinstance(directories, list)
        or not isinstance(files, list)
        or any(not isinstance(item, Mapping) for item in [*directories, *files])
        or _SHA256.fullmatch(str(auth_target_path_sha256)) is None
        or _SHA256.fullmatch(str(codex_target_path_sha256)) is None
        or _SHA256.fullmatch(str(codex_file_sha256)) is None
    ):
        return False
    manifest_body = {
        "schema_version": system_manifest["schema_version"],
        "directories": directories,
        "files": files,
    }
    if system_manifest.get("tree_sha256") != canonical_sha256(manifest_body):
        return False
    entries = value["entries"]
    by_path = {entry["path"]: entry for entry in entries}
    system_kinds: dict[str, tuple[str, str]] = {}
    for item in directories:
        if (
            set(item) != {"path", "mode"}
            or not isinstance(item.get("path"), str)
            or re.fullmatch(r"0o[0-7]{3,4}", str(item.get("mode"))) is None
            or oct(int(str(item.get("mode")), 8)) != item.get("mode")
            or int(item["mode"], 8) & 0o7022
            or int(item["mode"], 8) & 0o500 != 0o500
        ):
            return False
        system_kinds[item["path"]] = ("directory", item["mode"])
    for item in files:
        if (
            set(item) != {"path", "mode", "byte_size", "sha256"}
            or not isinstance(item.get("path"), str)
            or re.fullmatch(r"0o[0-7]{3,4}", str(item.get("mode"))) is None
            or oct(int(str(item.get("mode")), 8)) != item.get("mode")
            or int(item["mode"], 8) & 0o7022
            or not int(item["mode"], 8) & 0o400
            or type(item.get("byte_size")) is not int
            or item["byte_size"] < 0
            or _SHA256.fullmatch(str(item.get("sha256"))) is None
        ):
            return False
        if item["path"] in system_kinds:
            return False
        system_kinds[item["path"]] = ("file", item["mode"])
    directory_paths = [item["path"] for item in directories]
    file_paths = [item["path"] for item in files]
    if (
        directory_paths != sorted(directory_paths)
        or file_paths != sorted(file_paths)
        or len(directory_paths) != len(set(directory_paths))
        or len(file_paths) != len(set(file_paths))
        or set(directory_paths) & set(file_paths)
    ):
        return False
    if system_kinds:
        if not {"skills", "skills/.system"}.issubset(system_kinds):
            return False
        if any(
            path not in {"skills", "skills/.system"}
            and not path.startswith("skills/.system/")
            for path in system_kinds
        ):
            return False
        for path, (kind, _mode) in system_kinds.items():
            if path in {"skills", "skills/.system"}:
                continue
            parent = path.rsplit("/", 1)[0]
            if system_kinds.get(parent, (None, None))[0] != "directory":
                return False
    required = {
        "auth.json",
        "frontier-canary.config.toml",
        "frontier-canary-sentinel",
        *system_kinds,
    }
    allowed = set(required)
    expected_kinds: dict[str, str] = {
        "auth.json": "symlink",
        "frontier-canary.config.toml": "file",
        "frontier-canary-sentinel": "file",
        **{path: kind for path, (kind, _mode) in system_kinds.items()},
    }
    if model_cache_contract is not None:
        if not model_cache_contract_valid(model_cache_contract):
            return False
        required.add("models_cache.json")
        allowed.add("models_cache.json")
        expected_kinds["models_cache.json"] = "file"
    arg0_runs: set[str] = set()
    if phase == "after":
        allowed.update(_RUNTIME_HOME_DYNAMIC_TOP_LEVEL)
        allowed.add("tmp/arg0")
        expected_kinds.update(
            {
                path: "file"
                for path in _RUNTIME_HOME_DYNAMIC_TOP_LEVEL
                if path not in {"os-tmp", "skills", "tmp"}
            }
        )
        expected_kinds.update(
            {"os-tmp": "directory", "skills": "directory", "tmp": "directory", "tmp/arg0": "directory"}
        )
        arg0_runs = {
            path
            for path in by_path
            if re.fullmatch(r"tmp/arg0/codex-arg0[A-Za-z0-9]+", path)
        }
        if len(arg0_runs) > 1:
            return False
        for run in arg0_runs:
            group = {
                "tmp",
                "tmp/arg0",
                run,
                f"{run}/.lock",
                f"{run}/apply_patch",
                f"{run}/applypatch",
                f"{run}/codex-execve-wrapper",
            }
            required.update(group)
            allowed.update(group)
            expected_kinds.update(
                {
                    run: "directory",
                    f"{run}/.lock": "file",
                    f"{run}/apply_patch": "symlink",
                    f"{run}/applypatch": "symlink",
                    f"{run}/codex-execve-wrapper": "symlink",
                }
            )
    if not required.issubset(by_path) or not set(by_path).issubset(allowed):
        return False
    for path in by_path:
        if "/" not in path:
            continue
        parent = path.rsplit("/", 1)[0]
        if by_path.get(parent, {}).get("kind") != "directory":
            return False
    if not system_kinds and any(path == "skills" or path.startswith("skills/") for path in by_path):
        return False
    for path, entry in by_path.items():
        if entry["kind"] != expected_kinds.get(path):
            return False
        if entry["kind"] == "symlink" and entry["mode"] != "0o755":
            return False
        mode = int(entry["mode"], 8)
        if path in system_kinds:
            if entry["mode"] != system_kinds[path][1]:
                return False
        elif entry["kind"] == "directory":
            if mode & 0o7022 or mode & 0o500 != 0o500:
                return False
        elif entry["kind"] == "file":
            if path in {"frontier-canary.config.toml", "frontier-canary-sentinel"}:
                if mode != 0o600:
                    return False
            elif path == "models_cache.json":
                if (
                    mode != 0o400
                    or entry.get("sha256")
                    != model_cache_contract["file_sha256"]
                    or entry.get("byte_size")
                    != model_cache_contract["byte_size"]
                ):
                    return False
            elif mode & 0o7133 or not mode & 0o400:
                return False
        elif path == "auth.json":
            if (
                entry.get("target_role") != "credential_reference"
                or entry.get("target_path_sha256") != auth_target_path_sha256
            ):
                return False
        else:
            if (
                entry.get("target_role") != "codex_binary"
                or entry.get("target_path_sha256") != codex_target_path_sha256
                or entry.get("resolved_file_sha256") != codex_file_sha256
            ):
                return False
    return True


def canonical_sha256(document: Any) -> str:
    """Return the hash of a JSON document under the contract's canonical form."""

    payload = canonical_json_bytes(document)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def verify_git_registration_anchor(
    manifest: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    anchor: GitRegistrationAnchor,
) -> dict[str, Any]:
    """Verify exact canonical manifest bytes in an immutable Git commit object."""

    issues: list[ValidationIssue] = []
    report = _git_registration_anchor_report(manifest, runs, anchor, issues)
    report["errors"] = [issue.to_dict() for issue in issues]
    return report


def _git_registration_anchor_report(
    manifest: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    anchor: GitRegistrationAnchor,
    issues: list[ValidationIssue],
) -> dict[str, Any]:
    limitations = [
        "Git commit timestamps are supplied by the committer and can be backdated.",
        "A local Git object proves content identity, not independent publication or third-party custody.",
        "Remote reachability and public hosting time still require reviewer verification.",
        "The absolute Git executable is content-addressed, but its dynamic libraries, operating "
        "system, and audit host remain trusted verification infrastructure.",
    ]
    report: dict[str, Any] = {
        "kind": "git_commit",
        "provided": True,
        "verified": False,
        "repo_path": str(anchor.repo_path),
        "requested_commit": anchor.commit,
        "resolved_commit": None,
        "verification_ref": "HEAD",
        "verification_ref_commit": None,
        "manifest_path": anchor.manifest_path,
        "commit_timestamp": None,
        "timestamp_precedes_runs": False,
        "limitations": limitations,
        "audit_host": {
            "git_path": str(_TRUSTED_GIT_BINARY) if _TRUSTED_GIT_BINARY is not None else None,
            "git_sha256": (
                file_sha256(_TRUSTED_GIT_BINARY)
                if _TRUSTED_GIT_BINARY is not None
                else None
            ),
        },
    }
    if _TRUSTED_GIT_BINARY is None:
        issues.append(
            _error(
                "git_anchor_command_failed",
                "$.registration_anchor",
                "No trusted absolute Git executable is available.",
            )
        )
        return report
    if not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", anchor.commit):
        issues.append(
            _error(
                "mutable_or_short_git_anchor",
                "$.registration_anchor.commit",
                "Registration anchors require a full immutable Git object ID, not a ref or abbreviation.",
            )
        )
        return report
    if not _safe_relative_uri(anchor.manifest_path):
        issues.append(
            _error(
                "unsafe_registration_manifest_path",
                "$.registration_anchor.manifest_path",
                "The anchored manifest path must be safe and repository-relative.",
            )
        )
        return report
    intended_path = manifest.get("registration", {}).get("manifest_path")
    if anchor.manifest_path != intended_path:
        issues.append(
            _error(
                "registration_manifest_path_mismatch",
                "$.registration_anchor.manifest_path",
                "The external anchor path differs from the path frozen in the manifest.",
            )
        )
        return report

    repo_path = anchor.repo_path.resolve()
    resolved = _git_output(
        repo_path, ["rev-parse", "--verify", f"{anchor.commit}^{{commit}}"], issues
    )
    if resolved is None:
        return report
    resolved = resolved.decode("ascii", errors="replace").strip()
    report["resolved_commit"] = resolved
    if resolved.lower() != anchor.commit.lower():
        issues.append(
            _error(
                "git_anchor_resolution_mismatch",
                "$.registration_anchor.commit",
                "Resolved Git commit differs from the supplied full object ID.",
            )
        )
        return report
    head_bytes = _git_output(repo_path, ["rev-parse", "--verify", "HEAD^{commit}"], issues)
    if head_bytes is None:
        return report
    head_commit = head_bytes.decode("ascii", errors="replace").strip()
    report["verification_ref_commit"] = head_commit
    if not _git_is_ancestor(repo_path, resolved, head_commit, issues):
        return report
    committed_bytes = _git_output(
        repo_path, ["cat-file", "blob", f"{resolved}:{anchor.manifest_path}"], issues
    )
    if committed_bytes is None:
        return report
    expected_bytes = canonical_json_bytes(manifest)
    if committed_bytes != expected_bytes:
        issues.append(
            _error(
                "registration_manifest_bytes_mismatch",
                "$.registration_anchor",
                "The committed file is not the exact canonical byte serialization of this manifest.",
            )
        )
        return report

    timestamp_bytes = _git_output(
        repo_path, ["show", "-s", "--format=%cI", resolved], issues
    )
    if timestamp_bytes is None:
        return report
    timestamp_text = timestamp_bytes.decode("utf-8", errors="replace").strip()
    try:
        commit_time = _datetime(timestamp_text)
    except ValueError:
        issues.append(
            _error(
                "invalid_git_commit_timestamp",
                "$.registration_anchor",
                "Git did not return a parseable offset-aware committer timestamp.",
            )
        )
        return report
    report["commit_timestamp"] = timestamp_text
    run_starts = [
        parsed
        for run in runs
        for parsed in [_safe_run_start(run)]
        if parsed is not None
    ]
    if not run_starts:
        issues.append(
            _error(
                "registration_anchor_has_no_run_boundary",
                "$.registration_anchor",
                "At least one valid run start is required to verify that registration preceded execution.",
            )
        )
        return report
    if run_starts and commit_time >= min(run_starts):
        issues.append(
            _error(
                "registration_anchor_does_not_predate_runs",
                "$.registration_anchor",
                "The Git committer timestamp does not precede the earliest supplied run.",
            )
        )
        return report
    if commit_time > _datetime(manifest["registered_at"]):
        issues.append(
            _error(
                "registration_anchor_postdates_registration",
                "$.registration_anchor",
                "The Git committer timestamp is later than the manifest's registration time.",
            )
        )
        return report
    report["timestamp_precedes_runs"] = bool(run_starts)
    report["verified"] = True
    return report


def _git_output(
    repo_path: Path,
    arguments: Sequence[str],
    issues: list[ValidationIssue],
) -> bytes | None:
    try:
        completed = subprocess.run(
            [
                str(_TRUSTED_GIT_BINARY),
                "--no-replace-objects",
                "-C",
                str(repo_path),
                *arguments,
            ],
            check=False,
            capture_output=True,
            timeout=10,
            env=_git_anchor_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        issues.append(
            _error(
                "git_anchor_command_failed",
                "$.registration_anchor",
                f"Could not inspect the Git registration anchor: {error}.",
            )
        )
        return None
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        issues.append(
            _error(
                "git_anchor_command_failed",
                "$.registration_anchor",
                f"Git anchor inspection failed: {stderr or 'unknown git error'}.",
            )
        )
        return None
    return completed.stdout


def _git_is_ancestor(
    repo_path: Path,
    ancestor: str,
    descendant: str,
    issues: list[ValidationIssue],
) -> bool:
    try:
        completed = subprocess.run(
            [
                str(_TRUSTED_GIT_BINARY),
                "--no-replace-objects",
                "-C",
                str(repo_path),
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
            ],
            check=False,
            capture_output=True,
            timeout=10,
            env=_git_anchor_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        issues.append(
            _error(
                "git_anchor_command_failed",
                "$.registration_anchor",
                f"Could not verify Git reachability: {error}.",
            )
        )
        return False
    if completed.returncode != 0:
        issues.append(
            _error(
                "git_anchor_not_reachable",
                "$.registration_anchor.commit",
                "The registration commit is not an ancestor of the repository's current HEAD.",
            )
        )
        return False
    return True


def _git_anchor_environment() -> dict[str, str]:
    """Return a Git environment that cannot redirect or replace anchor objects."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_COUNT"] = "0"
    if _TRUSTED_GIT_BINARY is not None:
        environment["PATH"] = os.pathsep.join(
            dict.fromkeys(
                (
                    str(_TRUSTED_GIT_BINARY.parent),
                    "/usr/bin",
                    "/bin",
                )
            )
        )
    return environment


def validate_experiment_manifest(manifest: Mapping[str, Any]) -> list[ValidationIssue]:
    """Validate experiment shape and preregistration semantics."""

    issues = _validate_against_schema(manifest, EXPERIMENT_SCHEMA_PATH)
    if _has_errors(issues):
        return issues

    registered_at = _datetime(manifest["registered_at"])
    locked_at = _datetime(manifest["exclusion_policy"]["locked_at"])
    if locked_at > registered_at:
        issues.append(
            _error(
                "exclusion_policy_locked_late",
                "$.exclusion_policy.locked_at",
                "The exclusion policy must be locked no later than experiment registration.",
            )
        )

    _check_manifest_pin_labels(manifest, issues)
    _check_model_backend_identity_contract(manifest, issues)
    _check_relative_artifact_pins(manifest, issues, "$")
    _check_evidence_roles(manifest, issues)
    _check_declared_state_provenance(manifest, issues)
    _check_unique_ids(
        manifest["reference_agent_stack"]["tools"],
        "id",
        "$.reference_agent_stack.tools",
        "duplicate_tool_id",
        issues,
    )
    _check_unique_ids(
        manifest["arms"], "arm_id", "$.arms", "duplicate_arm_id", issues
    )
    _check_unique_ids(
        manifest["outcome_metrics"],
        "metric_id",
        "$.outcome_metrics",
        "duplicate_metric_id",
        issues,
    )
    _check_unique_ids(
        manifest["exclusion_policy"]["codes"],
        "code",
        "$.exclusion_policy.codes",
        "duplicate_exclusion_code",
        issues,
    )
    declared_stages = manifest["task"]["lifecycle_stages"]
    stage_positions = [_LIFECYCLE_STAGES.index(stage) for stage in declared_stages]
    if stage_positions != sorted(stage_positions):
        issues.append(
            _error(
                "noncanonical_lifecycle_order",
                "$.task.lifecycle_stages",
                "Task lifecycle stages must follow the canonical Drupal agent lifecycle.",
            )
        )
    _validate_execution_plan(manifest, issues)
    _validate_inference_plan(manifest, issues)
    _validate_confidence_plan(manifest, issues)
    _validate_guardrail_plan(manifest, issues)
    _validate_cost_measurement_plan(manifest, issues)

    for index, arm in enumerate(manifest["arms"]):
        _check_drupal_state(arm["drupal_state"], f"$.arms[{index}].drupal_state", issues)

    metric_ids = {metric["metric_id"] for metric in manifest["outcome_metrics"]}
    primary_metric_id = manifest["claim_plan"]["primary_metric_id"]
    if primary_metric_id not in metric_ids:
        issues.append(
            _error(
                "unknown_primary_metric",
                "$.claim_plan.primary_metric_id",
                "The primary metric must be declared in outcome_metrics.",
            )
        )
    verdict_metric_id = manifest["evaluation"]["verdict_metric_id"]
    verdict_definition = next(
        (
            metric
            for metric in manifest["outcome_metrics"]
            if metric["metric_id"] == verdict_metric_id
        ),
        None,
    )
    if verdict_definition is None:
        issues.append(
            _error(
                "unknown_verdict_metric",
                "$.evaluation.verdict_metric_id",
                "The evaluator verdict must name a registered outcome metric.",
            )
        )
    elif verdict_definition["kind"] != "binary":
        issues.append(
            _error(
                "nonbinary_verdict_metric",
                "$.evaluation.verdict_metric_id",
                "The evaluator verdict metric must be registered as binary.",
            )
        )

    lane = manifest["lane"]
    if lane == "fixed_regression":
        _validate_fixed_manifest(manifest, issues)
    else:
        _validate_frontier_manifest(manifest, issues)

    return issues


def validate_run_result(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any] | None = None,
) -> list[ValidationIssue]:
    """Validate one run and, when supplied, bind it to its registered manifest."""

    issues = _validate_against_schema(run, RUN_SCHEMA_PATH)
    if _has_errors(issues):
        return issues

    _check_relative_artifact_pins(run, issues, "$")
    _check_run_pin_labels(run, issues)
    _check_run_timestamps(run, issues)
    _check_drupal_state(run["arm"]["drupal_state"], "$.arm.drupal_state", issues)
    _check_drupal_state(run["final_drupal_state"], "$.final_drupal_state", issues)
    _check_run_artifacts_and_references(run, issues)
    _check_prompt_delivery(run, issues)
    _check_model_identity_receipt(run, issues)
    _check_provider_request_identity(run, issues)
    _check_execution_receipt(run, issues)
    _check_state_capture_receipts(run, issues)
    _check_evaluator_receipt(run, issues)
    _check_costs_and_budget(run, manifest, issues)
    _check_behavior_events(run, issues)
    _check_outcome_metrics(run, manifest, issues)
    _check_validity(run, manifest, issues)
    _check_attempt(run, issues)

    if manifest is not None:
        manifest_issues = validate_experiment_manifest(manifest)
        if _has_errors(manifest_issues):
            issues.append(
                _error(
                    "invalid_experiment_manifest",
                    "$.experiment_manifest_sha256",
                    "The run cannot be bound to an invalid experiment manifest.",
                )
            )
            return issues
        _bind_run_to_manifest(run, manifest, issues)

    return issues


def _check_provider_request_identity(
    run: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    execution = run["execution_receipt"]
    status = execution["provider_request_id_status"]
    provider_id = execution["provider_request_id"]
    valid = (
        status == "verified_distinct"
        and isinstance(provider_id, str)
        and bool(provider_id)
    ) or (status == "unverified_not_reported" and provider_id is None)
    if not valid:
        issues.append(
            _error(
                "provider_request_identity_status_mismatch",
                "$.execution_receipt.provider_request_id",
                "A verified provider request requires a non-empty distinct ID; an unreported "
                "provider request requires null and must not be fabricated from thread_id.",
            )
        )


def _check_model_backend_identity_contract(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    contract = manifest["reference_agent_stack"]["model"][
        "backend_identity_contract"
    ]
    if not _backend_identity_contract_shape(
        contract,
        "$.reference_agent_stack.model.backend_identity_contract",
        issues,
    ):
        return
    mode = contract["mode"]
    expected = contract["expected_backend_identity"]
    if mode == "provider_attested_snapshot":
        _reject_mutable_labels(
            [("$.reference_agent_stack.model.backend_identity_contract.expected_backend_identity", expected)],
            issues,
        )
        issues.append(
            _warning(
                "provider_attestation_verification_unimplemented",
                "$.reference_agent_stack.model.backend_identity_contract.mode",
                "Provider-attested identity is retained for diagnostics, but v1 has no "
                "trusted issuer-key or provider-API verifier and therefore cannot promote it "
                "to claim-grade backend identity.",
            )
        )
    elif mode == "local_model_artifact":
        artifact = contract["local_model_artifact"]
        if artifact["sha256"] != expected:
            issues.append(
                _error(
                    "local_model_identity_hash_mismatch",
                    "$.reference_agent_stack.model.backend_identity_contract",
                    "The expected local backend identity must equal the pinned model artifact hash.",
                )
            )
        required_argument = f"--model-artifact-sha256={expected}"
        if contract["required_invocation_argument"] != required_argument:
            issues.append(
                _error(
                    "local_model_invocation_binding_invalid",
                    "$.reference_agent_stack.model.backend_identity_contract.required_invocation_argument",
                    "The required local-model invocation argument must bind the exact registered "
                    "artifact SHA-256.",
                )
            )
    elif manifest["lane"] == "fixed_regression":
        issues.append(
            _warning(
                "backend_identity_unverified_directional_only",
                "$.reference_agent_stack.model.backend_identity_contract.mode",
                "A fixed regression with only a held selector is directional_only; it cannot "
                "produce a claim-grade estimate or satisfy the registered effect rule.",
            )
        )


def _backend_identity_contract_shape(
    contract: Any, path: str, issues: list[ValidationIssue]
) -> bool:
    valid = isinstance(contract, Mapping)
    if not valid:
        issues.append(
            _error(
                "model_backend_identity_contract_invalid",
                path,
                "Model backend identity contract must be an object.",
            )
        )
        return False
    mode = contract.get("mode")
    expected = contract.get("expected_backend_identity")
    attestation = contract.get("attestation_contract")
    local = contract.get("local_model_artifact")
    runner_attestation = contract.get("runner_attestation_contract")
    invocation_argument = contract.get("required_invocation_argument")

    def pin_sha(value: Any, *, versioned: bool) -> str | None:
        if not isinstance(value, Mapping):
            return None
        artifact = value.get("artifact") if versioned else value
        if not isinstance(artifact, Mapping):
            return None
        sha256 = artifact.get("sha256")
        return sha256 if isinstance(sha256, str) and _SHA256.fullmatch(sha256) else None

    if mode == "provider_attested_snapshot":
        valid = bool(
            isinstance(expected, str)
            and expected
            and pin_sha(attestation, versioned=True)
            and local is None
            and runner_attestation is None
            and invocation_argument is None
        )
    elif mode == "local_model_artifact":
        valid = bool(
            isinstance(expected, str)
            and _SHA256.fullmatch(expected)
            and attestation is None
            and pin_sha(local, versioned=False)
            and pin_sha(runner_attestation, versioned=True)
            and isinstance(invocation_argument, str)
            and invocation_argument
        )
    elif mode == "held_selector":
        valid = (
            expected is None
            and attestation is None
            and local is None
            and runner_attestation is None
            and invocation_argument is None
        )
    else:
        valid = False
    if not valid:
        issues.append(
            _error(
                "model_backend_identity_contract_invalid",
                path,
                "Backend identity mode and expected identity/attestation/local artifact fields "
                "are incoherent.",
            )
        )
    return valid


def _check_model_identity_receipt(
    run: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    receipt = run["model_identity_receipt"]
    model = run["agent_stack"]["model"]
    contract = model["backend_identity_contract"]
    if not _backend_identity_contract_shape(
        contract,
        "$.agent_stack.model.backend_identity_contract",
        issues,
    ):
        return
    execution = run["execution_receipt"]
    expected_bindings = {
        "model_provider": model["provider"],
        "model_id": model["id"],
        "declared_selector": model["snapshot"],
        "provider_request_id": execution["provider_request_id"],
    }
    mismatches = [
        field
        for field, expected in expected_bindings.items()
        if receipt[field] != expected
    ]
    if receipt["observed_at"] != run["timestamps"]["completed_at"]:
        mismatches.append("observed_at")
    artifacts = _run_artifacts_by_kind(run)
    artifact = artifacts.get("model_identity_receipt")
    if artifact is not None and receipt["receipt_artifact_id"] != artifact["artifact_id"]:
        mismatches.append("receipt_artifact_id")

    mode = contract["mode"]
    if mode == "provider_attested_snapshot":
        attestation = contract["attestation_contract"]
        expected_values = {
            "status": "provider_attested_immutable",
            "source": "provider_attestation",
            "backend_identity": contract["expected_backend_identity"],
            "attestation_contract_sha256": attestation["artifact"]["sha256"],
            "local_model_artifact_sha256": None,
            "runner_attestation_contract_sha256": None,
        }
        if execution["provider_request_id_status"] != "verified_distinct":
            mismatches.append("provider_request_id_status")
    elif mode == "local_model_artifact":
        expected_values = {
            "status": "local_artifact_hash_verified",
            "source": "trusted_local_runner_attestation",
            "backend_identity": contract["expected_backend_identity"],
            "attestation_contract_sha256": None,
            "local_model_artifact_sha256": contract["local_model_artifact"][
                "sha256"
            ],
            "runner_attestation_contract_sha256": contract[
                "runner_attestation_contract"
            ]["artifact"]["sha256"],
        }
        if contract["required_invocation_argument"] not in execution["argv"]:
            mismatches.append("required_invocation_argument")
    else:
        expected_values = {
            "status": "unverified_held_selector",
            "source": "declared_selector_only",
            "backend_identity": None,
            "attestation_contract_sha256": None,
            "local_model_artifact_sha256": None,
            "runner_attestation_contract_sha256": None,
        }
    mismatches.extend(
        field
        for field, expected in expected_values.items()
        if receipt[field] != expected
    )
    if mismatches:
        issues.append(
            _error(
                "model_identity_contract_mismatch",
                "$.model_identity_receipt",
                "The retained model identity receipt does not satisfy the registered backend "
                f"identity contract; mismatches={sorted(set(mismatches))!r}.",
            )
        )


# Short aliases for callers that prefer the domain nouns.
validate_manifest = validate_experiment_manifest
validate_run = validate_run_result


def _model_backend_identity_assurance(
    manifest: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    model = manifest.get("reference_agent_stack", {}).get("model", {})
    contract = model.get("backend_identity_contract", {})
    mode = contract.get("mode")
    receipts = [run.get("model_identity_receipt", {}) for run in runs]
    statuses = {
        receipt.get("status") for receipt in receipts if isinstance(receipt, Mapping)
    }
    identities = {
        receipt.get("backend_identity")
        for receipt in receipts
        if isinstance(receipt, Mapping)
    }
    expected_status = {
        "provider_attested_snapshot": "provider_attested_immutable",
        "local_model_artifact": "local_artifact_hash_verified",
        "held_selector": "unverified_held_selector",
    }.get(mode)
    expected_identity = contract.get("expected_backend_identity")
    receipt_consistent = bool(
        receipts
        and expected_status is not None
        and statuses == {expected_status}
        and identities == {expected_identity}
    )
    verified = bool(
        mode == "local_model_artifact"
        and receipt_consistent
        and isinstance(contract.get("runner_attestation_contract"), Mapping)
        and contract.get("required_invocation_argument")
        == f"--model-artifact-sha256={expected_identity}"
    )
    if manifest.get("lane") == "frontier_observation":
        classification = "descriptive_snapshot"
    elif verified:
        classification = "trusted_harness_bound"
    else:
        classification = "directional_only"
    limitations = [
        "Provider request identity proves invocation uniqueness, not backend model weights."
    ]
    if mode == "provider_attested_snapshot":
        assurance_reason = "provider_attestation_verification_unimplemented"
        limitations.append(
            "Internally consistent provider-attestation fields are not authenticity evidence; "
            "v1 does not execute a trusted issuer-key or provider-API verifier."
        )
    elif mode == "local_model_artifact" and verified:
        assurance_reason = "local_artifact_and_runner_binding_verified"
        limitations.append(
            "Claim eligibility is relative to a trusted pinned harness: artifact bytes, the "
            "runner contract, launch argument, attempt receipt, and execution receipt are "
            "hash-bound, but no hardware remote attestation proves a malicious runner loaded "
            "those bytes."
        )
    elif mode == "local_model_artifact":
        assurance_reason = "local_runtime_binding_incomplete"
    else:
        assurance_reason = "held_selector_only"
    if classification == "directional_only":
        limitations.append(
            "The declared model selector is held, but backend identity is not claim-grade; "
            "fixed-regression output is directional_only."
        )
    elif classification == "descriptive_snapshot" and not verified:
        limitations.append(
            "The frontier result describes the retained selector-bound execution only; its "
            "provider backend identity remains unverified."
        )
    return {
        "contract_mode": mode,
        "expected_backend_identity": expected_identity,
        "observed_backend_identities": sorted(
            identity for identity in identities if isinstance(identity, str)
        ),
        "receipt_statuses": sorted(
            status for status in statuses if isinstance(status, str)
        ),
        "claim_grade_eligible": verified,
        "classification": classification,
        "assurance_reason": assurance_reason,
        "limitations": limitations,
    }


def audit_measurement_v1(
    manifest: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    *,
    artifact_root: Path | None = None,
    registration_anchor: GitRegistrationAnchor | None = None,
) -> dict[str, Any]:
    """Audit a complete measurement set and return a claim-safety report."""

    issues = validate_experiment_manifest(manifest)
    manifest_valid = not _has_errors(issues)

    valid_runs: list[Mapping[str, Any]] = []
    for index, run in enumerate(runs):
        run_issues = validate_run_result(run, manifest if manifest_valid else None)
        issues.extend(_prefix_issue(issue, f"$.runs[{index}]") for issue in run_issues)
        if not _has_errors(run_issues):
            valid_runs.append(run)

    if manifest_valid:
        raw_lanes = {run.get("lane") for run in runs}
        if len(raw_lanes) > 1 or (raw_lanes and raw_lanes != {manifest["lane"]}):
            issues.append(
                _error(
                    "mixed_measurement_lanes",
                    "$.runs",
                    "Fixed regressions and frontier observations cannot share an analysis set.",
                )
            )
        _check_collection(manifest, valid_runs, issues)

    contract_valid = not _has_errors(issues)
    census = _census_summary(manifest, valid_runs) if manifest_valid else {
        "expected_slots": 0,
        "resolved_slots": 0,
        "missing_slots": [],
        "unregistered_slots": [],
        "duplicate_slots": [],
        "excluded_slots": [],
        "complete": False,
        "limitations": [
            "Census completeness is relative to supplied run records; independent append-only "
            "run custody is needed to prove that no executions were omitted."
        ],
    }
    if registration_anchor is None:
        registration_report = {
            "kind": "git_commit",
            "provided": False,
            "verified": False,
            "repo_path": None,
            "requested_commit": None,
            "resolved_commit": None,
            "verification_ref": "HEAD",
            "verification_ref_commit": None,
            "manifest_path": manifest.get("registration", {}).get("manifest_path"),
            "commit_timestamp": None,
            "timestamp_precedes_runs": False,
            "limitations": [
                "No external Git commit anchor was supplied.",
                "Manifest timestamps and in-manifest registration fields are self-attested.",
            ],
        }
        issues.append(
            _warning(
                "registration_anchor_not_verified",
                "$.registration_anchor",
                "Claim-grade evidence requires exact canonical manifest bytes in a supplied Git commit.",
            )
        )
    elif manifest_valid:
        registration_report = _git_registration_anchor_report(
            manifest, runs, registration_anchor, issues
        )
    else:
        registration_report = {
            "kind": "git_commit",
            "provided": True,
            "verified": False,
            "repo_path": str(registration_anchor.repo_path),
            "requested_commit": registration_anchor.commit,
            "resolved_commit": None,
            "verification_ref": "HEAD",
            "verification_ref_commit": None,
            "manifest_path": registration_anchor.manifest_path,
            "commit_timestamp": None,
            "timestamp_precedes_runs": False,
            "limitations": ["Invalid manifests cannot be externally anchored for analysis."],
        }

    artifacts_verified = False
    artifact_semantics_verified = False
    if artifact_root is None:
        issues.append(
            _warning(
                "artifact_verification_not_run",
                "$.artifacts",
                "Declared hashes were not compared with bytes; claims remain ineligible.",
            )
        )
    elif manifest_valid:
        before = len([issue for issue in issues if issue.severity == "error"])
        _verify_all_artifacts(manifest, valid_runs, artifact_root, issues)
        after = len([issue for issue in issues if issue.severity == "error"])
        artifacts_verified = before == after and len(valid_runs) == len(runs)
        if artifacts_verified:
            before_semantics = after
            _verify_model_identity_contract_artifacts(
                manifest,
                artifact_root,
                issues,
            )
            _verify_state_provenance_artifacts(
                manifest,
                valid_runs,
                artifact_root,
                issues,
            )
            _verify_run_artifact_semantics(
                manifest, valid_runs, artifact_root, issues
            )
            after_semantics = len(
                [issue for issue in issues if issue.severity == "error"]
            )
            artifact_semantics_verified = before_semantics == after_semantics

    receipt_assurance = {
        "mode": manifest.get("evaluation", {}).get("assurance", {}).get("mode"),
        "trusted_receipt_contract": bool(
            manifest_valid
            and manifest["evaluation"]["assurance"]["mode"]
            == "trusted_execution_receipt"
        ),
        "complete": bool(
            contract_valid
            and artifacts_verified
            and artifact_semantics_verified
            and len(valid_runs) == len(runs)
        ),
        "limitations": [
            "Trusted-receipt eligibility assumes the preregistered issuer controls its "
            "invocation identities; this audit verifies content bindings, not external custody."
        ],
    }
    denominator = _denominator_summary(manifest, valid_runs) if manifest_valid else {
        "planned": None,
        "observed": 0,
        "unit": None,
        "status": "invalid_manifest",
    }
    analysis = _analyze_primary_metric(manifest, valid_runs) if manifest_valid else None
    guardrail_analysis = (
        _analyze_guardrails(manifest, valid_runs)
        if manifest_valid
        else {"all_passed": False, "guardrails": []}
    )
    backend_identity = (
        _model_backend_identity_assurance(manifest, valid_runs)
        if manifest_valid
        else {
            "contract_mode": None,
            "expected_backend_identity": None,
            "observed_backend_identities": [],
            "receipt_statuses": [],
            "claim_grade_eligible": False,
            "classification": "invalid",
            "limitations": [
                "Invalid manifests cannot establish model backend identity assurance."
            ],
        }
    )
    evidence_complete = (
        contract_valid
        and registration_report["verified"]
        and artifacts_verified
        and artifact_semantics_verified
        and receipt_assurance["complete"]
        and census["complete"]
    )
    bounded_result_available = (
        evidence_complete
        and not census["excluded_slots"]
        and denominator["status"] == "complete"
        and analysis is not None
    )
    directional_result_available = bool(
        bounded_result_available and manifest.get("lane") == "fixed_regression"
    )
    estimate_reportable = bool(
        bounded_result_available
        and (
            manifest.get("lane") != "fixed_regression"
            or backend_identity["claim_grade_eligible"]
        )
    )
    if analysis is not None:
        analysis["reportable"] = estimate_reportable
        analysis["directional_only"] = bool(
            directional_result_available and not estimate_reportable
        )
    decision = (
        _derive_effect_rule_decision(
            manifest,
            analysis,
            guardrail_analysis,
            estimate_reportable,
            backend_identity,
        )
        if manifest_valid
        else {
            "rule": None,
            "minimum_favorable_effect": None,
            "favorable_confidence_lower_bound": None,
            "guardrails_passed": False,
            "registered_effect_rule_met": False,
            "reason": "invalid_manifest",
        }
    )
    registered_effect_rule_met = decision["registered_effect_rule_met"]
    shared_content = _shared_content_summary(valid_runs)
    cost_measurement = _cost_measurement_summary(manifest, valid_runs) if manifest_valid else {
        "mode": None,
        "cost_reportable": False,
        "price_schedule_sha256": None,
        "limitations": ["Invalid manifests cannot support cost reporting."],
    }

    return {
        "schema_version": "drupal_agent_readiness.measurement_audit.v1",
        "experiment_id": manifest.get("experiment_id"),
        "governance": manifest.get("governance"),
        "lane": manifest.get("lane"),
        "manifest_sha256": canonical_sha256(manifest) if manifest_valid else None,
        "contract_valid": contract_valid,
        "audit_valid": not _has_errors(issues),
        "registration_anchor": registration_report,
        "artifacts_verified": artifacts_verified,
        "artifact_semantics_verified": artifact_semantics_verified,
        "receipt_assurance": receipt_assurance,
        "attempt_census": census,
        "evidence_complete": evidence_complete,
        "directional_result_available": directional_result_available,
        "estimate_reportable": estimate_reportable,
        "registered_effect_rule_met": registered_effect_rule_met,
        "claim_class": manifest.get("claim_plan", {}).get("claim_class"),
        "denominator": denominator,
        "analysis": analysis,
        "guardrails": guardrail_analysis,
        "cost_measurement": cost_measurement,
        "decision": decision,
        "model_backend_identity": backend_identity,
        "shared_artifact_content": shared_content,
        "limitations": [
            *registration_report["limitations"],
            "Semantic artifact reconciliation proves internal consistency, not that an agent "
            "or harness truthfully emitted the retained evidence.",
            *receipt_assurance["limitations"],
            *cost_measurement["limitations"],
            *backend_identity["limitations"],
            "registered_effect_rule_met is a measurement result only; it does not prove "
            "that the governance IDs resolve to a compatible decided or adopted action record.",
            *census["limitations"],
        ],
        "errors": [issue.to_dict() for issue in issues if issue.severity == "error"],
        "warnings": [issue.to_dict() for issue in issues if issue.severity == "warning"],
    }


audit_measurement = audit_measurement_v1


def _check_evidence_roles(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    role_pins = [
        ("$.task.prompt", manifest["task"]["prompt"], "task_prompt"),
        (
            "$.reference_agent_stack.system_prompt",
            manifest["reference_agent_stack"]["system_prompt"],
            "system_prompt",
        ),
        (
            "$.reference_agent_stack.output_schema",
            manifest["reference_agent_stack"]["output_schema"],
            "output_schema",
        ),
        (
            "$.prompt_composition.render_inputs",
            manifest["prompt_composition"]["render_inputs"],
            "render_inputs",
        ),
        ("$.task.ground_truth", manifest["task"]["ground_truth"], "ground_truth"),
        (
            "$.evaluation.evaluator.artifact",
            manifest["evaluation"]["evaluator"]["artifact"],
            "evaluator_implementation",
        ),
        (
            "$.evaluation.rubric.artifact",
            manifest["evaluation"]["rubric"]["artifact"],
            "evaluation_rubric",
        ),
        (
            "$.evaluation.scoring.artifact",
            manifest["evaluation"]["scoring"]["artifact"],
            "scoring_implementation",
        ),
    ]
    seen_hashes: dict[str, str] = {}
    for path, pin, expected_role in role_pins:
        expected_visibility, expected_audience = _ROLE_EXPECTATIONS[expected_role]
        if (
            pin["evidence_role"] != expected_role
            or pin["visibility"] != expected_visibility
            or set(pin["audience"]) != expected_audience
        ):
            issues.append(
                _error(
                    "evidence_role_semantics_mismatch",
                    path,
                    f"{expected_role} must be {expected_visibility} for "
                    f"{sorted(expected_audience)!r}.",
                )
            )
        previous = seen_hashes.get(pin["sha256"])
        if previous is not None:
            issues.append(
                _error(
                    "evidence_role_artifact_alias",
                    path,
                    f"Role artifact bytes alias incompatible role at {previous}.",
                )
            )
        seen_hashes[pin["sha256"]] = path

    visible = {
        pin["sha256"]
        for _, pin, role in role_pins
        if _ROLE_EXPECTATIONS[role][0] == "agent_visible"
    }
    withheld = {
        pin["sha256"]
        for _, pin, role in role_pins
        if _ROLE_EXPECTATIONS[role][0] == "withheld_from_agent"
    }
    withheld.add(manifest["exclusion_policy"]["policy"]["sha256"])
    if visible & withheld:
        issues.append(
            _error(
                "agent_visible_withheld_artifact_alias",
                "$.task",
                "Agent-visible prompt inputs cannot share byte identity with withheld "
                "ground truth, evaluator, rubric, scoring, or exclusion evidence.",
            )
        )


def _check_declared_state_provenance(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    _check_site_state_source_links(
        manifest["substrate"]["starting_site_seed"],
        "$.substrate.starting_site_seed",
        issues,
    )


def _check_site_state_source_links(
    site: Mapping[str, Any], path: str, issues: list[ValidationIssue]
) -> None:
    for field, source, label in (
        ("database_sha256", "database", "Database"),
        ("active_config_sha256", "active_config", "Active-config"),
        ("public_files_sha256", "public_files", "Public-files"),
        ("private_files_sha256", "private_files", "Private-files"),
    ):
        if site[field] != site["sources"][source]["sha256"]:
            issues.append(
                _error(
                    "state_source_hash_mismatch",
                    f"{path}.{field}",
                    f"{label} state hash is not its retained source hash.",
                )
            )
    if site["composite_sha256"] != site["manifest"]["sha256"]:
        issues.append(
            _error(
                "state_manifest_hash_mismatch",
                f"{path}.composite_sha256",
                "Site composite hash must equal the retained canonical site-manifest hash.",
            )
        )


def _check_code_state_source_links(
    code: Mapping[str, Any], path: str, issues: list[ValidationIssue]
) -> None:
    for field, source, label in (
        ("composer_lock_sha256", "composer_lock", "Composer-lock"),
        ("extensions_manifest_sha256", "extensions_manifest", "Extensions-manifest"),
        ("codebase_tree_sha256", "codebase", "Codebase-tree"),
    ):
        if code[field] != code["sources"][source]["sha256"]:
            issues.append(
                _error(
                    "state_source_hash_mismatch",
                    f"{path}.{field}",
                    f"{label} hash is not its retained source hash.",
                )
            )


def _validate_inference_plan(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    scope = manifest["inference_scope"]
    design = manifest["sampling_design"]
    expected_unit = (
        "complete_pair" if manifest["lane"] == "fixed_regression" else "included_run"
    )
    if design["sampling_unit"] != expected_unit:
        issues.append(
            _error(
                "sampling_unit_lane_mismatch",
                "$.sampling_design.sampling_unit",
                f"This lane requires sampling_unit {expected_unit!r}.",
            )
        )
    if scope["kind"] == "registered_roster_only":
        if scope["target_population"] is not None:
            issues.append(
                _error(
                    "exact_roster_has_target_population",
                    "$.inference_scope.target_population",
                    "Exact-roster estimates cannot name an inferred target population.",
                )
            )
    elif not scope["target_population"]:
        issues.append(
            _error(
                "missing_target_population",
                "$.inference_scope.target_population",
                "Population inference requires an explicit target population.",
            )
        )


def _validate_guardrail_plan(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    guardrails = manifest["claim_plan"]["guardrails"]
    _check_unique_ids(
        guardrails,
        "guardrail_id",
        "$.claim_plan.guardrails",
        "duplicate_guardrail_id",
        issues,
    )
    outcome_ids = {metric["metric_id"] for metric in manifest["outcome_metrics"]}
    has_absolute_rule = False
    has_outcome_guardrail = False
    has_zero_intervention_rule = False
    has_resource_delta_rule = False
    for index, guardrail in enumerate(guardrails):
        source = guardrail["source"]
        metric_id = source["metric_id"]
        if source["kind"] == "outcome_metric" and metric_id not in outcome_ids:
            issues.append(
                _error(
                    "unknown_guardrail_metric",
                    f"$.claim_plan.guardrails[{index}].source.metric_id",
                    f"Guardrail metric {metric_id!r} is not registered.",
                )
            )
        if (
            source["kind"] == "outcome_metric"
            and metric_id != manifest["claim_plan"]["primary_metric_id"]
        ):
            has_outcome_guardrail = True
        if source["kind"] == "cost" and metric_id not in _COST_GUARDRAIL_METRICS:
            issues.append(
                _error(
                    "unknown_guardrail_cost",
                    f"$.claim_plan.guardrails[{index}].source.metric_id",
                    f"Unsupported cost guardrail {metric_id!r}.",
                )
            )
        seen_rules: set[tuple[str, str, float]] = set()
        guardrail_has_absolute_rule = False
        for rule_index, rule in enumerate(guardrail["rules"]):
            identity = (rule["statistic"], rule["operator"], float(rule["threshold"]))
            if identity in seen_rules:
                issues.append(
                    _error(
                        "duplicate_guardrail_rule",
                        f"$.claim_plan.guardrails[{index}].rules[{rule_index}]",
                        "Guardrail rules must be unique.",
                    )
                )
            seen_rules.add(identity)
            if (
                rule["statistic"] in {"maximum_all", "maximum_post"}
                and rule["operator"] == "at_most"
            ) or (
                rule["statistic"] == "minimum_post"
                and rule["operator"] == "at_least"
            ):
                has_absolute_rule = True
                guardrail_has_absolute_rule = True
            if (
                source == {"kind": "cost", "metric_id": "human_interventions"}
                and rule["statistic"] == "maximum_all"
                and rule["operator"] == "at_most"
                and rule["threshold"] == 0
            ):
                has_zero_intervention_rule = True
            if (
                source["kind"] == "cost"
                and metric_id != "human_interventions"
                and rule["statistic"] == "mean_post_minus_pre"
            ):
                has_resource_delta_rule = True
        if source["kind"] == "outcome_metric" and not guardrail_has_absolute_rule:
            issues.append(
                _error(
                    "outcome_guardrail_missing_absolute_rule",
                    f"$.claim_plan.guardrails[{index}].rules",
                    "Outcome guardrails require an absolute post-arm ceiling or floor.",
                )
            )
    if manifest["claim_plan"]["claim_class"] == "comparative":
        if not has_absolute_rule:
            issues.append(_error("missing_absolute_guardrail", "$.claim_plan.guardrails", "Comparative effect rules require at least one absolute guardrail ceiling or floor."))
        if not has_outcome_guardrail:
            issues.append(_error("missing_outcome_guardrail", "$.claim_plan.guardrails", "Comparative effect rules require at least one preregistered non-primary outcome guardrail."))
        if manifest["budget"]["human_interventions"] == 0 and not has_zero_intervention_rule:
            issues.append(_error("missing_autonomy_guardrail", "$.claim_plan.guardrails", "Autonomous comparisons must explicitly guard human_interventions at zero."))
        if not has_resource_delta_rule:
            issues.append(_error("missing_resource_guardrail", "$.claim_plan.guardrails", "Comparative effect rules must preregister an acceptable paired resource or latency delta."))


def _validate_confidence_plan(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    confidence = manifest["claim_plan"]["confidence"]
    method = confidence["method"]
    if method == "bootstrap_percentile":
        if "resamples" not in confidence or "seed_sha256" not in confidence:
            issues.append(
                _error(
                    "incomplete_bootstrap_plan",
                    "$.claim_plan.confidence",
                    "Descriptive bootstrap plans require resamples and a pinned seed.",
                )
            )
    elif "resamples" in confidence or "seed_sha256" in confidence:
        issues.append(
            _error(
                "irrelevant_confidence_parameters",
                "$.claim_plan.confidence",
                "Only bootstrap intervals may register resamples or a bootstrap seed.",
            )
        )
    if method == "none" and confidence["tail"] != "none":
        issues.append(
            _error(
                "confidence_tail_without_interval",
                "$.claim_plan.confidence.tail",
                "Confidence method none requires tail none.",
            )
        )


def _validate_cost_measurement_plan(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    plan = manifest["cost_measurement"]
    if plan["mode"] == "derived_from_usage" and plan["price_schedule"] is None:
        issues.append(
            _error(
                "derived_cost_missing_price_schedule",
                "$.cost_measurement.price_schedule",
                "Derived provider cost requires a preregistered content-pinned price schedule.",
            )
        )
    if plan["mode"] != "derived_from_usage" and plan["price_schedule"] is not None:
        issues.append(
            _error(
                "irrelevant_price_schedule",
                "$.cost_measurement.price_schedule",
                "Only derived costs may register a price schedule.",
            )
        )
def _validate_execution_plan(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    roster = manifest["execution_plan"]["attempt_roster"]
    stopping = manifest["execution_plan"]["stopping_rule"]
    indexes = [entry["index"] for entry in roster]
    units = [entry["unit_id"] for entry in roster]
    pair_ids = [entry["pair_id"] for entry in roster if entry["pair_id"] is not None]
    slots = [
        slot
        for entry in roster
        for slot in entry["executions"]
    ]
    slot_ids = [slot["slot_id"] for slot in slots]
    if len(indexes) != len(set(indexes)):
        issues.append(
            _error(
                "duplicate_roster_index",
                "$.execution_plan.attempt_roster",
                "Every preregistered attempt index must be unique.",
            )
        )
    if len(units) != len(set(units)):
        issues.append(
            _error(
                "duplicate_roster_unit",
                "$.execution_plan.attempt_roster",
                "Every preregistered experimental unit must be unique.",
            )
        )
    if len(pair_ids) != len(set(pair_ids)):
        issues.append(
            _error(
                "duplicate_roster_pair",
                "$.execution_plan.attempt_roster",
                "Every preregistered pair ID must be unique.",
            )
        )
    if len(slot_ids) != len(set(slot_ids)):
        issues.append(
            _error(
                "duplicate_roster_slot",
                "$.execution_plan.attempt_roster",
                "Every preregistered execution slot must be unique.",
            )
        )
    if stopping["required_resolved_slots"] != len(slots):
        issues.append(
            _error(
                "stopping_rule_slot_count_mismatch",
                "$.execution_plan.stopping_rule.required_resolved_slots",
                "The fixed-census stopping rule must require every registered slot.",
            )
        )
    arm_ids = {arm["arm_id"] for arm in manifest["arms"]}
    unknown_arms = sorted({slot["arm_id"] for slot in slots} - arm_ids)
    if unknown_arms:
        issues.append(
            _error(
                "unknown_roster_arm",
                "$.execution_plan.attempt_roster",
                f"Roster slots reference unknown arms: {unknown_arms!r}.",
            )
        )

    if manifest["lane"] == "fixed_regression":
        expected_arms = {
            manifest["comparison"].get("pre_arm_id"),
            manifest["comparison"].get("post_arm_id"),
        }
        pre_first = 0
        post_first = 0
        for index, entry in enumerate(roster):
            executions = entry["executions"]
            if (
                entry["pair_id"] is None
                or len(executions) != 2
                or {slot["arm_id"] for slot in executions} != expected_arms
                or {slot["order"] for slot in executions} != {1, 2}
            ):
                issues.append(
                    _error(
                        "invalid_fixed_roster_entry",
                        f"$.execution_plan.attempt_roster[{index}]",
                        "Each fixed-lane roster entry needs one pre and one post slot ordered 1 and 2.",
                    )
                )
                continue
            first_arm = next(slot["arm_id"] for slot in executions if slot["order"] == 1)
            if first_arm == manifest["comparison"].get("pre_arm_id"):
                pre_first += 1
            else:
                post_first += 1
            policy = manifest["comparison"]["order_policy"]
            if policy == "pre_then_post" and first_arm != manifest["comparison"].get("pre_arm_id"):
                issues.append(
                    _error(
                        "roster_order_policy_mismatch",
                        f"$.execution_plan.attempt_roster[{index}].executions",
                        "Roster contradicts the preregistered pre-then-post policy.",
                    )
                )
            if policy == "post_then_pre" and first_arm != manifest["comparison"].get("post_arm_id"):
                issues.append(
                    _error(
                        "roster_order_policy_mismatch",
                        f"$.execution_plan.attempt_roster[{index}].executions",
                        "Roster contradicts the preregistered post-then-pre policy.",
                    )
                )
        if (
            manifest["comparison"]["order_policy"] == "counterbalanced"
            and abs(pre_first - post_first) > 1
        ):
            issues.append(
                _error(
                    "uncounterbalanced_roster",
                    "$.execution_plan.attempt_roster",
                    "Counterbalancing must be frozen in the roster, not inferred after runs.",
                )
            )
        planned_units = len(roster)
    else:
        for index, entry in enumerate(roster):
            if (
                entry["pair_id"] is not None
                or len(entry["executions"]) != 1
                or entry["executions"][0]["order"] != 1
            ):
                issues.append(
                    _error(
                        "invalid_frontier_roster_entry",
                        f"$.execution_plan.attempt_roster[{index}]",
                        "Each frontier roster entry must contain one unpaired observation slot.",
                    )
                )
        planned_units = len(slots)

    if manifest["claim_plan"]["planned_denominator"] != planned_units:
        issues.append(
            _error(
                "planned_denominator_roster_mismatch",
                "$.claim_plan.planned_denominator",
                "The planned denominator must be derived from the frozen attempt roster.",
            )
        )


def _validate_fixed_manifest(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    comparison = manifest["comparison"]
    arms = manifest["arms"]
    roles = [arm["role"] for arm in arms]
    if len(arms) != 2 or sorted(roles) != ["post", "pre"]:
        issues.append(
            _error(
                "fixed_lane_requires_pre_post",
                "$.arms",
                "A fixed_regression experiment requires exactly one pre and one post arm.",
            )
        )
        return
    if comparison["mode"] != "paired_pre_post":
        issues.append(
            _error(
                "fixed_lane_requires_pairing",
                "$.comparison.mode",
                "A fixed_regression experiment must use paired_pre_post comparison.",
            )
        )
    if comparison["order_policy"] == "not_applicable":
        issues.append(
            _error(
                "missing_pair_order_policy",
                "$.comparison.order_policy",
                "A paired comparison must preregister its execution order policy.",
            )
        )

    arm_by_role = {arm["role"]: arm for arm in arms}
    pre = arm_by_role["pre"]
    post = arm_by_role["post"]
    if manifest["substrate"]["starting_site_seed"] != pre["drupal_state"]["site"]:
        issues.append(
            _error(
                "substrate_pre_arm_site_mismatch",
                "$.substrate.starting_site_seed",
                "The registered substrate seed must exactly equal the pre-arm starting site.",
            )
        )
    if comparison.get("pre_arm_id") != pre["arm_id"]:
        issues.append(
            _error(
                "pre_arm_reference_mismatch",
                "$.comparison.pre_arm_id",
                "pre_arm_id must identify the registered pre arm.",
            )
        )
    if comparison.get("post_arm_id") != post["arm_id"]:
        issues.append(
            _error(
                "post_arm_reference_mismatch",
                "$.comparison.post_arm_id",
                "post_arm_id must identify the registered post arm.",
            )
        )
    if pre["treatment"]["kind"] != "none":
        issues.append(
            _error(
                "pre_arm_has_treatment",
                "$.arms",
                "The pre arm must register treatment kind 'none'.",
            )
        )
    if post["treatment"]["kind"] == "none":
        issues.append(
            _error(
                "post_arm_missing_treatment",
                "$.arms",
                "The post arm must identify the Drupal treatment under test.",
            )
        )

    try:
        actual_differences = _leaf_differences(pre["drupal_state"], post["drupal_state"])
    except _ListIdentityCollision as error:
        issues.append(
            _error(
                "colliding_list_identity",
                "$.arms",
                str(error),
            )
        )
        actual_differences = set()
    allowed_differences = set(comparison["allowed_changed_paths"])
    if actual_differences != allowed_differences:
        issues.append(
            _error(
                "unregistered_treatment_difference",
                "$.comparison.allowed_changed_paths",
                "Registered changed paths must exactly equal all pre/post Drupal state differences; "
                f"actual={sorted(actual_differences)!r}, registered={sorted(allowed_differences)!r}.",
            )
        )
    if not actual_differences:
        issues.append(
            _error(
                "treatment_has_no_state_change",
                "$.arms",
                "A fixed regression cannot attribute an effect to an unchanged Drupal state.",
            )
        )

    claim = manifest["claim_plan"]
    confidence = claim["confidence"]
    primary_definition = next(
        (
            metric
            for metric in manifest["outcome_metrics"]
            if metric["metric_id"] == claim["primary_metric_id"]
        ),
        None,
    )
    if claim["claim_class"] == "causal":
        issues.append(
            _error(
                "causal_claim_not_supported_v1",
                "$.claim_plan.claim_class",
                "V1 cannot independently verify assignment and reset integrity, so causal claims fail closed.",
            )
        )
    if claim["claim_class"] == "comparative" and claim["planned_denominator"] < 2:
        issues.append(
            _error(
                "comparative_sample_too_small",
                "$.claim_plan.planned_denominator",
                "Comparative v1 claims require at least two preregistered complete pairs.",
            )
        )
    if (
        claim["claim_class"] == "comparative"
        and primary_definition is not None
        and primary_definition["kind"] not in {"binary", "rate"}
    ):
        issues.append(
            _error(
                "unbounded_primary_metric",
                "$.claim_plan.primary_metric_id",
                "Hoeffding effect rules support only registered binary or rate metrics in [0,1].",
            )
        )
    if (
        claim["claim_class"] == "comparative"
        and claim["minimum_favorable_effect"] <= 0
    ):
        issues.append(
            _error(
                "nonpositive_improvement_threshold",
                "$.claim_plan.minimum_favorable_effect",
                "Demonstrating improvement requires a preregistered favorable effect greater than zero.",
            )
        )
    if claim["estimand"] != "mean_paired_difference":
        issues.append(
            _error(
                "unsupported_fixed_estimand",
                "$.claim_plan.estimand",
                "Fixed v1 comparisons support only mean_paired_difference.",
            )
        )
    if (
        claim["claim_class"] in {"comparative", "causal"}
        and claim["decision_rule"] != "confidence_lower_bound_at_least_minimum"
    ):
        issues.append(
            _error(
                "unsupported_comparative_decision_rule",
                "$.claim_plan.decision_rule",
                "Comparative decisions require the preregistered confidence-lower-bound rule.",
            )
        )
    if claim["denominator_unit"] != "complete_pair":
        issues.append(
            _error(
                "wrong_fixed_lane_denominator_unit",
                "$.claim_plan.denominator_unit",
                "Fixed-lane denominators count complete included pairs.",
            )
        )
    if claim["claim_class"] in {"comparative", "causal"}:
        if confidence["method"] != "paired_hoeffding_lower":
            issues.append(
                _error(
                    "unsupported_effect_bound",
                    "$.claim_plan.confidence.method",
                    "Comparative fixed-lane effect rules require a paired Hoeffding lower bound.",
                )
            )
        if confidence["level"] < 0.95:
            issues.append(
                _error(
                    "insufficient_confidence_level",
                    "$.claim_plan.confidence.level",
                    "Comparative effect rules require confidence of at least 0.95.",
                )
            )
        if confidence["tail"] != "one_sided_lower":
            issues.append(
                _error(
                    "wrong_effect_bound_tail",
                    "$.claim_plan.confidence.tail",
                    "Comparative effect rules require an explicit one-sided lower bound.",
                )
            )
    elif claim["claim_class"] in {"exploratory", "descriptive"}:
        if claim["decision_rule"] != "descriptive_only":
            issues.append(
                _error(
                    "noncomparative_effect_rule_forbidden",
                    "$.claim_plan.decision_rule",
                    "Exploratory and descriptive fixed-lane analyses cannot register an effect decision.",
                )
            )
        if claim["minimum_favorable_effect"] != 0:
            issues.append(
                _error(
                    "noncomparative_effect_threshold_forbidden",
                    "$.claim_plan.minimum_favorable_effect",
                    "Exploratory and descriptive analyses must use a zero descriptive threshold.",
                )
            )


def _validate_frontier_manifest(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    comparison = manifest["comparison"]
    if any(arm["role"] != "observation" for arm in manifest["arms"]):
        issues.append(
            _error(
                "frontier_lane_requires_observation_arms",
                "$.arms",
                "frontier_observation arms cannot be labelled pre or post.",
            )
        )
    if any(arm["treatment"]["kind"] != "none" for arm in manifest["arms"]):
        issues.append(
            _error(
                "frontier_observation_has_treatment",
                "$.arms",
                "Frontier observation arms record current state and cannot encode a treatment.",
            )
        )
    if comparison["mode"] != "unpaired_observation":
        issues.append(
            _error(
                "frontier_lane_cannot_pair",
                "$.comparison.mode",
                "Frontier observations cannot masquerade as a fixed paired regression.",
            )
        )
    if comparison["order_policy"] != "not_applicable":
        issues.append(
            _error(
                "frontier_order_policy",
                "$.comparison.order_policy",
                "Unpaired frontier observation must use order_policy 'not_applicable'.",
            )
        )
    if comparison["allowed_changed_paths"]:
        issues.append(
            _error(
                "frontier_registered_treatment",
                "$.comparison.allowed_changed_paths",
                "Frontier observation cannot register a pre/post treatment delta.",
            )
        )
    if "pre_arm_id" in comparison or "post_arm_id" in comparison:
        issues.append(
            _error(
                "frontier_has_pair_arm_references",
                "$.comparison",
                "Unpaired observation cannot name pre/post arms.",
            )
        )

    claim = manifest["claim_plan"]
    if claim["claim_class"] == "causal":
        issues.append(
            _error(
                "causal_claim_not_supported_v1",
                "$.claim_plan.claim_class",
                "V1 cannot independently verify assignment and reset integrity, so causal claims fail closed.",
            )
        )
    if claim["claim_class"] not in {"exploratory", "descriptive"}:
        issues.append(
            _error(
                "frontier_claim_overreach",
                "$.claim_plan.claim_class",
                "A changing frontier stack supports exploratory or descriptive claims only.",
            )
        )
    if claim["estimand"] != "mean_observed_value":
        issues.append(
            _error(
                "unsupported_frontier_estimand",
                "$.claim_plan.estimand",
                "Frontier v1 observations support only mean_observed_value.",
            )
        )
    if claim["decision_rule"] != "descriptive_only":
        issues.append(
            _error(
                "frontier_improvement_decision_forbidden",
                "$.claim_plan.decision_rule",
                "A changing frontier stack can be described, not used to demonstrate Drupal improvement.",
            )
        )
    if claim["denominator_unit"] != "included_run":
        issues.append(
            _error(
                "wrong_frontier_denominator_unit",
                "$.claim_plan.denominator_unit",
                "Frontier-observation denominators count included runs.",
            )
        )
    exact_roster = (
        manifest["sampling_design"]["selection_method"]
        == "fixed_registered_census"
        and manifest["inference_scope"]["target_population"] is None
    )
    expected_method = "none" if exact_roster else "bootstrap_percentile"
    expected_tail = "none" if exact_roster else "two_sided"
    if (
        claim["claim_class"] == "descriptive"
        and claim["confidence"]["method"] != expected_method
    ):
        issues.append(
            _error(
                "wrong_frontier_confidence_method",
                "$.claim_plan.confidence.method",
                "Exact-roster frontier censuses use no sampling interval; sampled frontier "
                "claims require unpaired bootstrap confidence.",
            )
        )
    if (
        claim["claim_class"] == "descriptive"
        and claim["confidence"]["tail"] != expected_tail
    ):
        issues.append(
            _error(
                "wrong_frontier_confidence_tail",
                "$.claim_plan.confidence.tail",
                "Frontier confidence tails must match the registered sampling design.",
            )
        )


def _check_drupal_state(
    state: Mapping[str, Any], path: str, issues: list[ValidationIssue]
) -> None:
    code = state["code"]
    _check_code_state_source_links(code, f"{path}.code", issues)
    _check_site_state_source_links(state["site"], f"{path}.site", issues)
    core = code["core"]
    if core["kind"] != "core" or core["name"] != "drupal/core":
        issues.append(
            _error(
                "invalid_core_pin",
                f"{path}.code.core",
                "The mandatory core pin must be kind 'core' and name 'drupal/core'.",
            )
        )
    components = code["components"]
    keys = [(component["kind"], component["name"]) for component in components]
    if len(keys) != len(set(keys)):
        issues.append(
            _error(
                "duplicate_drupal_component",
                f"{path}.code.components",
                "Each Drupal project may appear only once in a code-state pin set.",
            )
        )
    if any(component["kind"] == "core" for component in components):
        issues.append(
            _error(
                "duplicate_core_pin",
                f"{path}.code.components",
                "Core belongs only in the mandatory core field.",
            )
        )
    if keys != sorted(keys):
        issues.append(
            _error(
                "noncanonical_component_order",
                f"{path}.code.components",
                "Components must be sorted by kind then name for stable comparison.",
            )
        )


def _check_manifest_pin_labels(
    manifest: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    stack = manifest["reference_agent_stack"]
    values: list[tuple[str, str]] = [
        ("$.task.version", manifest["task"]["version"]),
        ("$.reference_agent_stack.agent.version", stack["agent"]["version"]),
        ("$.reference_agent_stack.model.snapshot", stack["model"]["snapshot"]),
        ("$.reference_agent_stack.harness.version", stack["harness"]["version"]),
        ("$.substrate.runtime.php_version", manifest["substrate"]["runtime"]["php_version"]),
        (
            "$.substrate.runtime.database_version",
            manifest["substrate"]["runtime"]["database_version"],
        ),
        ("$.evaluation.evaluator.version", manifest["evaluation"]["evaluator"]["version"]),
        ("$.evaluation.rubric.version", manifest["evaluation"]["rubric"]["version"]),
        ("$.evaluation.scoring.version", manifest["evaluation"]["scoring"]["version"]),
        (
            "$.evaluation.assurance.trusted_issuer.version",
            manifest["evaluation"]["assurance"]["trusted_issuer"]["version"],
        ),
        (
            "$.prompt_composition.renderer.version",
            manifest["prompt_composition"]["renderer"]["version"],
        ),
        (
            "$.state_capture.collector.version",
            manifest["state_capture"]["collector"]["version"],
        ),
        (
            "$.governance.registry_design.version",
            manifest["governance"]["registry_design"]["version"],
        ),
    ]
    values.extend(
        (f"$.reference_agent_stack.tools[{index}].version", tool["version"])
        for index, tool in enumerate(stack["tools"])
    )
    backend_contract = stack["model"]["backend_identity_contract"]
    if (
        backend_contract["mode"] == "provider_attested_snapshot"
        and isinstance(backend_contract["attestation_contract"], Mapping)
        and isinstance(backend_contract["attestation_contract"].get("version"), str)
    ):
        values.append(
            (
                "$.reference_agent_stack.model.backend_identity_contract."
                "attestation_contract.version",
                backend_contract["attestation_contract"]["version"],
            )
        )
    for arm_index, arm in enumerate(manifest["arms"]):
        code = arm["drupal_state"]["code"]
        values.extend(
            [
                (f"$.arms[{arm_index}].drupal_state.code.core.version", code["core"]["version"]),
                (
                    f"$.arms[{arm_index}].drupal_state.code.core.revision",
                    code["core"]["revision"],
                ),
            ]
        )
        for component_index, component in enumerate(code["components"]):
            values.extend(
                [
                    (
                        f"$.arms[{arm_index}].drupal_state.code.components[{component_index}].version",
                        component["version"],
                    ),
                    (
                        f"$.arms[{arm_index}].drupal_state.code.components[{component_index}].revision",
                        component["revision"],
                    ),
                ]
            )
    _reject_mutable_labels(values, issues)


def _check_run_pin_labels(run: Mapping[str, Any], issues: list[ValidationIssue]) -> None:
    stack = run["agent_stack"]
    values: list[tuple[str, str]] = [
        ("$.task.version", run["task"]["version"]),
        ("$.agent_stack.agent.version", stack["agent"]["version"]),
        ("$.agent_stack.model.snapshot", stack["model"]["snapshot"]),
        ("$.agent_stack.harness.version", stack["harness"]["version"]),
        ("$.evaluation.evaluator.version", run["evaluation"]["evaluator"]["version"]),
        ("$.evaluation.rubric.version", run["evaluation"]["rubric"]["version"]),
        ("$.evaluation.scoring.version", run["evaluation"]["scoring"]["version"]),
        (
            "$.evaluation.assurance.trusted_issuer.version",
            run["evaluation"]["assurance"]["trusted_issuer"]["version"],
        ),
        (
            "$.governance.registry_design.version",
            run["governance"]["registry_design"]["version"],
        ),
    ]
    values.extend(
        (f"$.agent_stack.tools[{index}].version", tool["version"])
        for index, tool in enumerate(stack["tools"])
    )
    backend_contract = stack["model"]["backend_identity_contract"]
    if (
        backend_contract["mode"] == "provider_attested_snapshot"
        and isinstance(backend_contract["attestation_contract"], Mapping)
        and isinstance(backend_contract["attestation_contract"].get("version"), str)
    ):
        values.append(
            (
                "$.agent_stack.model.backend_identity_contract."
                "attestation_contract.version",
                backend_contract["attestation_contract"]["version"],
            )
        )
    code = run["arm"]["drupal_state"]["code"]
    values.extend(
        [
            ("$.arm.drupal_state.code.core.version", code["core"]["version"]),
            ("$.arm.drupal_state.code.core.revision", code["core"]["revision"]),
        ]
    )
    for index, component in enumerate(code["components"]):
        values.extend(
            [
                (f"$.arm.drupal_state.code.components[{index}].version", component["version"]),
                (f"$.arm.drupal_state.code.components[{index}].revision", component["revision"]),
            ]
        )
    _reject_mutable_labels(values, issues)


def _reject_mutable_labels(
    values: Iterable[tuple[str, str]], issues: list[ValidationIssue]
) -> None:
    for path, value in values:
        if _MUTABLE_LABEL.search(value):
            issues.append(
                _error(
                    "mutable_pin_label",
                    path,
                    f"'{value}' is a moving label, not an immutable version or snapshot.",
                )
            )


def _check_run_timestamps(
    run: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    timestamps = run["timestamps"]
    names = [
        "started_at",
        "completed_at",
        "evaluation_started_at",
        "evaluation_completed_at",
        "recorded_at",
    ]
    values = [_datetime(timestamps[name]) for name in names]
    if any(left > right for left, right in zip(values, values[1:])):
        issues.append(
            _error(
                "nonmonotonic_run_timestamps",
                "$.timestamps",
                "Run, evaluation, and recording timestamps must be monotonically ordered.",
            )
        )


def _check_run_artifacts_and_references(
    run: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    artifacts = run["artifacts"]
    _check_unique_ids(artifacts, "artifact_id", "$.artifacts", "duplicate_artifact_id", issues)
    artifact_by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    kinds = {artifact["kind"] for artifact in artifacts}
    missing_kinds = sorted(_REQUIRED_ARTIFACT_KINDS - kinds)
    if missing_kinds:
        issues.append(
            _error(
                "missing_evidence_artifact",
                "$.artifacts",
                f"Every run must retain these evidence kinds: {missing_kinds!r}.",
            )
        )
    for kind in sorted(_REQUIRED_ARTIFACT_KINDS):
        count = sum(artifact["kind"] == kind for artifact in artifacts)
        if count > 1:
            issues.append(
                _error(
                    "duplicate_required_artifact_kind",
                    "$.artifacts",
                    f"Required evidence kind '{kind}' must resolve to exactly one artifact.",
                )
            )
    identity_kinds: dict[str, set[str]] = {}
    for artifact in artifacts:
        if artifact["kind"] in _REQUIRED_ARTIFACT_KINDS:
            identity = artifact["sha256"]
            identity_kinds.setdefault(identity, set()).add(artifact["kind"])
    for identity, identity_kind_set in identity_kinds.items():
        if len(identity_kind_set) > 1:
            issues.append(
                _error(
                    "artifact_kind_aliasing",
                    "$.artifacts",
                    f"One byte identity {identity!r} cannot satisfy incompatible evidence kinds "
                    f"{sorted(identity_kind_set)!r}.",
                )
            )
    for index, artifact in enumerate(artifacts):
        if artifact["byte_size"] == 0 and artifact["kind"] != "attempt_stderr":
            issues.append(
                _error(
                    "schema_minimum",
                    f"$.artifacts[{index}].byte_size",
                    "Only a successful attempt's retained raw stderr may be empty.",
                )
            )
        if not _safe_relative_uri(artifact["uri"]):
            issues.append(
                _error(
                    "unsafe_artifact_uri",
                    f"$.artifacts[{index}].uri",
                    "Artifact URIs must be relative and cannot traverse outside the evidence root.",
                )
            )

    _require_artifact_kind(
        run["costs"]["measurement_artifact_id"],
        {"cost_trace"},
        "$.costs.measurement_artifact_id",
        artifact_by_id,
        issues,
    )
    _require_artifact_kind(
        run["outcomes"]["evaluator_artifact_id"],
        {"evaluator_output"},
        "$.outcomes.evaluator_artifact_id",
        artifact_by_id,
        issues,
    )
    for artifact_id, allowed_kinds, path in (
        (
            run["prompt_delivery"]["render_inputs_artifact_id"],
            {"render_inputs"},
            "$.prompt_delivery.render_inputs_artifact_id",
        ),
        (
            run["prompt_delivery"]["rendered_prompt_artifact_id"],
            {"prompt"},
            "$.prompt_delivery.rendered_prompt_artifact_id",
        ),
        (
            run["prompt_delivery"]["receipt_artifact_id"],
            {"prompt_receipt"},
            "$.prompt_delivery.receipt_artifact_id",
        ),
        (
            run["execution_receipt"]["receipt_artifact_id"],
            {"execution_receipt"},
            "$.execution_receipt.receipt_artifact_id",
        ),
        (
            run["evaluator_receipt"]["receipt_artifact_id"],
            {"evaluator_receipt"},
            "$.evaluator_receipt.receipt_artifact_id",
        ),
    ):
        _require_artifact_kind(artifact_id, allowed_kinds, path, artifact_by_id, issues)
    for index, metric in enumerate(run["outcomes"]["metrics"]):
        _require_artifact_kind(
            metric["source_artifact_id"],
            {"evaluator_output", "final_state", "tool_log"},
            f"$.outcomes.metrics[{index}].source_artifact_id",
            artifact_by_id,
            issues,
        )
    for index, event in enumerate(run["behavior_events"]):
        _require_artifact_kind(
            event["source_artifact_id"],
            _EVENT_SOURCE_ARTIFACT_KINDS.get(event["source"], set()),
            f"$.behavior_events[{index}].source_artifact_id",
            artifact_by_id,
            issues,
        )
    basis_id = run["validity"]["decision_basis_artifact_id"]
    if not basis_id:
        issues.append(
            _error(
                "missing_validity_evidence",
                "$.validity.decision_basis_artifact_id",
                "Inclusion and exclusion decisions both require retained gate evidence.",
            )
        )
    else:
        _require_artifact_kind(
            basis_id,
            {"validity_decision"},
            "$.validity.decision_basis_artifact_id",
            artifact_by_id,
            issues,
        )


def _run_artifacts_by_kind(run: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {artifact["kind"]: artifact for artifact in run["artifacts"]}


def _check_prompt_delivery(
    run: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    delivery = run["prompt_delivery"]
    artifacts = _run_artifacts_by_kind(run)
    expected_fields = {
        "task_id": run["task"]["id"],
        "task_version": run["task"]["version"],
        "task_prompt_sha256": run["task"]["prompt"]["sha256"],
        "system_prompt_sha256": run["agent_stack"]["system_prompt"]["sha256"],
    }
    for field, expected in expected_fields.items():
        if delivery[field] != expected:
            issues.append(
                _error(
                    "prompt_delivery_binding_mismatch",
                    f"$.prompt_delivery.{field}",
                    f"Delivered-prompt receipt does not bind the run's registered {field}.",
                )
            )
    recipient = delivery["recipient"]
    expected_recipient = {
        "agent_id": run["agent_stack"]["agent"]["id"],
        "model_provider": run["agent_stack"]["model"]["provider"],
        "model_id": run["agent_stack"]["model"]["id"],
        "model_snapshot": run["agent_stack"]["model"]["snapshot"],
    }
    if recipient != expected_recipient:
        issues.append(
            _error(
                "prompt_recipient_mismatch",
                "$.prompt_delivery.recipient",
                "Prompt receipt recipient is not the registered agent/model snapshot.",
            )
        )
    for field, kind in (
        ("render_inputs_sha256", "render_inputs"),
        ("rendered_prompt_sha256", "prompt"),
    ):
        artifact = artifacts.get(kind)
        if artifact is not None and delivery[field] != artifact["sha256"]:
            issues.append(
                _error(
                    "prompt_delivery_artifact_hash_mismatch",
                    f"$.prompt_delivery.{field}",
                    f"Prompt receipt does not bind the retained {kind} bytes.",
                )
            )
    if _datetime(delivery["delivered_at"]) != _datetime(run["timestamps"]["started_at"]):
        issues.append(
            _error(
                "prompt_delivery_time_mismatch",
                "$.prompt_delivery.delivered_at",
                "Delivered prompt must be receipted at the registered execution start.",
            )
        )


def _check_execution_receipt(
    run: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    receipt = run["execution_receipt"]
    artifacts = _run_artifacts_by_kind(run)
    if receipt["roster_slot_id"] != run["attempt"]["roster_slot_id"]:
        issues.append(_error("execution_receipt_slot_mismatch", "$.execution_receipt.roster_slot_id", "Execution receipt does not bind the registered roster slot."))
    if receipt["harness_sha256"] != run["agent_stack"]["harness"]["artifact"]["sha256"]:
        issues.append(_error("execution_receipt_harness_mismatch", "$.execution_receipt.harness_sha256", "Execution receipt does not bind the registered harness bytes."))
    if (
        receipt["started_at"] != run["timestamps"]["started_at"]
        or receipt["completed_at"] != run["timestamps"]["completed_at"]
    ):
        issues.append(_error("execution_receipt_time_mismatch", "$.execution_receipt", "Execution receipt times must equal the run boundary."))
    prompt_receipt = artifacts.get("prompt_receipt")
    if prompt_receipt is not None and receipt["prompt_receipt_sha256"] != prompt_receipt["sha256"]:
        issues.append(_error("execution_prompt_receipt_mismatch", "$.execution_receipt.prompt_receipt_sha256", "Execution receipt does not bind the prompt-delivery receipt."))
    for kind, expected_hash in receipt["artifact_hashes"].items():
        artifact = artifacts.get(kind)
        if artifact is not None and expected_hash != artifact["sha256"]:
            issues.append(_error("execution_artifact_hash_mismatch", f"$.execution_receipt.artifact_hashes.{kind}", f"Execution receipt does not bind retained {kind} bytes."))


def _check_state_capture_receipts(
    run: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    capture = run["state_capture"]
    if capture["starting"]["invocation_id"] == capture["final"]["invocation_id"]:
        issues.append(_error("state_capture_invocation_alias", "$.state_capture", "Starting and final state captures require distinct collector invocations."))
    if capture["starting"]["captured_at"] != run["timestamps"]["started_at"]:
        issues.append(_error("starting_state_capture_time_mismatch", "$.state_capture.starting.captured_at", "Starting state must be captured at the execution boundary."))
    if capture["final"]["captured_at"] != run["timestamps"]["completed_at"]:
        issues.append(_error("final_state_capture_time_mismatch", "$.state_capture.final.captured_at", "Final state must be captured at the execution boundary."))


def _check_evaluator_receipt(
    run: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    receipt = run["evaluator_receipt"]
    artifacts = _run_artifacts_by_kind(run)
    assurance = run["evaluation"]["assurance"]
    issuer = assurance["trusted_issuer"]
    expected_issuer = (
        issuer["id"],
        issuer["version"],
        issuer["artifact"]["sha256"],
    )
    observed_issuer = (
        receipt["issuer_id"],
        receipt["issuer_version"],
        receipt["issuer_sha256"],
    )
    if observed_issuer != expected_issuer:
        issues.append(_error("untrusted_evaluator_receipt_issuer", "$.evaluator_receipt", "Evaluator receipt issuer does not match the preregistered trust anchor."))
    if receipt["evaluator_sha256"] != run["evaluation"]["evaluator"]["artifact"]["sha256"]:
        issues.append(_error("evaluator_receipt_implementation_mismatch", "$.evaluator_receipt.evaluator_sha256", "Evaluator receipt does not bind the registered evaluator implementation."))
    expected_inputs = {
        "answer": artifacts.get("answer", {}).get("sha256"),
        "ground_truth": run["task"]["ground_truth"]["sha256"],
        "final_state": artifacts.get("final_state", {}).get("sha256"),
        "tool_log": artifacts.get("tool_log", {}).get("sha256"),
    }
    if receipt["input_hashes"] != expected_inputs:
        issues.append(_error("evaluator_input_binding_mismatch", "$.evaluator_receipt.input_hashes", "Evaluator receipt does not bind answer, ground truth, final state, and tool log."))
    output = artifacts.get("evaluator_output")
    if output is not None and (
        receipt["output_artifact_id"] != output["artifact_id"]
        or receipt["output_sha256"] != output["sha256"]
    ):
        issues.append(_error("evaluator_output_binding_mismatch", "$.evaluator_receipt", "Evaluator receipt does not bind the retained evaluator output."))
    if (
        receipt["started_at"] != run["timestamps"]["evaluation_started_at"]
        or receipt["completed_at"] != run["timestamps"]["evaluation_completed_at"]
    ):
        issues.append(_error("evaluator_receipt_time_mismatch", "$.evaluator_receipt", "Evaluator invocation receipt times must equal the evaluation boundary."))


def _require_artifact_kind(
    artifact_id: str,
    allowed_kinds: set[str],
    path: str,
    artifact_by_id: Mapping[str, Mapping[str, Any]],
    issues: list[ValidationIssue],
) -> None:
    artifact = artifact_by_id.get(artifact_id)
    if artifact is None:
        issues.append(
            _error(
                "unknown_artifact_reference",
                path,
                f"Artifact '{artifact_id}' is not declared in this run.",
            )
        )
    elif artifact["kind"] not in allowed_kinds:
        issues.append(
            _error(
                "wrong_artifact_kind",
                path,
                f"Artifact '{artifact_id}' has kind '{artifact['kind']}', expected one of "
                f"{sorted(allowed_kinds)!r}.",
            )
        )


def _check_costs_and_budget(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any] | None,
    issues: list[ValidationIssue],
) -> None:
    costs = run["costs"]
    if costs["cached_input_tokens"] > costs["input_tokens"]:
        issues.append(
            _error(
                "cached_tokens_exceed_input",
                "$.costs.cached_input_tokens",
                "Cached input tokens are a subset of total input tokens.",
            )
        )
    reasoning_tokens = costs.get("reasoning_output_tokens")
    if (
        reasoning_tokens is not None
        and reasoning_tokens > costs["output_tokens"]
    ):
        issues.append(
            _error(
                "reasoning_tokens_exceed_output",
                "$.costs.reasoning_output_tokens",
                "Reasoning output tokens are a subset of total output tokens.",
            )
        )
    if costs["source"] not in _TRUSTED_COST_SOURCES:
        issues.append(
            _error(
                "self_reported_costs",
                "$.costs.source",
                "Cost and effort metrics must come from instrumentation, provider usage, or an observer.",
            )
        )
    status = costs["cost_status"]
    cost_value = costs["cost_microusd"]
    schedule_hash = costs["price_schedule_sha256"]
    if status == "unavailable":
        if cost_value is not None or schedule_hash is not None:
            issues.append(
                _error(
                    "unavailable_cost_has_value",
                    "$.costs",
                    "Unavailable price must use null cost_microusd and null price_schedule_sha256.",
                )
            )
    elif cost_value is None:
        issues.append(
            _error(
                "available_cost_missing_value",
                "$.costs.cost_microusd",
                "Actual or derived cost status requires a numeric cost_microusd.",
            )
        )
    if status == "derived_from_usage" and schedule_hash is None:
        issues.append(
            _error(
                "derived_cost_missing_price_schedule",
                "$.costs.price_schedule_sha256",
                "Derived cost requires the registered price-schedule hash.",
            )
        )
    if status == "actual_provider_cost" and schedule_hash is not None:
        issues.append(
            _error(
                "actual_cost_has_price_schedule",
                "$.costs.price_schedule_sha256",
                "Provider-reported actual cost must not masquerade as a derived price.",
            )
        )
    if status == "actual_provider_cost" and costs["source"] != "provider_usage_api":
        issues.append(
            _error(
                "actual_cost_without_provider_source",
                "$.costs.source",
                "Actual provider cost requires provider_usage_api provenance.",
            )
        )
    if manifest is not None:
        plan = manifest["cost_measurement"]
        if status != plan["mode"]:
            issues.append(
                _error(
                    "cost_measurement_mode_mismatch",
                    "$.costs.cost_status",
                    "Run cost provenance differs from the preregistered cost-measurement mode.",
                )
            )
        expected_schedule_hash = (
            plan["price_schedule"]["sha256"]
            if plan["price_schedule"] is not None
            else None
        )
        if schedule_hash != expected_schedule_hash:
            issues.append(
                _error(
                    "cost_price_schedule_mismatch",
                    "$.costs.price_schedule_sha256",
                    "Run cost does not bind the preregistered price schedule.",
                )
            )
    budget = run["budget"]
    exceeded = [
        name
        for name in (
            "wall_time_ms",
            "input_tokens",
            "output_tokens",
            "tool_calls",
            "human_interventions",
            "cost_microusd",
        )
        if costs[name] is not None and costs[name] > budget[name]
    ]
    if exceeded and run["validity"]["status"] == "included":
        issues.append(
            _error(
                "included_run_exceeds_budget",
                "$.costs",
                f"An over-budget run cannot remain included: {exceeded!r}.",
            )
        )


def _check_behavior_events(
    run: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    events = run["behavior_events"]
    sequences = [event["sequence"] for event in events]
    if sequences != list(range(1, len(events) + 1)):
        issues.append(
            _error(
                "noncanonical_behavior_sequence",
                "$.behavior_events",
                "Behavior sequence numbers must be contiguous and stored in execution order.",
            )
        )

    declared_phases = run["task"]["lifecycle_stages"]
    phases = [event["phase"] for event in events]
    undeclared = sorted(set(phases) - set(declared_phases))
    if undeclared:
        issues.append(
            _error(
                "undeclared_behavior_phase",
                "$.behavior_events",
                f"Trace contains phases not declared by the task: {undeclared!r}.",
            )
        )
    for required in declared_phases:
        if required not in phases:
            issues.append(
                _error(
                    "missing_behavior_phase",
                    "$.behavior_events",
                    f"The instrumented trace has no task-declared '{required}' phase.",
                )
            )
    declared_position = {phase: index for index, phase in enumerate(declared_phases)}
    observed_positions = [
        declared_position[phase] for phase in phases if phase in declared_position
    ]
    if observed_positions != sorted(observed_positions):
        issues.append(
            _error(
                "invalid_behavior_phase_order",
                "$.behavior_events",
                "Behavior phases must follow the task-declared lifecycle order.",
            )
        )

    previous_end: datetime | None = None
    run_started = _datetime(run["timestamps"]["started_at"])
    run_completed = _datetime(run["timestamps"]["completed_at"])
    for index, event in enumerate(events):
        started = _datetime(event["started_at"])
        ended = _datetime(event["ended_at"])
        if event["source"] not in _TRUSTED_EVENT_SOURCES:
            issues.append(
                _error(
                    "self_reported_behavior",
                    f"$.behavior_events[{index}].source",
                    "Behavior must be reconstructed from a trace, tool log, or observer.",
                )
            )
        if started > ended or started < run_started or ended > run_completed:
            issues.append(
                _error(
                    "behavior_event_outside_run",
                    f"$.behavior_events[{index}]",
                    "Behavior event times must be ordered and contained within the agent run.",
                )
            )
        if previous_end is not None and started < previous_end:
            issues.append(
                _error(
                    "overlapping_behavior_events",
                    f"$.behavior_events[{index}]",
                    "Behavior events must be chronological and non-overlapping.",
                )
            )
        previous_end = ended
        result = event["result"]
        failure_code = event["failure_code"]
        if result == "success" and failure_code is not None:
            issues.append(
                _error(
                    "success_has_failure_code",
                    f"$.behavior_events[{index}].failure_code",
                    "Successful behavior events cannot carry failure codes.",
                )
            )
        if result in {"failure", "skipped"} and not failure_code:
            issues.append(
                _error(
                    "missing_behavior_failure_code",
                    f"$.behavior_events[{index}].failure_code",
                    "Failed and skipped events require a stable failure code.",
                )
            )

    expected_summary = _derive_behavior_summary(events)
    if run["behavior_summary"] != expected_summary:
        issues.append(
            _error(
                "behavior_summary_mismatch",
                "$.behavior_summary",
                f"Behavior summary must be derived from events; expected {expected_summary!r}.",
            )
        )


def _derive_behavior_summary(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    phases_observed = _ordered_unique(event["phase"] for event in events)
    successful_phases = _ordered_unique(
        event["phase"] for event in events if event["result"] == "success"
    )
    failed_phases = _ordered_unique(
        event["phase"] for event in events if event["result"] == "failure"
    )
    skipped_phases = _ordered_unique(
        event["phase"] for event in events if event["result"] == "skipped"
    )
    recovery_events = [
        event
        for event in events
        if event["phase"] == "recover" and event["result"] != "skipped"
    ]
    recovery_attempted = bool(recovery_events)
    recovery_succeeded = (
        any(event["result"] == "success" for event in recovery_events)
        if recovery_attempted
        else None
    )
    return {
        "event_count": len(events),
        "phases_observed": phases_observed,
        "successful_phases": successful_phases,
        "failed_phases": failed_phases,
        "skipped_phases": skipped_phases,
        "failure_count": sum(event["result"] == "failure" for event in events),
        "recovery_attempted": recovery_attempted,
        "recovery_succeeded": recovery_succeeded,
    }


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _check_outcome_metrics(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any] | None,
    issues: list[ValidationIssue],
) -> None:
    metrics = run["outcomes"]["metrics"]
    _check_unique_ids(metrics, "metric_id", "$.outcomes.metrics", "duplicate_metric_result", issues)
    for index, metric in enumerate(metrics):
        values = (metric["numerator"], metric["denominator"], metric["value"])
        if not all(math.isfinite(value) for value in values):
            issues.append(
                _error(
                    "nonfinite_metric",
                    f"$.outcomes.metrics[{index}]",
                    "Metric numerators, denominators, and values must be finite.",
                )
            )
            continue
        expected_value = metric["numerator"] / metric["denominator"]
        if not math.isclose(metric["value"], expected_value, rel_tol=1e-12, abs_tol=1e-12):
            issues.append(
                _error(
                    "metric_ratio_mismatch",
                    f"$.outcomes.metrics[{index}].value",
                    "Metric value must equal numerator divided by denominator.",
                )
            )

    evaluator_hash = run["evaluation"]["evaluator"]["artifact"]["sha256"]
    if run["outcomes"]["evaluated_by_sha256"] != evaluator_hash:
        issues.append(
            _error(
                "evaluator_hash_mismatch",
                "$.outcomes.evaluated_by_sha256",
                "Outcome provenance does not match the pinned evaluator implementation.",
            )
        )

    if manifest is None:
        return
    definitions = {metric["metric_id"]: metric for metric in manifest["outcome_metrics"]}
    result_ids = {metric["metric_id"] for metric in metrics}
    if result_ids != set(definitions):
        issues.append(
            _error(
                "outcome_metric_set_mismatch",
                "$.outcomes.metrics",
                "Every registered outcome metric must be reported exactly once; "
                f"registered={sorted(definitions)!r}, reported={sorted(result_ids)!r}.",
            )
        )
    for index, metric in enumerate(metrics):
        definition = definitions.get(metric["metric_id"])
        if definition is None:
            continue
        if metric["unit"] != definition["unit"]:
            issues.append(
                _error(
                    "metric_unit_mismatch",
                    f"$.outcomes.metrics[{index}].unit",
                    "Metric units cannot change between registration and result capture.",
                )
            )
        if definition["kind"] in {"binary", "rate"} and not 0 <= metric["value"] <= 1:
            issues.append(
                _error(
                    "bounded_metric_out_of_range",
                    f"$.outcomes.metrics[{index}].value",
                    "Binary and rate metrics must remain between zero and one.",
                )
            )
        if definition["kind"] == "binary" and metric["value"] not in {0, 1}:
            issues.append(
                _error(
                    "nonbinary_metric_value",
                    f"$.outcomes.metrics[{index}].value",
                    "A binary metric must have value exactly zero or one.",
                )
            )
        if definition["kind"] == "binary" and (
            metric["numerator"] not in {0, 1} or metric["denominator"] != 1
        ):
            issues.append(
                _error(
                    "invalid_binary_metric_components",
                    f"$.outcomes.metrics[{index}]",
                    "Binary results require numerator 0 or 1 and denominator exactly 1.",
                )
            )
        if definition["kind"] == "rate" and not (
            0 <= metric["numerator"] <= metric["denominator"]
        ):
            issues.append(
                _error(
                    "invalid_rate_metric_components",
                    f"$.outcomes.metrics[{index}]",
                    "Rate results require 0 <= numerator <= denominator.",
                )
            )
        if definition["kind"] in {"count", "duration", "cost"} and (
            metric["numerator"] < 0 or metric["value"] < 0
        ):
            issues.append(
                _error(
                    "negative_nonnegative_metric",
                    f"$.outcomes.metrics[{index}]",
                    f"{definition['kind']} metrics cannot be negative.",
                )
            )

    if manifest is not None:
        verdict_metric_id = manifest["evaluation"]["verdict_metric_id"]
        verdict_metric = next(
            (metric for metric in metrics if metric["metric_id"] == verdict_metric_id),
            None,
        )
        if verdict_metric is not None:
            expected_passed = verdict_metric["value"] == 1
            if run["outcomes"]["evaluator_passed"] is not expected_passed:
                issues.append(
                    _error(
                        "evaluator_verdict_metric_mismatch",
                        "$.outcomes.evaluator_passed",
                        "Evaluator pass/fail must equal the registered binary verdict metric.",
                    )
                )
            if (
                verdict_metric["source_artifact_id"]
                != run["outcomes"]["evaluator_artifact_id"]
            ):
                issues.append(
                    _error(
                        "verdict_metric_wrong_source",
                        "$.outcomes.metrics",
                        "The registered verdict metric must be sourced from the evaluator output artifact.",
                    )
                )


def _check_validity(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any] | None,
    issues: list[ValidationIssue],
) -> None:
    validity = run["validity"]
    completed = _datetime(run["timestamps"]["completed_at"])
    evaluation_started = _datetime(run["timestamps"]["evaluation_started_at"])
    decided_at = _datetime(validity["decided_at"])
    if not completed <= decided_at <= evaluation_started:
        issues.append(
            _error(
                "post_hoc_validity_decision",
                "$.validity.decided_at",
                "Validity must be decided after execution but before outcome evaluation begins.",
            )
        )

    if validity["status"] == "included":
        if validity["exclusion_code"] is not None:
            issues.append(
                _error(
                    "included_run_has_exclusion_code",
                    "$.validity.exclusion_code",
                    "Included runs cannot carry an exclusion code.",
                )
            )
    else:
        code = validity["exclusion_code"]
        if not code:
            issues.append(
                _error(
                    "excluded_run_missing_code",
                    "$.validity.exclusion_code",
                    "Every excluded run needs a preregistered exclusion code.",
                )
            )
        elif manifest is not None:
            allowed = {item["code"] for item in manifest["exclusion_policy"]["codes"]}
            if code not in allowed:
                issues.append(
                    _error(
                        "post_hoc_exclusion_code",
                        "$.validity.exclusion_code",
                        f"Exclusion code '{code}' was not preregistered.",
                    )
                )


def _check_attempt(run: Mapping[str, Any], issues: list[ValidationIssue]) -> None:
    attempt = run["attempt"]
    if run["lane"] == "fixed_regression":
        if not attempt["pair_id"] or attempt["order_in_pair"] not in {1, 2}:
            issues.append(
                _error(
                    "missing_pair_identity",
                    "$.attempt",
                    "Every fixed-regression run must name its pair and order position.",
                )
            )
    elif attempt["pair_id"] is not None or attempt["order_in_pair"] is not None:
        issues.append(
            _error(
                "frontier_run_has_pair_identity",
                "$.attempt",
                "Unpaired frontier observations cannot carry pair identifiers.",
            )
        )


def _bind_run_to_manifest(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    expected_manifest_hash = canonical_sha256(manifest)
    comparisons = [
        (
            "experiment_id",
            run["experiment_id"],
            manifest["experiment_id"],
            "experiment_id_mismatch",
        ),
        ("governance", run["governance"], manifest["governance"], "governance_pin_mismatch"),
        ("lane", run["lane"], manifest["lane"], "mixed_measurement_lane"),
        ("task", run["task"], manifest["task"], "task_pin_mismatch"),
        ("substrate", run["substrate"], manifest["substrate"], "substrate_pin_mismatch"),
        ("evaluation", run["evaluation"], manifest["evaluation"], "evaluation_pin_mismatch"),
        ("budget", run["budget"], manifest["budget"], "budget_pin_mismatch"),
    ]
    for name, actual, expected, code in comparisons:
        if actual != expected:
            issues.append(
                _error(code, f"$.{name}", f"Run {name} does not equal its registered pin set.")
            )
    if run["experiment_manifest_sha256"] != expected_manifest_hash:
        issues.append(
            _error(
                "manifest_hash_mismatch",
                "$.experiment_manifest_sha256",
                "Run does not reference the canonical hash of the supplied manifest.",
            )
        )
    if manifest["lane"] == "fixed_regression" and run["agent_stack"] != manifest[
        "reference_agent_stack"
    ]:
        issues.append(
            _error(
                "fixed_agent_pin_mismatch",
                "$.agent_stack",
                "A fixed regression must use the exact registered agent/model/harness stack.",
            )
        )
    expected_renderer_hash = manifest["prompt_composition"]["renderer"]["artifact"][
        "sha256"
    ]
    if run["prompt_delivery"]["renderer_sha256"] != expected_renderer_hash:
        issues.append(
            _error(
                "prompt_renderer_mismatch",
                "$.prompt_delivery.renderer_sha256",
                "Delivered prompt does not bind the registered renderer.",
            )
        )
    if (
        run["prompt_delivery"]["render_inputs_sha256"]
        != manifest["prompt_composition"]["render_inputs"]["sha256"]
    ):
        issues.append(
            _error(
                "prompt_render_inputs_mismatch",
                "$.prompt_delivery.render_inputs_sha256",
                "Delivered prompt uses render inputs outside the preregistered visible envelope.",
            )
        )
    if (
        run["state_capture"]["collector_sha256"]
        != manifest["state_capture"]["collector"]["artifact"]["sha256"]
    ):
        issues.append(
            _error(
                "state_collector_mismatch",
                "$.state_capture.collector_sha256",
                "State receipts do not bind the registered collector implementation.",
            )
        )

    arms = {arm["arm_id"]: arm for arm in manifest["arms"]}
    registered_arm = arms.get(run["arm"]["arm_id"])
    if registered_arm is None:
        issues.append(
            _error(
                "unknown_arm",
                "$.arm.arm_id",
                "Run arm is not present in the preregistered manifest.",
            )
        )
    else:
        expected_arm = {
            "arm_id": registered_arm["arm_id"],
            "role": registered_arm["role"],
            "treatment_sha256": registered_arm["treatment"]["artifact"]["sha256"],
            "drupal_state": registered_arm["drupal_state"],
        }
        if run["arm"] != expected_arm:
            issues.append(
                _error(
                    "arm_pin_mismatch",
                    "$.arm",
                    "Run treatment and Drupal state must exactly match its registered arm.",
                )
            )

    roster_slots = {
        slot["slot_id"]: (entry, slot)
        for entry in manifest["execution_plan"]["attempt_roster"]
        for slot in entry["executions"]
    }
    roster_match = roster_slots.get(run["attempt"]["roster_slot_id"])
    if roster_match is None:
        issues.append(
            _error(
                "unregistered_roster_slot",
                "$.attempt.roster_slot_id",
                "Replacement or post-hoc execution slots are not permitted by the fixed census.",
            )
        )
    else:
        roster_entry, roster_slot = roster_match
        expected_attempt = {
            "roster_slot_id": roster_slot["slot_id"],
            "index": roster_entry["index"],
            "unit_id": roster_entry["unit_id"],
            "pair_id": roster_entry["pair_id"],
            "order_in_pair": roster_slot["order"]
            if manifest["lane"] == "fixed_regression"
            else None,
        }
        if run["attempt"] != expected_attempt or run["arm"]["arm_id"] != roster_slot["arm_id"]:
            issues.append(
                _error(
                    "roster_slot_mismatch",
                    "$.attempt",
                    "Run attempt, arm, unit, pair, and order must exactly match its registered slot.",
                )
            )

    expected_claim_context = {
        "claim_class": manifest["claim_plan"]["claim_class"],
        "primary_metric_id": manifest["claim_plan"]["primary_metric_id"],
        "estimand": manifest["claim_plan"]["estimand"],
        "planned_denominator": manifest["claim_plan"]["planned_denominator"],
        "denominator_unit": manifest["claim_plan"]["denominator_unit"],
        "confidence": manifest["claim_plan"]["confidence"],
        "minimum_favorable_effect": manifest["claim_plan"]["minimum_favorable_effect"],
        "decision_rule": manifest["claim_plan"]["decision_rule"],
        "inference_scope": manifest["inference_scope"],
        "sampling_design": manifest["sampling_design"],
        "guardrails": manifest["claim_plan"]["guardrails"],
    }
    if run["claim_context"] != expected_claim_context:
        issues.append(
            _error(
                "claim_context_mismatch",
                "$.claim_context",
                "Run-level claim metadata must repeat the registered claim plan exactly.",
            )
        )
    if _datetime(run["timestamps"]["started_at"]) < _datetime(manifest["registered_at"]):
        issues.append(
            _error(
                "run_predates_registration",
                "$.timestamps.started_at",
                "A preregistered measurement run cannot begin before registration.",
            )
        )


def _check_collection(
    manifest: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    issues: list[ValidationIssue],
) -> None:
    run_ids = [run.get("run_id") for run in runs]
    if len(run_ids) != len(set(run_ids)):
        issues.append(
            _error("duplicate_run_id", "$.runs", "Run IDs must be unique within an experiment.")
        )
    lanes = {run.get("lane") for run in runs}
    if len(lanes) > 1 or (lanes and lanes != {manifest["lane"]}):
        issues.append(
            _error(
                "mixed_measurement_lanes",
                "$.runs",
                "Fixed regressions and frontier observations cannot share an analysis set.",
            )
        )

    identity_sets = {
        "prompt_delivery_invocation": [
            run["prompt_delivery"]["invocation_id"] for run in runs
        ],
        "execution_invocation": [
            run["execution_receipt"]["invocation_id"] for run in runs
        ],
        "provider_request": [
            run["execution_receipt"]["provider_request_id"]
            for run in runs
            if run["execution_receipt"].get("provider_request_id_status")
            == "verified_distinct"
        ],
        "codex_thread": [run["execution_receipt"]["thread_id"] for run in runs],
        "evaluator_invocation": [
            run["evaluator_receipt"]["invocation_id"] for run in runs
        ],
        "state_capture_invocation": [
            invocation["invocation_id"]
            for run in runs
            for invocation in (
                run["state_capture"]["starting"],
                run["state_capture"]["final"],
            )
        ],
    }
    for identity_kind, values in identity_sets.items():
        duplicates = sorted(
            value for value in set(values) if values.count(value) > 1
        )
        if duplicates:
            issues.append(
                _error(
                    "duplicate_execution_identity",
                    "$.runs",
                    f"{identity_kind} identities must be unique; duplicates={duplicates!r}.",
                )
            )
    for kind in ("prompt_receipt", "execution_receipt", "evaluator_receipt"):
        hashes = [
            _run_artifacts_by_kind(run)[kind]["sha256"]
            for run in runs
        ]
        if len(hashes) != len(set(hashes)):
            issues.append(
                _error(
                    "duplicate_receipt_bytes",
                    "$.runs",
                    f"Distinct executions cannot reuse identical {kind} bytes.",
                )
            )
    for kind in ("transcript", "tool_log"):
        hashes = [
            _run_artifacts_by_kind(run)[kind]["sha256"]
            for run in runs
        ]
        if len(hashes) != len(set(hashes)):
            issues.append(
                _error(
                    "cross_run_execution_trace_reuse",
                    "$.runs",
                    f"Distinct execution receipts cannot reuse identical {kind} bytes.",
                )
            )

    if manifest["lane"] == "fixed_regression":
        _check_fixed_pairs(manifest, runs, issues)
    census = _census_summary(manifest, runs)
    if census["duplicate_slots"]:
        issues.append(
            _error(
                "duplicate_roster_execution",
                "$.runs",
                f"Roster slots were executed more than once, including excluded runs: "
                f"{census['duplicate_slots']!r}.",
            )
        )
    if census["missing_slots"]:
        issues.append(
            _warning(
                "incomplete_attempt_census",
                "$.runs",
                f"Fixed-census audit is missing registered slots: {census['missing_slots']!r}.",
            )
        )
    if census["excluded_slots"]:
        issues.append(
            _warning(
                "registered_exclusion_blocks_claim",
                "$.runs",
                "The preregistered stopping rule is on_exclusion=no_claim; excluded slots "
                f"{census['excluded_slots']!r} keep the estimate non-reportable.",
            )
        )

    denominator = _denominator_summary(manifest, runs)
    if denominator["status"] == "incomplete":
        issues.append(
            _warning(
                "denominator_incomplete",
                "$.runs",
                f"Observed {denominator['observed']} of {denominator['planned']} planned "
                f"{denominator['unit']} units; no planned claim is ready.",
            )
        )
    elif denominator["status"] == "overrun":
        issues.append(
            _error(
                "denominator_overrun",
                "$.runs",
                f"Observed {denominator['observed']} units after preregistering "
                f"{denominator['planned']}; optional continuation invalidates the planned analysis.",
            )
        )


def _check_fixed_pairs(
    manifest: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    issues: list[ValidationIssue],
) -> None:
    pairs: dict[str, list[Mapping[str, Any]]] = {}
    for run in runs:
        if run.get("lane") != "fixed_regression" or "attempt" not in run:
            continue
        pair_id = run["attempt"].get("pair_id")
        if pair_id:
            pairs.setdefault(pair_id, []).append(run)

    pre_first = 0
    post_first = 0
    seen_attempt_indexes: set[int] = set()
    seen_unit_ids: set[str] = set()
    for pair_id, pair_runs in sorted(pairs.items()):
        included = [run for run in pair_runs if run["validity"]["status"] == "included"]
        if len(included) == 1:
            issues.append(
                _error(
                    "unpaired_inclusion",
                    f"$.pairs.{pair_id}",
                    "A pair cannot contribute one included arm after its partner is excluded.",
                )
            )
        elif len(included) > 2:
            issues.append(
                _error(
                    "duplicate_pair_arm",
                    f"$.pairs.{pair_id}",
                    "A pair can contain only one included pre and one included post run.",
                )
            )
        if len(included) != 2:
            continue

        roles = {run["arm"]["role"] for run in included}
        if roles != {"pre", "post"}:
            issues.append(
                _error(
                    "incomparable_pair_roles",
                    f"$.pairs.{pair_id}",
                    "A complete pair must contain exactly one pre and one post result.",
                )
            )
            continue

        identity_statuses = {
            run["model_identity_receipt"]["status"] for run in included
        }
        backend_identities = {
            run["model_identity_receipt"]["backend_identity"] for run in included
        }
        if len(identity_statuses) != 1:
            issues.append(
                _error(
                    "mixed_backend_identity_attestation",
                    f"$.pairs.{pair_id}.model_identity_receipt.status",
                    "Paired arms must use the same backend identity attestation class.",
                )
            )
        if len(backend_identities) != 1:
            issues.append(
                _error(
                    "paired_backend_identity_mismatch",
                    f"$.pairs.{pair_id}.model_identity_receipt.backend_identity",
                    "Paired arms must attest the same immutable backend identity.",
                )
            )

        indexes = {run["attempt"]["index"] for run in included}
        units = {run["attempt"]["unit_id"] for run in included}
        positions = {run["attempt"]["order_in_pair"] for run in included}
        if len(indexes) != 1 or len(units) != 1 or positions != {1, 2}:
            issues.append(
                _error(
                    "pair_identity_mismatch",
                    f"$.pairs.{pair_id}",
                    "Paired arms must share attempt index and unit, with distinct order positions.",
                )
            )
        else:
            index = next(iter(indexes))
            unit = next(iter(units))
            if index in seen_attempt_indexes:
                issues.append(
                    _error(
                        "duplicate_attempt_index",
                        f"$.pairs.{pair_id}",
                        "Each pair needs a unique preregistered attempt index.",
                    )
                )
            if unit in seen_unit_ids:
                issues.append(
                    _error(
                        "duplicate_pair_unit",
                        f"$.pairs.{pair_id}",
                        "The same experimental unit cannot be counted in multiple pairs.",
                    )
                )
            seen_attempt_indexes.add(index)
            seen_unit_ids.add(unit)

        _compare_pair_pins(pair_id, included, issues)
        ordered = {run["attempt"]["order_in_pair"]: run for run in included}
        if (
            1 in ordered
            and 2 in ordered
            and _datetime(ordered[1]["timestamps"]["completed_at"])
            > _datetime(ordered[2]["timestamps"]["started_at"])
        ):
            issues.append(
                _error(
                    "pair_execution_order_mismatch",
                    f"$.pairs.{pair_id}",
                    "The recorded timestamps contradict order_in_pair or show overlapping arms.",
                )
            )
        role_by_position = {
            run["attempt"]["order_in_pair"]: run["arm"]["role"] for run in included
        }
        if role_by_position.get(1) == "pre":
            pre_first += 1
        elif role_by_position.get(1) == "post":
            post_first += 1
        _check_pair_order_policy(manifest, pair_id, role_by_position, issues)

    if manifest["comparison"]["order_policy"] == "counterbalanced":
        complete_count = pre_first + post_first
        if complete_count > 1 and abs(pre_first - post_first) > 1:
            issues.append(
                _error(
                    "uncounterbalanced_execution_order",
                    "$.runs",
                    "Counterbalanced execution requires pre-first and post-first counts to differ by at most one.",
                )
            )


def _compare_pair_pins(
    pair_id: str,
    pair_runs: Sequence[Mapping[str, Any]],
    issues: list[ValidationIssue],
) -> None:
    left, right = pair_runs
    pin_fields = (
        "experiment_id",
        "experiment_manifest_sha256",
        "governance",
        "lane",
        "task",
        "agent_stack",
        "substrate",
        "evaluation",
        "budget",
        "claim_context",
    )
    mismatches = [field for field in pin_fields if left[field] != right[field]]
    if mismatches:
        issues.append(
            _error(
                "fixed_pair_pin_mismatch",
                f"$.pairs.{pair_id}",
                f"Fixed-lane pair differs outside its registered Drupal treatment: {mismatches!r}.",
            )
        )


def _check_pair_order_policy(
    manifest: Mapping[str, Any],
    pair_id: str,
    role_by_position: Mapping[int, str],
    issues: list[ValidationIssue],
) -> None:
    policy = manifest["comparison"]["order_policy"]
    if policy == "pre_then_post" and role_by_position != {1: "pre", 2: "post"}:
        issues.append(
            _error(
                "pair_order_policy_violation",
                f"$.pairs.{pair_id}",
                "This experiment preregistered pre-then-post execution.",
            )
        )
    if policy == "post_then_pre" and role_by_position != {1: "post", 2: "pre"}:
        issues.append(
            _error(
                "pair_order_policy_violation",
                f"$.pairs.{pair_id}",
                "This experiment preregistered post-then-pre execution.",
            )
        )


def _denominator_summary(
    manifest: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    planned = manifest["claim_plan"]["planned_denominator"]
    unit = manifest["claim_plan"]["denominator_unit"]
    if manifest["lane"] == "fixed_regression":
        pairs: dict[str, set[str]] = {}
        for run in runs:
            if run.get("validity", {}).get("status") != "included":
                continue
            pair_id = run.get("attempt", {}).get("pair_id")
            role = run.get("arm", {}).get("role")
            if pair_id and role:
                pairs.setdefault(pair_id, set()).add(role)
        observed = sum(roles == {"pre", "post"} for roles in pairs.values())
    else:
        observed = sum(
            run.get("validity", {}).get("status") == "included"
            and run.get("lane") == "frontier_observation"
            for run in runs
        )
    status = "complete" if observed == planned else "incomplete" if observed < planned else "overrun"
    return {"planned": planned, "observed": observed, "unit": unit, "status": status}


def _census_summary(
    manifest: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    expected = [
        slot["slot_id"]
        for entry in manifest["execution_plan"]["attempt_roster"]
        for slot in entry["executions"]
    ]
    by_slot: dict[str, list[Mapping[str, Any]]] = {}
    for run in runs:
        slot_id = run.get("attempt", {}).get("roster_slot_id")
        if slot_id:
            by_slot.setdefault(slot_id, []).append(run)
    missing = sorted(set(expected) - set(by_slot))
    unregistered = sorted(set(by_slot) - set(expected))
    duplicates = sorted(slot_id for slot_id, slot_runs in by_slot.items() if len(slot_runs) != 1)
    excluded = sorted(
        slot_id
        for slot_id, slot_runs in by_slot.items()
        if len(slot_runs) == 1 and slot_runs[0]["validity"]["status"] == "excluded"
    )
    resolved = sum(
        slot_id in by_slot and len(by_slot[slot_id]) == 1
        for slot_id in expected
    )
    return {
        "expected_slots": len(expected),
        "resolved_slots": resolved,
        "missing_slots": missing,
        "unregistered_slots": unregistered,
        "duplicate_slots": duplicates,
        "excluded_slots": excluded,
        "complete": not missing and not unregistered and not duplicates,
        "limitations": [
            "Census completeness is relative to supplied run records; independent append-only "
            "run custody is needed to prove that no executions were omitted."
        ],
    }


def _analyze_primary_metric(
    manifest: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    primary_id = manifest["claim_plan"]["primary_metric_id"]
    confidence = manifest["claim_plan"]["confidence"]
    definition = next(
        metric for metric in manifest["outcome_metrics"] if metric["metric_id"] == primary_id
    )
    included = [run for run in runs if run.get("validity", {}).get("status") == "included"]
    values: list[float] = []
    raw_pairs: list[dict[str, Any]] = []
    if manifest["lane"] == "fixed_regression":
        pairs: dict[str, dict[str, Mapping[str, Any]]] = {}
        for run in included:
            pair_id = run["attempt"]["pair_id"]
            if pair_id:
                pairs.setdefault(pair_id, {})[run["arm"]["role"]] = run
        for pair_id, pair in sorted(pairs.items()):
            if set(pair) != {"pre", "post"}:
                continue
            pre_value = _metric_value(pair["pre"], primary_id)
            post_value = _metric_value(pair["post"], primary_id)
            if pre_value is None or post_value is None:
                continue
            delta = post_value - pre_value
            values.append(delta)
            raw_pairs.append(
                {
                    "pair_id": pair_id,
                    "pre": pre_value,
                    "post": post_value,
                    "delta": delta,
                }
            )
        sample_unit = "complete_pair"
        estimate_name = "mean_post_minus_pre"
    else:
        for run in included:
            value = _metric_value(run, primary_id)
            if value is not None:
                values.append(value)
        sample_unit = "included_run"
        estimate_name = "mean"

    if not values:
        return None
    estimate = fmean(values)
    favorable_values = (
        values
        if definition["direction"] == "higher_is_better"
        else [-value for value in values]
    )
    favorable_estimate = fmean(favorable_values)
    inference_eligible = _inference_supports_effect_bound(manifest)
    interval: list[float] | None = None
    favorable_interval: list[float] | None = None
    favorable_lower_bound: float | None = None
    assumptions: list[str] = []
    limitations: list[str] = []
    if confidence["method"] == "paired_hoeffding_lower":
        assumptions.extend([
            "Each complete-pair favorable difference is bounded in [-1, 1].",
            "Registered sampling units are independent draws from the named target population.",
            "The one-sided Hoeffding bound is nonasymptotic and distribution-free under those assumptions.",
        ])
        if inference_eligible:
            favorable_lower_bound = _paired_hoeffding_lower_bound(
                favorable_values, confidence["level"]
            )
            favorable_interval = [favorable_lower_bound, 1.0]
            interval = (
                favorable_interval
                if definition["direction"] == "higher_is_better"
                else [-1.0, -favorable_lower_bound]
            )
        else:
            limitations.append(
                "No population effect bound is available because the registered inference "
                "scope or independence design is exact-roster-only, correlated, or unknown."
            )
    elif confidence["method"] == "bootstrap_percentile":
        interval = _bootstrap_interval(values, confidence)
        if interval is not None:
            favorable_interval = (
                interval
                if definition["direction"] == "higher_is_better"
                else [-interval[1], -interval[0]]
            )
        assumptions.append(
            "The descriptive percentile interval treats supplied observations as the resampling units."
        )
        limitations.append(
            "A descriptive bootstrap interval is not an effect-rule or Drupal-improvement decision."
        )
    else:
        limitations.append("The preregistered analysis does not request an uncertainty interval.")
    if (
        manifest["lane"] == "fixed_regression"
        and manifest["comparison"]["order_policy"] != "counterbalanced"
    ):
        limitations.append(
            "Arm order is not counterbalanced, so the paired estimate is confounded with "
            "order, carryover, and time and cannot satisfy the registered effect rule."
        )
    result: dict[str, Any] = {
        "primary_metric_id": primary_id,
        "estimand": manifest["claim_plan"]["estimand"],
        "sample_unit": sample_unit,
        "sample_size": len(values),
        "n": len(values),
        "estimate_name": estimate_name,
        "estimate": estimate,
        "favorable_direction_estimate": favorable_estimate,
        "confidence": {
            "method": confidence["method"],
            "level": confidence["level"],
            "interval": interval,
            "favorable_direction_interval": favorable_interval,
            "favorable_direction_lower_bound": favorable_lower_bound,
            "tail": confidence["tail"],
            "applicable": favorable_lower_bound is not None
            or confidence["method"] == "bootstrap_percentile",
        },
        "inference_scope": manifest["inference_scope"],
        "sampling_design": manifest["sampling_design"],
        "generalization_boundary_sha256": manifest["inference_scope"][
            "generalization_boundary"
        ]["sha256"],
        "assumptions": assumptions,
        "limitations": limitations,
    }
    if raw_pairs:
        result["pairs"] = raw_pairs
    return result


def _derive_effect_rule_decision(
    manifest: Mapping[str, Any],
    analysis: Mapping[str, Any] | None,
    guardrails: Mapping[str, Any],
    estimate_reportable: bool,
    backend_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    claim = manifest["claim_plan"]
    rule = claim["decision_rule"]
    minimum = claim["minimum_favorable_effect"]
    result: dict[str, Any] = {
        "rule": rule,
        "minimum_favorable_effect": minimum,
        "favorable_confidence_lower_bound": None,
        "guardrails_passed": guardrails["all_passed"],
        "registered_effect_rule_met": False,
        "reason": None,
    }
    if (
        manifest["lane"] == "fixed_regression"
        and backend_identity is not None
        and not backend_identity.get("claim_grade_eligible")
    ):
        result["reason"] = "backend_identity_not_claim_grade"
        return result
    if not estimate_reportable:
        result["reason"] = "estimate_not_reportable"
        return result
    if manifest["lane"] != "fixed_regression" or claim["claim_class"] != "comparative":
        result["reason"] = "noncomparative_analysis_cannot_meet_effect_rule"
        return result
    if rule != "confidence_lower_bound_at_least_minimum":
        result["reason"] = "registered_effect_rule_unavailable"
        return result
    if manifest["comparison"]["order_policy"] != "counterbalanced":
        result["reason"] = "paired_order_confounded_effect_rule"
        return result
    if not _inference_supports_effect_bound(manifest):
        result["reason"] = "inference_scope_not_eligible_for_effect_rule"
        return result
    lower_bound = (
        analysis["confidence"]["favorable_direction_lower_bound"]
        if analysis
        else None
    )
    if lower_bound is None:
        result["reason"] = "registered_effect_bound_unavailable"
        return result
    result["favorable_confidence_lower_bound"] = lower_bound
    if not guardrails["all_passed"]:
        result["reason"] = "registered_guardrail_failed"
        return result
    result["registered_effect_rule_met"] = lower_bound >= minimum
    result["reason"] = (
        "registered_minimum_met"
        if result["registered_effect_rule_met"]
        else "registered_minimum_not_met"
    )
    return result


def _inference_supports_effect_bound(manifest: Mapping[str, Any]) -> bool:
    return (
        manifest["inference_scope"]["kind"] == "target_population"
        and manifest["sampling_design"]["selection_method"]
        == "independent_random_sample"
        and manifest["sampling_design"]["independence_assumption"]
        == "independent_units"
    )


def _paired_hoeffding_lower_bound(
    favorable_values: Sequence[float], confidence_level: float
) -> float:
    alpha = 1.0 - confidence_level
    margin = math.sqrt(2.0 * math.log(1.0 / alpha) / len(favorable_values))
    return max(-1.0, fmean(favorable_values) - margin)


def _analyze_guardrails(
    manifest: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    included = [run for run in runs if run.get("validity", {}).get("status") == "included"]
    results: list[dict[str, Any]] = []
    for guardrail in manifest["claim_plan"]["guardrails"]:
        source = guardrail["source"]
        all_values = [
            value
            for run in included
            for value in [_guardrail_value(run, source)]
            if value is not None
        ]
        post_values = [
            value
            for run in included
            if run["arm"]["role"] == "post"
            for value in [_guardrail_value(run, source)]
            if value is not None
        ]
        pairs: dict[str, dict[str, float]] = {}
        for run in included:
            pair_id = run["attempt"]["pair_id"]
            value = _guardrail_value(run, source)
            if pair_id is not None and value is not None:
                pairs.setdefault(pair_id, {})[run["arm"]["role"]] = value
        pair_deltas = [
            pair["post"] - pair["pre"]
            for pair in pairs.values()
            if set(pair) == {"pre", "post"}
        ]
        rule_results: list[dict[str, Any]] = []
        for rule in guardrail["rules"]:
            statistic = rule["statistic"]
            if statistic == "maximum_all":
                observed = max(all_values) if all_values else None
            elif statistic == "maximum_post":
                observed = max(post_values) if post_values else None
            elif statistic == "minimum_post":
                observed = min(post_values) if post_values else None
            else:
                observed = fmean(pair_deltas) if pair_deltas else None
            passed = bool(
                observed is not None
                and (
                    observed <= rule["threshold"]
                    if rule["operator"] == "at_most"
                    else observed >= rule["threshold"]
                )
            )
            rule_results.append({
                **rule,
                "observed": observed,
                "passed": passed,
            })
        results.append({
            "guardrail_id": guardrail["guardrail_id"],
            "source": source,
            "rules": rule_results,
            "passed": all(rule["passed"] for rule in rule_results),
        })
    return {
        "all_passed": bool(results) and all(result["passed"] for result in results),
        "guardrails": results,
    }


def _guardrail_value(
    run: Mapping[str, Any], source: Mapping[str, Any]
) -> float | None:
    if source["kind"] == "cost":
        value = run["costs"][source["metric_id"]]
        return float(value) if value is not None else None
    return _metric_value(run, source["metric_id"])


def _shared_content_summary(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    shared: list[dict[str, Any]] = []
    for kind in ("prompt", "render_inputs", "answer", "final_state"):
        by_hash: dict[str, list[str]] = {}
        for run in runs:
            artifact = _run_artifacts_by_kind(run)[kind]
            by_hash.setdefault(artifact["sha256"], []).append(run["run_id"])
        shared.extend(
            {
                "kind": kind,
                "sha256": identity,
                "run_count": len(run_ids),
                "run_ids": run_ids,
            }
            for identity, run_ids in sorted(by_hash.items())
            if len(run_ids) > 1
        )
    return {
        "groups": shared,
        "limitation": (
            "Shared prompt, input, answer, or state bytes can be legitimate; uniqueness is "
            "established by execution receipts rather than content uniqueness."
        ),
    }


def _cost_measurement_summary(
    manifest: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    plan = manifest["cost_measurement"]
    included = [run for run in runs if run.get("validity", {}).get("status") == "included"]
    reportable = bool(included) and all(
        run["costs"]["cost_status"] != "unavailable"
        and run["costs"]["cost_microusd"] is not None
        for run in included
    )
    return {
        "mode": plan["mode"],
        "cost_reportable": reportable,
        "price_schedule_sha256": (
            plan["price_schedule"]["sha256"]
            if plan["price_schedule"] is not None
            else None
        ),
        "limitations": (
            []
            if reportable
            else [
                "Provider price is explicitly unavailable; token and task estimates remain "
                "reportable, but no monetary cost estimate may be inferred and zero does not mean unknown."
            ]
        ),
    }


def _metric_value(run: Mapping[str, Any], metric_id: str) -> float | None:
    for metric in run["outcomes"]["metrics"]:
        if metric["metric_id"] == metric_id:
            return float(metric["value"])
    return None


def _bootstrap_interval(
    values: Sequence[float], confidence: Mapping[str, Any]
) -> list[float] | None:
    if confidence["method"] != "bootstrap_percentile":
        return None
    seed = int(confidence["seed_sha256"].removeprefix("sha256:")[:16], 16)
    rng = random.Random(seed)
    size = len(values)
    samples = [
        fmean(values[rng.randrange(size)] for _ in range(size))
        for _ in range(confidence["resamples"])
    ]
    samples.sort()
    tail = (1.0 - confidence["level"]) / 2.0
    return [_percentile(samples, tail), _percentile(samples, 1.0 - tail)]


def _percentile(sorted_values: Sequence[float], quantile: float) -> float:
    position = quantile * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def _verify_all_artifacts(
    manifest: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    artifact_root: Path,
    issues: list[ValidationIssue],
) -> None:
    root = artifact_root.resolve()
    seen: dict[str, str] = {}
    verified: set[tuple[str, str, str, int]] = set()

    def verify(pin: Mapping[str, Any], path: str) -> None:
        identity = (
            pin["uri"],
            pin["sha256"],
            pin["media_type"],
            pin["byte_size"],
        )
        if identity in verified:
            return
        _verify_artifact_pin(pin, path, root, seen, issues)
        verified.add(identity)

    for path, pin in _walk_artifact_pins(manifest, "$.manifest"):
        verify(pin, path)
    for run_index, run in enumerate(runs):
        for path, pin in _walk_artifact_pins(run, f"$.runs[{run_index}]"):
            verify(pin, path)


def _verify_model_identity_contract_artifacts(
    manifest: Mapping[str, Any],
    artifact_root: Path,
    issues: list[ValidationIssue],
) -> None:
    """Validate the v1 local-runner contract that gives a hash operational meaning."""
    contract = manifest["reference_agent_stack"]["model"][
        "backend_identity_contract"
    ]
    if contract["mode"] != "local_model_artifact":
        return
    pin = contract["runner_attestation_contract"]["artifact"]
    candidate = _resolve_artifact(artifact_root.resolve(), pin["uri"])
    if candidate is None or not candidate.is_file():
        return
    try:
        document = parse_canonical_json_bytes(candidate.read_bytes())
    except (OSError, UnicodeDecodeError, CanonicalJSONError):
        return
    expected_argument = contract["required_invocation_argument"]
    expected = {
        "schema_version": (
            "drupal_agent_readiness.local_model_runner_attestation_contract.v1"
        ),
        "required_invocation_argument": expected_argument,
        "trust_boundary": "pinned_harness_and_retained_execution_receipt",
    }
    if document != expected:
        issues.append(
            _error(
                "local_runner_attestation_contract_semantic_mismatch",
                "$.reference_agent_stack.model.backend_identity_contract.runner_attestation_contract",
                "The retained local-runner contract must canonically bind the exact model "
                "artifact argument and declare the pinned-harness trust boundary.",
            )
        )


def _verify_state_provenance_artifacts(
    manifest: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    artifact_root: Path,
    issues: list[ValidationIssue],
) -> None:
    root = artifact_root.resolve()
    sites = [
        ("$.manifest.substrate.starting_site_seed", manifest["substrate"]["starting_site_seed"])
    ]
    sites.extend(
        (f"$.manifest.arms[{index}].drupal_state.site", arm["drupal_state"]["site"])
        for index, arm in enumerate(manifest["arms"])
    )
    sites.extend(
        (path, state["site"])
        for run_index, run in enumerate(runs)
        for path, state in (
            (f"$.runs[{run_index}].arm.drupal_state.site", run["arm"]["drupal_state"]),
            (f"$.runs[{run_index}].final_drupal_state.site", run["final_drupal_state"]),
        )
    )
    for path, site in sites:
        expected = {
            "schema_version": "drupal_agent_readiness.site_state_manifest.v1",
            "fixture_id": site["fixture_id"],
            "database_sha256": site["database_sha256"],
            "active_config_sha256": site["active_config_sha256"],
            "public_files_sha256": site["public_files_sha256"],
            "private_files_sha256": site["private_files_sha256"],
        }
        _verify_expected_json_pin(site["manifest"], expected, path, root, issues)
    codes = [
        (f"$.manifest.arms[{index}].drupal_state.code", arm["drupal_state"]["code"])
        for index, arm in enumerate(manifest["arms"])
    ]
    codes.extend(
        (path, state["code"])
        for run_index, run in enumerate(runs)
        for path, state in (
            (f"$.runs[{run_index}].arm.drupal_state.code", run["arm"]["drupal_state"]),
            (f"$.runs[{run_index}].final_drupal_state.code", run["final_drupal_state"]),
        )
    )
    for path, code in codes:
        expected = {
            "schema_version": "drupal_agent_readiness.code_state_manifest.v1",
            "core": code["core"],
            "components": code["components"],
            "composer_lock_sha256": code["composer_lock_sha256"],
            "extensions_manifest_sha256": code["extensions_manifest_sha256"],
            "codebase_tree_sha256": code["codebase_tree_sha256"],
        }
        _verify_expected_json_pin(
            code["manifest"],
            expected,
            path,
            root,
            issues,
        )


def _verify_expected_json_pin(
    pin: Mapping[str, Any],
    expected: Mapping[str, Any],
    path: str,
    root: Path,
    issues: list[ValidationIssue],
) -> None:
    if pin["media_type"] != "application/json":
        issues.append(
            _error(
                "state_manifest_media_type_mismatch",
                f"{path}.manifest.media_type",
                "Retained Drupal state manifests must declare application/json.",
            )
        )
    candidate = _resolve_artifact(root, pin["uri"])
    if candidate is None or not candidate.is_file():
        return
    if candidate.read_bytes() != canonical_json_bytes(expected):
        issues.append(
            _error(
                "state_manifest_semantic_mismatch",
                path,
                "Retained canonical state manifest does not reconcile to the declared Drupal state.",
            )
        )


def _verify_run_artifact_semantics(
    manifest: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    artifact_root: Path,
    issues: list[ValidationIssue],
) -> None:
    root = artifact_root.resolve()
    try:
        task_prompt = (root / manifest["task"]["prompt"]["uri"]).read_text(
            encoding="utf-8"
        )
        system_prompt = (
            root / manifest["reference_agent_stack"]["system_prompt"]["uri"]
        ).read_text(encoding="utf-8")
        registered_render_inputs_bytes = (
            root / manifest["prompt_composition"]["render_inputs"]["uri"]
        ).read_bytes()
        registered_render_inputs = parse_canonical_json_bytes(
            registered_render_inputs_bytes
        )
        prompt_algorithm = manifest["prompt_composition"]["algorithm"]
        instruction_key = (
            "operator_prompt_envelope"
            if prompt_algorithm == "canonical_operator_prompt_envelope_v1"
            else "system_prompt"
        )
        expected_prompt = {
            "schema_version": "drupal_agent_readiness.prompt_envelope.v1",
            "task_prompt": task_prompt,
            instruction_key: system_prompt,
            "render_inputs": registered_render_inputs,
        }
        if (
            isinstance(registered_render_inputs, Mapping)
            and registered_render_inputs.get("snapshot_delivery")
            == "inline_canonical_prompt_envelope"
        ):
            snapshot_tool = next(
                tool
                for tool in manifest["reference_agent_stack"]["tools"]
                if tool["id"] == "governed-observation-snapshot"
            )
            expected_prompt["governed_observation"] = parse_canonical_json_bytes(
                (root / snapshot_tool["artifact"]["uri"]).read_bytes()
            )
        expected_prompt_bytes = canonical_json_bytes(expected_prompt)
    except (OSError, UnicodeError, CanonicalJSONError, StopIteration):
        registered_render_inputs_bytes = None
        expected_prompt_bytes = None
    for run_index, run in enumerate(runs):
        artifact_by_kind = {
            artifact["kind"]: artifact for artifact in run["artifacts"]
        }
        _verify_attempt_receipt_semantics(
            run,
            artifact_by_kind,
            run_index,
            root,
            issues,
        )
        expected_documents = {
            "cost_trace": run["costs"],
            "behavior_trace": {
                "events": run["behavior_events"],
                "summary": run["behavior_summary"],
            },
            "evaluator_output": run["outcomes"],
            "validity_decision": run["validity"],
            "starting_state": {
                "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
                "run_id": run["run_id"],
                "moment": "starting",
                "arm_id": run["arm"]["arm_id"],
                "roster_slot_id": run["attempt"]["roster_slot_id"],
                "unit_id": run["attempt"]["unit_id"],
                "collector_sha256": run["state_capture"]["collector_sha256"],
                "collector_invocation_id": run["state_capture"]["starting"][
                    "invocation_id"
                ],
                "captured_at": run["state_capture"]["starting"]["captured_at"],
                "drupal_state": run["arm"]["drupal_state"],
            },
            "final_state": {
                "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
                "run_id": run["run_id"],
                "moment": "final",
                "arm_id": run["arm"]["arm_id"],
                "roster_slot_id": run["attempt"]["roster_slot_id"],
                "unit_id": run["attempt"]["unit_id"],
                "collector_sha256": run["state_capture"]["collector_sha256"],
                "collector_invocation_id": run["state_capture"]["final"][
                    "invocation_id"
                ],
                "captured_at": run["state_capture"]["final"]["captured_at"],
                "drupal_state": run["final_drupal_state"],
            },
            "prompt_receipt": {
                "schema_version": "drupal_agent_readiness.prompt_delivery_receipt.v1",
                "run_id": run["run_id"],
                **run["prompt_delivery"],
            },
            "model_identity_receipt": {
                "schema_version": "drupal_agent_readiness.model_identity_receipt.v1",
                "run_id": run["run_id"],
                **run["model_identity_receipt"],
            },
            "execution_receipt": {
                "schema_version": "drupal_agent_readiness.execution_receipt.v1",
                "run_id": run["run_id"],
                **run["execution_receipt"],
            },
            "evaluator_receipt": {
                "schema_version": "drupal_agent_readiness.evaluator_receipt.v1",
                "run_id": run["run_id"],
                **run["evaluator_receipt"],
            },
        }
        for kind, expected_bytes in (
            ("render_inputs", registered_render_inputs_bytes),
            ("prompt", expected_prompt_bytes),
        ):
            if expected_bytes is None:
                continue
            artifact = artifact_by_kind[kind]
            if artifact["media_type"] != "application/json":
                issues.append(
                    _error(
                        "prompt_artifact_media_type",
                        f"$.runs[{run_index}].artifacts.{kind}.media_type",
                        f"{kind} must be retained as canonical application/json.",
                    )
                )
            candidate = _resolve_artifact(root, artifact["uri"])
            if candidate is not None and candidate.is_file() and candidate.read_bytes() != expected_bytes:
                issues.append(
                    _error(
                        "prompt_composition_mismatch",
                        f"$.runs[{run_index}].artifacts.{kind}",
                        "Retained delivered prompt bytes do not equal the preregistered visible prompt envelope.",
                    )
                )
        for kind, expected in expected_documents.items():
            artifact = artifact_by_kind[kind]
            path = f"$.runs[{run_index}].artifacts.{kind}"
            if artifact["media_type"] != "application/json":
                issues.append(
                    _error(
                        "semantic_artifact_media_type",
                        f"{path}.media_type",
                        f"{kind} must be retained as canonical application/json.",
                    )
                )
            candidate = _resolve_artifact(root, artifact["uri"])
            if candidate is None or not candidate.is_file():
                continue
            try:
                raw = candidate.read_bytes()
                document = json.loads(raw, object_pairs_hook=_object_without_duplicate_keys)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, CanonicalJSONError) as error:
                issues.append(
                    _error(
                        "semantic_artifact_invalid_json",
                        path,
                        f"{kind} is not valid UTF-8 JSON: {error}.",
                    )
                )
                continue
            try:
                canonical = canonical_json_bytes(document)
            except (TypeError, ValueError) as error:
                issues.append(
                    _error(
                        "semantic_artifact_noncanonical_value",
                        path,
                        f"{kind} contains a value outside canonical JSON: {error}.",
                    )
                )
                continue
            if raw != canonical:
                issues.append(
                    _error(
                        "semantic_artifact_not_canonical_json",
                        path,
                        f"{kind} bytes are not the canonical JSON encoding.",
                    )
                )
            if raw != canonical_json_bytes(expected):
                issues.append(
                    _error(
                        "semantic_artifact_mismatch",
                        path,
                        f"{kind} does not match the corresponding run fields.",
                    )
                )


def _verify_attempt_receipt_semantics(
    run: Mapping[str, Any],
    artifact_by_kind: Mapping[str, Mapping[str, Any]],
    run_index: int,
    root: Path,
    issues: list[ValidationIssue],
) -> None:
    path = f"$.runs[{run_index}].artifacts.attempt_receipt"
    artifact = artifact_by_kind.get("attempt_receipt")
    if artifact is None:
        return
    if artifact["media_type"] != "application/json":
        issues.append(
            _error(
                "attempt_receipt_media_type_mismatch",
                f"{path}.media_type",
                "Attempt receipts must be retained as canonical application/json.",
            )
        )
    candidate = _resolve_artifact(root, artifact["uri"])
    if candidate is None or not candidate.is_file():
        return
    try:
        receipt = parse_canonical_json_bytes(candidate.read_bytes())
    except (OSError, CanonicalJSONError) as error:
        issues.append(
            _error(
                "attempt_receipt_invalid_json",
                path,
                f"Attempt receipt is not canonical JSON: {error}.",
            )
        )
        return
    if not isinstance(receipt, Mapping):
        issues.append(
            _error(
                "attempt_receipt_semantic_mismatch",
                path,
                "Attempt receipt must be one canonical JSON object.",
            )
        )
        return

    expected_keys = {
        "schema_version",
        "run_id",
        "roster_slot_id",
        "attempt_id",
        "argv",
        "status",
        "returncode",
        "timed_out",
        "thread_id",
        "provider_request_id",
        "provider_request_id_status",
        "environment_policy_sha256",
        "runtime_home_verification",
        "process_containment",
        "stdout_artifact_id",
        "stdout_sha256",
        "stderr_artifact_id",
        "stderr_sha256",
    }
    execution = run["execution_receipt"]
    expected_bindings = {
        "schema_version": "drupal_agent_readiness.frontier_attempt_receipt.v1",
        "run_id": run["run_id"],
        "roster_slot_id": run["attempt"]["roster_slot_id"],
        "attempt_id": execution["invocation_id"],
        "argv": execution["argv"],
        "status": "succeeded",
        "returncode": 0,
        "timed_out": False,
        "thread_id": execution["thread_id"],
        "provider_request_id": execution["provider_request_id"],
        "provider_request_id_status": execution["provider_request_id_status"],
    }
    mismatches = [
        field
        for field, expected in expected_bindings.items()
        if receipt.get(field) != expected
        or (field == "returncode" and type(receipt.get(field)) is not int)
        or (field == "timed_out" and type(receipt.get(field)) is not bool)
    ]
    if set(receipt) != expected_keys:
        mismatches.append("object_keys")

    inference_pin = run["agent_stack"]["model"]["inference_parameters"]
    inference_path = _resolve_artifact(root, inference_pin["uri"])
    expected_policy_hash: Any = None
    if inference_path is not None and inference_path.is_file():
        try:
            inference_parameters = parse_canonical_json_bytes(
                inference_path.read_bytes()
            )
        except (OSError, CanonicalJSONError):
            inference_parameters = None
        if isinstance(inference_parameters, Mapping):
            expected_policy_hash = inference_parameters.get(
                "execution_environment_policy_sha256"
            )
    if (
        not isinstance(expected_policy_hash, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_policy_hash) is None
        or receipt.get("environment_policy_sha256") != expected_policy_hash
    ):
        mismatches.append("environment_policy_sha256")
    policy_tool = next(
        (
            tool
            for tool in run["agent_stack"]["tools"]
            if tool["id"] == "execution-environment-policy"
        ),
        None,
    )
    expected_system_skills_tree_sha256: Any = None
    expected_permissions_profile_sha256: Any = None
    expected_sentinel_sha256: Any = None
    expected_process_containment: Any = None
    expected_system_manifest: Any = None
    expected_model_cache_contract: Any = None
    policy_document: Any = None
    if (
        policy_tool is None
        or policy_tool["artifact"]["sha256"] != expected_policy_hash
    ):
        mismatches.append("execution_environment_policy_artifact")
    else:
        policy_path = _resolve_artifact(root, policy_tool["artifact"]["uri"])
        if policy_path is not None and policy_path.is_file():
            try:
                policy_document = parse_canonical_json_bytes(policy_path.read_bytes())
            except (OSError, CanonicalJSONError):
                pass
        if isinstance(policy_document, Mapping):
            expected_process_containment = policy_document.get("process_containment")
            expected_model_cache_contract = policy_document.get("model_cache")
            if (
                expected_model_cache_contract is not None
                and not model_cache_contract_valid(expected_model_cache_contract)
            ):
                mismatches.append("model_cache")
            elif (
                expected_model_cache_contract is not None
                and expected_model_cache_contract["selected_model_selector"]
                != run["agent_stack"]["model"]["snapshot"]
            ):
                mismatches.append("model_cache.selected_model_selector")
            preflight = policy_document.get("system_skills_preflight")
            preflight_manifest = (
                preflight.get("manifest") if isinstance(preflight, Mapping) else None
            )
            if isinstance(preflight_manifest, Mapping):
                expected_system_manifest = preflight_manifest
                expected_system_skills_tree_sha256 = preflight_manifest.get(
                    "tree_sha256"
                )
            permissions_preflight = policy_document.get("permissions_preflight")
            if isinstance(permissions_preflight, Mapping):
                expected_permissions_profile_sha256 = permissions_preflight.get(
                    "profile_sha256"
                )
                expected_sentinel_sha256 = permissions_preflight.get(
                    "sentinel_sha256"
                )
        if (
            not isinstance(expected_system_skills_tree_sha256, str)
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                expected_system_skills_tree_sha256,
            )
            is None
        ):
            mismatches.append("system_skills_preflight.manifest.tree_sha256")
    if mismatches:
        issues.append(
            _error(
                "attempt_receipt_semantic_mismatch",
                path,
                "Attempt receipt does not exactly bind the successful registered execution; "
                f"mismatches={sorted(set(mismatches))!r}.",
            )
        )

    runtime_verification = receipt.get("runtime_home_verification")
    system_preflight = (
        policy_document.get("system_skills_preflight")
        if isinstance(policy_document, Mapping)
        else None
    )
    host_denials = (
        system_preflight.get("host_read_denials")
        if isinstance(system_preflight, Mapping)
        else None
    )
    auth_path = (
        host_denials.get("auth_file", {}).get("path")
        if isinstance(host_denials, Mapping)
        and isinstance(host_denials.get("auth_file"), Mapping)
        else None
    )
    execution_argv = execution.get("argv")
    codex_path = (
        str(Path(execution_argv[0]).resolve())
        if isinstance(execution_argv, list)
        and execution_argv
        and isinstance(execution_argv[0], str)
        else None
    )
    codex_file_sha256 = run["agent_stack"]["agent"]["artifact"].get("sha256")
    expected_runtime_keys = {
        "before_home_mode",
        "after_home_mode",
        "before_home_identity_verified",
        "after_home_identity_verified",
        "before_home_mode_verified",
        "after_home_mode_verified",
        "before_layout_verified",
        "after_layout_verified",
        "before_layout_sha256",
        "after_layout_sha256",
        "before_layout_document",
        "after_layout_document",
        "before_auth_reference_verified",
        "after_auth_reference_verified",
        "before_profile_regular_file_verified",
        "after_profile_regular_file_verified",
        "before_sentinel_regular_file_verified",
        "after_sentinel_regular_file_verified",
        "before_forbidden_entries",
        "after_forbidden_entries",
        "before_system_skills_verified",
        "after_system_skills_verified",
        "system_skills_tree_sha256",
    }
    permissions_runtime_ok = True
    if expected_permissions_profile_sha256 is not None or expected_sentinel_sha256 is not None:
        expected_runtime_keys.update(
            {
                "before_permissions_profile_sha256",
                "after_permissions_profile_sha256",
                "before_sentinel_sha256",
                "after_sentinel_sha256",
            }
        )
        permissions_runtime_ok = (
            isinstance(runtime_verification, Mapping)
            and isinstance(expected_permissions_profile_sha256, str)
            and isinstance(expected_sentinel_sha256, str)
            and runtime_verification.get("before_permissions_profile_sha256")
            == expected_permissions_profile_sha256
            and runtime_verification.get("after_permissions_profile_sha256")
            == expected_permissions_profile_sha256
            and runtime_verification.get("before_sentinel_sha256")
            == expected_sentinel_sha256
            and runtime_verification.get("after_sentinel_sha256")
            == expected_sentinel_sha256
        )
    runtime_ok = (
        isinstance(runtime_verification, Mapping)
        and set(runtime_verification) == expected_runtime_keys
        and runtime_verification.get("before_home_mode") == "0o700"
        and runtime_verification.get("after_home_mode") == "0o700"
        and runtime_verification.get("before_home_identity_verified") is True
        and runtime_verification.get("after_home_identity_verified") is True
        and runtime_verification.get("before_home_mode_verified") is True
        and runtime_verification.get("after_home_mode_verified") is True
        and runtime_verification.get("before_layout_verified") is True
        and runtime_verification.get("after_layout_verified") is True
        and isinstance(runtime_verification.get("before_layout_sha256"), str)
        and re.fullmatch(
            r"sha256:[0-9a-f]{64}", runtime_verification["before_layout_sha256"]
        )
        is not None
        and isinstance(runtime_verification.get("after_layout_sha256"), str)
        and re.fullmatch(
            r"sha256:[0-9a-f]{64}", runtime_verification["after_layout_sha256"]
        )
        is not None
        and runtime_home_layout_document_valid(
            runtime_verification.get("before_layout_document")
        )
        and runtime_home_layout_document_valid(
            runtime_verification.get("after_layout_document")
        )
        and runtime_verification["before_layout_document"]["tree_sha256"]
        == runtime_verification["before_layout_sha256"]
        and runtime_verification["after_layout_document"]["tree_sha256"]
        == runtime_verification["after_layout_sha256"]
        and isinstance(auth_path, str)
        and isinstance(codex_path, str)
        and isinstance(codex_file_sha256, str)
        and runtime_home_layout_semantically_valid(
            runtime_verification.get("before_layout_document"),
            phase="before",
            system_manifest=expected_system_manifest,
            auth_target_path_sha256="sha256:"
            + hashlib.sha256(auth_path.encode()).hexdigest(),
            codex_target_path_sha256="sha256:"
            + hashlib.sha256(codex_path.encode()).hexdigest(),
            codex_file_sha256=codex_file_sha256,
            model_cache_contract=expected_model_cache_contract,
        )
        and runtime_home_layout_semantically_valid(
            runtime_verification.get("after_layout_document"),
            phase="after",
            system_manifest=expected_system_manifest,
            auth_target_path_sha256="sha256:"
            + hashlib.sha256(auth_path.encode()).hexdigest(),
            codex_target_path_sha256="sha256:"
            + hashlib.sha256(codex_path.encode()).hexdigest(),
            codex_file_sha256=codex_file_sha256,
            model_cache_contract=expected_model_cache_contract,
        )
        and runtime_verification.get("before_auth_reference_verified") is True
        and runtime_verification.get("after_auth_reference_verified") is True
        and runtime_verification.get("before_profile_regular_file_verified") is True
        and runtime_verification.get("after_profile_regular_file_verified") is True
        and runtime_verification.get("before_sentinel_regular_file_verified") is True
        and runtime_verification.get("after_sentinel_regular_file_verified") is True
        and runtime_verification.get("before_forbidden_entries") == []
        and runtime_verification.get("after_forbidden_entries") == []
        and runtime_verification.get("before_system_skills_verified") is True
        and runtime_verification.get("after_system_skills_verified") is True
        and isinstance(runtime_verification.get("system_skills_tree_sha256"), str)
        and re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            runtime_verification["system_skills_tree_sha256"],
        )
        is not None
        and runtime_verification["system_skills_tree_sha256"]
        == expected_system_skills_tree_sha256
        and permissions_runtime_ok
    )
    if not runtime_ok:
        issues.append(
            _error(
                "attempt_runtime_home_verification_failed",
                f"{path}.runtime_home_verification",
                "Successful attempts require clean before/after runtime homes and verified system skills.",
            )
        )

    process_receipt = receipt.get("process_containment")
    process_policy_ok = bool(
        isinstance(expected_process_containment, Mapping)
        and set(expected_process_containment)
        == {
            "kind",
            "sandbox_binary",
            "sandbox_sha256",
            "profile",
            "profile_sha256",
            "child_process_creation",
            "claim_boundary",
            "sandbox_platform",
        }
        and expected_process_containment.get("kind")
        == "darwin_seatbelt_process_fork_denied"
        and expected_process_containment.get("profile")
        == "(version 1)\n(allow default)\n(deny process-fork)\n"
        and expected_process_containment.get("profile_sha256")
        == "sha256:"
        + hashlib.sha256(
            "(version 1)\n(allow default)\n(deny process-fork)\n".encode("utf-8")
        ).hexdigest()
        and expected_process_containment.get("child_process_creation")
        == "denied_by_seatbelt_process_fork"
        and isinstance(expected_process_containment.get("sandbox_binary"), str)
        and isinstance(expected_process_containment.get("sandbox_sha256"), str)
        and re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(expected_process_containment.get("sandbox_sha256")),
        )
        is not None
        and isinstance(expected_process_containment.get("sandbox_platform"), Mapping)
        and expected_process_containment["sandbox_platform"].get("sys_platform")
        == "darwin"
    )
    expected_process_receipt = (
        {
            "status": "verified",
            "policy_sha256": canonical_sha256(expected_process_containment),
            "sandbox_sha256": expected_process_containment["sandbox_sha256"],
            "child_process_creation_denied": True,
            "inner_argv": execution["argv"],
            "outer_argv": [
                expected_process_containment["sandbox_binary"],
                "-p",
                expected_process_containment["profile"],
                *execution["argv"],
            ],
        }
        if process_policy_ok
        else None
    )
    if not isinstance(process_receipt, Mapping) or dict(process_receipt) != (
        expected_process_receipt
    ):
        issues.append(
            _error(
                "attempt_process_containment_failed",
                f"{path}.process_containment",
                "Successful attempts require an exact retained no-child-process Seatbelt receipt.",
            )
        )

    for stream in ("stdout", "stderr"):
        stream_artifact = artifact_by_kind.get(f"attempt_{stream}")
        if stream_artifact is None:
            continue
        if (
            receipt.get(f"{stream}_artifact_id") != stream_artifact["artifact_id"]
            or receipt.get(f"{stream}_sha256") != stream_artifact["sha256"]
        ):
            issues.append(
                _error(
                    "attempt_raw_log_binding_mismatch",
                    f"{path}.{stream}_sha256",
                    f"Attempt receipt does not bind the retained raw {stream} artifact.",
                )
            )
        if stream_artifact["media_type"] != "text/plain":
            issues.append(
                _error(
                    "attempt_raw_log_media_type_mismatch",
                    f"$.runs[{run_index}].artifacts.attempt_{stream}.media_type",
                    f"Raw attempt {stream} must declare text/plain.",
                )
            )


def _verify_artifact_pin(
    pin: Mapping[str, Any],
    path: str,
    root: Path,
    seen: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    uri = pin["uri"]
    expected_hash = pin["sha256"]
    previous_hash = seen.get(uri)
    if previous_hash is not None and previous_hash != expected_hash:
        issues.append(
            _error(
                "conflicting_artifact_pin",
                f"{path}.sha256",
                f"Artifact '{uri}' is pinned to more than one hash.",
            )
        )
    seen[uri] = expected_hash
    candidate = _resolve_artifact(root, uri)
    if candidate is None:
        issues.append(
            _error(
                "artifact_path_escape",
                f"{path}.uri",
                "Artifact path resolves outside the declared evidence root.",
            )
        )
    elif not candidate.is_file():
        issues.append(
            _error(
                "artifact_missing",
                f"{path}.uri",
                f"Pinned artifact '{uri}' does not exist as a regular file.",
            )
        )
    else:
        actual_hash = file_sha256(candidate)
        if actual_hash != expected_hash:
            issues.append(
                _error(
                    "artifact_hash_mismatch",
                    f"{path}.sha256",
                    f"Pinned {expected_hash}, found {actual_hash} for '{uri}'.",
                )
            )
        actual_size = candidate.stat().st_size
        if actual_size != pin["byte_size"]:
            issues.append(
                _error(
                    "artifact_size_mismatch",
                    f"{path}.byte_size",
                    f"Declared {pin['byte_size']} bytes, found {actual_size} for '{uri}'.",
                )
            )
        expected_media_type = {
            ".json": "application/json",
            ".py": "text/x-python",
            ".md": "text/markdown",
            ".patch": "text/x-diff",
        }.get(candidate.suffix.lower())
        if expected_media_type is not None and pin["media_type"] != expected_media_type:
            issues.append(
                _error(
                    "artifact_media_type_mismatch",
                    f"{path}.media_type",
                    f"Artifact '{uri}' must declare {expected_media_type!r}.",
                )
            )
        if pin["media_type"] == "application/json":
            try:
                raw = candidate.read_bytes()
                document = json.loads(raw, object_pairs_hook=_object_without_duplicate_keys)
                canonical = canonical_json_bytes(document)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, CanonicalJSONError, TypeError, ValueError) as error:
                issues.append(
                    _error(
                        "pinned_json_invalid",
                        path,
                        f"Pinned JSON artifact '{uri}' is invalid: {error}.",
                    )
                )
            else:
                if raw != canonical:
                    issues.append(
                        _error(
                            "pinned_json_not_canonical",
                            path,
                            f"Pinned JSON artifact '{uri}' must use canonical JSON bytes.",
                        )
                    )


def _walk_artifact_pins(
    value: Any, path: str
) -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        if {"uri", "sha256", "media_type", "byte_size"} <= set(value):
            yield path, value
            return
        for key, child in value.items():
            yield from _walk_artifact_pins(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_artifact_pins(child, f"{path}[{index}]")


def _resolve_artifact(root: Path, uri: str) -> Path | None:
    if not _safe_relative_uri(uri):
        return None
    candidate = (root / uri).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _check_relative_artifact_pins(
    value: Any, issues: list[ValidationIssue], path: str
) -> None:
    for pin_path, pin in _walk_artifact_pins(value, path):
        if not _safe_relative_uri(pin["uri"]):
            issues.append(
                _error(
                    "unsafe_artifact_uri",
                    f"{pin_path}.uri",
                    "Pinned artifacts must use safe paths relative to the evidence root.",
                )
            )


def _safe_relative_uri(uri: str) -> bool:
    path = Path(uri)
    return bool(uri) and not path.is_absolute() and ".." not in path.parts


def _leaf_differences(left: Any, right: Any, path: str = "") -> set[str]:
    left_leaves = _leaf_map(left, path)
    right_leaves = _leaf_map(right, path)
    keys = set(left_leaves) | set(right_leaves)
    return {key or "/" for key in keys if left_leaves.get(key) != right_leaves.get(key)}


def _leaf_map(value: Any, path: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}/{_json_pointer_escape(str(key))}"
            _merge_leaf_maps(result, _leaf_map(child, child_path), child_path)
        return result
    if isinstance(value, list):
        result: dict[str, Any] = {}
        seen_segments: set[str] = set()
        for index, child in enumerate(value):
            if isinstance(child, Mapping) and "kind" in child and "name" in child:
                identity = f"{child['kind']}:{child['name']}"
                segment = _json_pointer_escape(identity)
            elif isinstance(child, Mapping) and "id" in child:
                segment = _json_pointer_escape(f"id:{child['id']}")
            elif isinstance(child, Mapping) and "name" in child:
                segment = _json_pointer_escape(f"name:{child['name']}")
            else:
                segment = str(index)
            if segment in seen_segments:
                raise _ListIdentityCollision(
                    f"List identity collision at {path or '/'} for segment {segment!r}."
                )
            seen_segments.add(segment)
            child_path = f"{path}/{segment}"
            _merge_leaf_maps(result, _leaf_map(child, child_path), child_path)
        return result
    return {path: value}


def _merge_leaf_maps(
    destination: dict[str, Any], source: Mapping[str, Any], path: str
) -> None:
    overlap = set(destination) & set(source)
    if overlap:
        raise _ListIdentityCollision(
            f"Flattened leaf collision at {path}: {sorted(overlap)!r}."
        )
    destination.update(source)


def _json_pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _check_unique_ids(
    values: Sequence[Mapping[str, Any]],
    field: str,
    path: str,
    code: str,
    issues: list[ValidationIssue],
) -> None:
    identities = [value[field] for value in values]
    if len(identities) != len(set(identities)):
        issues.append(_error(code, path, f"Values of '{field}' must be unique."))


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Timestamp must include an offset: {value!r}")
    return parsed


def _safe_run_start(run: Mapping[str, Any]) -> datetime | None:
    timestamps = run.get("timestamps")
    if not isinstance(timestamps, Mapping):
        return None
    value = timestamps.get("started_at")
    if not isinstance(value, str):
        return None
    try:
        return _datetime(value)
    except ValueError:
        return None


def _prefix_issue(issue: ValidationIssue, prefix: str) -> ValidationIssue:
    suffix = issue.path[1:] if issue.path.startswith("$") else "." + issue.path
    return ValidationIssue(issue.severity, issue.code, prefix + suffix, issue.message)


def _error(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue("error", code, path, message)


def _warning(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue("warning", code, path, message)


def _has_errors(issues: Iterable[ValidationIssue]) -> bool:
    return any(issue.severity == "error" for issue in issues)


def _validate_against_schema(
    document: Any, schema_path: Path
) -> list[ValidationIssue]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return _shape_issues(document, schema, schema, "$")


def _shape_issues(
    value: Any,
    schema: Any,
    root_schema: Mapping[str, Any],
    path: str,
) -> list[ValidationIssue]:
    if schema is True:
        return []
    if schema is False:
        return [
            _error("schema_false", path, "This value is forbidden by the JSON schema.")
        ]
    if not isinstance(schema, Mapping):
        return [_error("schema_node", path, "JSON schema node is not an object or boolean.")]
    if "$ref" in schema:
        target = root_schema
        reference = schema["$ref"]
        if not reference.startswith("#/"):
            return [_error("schema_ref", path, f"Unsupported schema reference {reference!r}.")]
        for segment in reference[2:].split("/"):
            target = target[segment.replace("~1", "/").replace("~0", "~")]
        issues = _shape_issues(value, target, root_schema, path)
        siblings = {key: item for key, item in schema.items() if key != "$ref"}
        if siblings:
            issues.extend(_shape_issues(value, siblings, root_schema, path))
        return issues

    issues: list[ValidationIssue] = []
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for branch in all_of:
            issues.extend(_shape_issues(value, branch, root_schema, path))

    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and not any(
        not _shape_issues(value, branch, root_schema, path) for branch in any_of
    ):
        issues.append(
            _error(
                "schema_any_of",
                path,
                "Value does not satisfy any registered JSON Schema anyOf branch.",
            )
        )

    condition = schema.get("if")
    if condition is not None:
        condition_matches = not _shape_issues(value, condition, root_schema, path)
        selected = schema.get("then") if condition_matches else schema.get("else")
        if selected is not None:
            issues.extend(_shape_issues(value, selected, root_schema, path))
    expected_type = schema.get("type")
    if expected_type is not None:
        allowed_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_json_type(value, candidate) for candidate in allowed_types):
            return [
                _error(
                    "schema_type",
                    path,
                    f"Expected JSON type {allowed_types!r}, got {_json_type_name(value)!r}.",
                )
            ]

    if "const" in schema and value != schema["const"]:
        issues.append(
            _error("schema_const", path, f"Expected constant value {schema['const']!r}.")
        )
    if "enum" in schema and value not in schema["enum"]:
        issues.append(
            _error("schema_enum", path, f"Value must be one of {schema['enum']!r}.")
        )

    if isinstance(value, Mapping):
        required = schema.get("required", [])
        for field in required:
            if field not in value:
                issues.append(
                    _error(
                        "schema_required",
                        f"{path}.{field}",
                        f"Required field '{field}' is missing.",
                    )
                )
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for field, child in value.items():
            child_path = f"{path}.{field}"
            if field in properties:
                issues.extend(_shape_issues(child, properties[field], root_schema, child_path))
            elif additional is False:
                issues.append(
                    _error(
                        "schema_additional_property",
                        child_path,
                        f"Unexpected field '{field}'.",
                    )
                )
            elif isinstance(additional, Mapping):
                issues.extend(_shape_issues(child, additional, root_schema, child_path))

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            issues.append(
                _error(
                    "schema_min_items",
                    path,
                    f"Expected at least {schema['minItems']} items.",
                )
            )
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            issues.append(
                _error(
                    "schema_max_items",
                    path,
                    f"Expected at most {schema['maxItems']} items.",
                )
            )
        if schema.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(canonical) != len(set(canonical)):
                issues.append(_error("schema_unique_items", path, "Array items must be unique."))
        item_schema = schema.get("items")
        if item_schema:
            for index, child in enumerate(value):
                issues.extend(
                    _shape_issues(child, item_schema, root_schema, f"{path}[{index}]")
                )

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            issues.append(_error("schema_min_length", path, "String is too short."))
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            issues.append(
                _error("schema_pattern", path, f"String does not match pattern {pattern!r}.")
            )
        if schema.get("format") == "date-time":
            try:
                _datetime(value)
            except (TypeError, ValueError):
                issues.append(
                    _error(
                        "schema_date_time",
                        path,
                        "Timestamp must be ISO-8601 with an explicit UTC offset.",
                    )
                )

    if _is_json_number(value):
        if isinstance(value, float) and not math.isfinite(value):
            issues.append(_error("schema_nonfinite_number", path, "JSON numbers must be finite."))
            return issues
        if "minimum" in schema and value < schema["minimum"]:
            issues.append(
                _error("schema_minimum", path, f"Value must be at least {schema['minimum']}.")
            )
        if "maximum" in schema and value > schema["maximum"]:
            issues.append(
                _error("schema_maximum", path, f"Value must be at most {schema['maximum']}.")
            )
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            issues.append(
                _error(
                    "schema_exclusive_minimum",
                    path,
                    f"Value must be greater than {schema['exclusiveMinimum']}.",
                )
            )
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            issues.append(
                _error(
                    "schema_exclusive_maximum",
                    path,
                    f"Value must be less than {schema['exclusiveMaximum']}.",
                )
            )
    return issues


def _matches_json_type(value: Any, type_name: str) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": _is_json_number(value),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(type_name, False)


def _is_json_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__
