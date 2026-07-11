#!/usr/bin/env python3
"""CLI for the measurement-v1 frontier canary."""

from __future__ import annotations

import posix
import sys


if __name__ == "__main__" and not sys.flags.isolated:
    script_path = __file__
    if not script_path.startswith("/"):
        script_path = posix.getcwd() + "/" + script_path
    posix.execv(
        sys.executable,
        [sys.executable, "-I", "-B", script_path, *sys.argv[1:]],
    )
    raise RuntimeError("Python isolated re-exec unexpectedly returned")


import argparse
import atexit
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import uuid
from typing import Any, Mapping


def _configure_fresh_pycache() -> None:
    source_root = Path(__file__).resolve().parents[2]
    if not sys.flags.isolated:
        raise SystemExit("Frontier canary local imports require Python isolated mode")
    prefix = Path(tempfile.mkdtemp(prefix="frontier-canary-pycache-"))
    prefix.chmod(0o700)
    if (
        not prefix.is_dir()
        or (prefix.stat().st_mode & 0o777) != 0o700
        or any(prefix.iterdir())
        or prefix == source_root
        or source_root in prefix.parents
        or prefix in source_root.parents
    ):
        raise SystemExit(
            "Frontier canary requires a fresh external PYTHONPYCACHEPREFIX before local imports"
        )
    sys.pycache_prefix = str(prefix)
    sys.dont_write_bytecode = True
    atexit.register(shutil.rmtree, prefix, ignore_errors=True)


def _load_local_agent_readiness_package() -> None:
    import importlib.util

    package_root = Path(__file__).resolve().parents[1]
    initializer = package_root / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "agent_readiness",
        initializer,
        submodule_search_locations=[str(package_root)],
    )
    if spec is None or spec.loader is None:
        raise SystemExit("Could not establish the source-bound agent_readiness package")
    package = importlib.util.module_from_spec(spec)
    sys.modules["agent_readiness"] = package
    spec.loader.exec_module(package)


if __name__ == "__main__":
    _configure_fresh_pycache()
    _load_local_agent_readiness_package()

from agent_readiness.codex_runner_utils import (
    classify_infrastructure_failure,
    count_codex_tool_calls,
    process_output,
    run_command,
)
from agent_readiness.evaluators.common import collect_live_state
from agent_readiness.frontier_canary import (
    CODEX_CONFIG_PROFILE,
    CODEX_PERMISSION_PROFILE,
    FRONTIER_INVENTORY_OUTPUT_SCHEMA_SOURCE,
    FRONTIER_PROCESS_CONTAINMENT_PROFILE,
    SYSTEM_SKILL_BOOTSTRAP_SANDBOX_PROFILE,
    SYSTEM_SKILL_BOOTSTRAP_PROMPT,
    SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL,
    SYSTEM_SKILL_REQUIRED_HOST_DENIALS,
    SYSTEM_SKILL_NETWORK_PROBE_CODE,
    SYSTEM_SKILL_NETWORK_PROBE_EXIT_CODE,
    SYSTEM_SKILL_NETWORK_PROBE_STDERR,
    SYSTEM_SKILL_NETWORK_PROBE_STDOUT,
    FrontierCanaryError,
    build_codex_argv,
    build_frontier_process_containment_policy,
    build_system_skill_bootstrap_sandbox_profile,
    classify_system_skill_bootstrap_transport,
    derive_agent_visible_workspace,
    derive_ddev_substrate,
    derive_ddev_site_projection,
    expected_system_skill_host_denials,
    _parse_retained_codex_jsonl,
    _paths_overlap,
    _tree_sha256,
    parse_json_without_duplicate_keys,
    run_frontier_canary,
    seal_frontier_evidence,
    validate_frontier_process_containment_policy,
)
from agent_readiness.measurement_v1 import (
    audit_measurement_v1,
    canonical_json_bytes,
    file_sha256,
    model_cache_contract_valid,
    runtime_home_layout_document_valid,
)


ISOLATED_ENVIRONMENT_POLICY = {
    "schema_version": "drupal_agent_readiness.codex_environment_policy.v1",
    "mode": "isolated_codex_home_per_attempt",
    "home_mode": "0700",
    "allowed_initial_entries": [
        "auth.json symlink",
        "frontier-canary.config.toml exact preregistered bytes",
        "frontier-canary-sentinel non-secret canary",
        "models_cache.json exact preregistered behavior-metadata bytes",
        "skills/.system exact preregistered tree",
    ],
    "forbidden_home_entries": [
        "config.toml",
        "skills outside skills/.system",
        "plugins",
        "memories",
        "apps",
    ],
    "credential_handling": (
        "auth.json is referenced by symlink only; credential bytes and hashes are never read "
        "or recorded; the exact named permissions profile denies all auth.json paths"
    ),
    "inherited_environment_keys": [
        "LANG",
        "LC_ALL",
        "PATH",
        "SHELL",
        "TERM",
        "TMPDIR",
    ],
    "forced_environment_keys": ["CODEX_HOME", "HOME"],
}


def _permissions_profile_text(
    host_probe_paths: Mapping[str, Path] | None = None,
) -> str:
    exact_denials = "".join(
        f'{json.dumps(path)} = "deny"\n'
        for path in sorted(
            {
                str(value.expanduser().resolve())
                for value in (host_probe_paths or {}).values()
            }
        )
    )
    return (
        f'default_permissions = "{CODEX_PERMISSION_PROFILE}"\n'
        f'[permissions.{CODEX_PERMISSION_PROFILE}]\n'
        'description = "Snapshot-only read access with credential denial"\n'
        f'[permissions.{CODEX_PERMISSION_PROFILE}.filesystem]\n'
        '":root" = "deny"\n'
        '":minimal" = "read"\n'
        '"/**/auth.json" = "deny"\n'
        '"/**/frontier-canary-sentinel" = "deny"\n'
        '"/**/.git" = "deny"\n'
        '"/**/.git/**" = "deny"\n'
        f'{exact_denials}'
        '":tmpdir" = "deny"\n'
        f'[permissions.{CODEX_PERMISSION_PROFILE}.filesystem.":workspace_roots"]\n'
        '"." = "read"\n'
        f'[permissions.{CODEX_PERMISSION_PROFILE}.network]\n'
        'enabled = false\n'
    )


def _host_execution_context(codex_binary: Path) -> dict[str, Any]:
    inherited = {
        key: os.environ[key]
        for key in ISOLATED_ENVIRONMENT_POLICY["inherited_environment_keys"]
        if key in os.environ
    }
    requested = {
        "codex": str(codex_binary.expanduser().resolve()),
        "ddev": shutil.which("ddev"),
        "docker": shutil.which("docker"),
        "git": "/usr/bin/git" if Path("/usr/bin/git").is_file() else shutil.which("git"),
        "python": sys.executable,
        "network_sandbox": (
            "/usr/bin/sandbox-exec"
            if Path("/usr/bin/sandbox-exec").is_file()
            else None
        ),
        "sandbox_shell": "/bin/sh",
        "inherited_shell": inherited.get("SHELL"),
    }
    tools: dict[str, Any] = {}
    for name, raw in requested.items():
        if not isinstance(raw, str) or not raw:
            raise FrontierCanaryError(f"Required host tool is unavailable: {name}")
        invocation_path = Path(raw).expanduser().absolute()
        path = invocation_path.resolve()
        if not invocation_path.is_file() or not path.is_file():
            raise FrontierCanaryError(
                f"Required host tool is not a file: {invocation_path}"
            )
        version_command = [str(invocation_path), "--version"]
        completed = subprocess.run(
            version_command,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        version_text = "\n".join(
            part.strip()
            for part in (completed.stdout or "", completed.stderr or "")
            if part.strip()
        )[:2000]
        tools[name] = {
            "path": str(path),
            "invocation_path": str(invocation_path),
            "sha256": file_sha256(path),
            "version_argv": version_command,
            "version_returncode": completed.returncode,
            "version_output": version_text,
        }
    docker_context = subprocess.run(
        [
            tools["docker"]["invocation_path"],
            "context",
            "inspect",
            "--format",
            "{{.Endpoints.docker.Host}}",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    endpoint = (docker_context.stdout or "").strip()
    if not endpoint.startswith("unix://"):
        raise FrontierCanaryError(
            "Frontier canary requires a local Unix Docker endpoint for denial proof"
        )
    docker_socket = Path(endpoint.removeprefix("unix://")).expanduser().resolve()
    if not os.path.lexists(docker_socket):
        raise FrontierCanaryError(f"Docker socket endpoint is missing: {docker_socket}")
    return {
        "inherited_environment": inherited,
        "host_tools": tools,
        "docker_socket_path": str(docker_socket),
        "python_bytecode_policy": {
            "isolated_interpreter": bool(sys.flags.isolated),
            "fresh_external_prefix": bool(sys.pycache_prefix),
            "prefix": sys.pycache_prefix,
            "dont_write_bytecode": bool(sys.dont_write_bytecode),
            "local_package_pycache_accepted": False,
        },
        "trust_boundary": (
            "top-level host executables are content-addressed; dynamic libraries, the remaining "
            "Drupal bootstrap/runtime, container daemon internals, and arbitrary nested "
            "subprocesses remain trusted audit-host state"
        ),
    }


def _pinned_project_runner(
    host_context: Mapping[str, Any],
    site_root: Path,
    *,
    expected_vendor_tree_sha256: str | None,
):
    root = site_root.resolve()
    host_tools = host_context.get("host_tools")
    if not isinstance(host_tools, Mapping):
        raise FrontierCanaryError("Pinned project runner lacks host tool metadata")
    tool_pins: dict[str, tuple[Path, Path, str]] = {}
    for name in ("ddev", "docker"):
        tool = host_tools.get(name)
        if not isinstance(tool, Mapping):
            raise FrontierCanaryError(f"Pinned project runner lacks {name}")
        path = Path(str(tool.get("path", ""))).resolve()
        invocation_path = Path(str(tool.get("invocation_path", path))).absolute()
        sha256 = tool.get("sha256")
        if (
            not invocation_path.is_file()
            or not path.is_file()
            or not isinstance(sha256, str)
            or file_sha256(path) != sha256
        ):
            raise FrontierCanaryError(f"Pinned project runner {name} bytes do not match")
        tool_pins[name] = (invocation_path, path, sha256)
    vendor = root / "vendor"
    inherited = host_context.get("inherited_environment")
    inherited = inherited if isinstance(inherited, Mapping) else {}
    environment = {
        "PATH": str(inherited.get("PATH", "/usr/bin:/bin")),
        "HOME": str(Path.home()),
        "LANG": str(inherited.get("LANG", "C")),
        "LC_ALL": str(inherited.get("LC_ALL", "C")),
        "TZ": "UTC",
        "DOCKER_HOST": f"unix://{host_context['docker_socket_path']}",
    }

    def runner(
        argv: tuple[str, ...] | list[str], cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        command = [str(item) for item in argv]
        if not command:
            raise FrontierCanaryError("Pinned project runner received an empty command")
        if cwd.resolve() != root:
            raise FrontierCanaryError("Pinned project command escaped the observed site root")
        first = command[0]
        if first in tool_pins:
            invocation_path, executable, expected_sha256 = tool_pins[first]
            if invocation_path.resolve() != executable or file_sha256(executable) != expected_sha256:
                raise FrontierCanaryError(f"Pinned {first} binary changed before execution")
            command[0] = str(invocation_path)
            vendor_guard = False
        else:
            executable = Path(first)
            try:
                executable.resolve().relative_to(vendor.resolve())
            except (OSError, ValueError) as error:
                raise FrontierCanaryError(
                    f"Unregistered observed-project executable: {first}"
                ) from error
            if expected_vendor_tree_sha256 is None or (
                _tree_sha256(vendor) != expected_vendor_tree_sha256
            ):
                raise FrontierCanaryError(
                    "Observed-project vendor tree drifted before command execution"
                )
            command[0] = str(executable.resolve())
            expected_sha256 = None
            vendor_guard = True
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if vendor_guard:
            if _tree_sha256(vendor) != expected_vendor_tree_sha256:
                raise FrontierCanaryError(
                    "Observed-project vendor tree drifted during command execution"
                )
        elif invocation_path.resolve() != executable or file_sha256(executable) != expected_sha256:
            raise FrontierCanaryError(f"Pinned {first} binary changed during execution")
        return completed

    return runner


def _validate_nonoverlap_paths(named_paths: dict[str, Path]) -> None:
    items = [(name, path.resolve()) for name, path in named_paths.items()]
    for index, (left_name, left) in enumerate(items):
        for right_name, right in items[index + 1 :]:
            if _paths_overlap(left, right):
                raise FrontierCanaryError(
                    f"{left_name} and {right_name} must not overlap: {left} / {right}"
                )


def _validate_dedicated_output_directory(path: Path, label: str) -> None:
    resolved = path.resolve()
    if resolved.exists() and (
        not resolved.is_dir() or any(resolved.iterdir())
    ):
        raise FrontierCanaryError(
            f"{label} must be absent or an empty dedicated directory"
        )


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp requires an explicit UTC offset")
    return parsed


def _events(stdout: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(stdout.splitlines(), start=1):
        if not line.strip():
            continue
        value = parse_json_without_duplicate_keys(
            line,
            label=f"Codex JSONL line {line_number}",
        )
        if not isinstance(value, dict):
            raise FrontierCanaryError(f"Codex JSONL line {line_number} is not an object")
        result.append(value)
    return result


def _answer(
    events: list[dict[str, Any]], *, returncode: int, stderr: str
) -> dict[str, Any]:
    messages: list[str] = []
    for event in events:
        item = event.get("item")
        if (
            event.get("type") != "item.completed"
            or not isinstance(item, dict)
            or item.get("type") != "agent_message"
        ):
            continue
        text = item.get("text") or item.get("content")
        if isinstance(text, str):
            messages.append(text)
    if not messages:
        raise FrontierCanaryError(
            "Codex JSONL contained no final agent message; "
            + _failure_context(events, returncode=returncode, stderr=stderr)
        )
    answer = parse_json_without_duplicate_keys(
        messages[-1], label="Codex final message"
    )
    if not isinstance(answer, dict):
        raise FrontierCanaryError("Codex final answer is not a JSON object")
    return answer


def _failure_context(
    events: list[dict[str, Any]], *, returncode: int | None, stderr: str
) -> str:
    messages: list[str] = []
    for event in events:
        event_type = str(event.get("type", ""))
        if "error" not in event_type and "fail" not in event_type:
            continue
        candidates = [event.get("message"), event.get("error")]
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate = candidate.get("message") or candidate.get("code")
            if isinstance(candidate, str) and candidate.strip():
                messages.append(candidate.strip())
    event_text = " | ".join(messages[:3]) or "none"
    stderr_text = " ".join(stderr.strip().split())[:400] or "none"
    serialized_events = "\n".join(json.dumps(event, sort_keys=True) for event in events)
    classification = classify_infrastructure_failure(
        returncode=returncode if returncode is not None else 1,
        stdout=serialized_events,
        stderr=stderr,
        tool_calls=count_codex_tool_calls(serialized_events),
    )
    return (
        f"classification={classification or 'unclassified'}; returncode={returncode}; "
        f"error_events={event_text}; stderr={stderr_text}"
    )


_SENSITIVE_OUTPUT_PATTERNS = {
    "access_token_key": re.compile(r'(?i)["\']access_token["\']\s*:'),
    "refresh_token_key": re.compile(r'(?i)["\']refresh_token["\']\s*:'),
    "id_token_key": re.compile(r'(?i)["\']id_token["\']\s*:'),
    "api_key_marker": re.compile(r"(?i)(?:OPENAI_API_KEY|[\"']api_key[\"']\s*:|sk-[A-Za-z0-9_-]{16,})"),
    "jwt_shape": re.compile(r"eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}"),
}


def _sensitive_output_detections(
    stdout: str,
    stderr: str,
    *,
    sentinel_token: str,
) -> list[str]:
    combined = f"{stdout}\n{stderr}"
    detections = [
        name for name, pattern in _SENSITIVE_OUTPUT_PATTERNS.items() if pattern.search(combined)
    ]
    if sentinel_token and sentinel_token in combined:
        detections.append("nonsecret_canary_token")
    return sorted(set(detections))


def _record_sensitive_output_rejection(
    artifact_repo: Path,
    *,
    invocation_id: str,
    attempt: int,
    slot_id: str,
    argv: list[str] | tuple[str, ...],
    stdout: str,
    stderr: str,
    detections: list[str],
) -> Path:
    """Retain only non-sensitive metadata; never persist or hash rejected streams."""

    root = artifact_repo.resolve()
    ledger = root / "attempts" / invocation_id
    ledger.mkdir(parents=True, exist_ok=True)
    attempt_dir = ledger / f"attempt-{attempt:03d}"
    if attempt_dir.exists():
        raise FrontierCanaryError(
            f"Attempt already exists and cannot be overwritten: {attempt_dir}"
        )
    existing = sorted(path for path in ledger.iterdir() if path.is_dir())
    expected_existing = [f"attempt-{index:03d}" for index in range(1, attempt)]
    if [path.name for path in existing] != expected_existing:
        raise FrontierCanaryError("Attempt ledger is not a contiguous append-only prefix")
    attempt_dir.mkdir()
    document = {
        "schema_version": "drupal_agent_readiness.frontier_sensitive_output_rejection.v1",
        "invocation_id": invocation_id,
        "attempt": attempt,
        "run_id": f"run-{slot_id}",
        "roster_slot_id": slot_id,
        "argv": list(argv),
        "status": "rejected_before_persistence",
        "classification": "sensitive_output_detected",
        "detections": detections,
        "stdout_byte_size": len(stdout.encode("utf-8", errors="replace")),
        "stderr_byte_size": len(stderr.encode("utf-8", errors="replace")),
        "raw_bytes_retained": False,
        "raw_bytes_hashed": False,
    }
    path = attempt_dir / "security-rejection.json"
    _write_new(path, canonical_json_bytes(document))
    return path


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError as error:
        raise FrontierCanaryError(f"Refusing to overwrite append-only attempt evidence: {path}") from error


def _begin_attempt(
    artifact_repo: Path,
    *,
    invocation_id: str,
    attempt: int,
    slot_id: str,
    argv: list[str] | tuple[str, ...],
    stdout: str,
    stderr: str,
    returncode: int | None,
    timed_out: bool,
    runtime_home: dict[str, Any] | None = None,
    environment_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = artifact_repo.resolve()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}", invocation_id) is None:
        raise FrontierCanaryError("Attempt invocation_id is not a safe immutable identifier")
    ledger = root / "attempts" / invocation_id
    ledger.mkdir(parents=True, exist_ok=True)
    attempt_dir = ledger / f"attempt-{attempt:03d}"
    if attempt_dir.exists():
        raise FrontierCanaryError(f"Attempt already exists and cannot be overwritten: {attempt_dir}")
    existing = sorted(path for path in ledger.iterdir() if path.is_dir())
    expected_existing = [f"attempt-{index:03d}" for index in range(1, attempt)]
    if [path.name for path in existing] != expected_existing:
        raise FrontierCanaryError("Attempt ledger is not a contiguous append-only prefix")
    for previous in existing:
        if not (previous / "attempt-capture.json").is_file() or not (
            previous / "attempt-receipt.json"
        ).is_file():
            raise FrontierCanaryError(f"Attempt ledger contains an orphan: {previous}")
    try:
        attempt_dir.mkdir()
    except FileExistsError as error:
        raise FrontierCanaryError(f"Attempt already exists and cannot be overwritten: {attempt_dir}") from error
    stdout_bytes = stdout.encode("utf-8", errors="replace")
    stderr_bytes = stderr.encode("utf-8", errors="replace")
    stdout_path = attempt_dir / "codex.stdout.jsonl"
    stderr_path = attempt_dir / "codex.stderr.txt"
    _write_new(stdout_path, stdout_bytes)
    _write_new(stderr_path, stderr_bytes)
    environment_policy_bytes = canonical_json_bytes(environment_policy or {})
    process_containment_policy_bytes = canonical_json_bytes(
        (environment_policy or {}).get("process_containment", {})
    )
    capture = {
        "schema_version": "drupal_agent_readiness.frontier_attempt_capture.v1",
        "invocation_id": invocation_id,
        "attempt": attempt,
        "attempt_id": f"{invocation_id}-attempt-{attempt:03d}",
        "run_id": f"run-{slot_id}",
        "roster_slot_id": slot_id,
        "argv": list(argv),
        "returncode": returncode,
        "timed_out": timed_out,
        "classification": (
            "codex_timeout"
            if timed_out
            else classify_infrastructure_failure(
                returncode=returncode if returncode is not None else 1,
                stdout=stdout,
                stderr=stderr,
                tool_calls=count_codex_tool_calls(stdout),
            )
        ),
        "runtime_home": runtime_home,
        "environment_policy_sha256": "sha256:"
        + hashlib.sha256(environment_policy_bytes).hexdigest(),
        "process_containment_policy_sha256": "sha256:"
        + hashlib.sha256(process_containment_policy_bytes).hexdigest(),
        "stdout": {
            "uri": str(stdout_path.relative_to(root)),
            "sha256": "sha256:" + hashlib.sha256(stdout_bytes).hexdigest(),
            "byte_size": len(stdout_bytes),
        },
        "stderr": {
            "uri": str(stderr_path.relative_to(root)),
            "sha256": "sha256:" + hashlib.sha256(stderr_bytes).hexdigest(),
            "byte_size": len(stderr_bytes),
        },
    }
    capture_path = attempt_dir / "attempt-capture.json"
    capture_bytes = canonical_json_bytes(capture)
    _write_new(capture_path, capture_bytes)
    return {
        "root": root,
        "attempt_dir": attempt_dir,
        "capture": capture,
        "capture_path": capture_path,
        "capture_sha256": "sha256:" + hashlib.sha256(capture_bytes).hexdigest(),
    }


def _finalize_attempt(
    begun: dict[str, Any],
    *,
    status: str,
    thread_id: str | None,
    provider_request_id: str | None = None,
    provider_request_id_status: str = "unverified_not_reported",
    failure: str | None = None,
) -> dict[str, Any]:
    if status not in {"succeeded", "failed"}:
        raise FrontierCanaryError("Attempt terminal status must be succeeded or failed")
    capture = begun["capture"]
    if provider_request_id_status not in {
        "verified_distinct",
        "unverified_not_reported",
    }:
        raise FrontierCanaryError("Provider request identity status is invalid")
    if (
        provider_request_id_status == "verified_distinct"
        and (not isinstance(provider_request_id, str) or not provider_request_id)
    ) or (
        provider_request_id_status == "unverified_not_reported"
        and provider_request_id is not None
    ):
        raise FrontierCanaryError("Provider request identity does not match its verification status")
    if status == "succeeded" and (
        capture["returncode"] != 0
        or capture["timed_out"]
        or not isinstance(thread_id, str)
        or not thread_id
    ):
        raise FrontierCanaryError("A successful attempt requires returncode 0 and a thread identity")
    home = capture.get("runtime_home") or {}
    before = home.get("before") or {}
    after = home.get("after") or {}
    process_containment = home.get("process_containment") or {}
    tree_hash = before.get("system_skills_tree_sha256")
    profile_hash = before.get("permissions_profile_sha256")
    sentinel_hash = before.get("sentinel_sha256")
    if status == "succeeded" and not (
        before.get("mode") == "0o700"
        and after.get("mode") == "0o700"
        and before.get("home_identity_verified") is True
        and after.get("home_identity_verified") is True
        and before.get("home_mode_verified") is True
        and after.get("home_mode_verified") is True
        and before.get("layout_verified") is True
        and after.get("layout_verified") is True
        and isinstance(before.get("layout_sha256"), str)
        and isinstance(after.get("layout_sha256"), str)
        and runtime_home_layout_document_valid(before.get("layout_document"))
        and runtime_home_layout_document_valid(after.get("layout_document"))
        and before["layout_document"]["tree_sha256"]
        == before.get("layout_sha256")
        and after["layout_document"]["tree_sha256"]
        == after.get("layout_sha256")
        and before.get("auth_reference_verified") is True
        and after.get("auth_reference_verified") is True
        and before.get("permissions_profile_regular_file_verified") is True
        and after.get("permissions_profile_regular_file_verified") is True
        and before.get("sentinel_regular_file_verified") is True
        and after.get("sentinel_regular_file_verified") is True
        and process_containment.get("status") == "verified"
        and process_containment.get("child_process_creation_denied") is True
        and process_containment.get("policy_sha256")
        == capture.get("process_containment_policy_sha256")
        and process_containment.get("inner_argv") == capture.get("argv")
        and process_containment.get("outer_argv", [None, None, None])[3:]
        == capture.get("argv")
        and before.get("forbidden_entries") == []
        and after.get("forbidden_entries") == []
        and before.get("system_skills_verified") is True
        and after.get("system_skills_verified") is True
        and isinstance(tree_hash, str)
        and tree_hash == after.get("system_skills_tree_sha256")
        and isinstance(profile_hash, str)
        and profile_hash == after.get("permissions_profile_sha256")
        and isinstance(sentinel_hash, str)
        and sentinel_hash == after.get("sentinel_sha256")
    ):
        raise FrontierCanaryError("Successful attempt lacks exact runtime-home/system-skill verification")
    receipt = {
        "schema_version": (
            "drupal_agent_readiness.frontier_attempt_receipt.v1"
            if status == "succeeded"
            else "drupal_agent_readiness.frontier_failed_attempt_receipt.v1"
        ),
        "run_id": capture["run_id"],
        "roster_slot_id": capture["roster_slot_id"],
        "attempt_id": capture["attempt_id"],
        "argv": capture["argv"],
        "status": status,
        "returncode": capture["returncode"],
        "timed_out": capture["timed_out"],
        "thread_id": thread_id,
        "provider_request_id": provider_request_id,
        "provider_request_id_status": provider_request_id_status,
        "environment_policy_sha256": capture["environment_policy_sha256"],
        "process_containment": process_containment,
        "runtime_home_verification": {
            "before_home_mode": before.get("mode"),
            "after_home_mode": after.get("mode"),
            "before_home_identity_verified": before.get("home_identity_verified"),
            "after_home_identity_verified": after.get("home_identity_verified"),
            "before_home_mode_verified": before.get("home_mode_verified"),
            "after_home_mode_verified": after.get("home_mode_verified"),
            "before_layout_verified": before.get("layout_verified"),
            "after_layout_verified": after.get("layout_verified"),
            "before_layout_sha256": before.get("layout_sha256"),
            "after_layout_sha256": after.get("layout_sha256"),
            "before_layout_document": before.get("layout_document"),
            "after_layout_document": after.get("layout_document"),
            "before_auth_reference_verified": before.get("auth_reference_verified"),
            "after_auth_reference_verified": after.get("auth_reference_verified"),
            "before_profile_regular_file_verified": before.get(
                "permissions_profile_regular_file_verified"
            ),
            "after_profile_regular_file_verified": after.get(
                "permissions_profile_regular_file_verified"
            ),
            "before_sentinel_regular_file_verified": before.get(
                "sentinel_regular_file_verified"
            ),
            "after_sentinel_regular_file_verified": after.get(
                "sentinel_regular_file_verified"
            ),
            "before_forbidden_entries": before.get("forbidden_entries"),
            "after_forbidden_entries": after.get("forbidden_entries"),
            "before_system_skills_verified": before.get("system_skills_verified"),
            "after_system_skills_verified": after.get("system_skills_verified"),
            "system_skills_tree_sha256": tree_hash,
            "before_permissions_profile_sha256": profile_hash,
            "after_permissions_profile_sha256": after.get(
                "permissions_profile_sha256"
            ),
            "before_sentinel_sha256": sentinel_hash,
            "after_sentinel_sha256": after.get("sentinel_sha256"),
        },
        "stdout_artifact_id": f"{capture['run_id']}-attempt-stdout",
        "stdout_sha256": capture["stdout"]["sha256"],
        "stderr_artifact_id": f"{capture['run_id']}-attempt-stderr",
        "stderr_sha256": capture["stderr"]["sha256"],
    }
    if status == "failed":
        receipt["classification"] = capture["classification"]
        receipt["failure"] = failure
    receipt_path = begun["attempt_dir"] / "attempt-receipt.json"
    receipt_bytes = canonical_json_bytes(receipt)
    _write_new(receipt_path, receipt_bytes)
    return {
        "uri": str(receipt_path.relative_to(begun["root"])),
        "sha256": "sha256:" + hashlib.sha256(receipt_bytes).hexdigest(),
        "media_type": "application/json",
        "byte_size": len(receipt_bytes),
        "attempt_id": receipt["attempt_id"],
        "run_id": receipt["run_id"],
        "roster_slot_id": receipt["roster_slot_id"],
        "stdout": capture["stdout"],
        "stderr": capture["stderr"],
    }


def _finalize_semantically_valid_attempt(
    begun: dict[str, Any], *, slot_id: str, stderr: str
) -> dict[str, Any]:
    stdout_path = begun["root"] / begun["capture"]["stdout"]["uri"]
    thread_id: str | None = None
    try:
        retained = _parse_retained_codex_jsonl(stdout_path, slot_id=slot_id)
        thread_id = retained["thread_id"]
        returncode = begun["capture"]["returncode"]
        if returncode != 0:
            raise FrontierCanaryError(
                "Codex invocation failed; "
                + _failure_context([], returncode=returncode, stderr=stderr)
            )
    except FrontierCanaryError as error:
        receipt = _finalize_attempt(
            begun,
            status="failed",
            thread_id=thread_id,
            failure=str(error),
        )
        raise FrontierCanaryError(f"{error}; attempt_receipt={receipt['uri']}") from error
    return _finalize_attempt(
        begun,
        status="succeeded",
        thread_id=thread_id,
        failure=None,
    )


def _isolated_environment(
    home: Path, *, environment_policy: dict[str, Any] | None = None
) -> dict[str, str]:
    inherited = ISOLATED_ENVIRONMENT_POLICY["inherited_environment_keys"]
    pinned = (environment_policy or {}).get("inherited_environment")
    if pinned is not None:
        if not isinstance(pinned, dict) or any(
            key not in inherited or not isinstance(value, str)
            for key, value in pinned.items()
        ):
            raise FrontierCanaryError("Pinned inherited environment is malformed")
        environment = dict(pinned)
    else:
        environment = {key: os.environ[key] for key in inherited if key in os.environ}
    environment["CODEX_HOME"] = str(home)
    environment["HOME"] = str(home)
    return environment


def _system_skill_manifest(home: Path) -> dict[str, Any]:
    skills_root = home / "skills"
    system_root = skills_root / ".system"
    if os.path.lexists(skills_root) and (
        skills_root.is_symlink() or not skills_root.is_dir()
    ):
        raise FrontierCanaryError(
            "Bundled skills root exists but is not a real directory"
        )
    if not os.path.lexists(system_root):
        if os.path.lexists(skills_root):
            raise FrontierCanaryError(
                "Bundled skills root exists without the registered .system tree"
            )
        file_manifest = {
            "schema_version": "drupal_agent_readiness.system_skills_manifest.v1",
            "directories": [],
            "files": [],
        }
        return {
            **file_manifest,
            "tree_sha256": "sha256:"
            + hashlib.sha256(canonical_json_bytes(file_manifest)).hexdigest(),
        }
    if system_root.is_symlink() or not system_root.is_dir():
        raise FrontierCanaryError(
            "Bundled system-skill root exists but is not a real directory"
        )
    directories: list[dict[str, Any]] = [
        {
            "path": skills_root.relative_to(home).as_posix(),
            "mode": oct(stat.S_IMODE(skills_root.lstat().st_mode)),
        },
        {
            "path": system_root.relative_to(home).as_posix(),
            "mode": oct(stat.S_IMODE(system_root.lstat().st_mode)),
        },
    ]
    if any(
        int(item["mode"], 8) & 0o7022
        or int(item["mode"], 8) & 0o500 != 0o500
        for item in directories
    ):
        raise FrontierCanaryError(
            "Bundled system-skill directories have unsafe permissions"
        )
    files: list[dict[str, Any]] = []
    for path in sorted(
        system_root.rglob("*"), key=lambda item: item.relative_to(home).as_posix()
    ):
        if path.is_symlink():
            raise FrontierCanaryError(f"Bundled system-skill tree contains a symlink: {path}")
        if path.is_dir():
            directory = {
                "path": path.relative_to(home).as_posix(),
                "mode": oct(stat.S_IMODE(path.lstat().st_mode)),
            }
            if int(directory["mode"], 8) & 0o7022 or int(
                directory["mode"], 8
            ) & 0o500 != 0o500:
                raise FrontierCanaryError(
                    f"Bundled system-skill directory has unsafe permissions: {path}"
                )
            directories.append(directory)
            continue
        if not path.is_file():
            raise FrontierCanaryError(f"Bundled system-skill tree contains an unsupported entry: {path}")
        payload = path.read_bytes()
        mode = oct(stat.S_IMODE(path.lstat().st_mode))
        if (
            int(mode, 8) & 0o7022
            or not int(mode, 8) & 0o400
            or path.lstat().st_nlink != 1
        ):
            raise FrontierCanaryError(
                f"Bundled system-skill file has unsafe permissions: {path}"
            )
        files.append(
            {
                "path": path.relative_to(home).as_posix(),
                "mode": mode,
                "byte_size": len(payload),
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            }
        )
    if not files:
        raise FrontierCanaryError("Bundled system-skill tree is empty")
    file_manifest = {
        "schema_version": "drupal_agent_readiness.system_skills_manifest.v1",
        "directories": directories,
        "files": files,
    }
    return {
        **file_manifest,
        "tree_sha256": "sha256:"
        + hashlib.sha256(canonical_json_bytes(file_manifest)).hexdigest(),
    }


def _bootstrap_environment(home: Path) -> dict[str, str]:
    resolved = home.resolve()
    tmpdir = resolved / "os-tmp"
    tmpdir.mkdir(mode=0o700, exist_ok=True)
    if tmpdir.is_symlink() or not tmpdir.is_dir():
        raise FrontierCanaryError("Bootstrap TMPDIR is not a private real directory")
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "SHELL": "/bin/sh",
        "TERM": "dumb",
        "HOME": str(resolved),
        "CODEX_HOME": str(resolved),
        "TMPDIR": str(tmpdir),
    }


def _bootstrap_home_manifest(
    home: Path,
    *,
    expected_arg0_symlink_target: Path | None = None,
    expected_root_identity: tuple[int, int] | None = None,
) -> dict[str, Any]:
    root = home.absolute()
    try:
        root_stat = root.lstat()
    except OSError as error:
        raise FrontierCanaryError("Bootstrap home is missing") from error
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or expected_root_identity is not None
        and (root_stat.st_dev, root_stat.st_ino) != expected_root_identity
    ):
        raise FrontierCanaryError("Bootstrap home is not a real directory")
    root_mode = oct(stat.S_IMODE(root_stat.st_mode))
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            expected = expected_arg0_symlink_target.resolve() if expected_arg0_symlink_target else None
            if (
                expected is None
                or re.fullmatch(
                    r"tmp/arg0/codex-arg0[A-Za-z0-9]+/"
                    r"(?:apply_patch|applypatch|codex-execve-wrapper)",
                    relative,
                )
                is None
                or str(path.readlink()) != str(expected)
                or path.resolve() != expected
                or not path.resolve().is_file()
            ):
                raise FrontierCanaryError(
                    f"Bootstrap home contains an unregistered symlink: {relative}"
                )
            entries.append(
                {
                    "path": relative,
                    "kind": "symlink",
                    "mode": oct(stat.S_IMODE(path.lstat().st_mode)),
                    "target": str(path.readlink()),
                    "resolved_sha256": file_sha256(expected),
                }
            )
        elif path.is_dir():
            entries.append(
                {
                    "path": relative,
                    "kind": "directory",
                    "mode": oct(stat.S_IMODE(path.lstat().st_mode)),
                }
            )
        elif path.is_file():
            payload = path.read_bytes()
            entries.append(
                {
                    "path": relative,
                    "kind": "file",
                    "mode": oct(stat.S_IMODE(path.lstat().st_mode)),
                    "byte_size": len(payload),
                    "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                }
            )
        else:
            raise FrontierCanaryError(
                f"Bootstrap home contains an unsupported entry: {relative}"
            )
    body = {
        "schema_version": "drupal_agent_readiness.bootstrap_home_manifest.v1",
        "root_mode": root_mode,
        "entries": entries,
    }
    return {
        **body,
        "tree_sha256": "sha256:"
        + hashlib.sha256(canonical_json_bytes(body)).hexdigest(),
    }


def _prove_network_denial(
    network_sandbox_binary: Path,
    *,
    sandbox_profile: str,
    network_sandbox_sha256: str,
    python_binary: Path,
    python_sha256: str,
) -> dict[str, Any]:
    sandbox_invocation = network_sandbox_binary.absolute()
    sandbox = sandbox_invocation.resolve()
    python = python_binary.resolve()
    if (
        not sandbox_invocation.is_file()
        or not sandbox.is_file()
        or file_sha256(sandbox) != network_sandbox_sha256
        or not python.is_file()
        or file_sha256(python) != python_sha256
    ):
        raise FrontierCanaryError("Network-denial probe executable bytes do not match their pins")
    home = Path(tempfile.mkdtemp(prefix="drupal-agent-canary-network-proof-")).resolve()
    home.chmod(0o700)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        host, port = listener.getsockname()
        with socket.create_connection((host, port), timeout=2):
            control, _ = listener.accept()
            control.close()
        command = [
            str(sandbox_invocation),
            "-p",
            sandbox_profile,
            str(python),
            "-I",
            "-S",
            "-c",
            SYSTEM_SKILL_NETWORK_PROBE_CODE,
            host,
            str(port),
        ]
        probe_environment = _bootstrap_environment(home)
        completed = run_command(
            command,
            input=None,
            cwd=home,
            env=probe_environment,
            text=True,
            capture_output=True,
            timeout=10,
        )
        listener.settimeout(0.25)
        sandbox_connected = False
        try:
            leaked, _ = listener.accept()
        except TimeoutError:
            pass
        else:
            sandbox_connected = True
            leaked.close()
        probe_stdout = completed.stdout or ""
        probe_stderr = completed.stderr or ""
        if completed.returncode == 0 or sandbox_connected:
            raise FrontierCanaryError("Network-denial sandbox allowed a loopback connection")
        if (
            completed.returncode != SYSTEM_SKILL_NETWORK_PROBE_EXIT_CODE
            or probe_stdout != SYSTEM_SKILL_NETWORK_PROBE_STDOUT
            or probe_stderr != SYSTEM_SKILL_NETWORK_PROBE_STDERR
        ):
            raise FrontierCanaryError(
                "Network-denial probe did not produce the exact in-sandbox denial proof"
            )
        if (
            file_sha256(sandbox) != network_sandbox_sha256
            or file_sha256(python) != python_sha256
        ):
            raise FrontierCanaryError("Network-denial probe executable changed during proof")
        profile_sha256 = "sha256:" + hashlib.sha256(
            sandbox_profile.encode("utf-8")
        ).hexdigest()
        return {
            "status": "verified",
            "control_connected": True,
            "sandbox_connected": False,
            "returncode": completed.returncode,
            "argv": command,
            "environment": probe_environment,
            "sandbox_profile": sandbox_profile,
            "sandbox_profile_sha256": profile_sha256,
            "stdout": probe_stdout,
            "stderr": probe_stderr,
            "stdout_sha256": "sha256:"
            + hashlib.sha256(probe_stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": "sha256:"
            + hashlib.sha256(probe_stderr.encode("utf-8")).hexdigest(),
            "stdout_byte_size": len(probe_stdout.encode("utf-8")),
            "stderr_byte_size": len(probe_stderr.encode("utf-8")),
        }
    finally:
        listener.close()
        shutil.rmtree(home)


def _preflight_system_skills(
    codex_binary: Path,
    *,
    codex_sha256: str,
    network_sandbox_binary: Path,
    network_sandbox_sha256: str,
    python_binary: Path,
    python_sha256: str,
    permissions_profile: Mapping[str, Any],
    host_read_denials: Mapping[str, Mapping[str, str]],
    workdir: Path,
    output_schema: Path,
    model: str,
) -> dict[str, Any]:
    binary = codex_binary.resolve()
    sandbox_invocation = network_sandbox_binary.absolute()
    sandbox = sandbox_invocation.resolve()
    python = python_binary.resolve()
    if (
        not binary.is_file()
        or file_sha256(binary) != codex_sha256
        or not sandbox_invocation.is_file()
        or not sandbox.is_file()
        or file_sha256(sandbox) != network_sandbox_sha256
        or not python.is_file()
        or file_sha256(python) != python_sha256
    ):
        raise FrontierCanaryError("System-skill bootstrap executable bytes do not match their pins")
    profile_text = permissions_profile.get("profile_text")
    profile_sha256 = permissions_profile.get("profile_sha256")
    if not isinstance(profile_text, str) or not isinstance(profile_sha256, str):
        raise FrontierCanaryError("System-skill bootstrap permissions profile is malformed")
    if set(host_read_denials) != set(SYSTEM_SKILL_REQUIRED_HOST_DENIALS):
        raise FrontierCanaryError("System-skill bootstrap host read denials are incomplete")
    if dict(host_read_denials) != expected_system_skill_host_denials():
        raise FrontierCanaryError(
            "System-skill bootstrap host read denial identities are not exact"
        )
    sandbox_profile = build_system_skill_bootstrap_sandbox_profile(host_read_denials)
    network_probe = _prove_network_denial(
        sandbox_invocation,
        sandbox_profile=sandbox_profile,
        network_sandbox_sha256=network_sandbox_sha256,
        python_binary=python,
        python_sha256=python_sha256,
    )
    home = Path(tempfile.mkdtemp(prefix="drupal-agent-canary-system-skills-")).resolve()
    home.chmod(0o700)
    home_stat = home.lstat()
    home_identity = (home_stat.st_dev, home_stat.st_ino)
    try:
        profile = home / f"{CODEX_CONFIG_PROFILE}.config.toml"
        profile.write_text(profile_text, encoding="utf-8")
        profile.chmod(0o600)
        if file_sha256(profile) != profile_sha256 or os.path.lexists(home / "auth.json"):
            raise FrontierCanaryError(
                "System-skill bootstrap did not start from the preregistered unauthenticated home"
            )
        bootstrap_environment = _bootstrap_environment(home)
        initial_home = _bootstrap_home_manifest(
            home, expected_root_identity=home_identity
        )
        if [entry["path"] for entry in initial_home["entries"]] != [
            f"{CODEX_CONFIG_PROFILE}.config.toml",
            "os-tmp",
        ]:
            raise FrontierCanaryError("System-skill bootstrap initial home is not exact")
        inner = build_codex_argv(
            binary,
            workdir=workdir,
            output_schema=output_schema,
            model=model,
        )
        command = [
            str(sandbox_invocation),
            "-p",
            sandbox_profile,
            *inner,
        ]
        completed = run_command(
            command,
            input=SYSTEM_SKILL_BOOTSTRAP_PROMPT,
            cwd=workdir,
            env=bootstrap_environment,
            text=True,
            capture_output=True,
            timeout=60,
        )
        events = _events(completed.stdout or "")
        event_types = [str(event.get("type", "")) for event in events]
        provider_response_received = any(
            event.get("type") == "turn.completed"
            or (
                event.get("type") == "item.completed"
                and isinstance(event.get("item"), dict)
                and event["item"].get("type") == "agent_message"
            )
            for event in events
        )
        allowed_events = all(
            event.get("type")
            in {"thread.started", "turn.started", "error", "turn.failed"}
            or (
                event.get("type") == "item.completed"
                and isinstance(event.get("item"), dict)
                and event["item"].get("type") == "error"
            )
            for event in events
        )
        transport_failure_class = classify_system_skill_bootstrap_transport(
            events,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        if (
            completed.returncode == 0
            or event_types.count("thread.started") != 1
            or event_types.count("turn.started") != 1
            or event_types.count("turn.failed") != 1
            or not allowed_events
            or provider_response_received
            or count_codex_tool_calls(completed.stdout or "") != 0
        ):
            raise FrontierCanaryError(
                "Network-denied system-skill bootstrap produced unexpected execution semantics"
            )
        if _sensitive_output_detections(
            completed.stdout or "",
            completed.stderr or "",
            sentinel_token="frontier-bootstrap-nonsecret-sentinel-not-emitted",
        ):
            raise FrontierCanaryError("System-skill bootstrap emitted secret-shaped output")
        if (
            os.path.lexists(home / "auth.json")
            or file_sha256(profile) != profile_sha256
            or os.path.lexists(home / "plugins")
            or os.path.lexists(home / ".tmp")
            or os.path.lexists(home / "config.toml")
        ):
            raise FrontierCanaryError(
                "System-skill bootstrap acquired auth, plugins, or unregistered config"
            )
        skills = home / "skills"
        if (
            not skills.is_dir()
            or skills.is_symlink()
            or sorted(path.name for path in skills.iterdir()) != [".system"]
        ):
            raise FrontierCanaryError(
                "System-skill bootstrap acquired skills outside the bundled system tree"
            )
        manifest = _system_skill_manifest(home)
        if not manifest["files"]:
            raise FrontierCanaryError("Codex bootstrap materialized no bundled system skills")
        top_level = {path.name for path in home.iterdir()}
        if top_level != SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL:
            raise FrontierCanaryError(
                "System-skill bootstrap final home has unexpected top-level entries: "
                f"missing={sorted(SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL - top_level)}; "
                f"extra={sorted(top_level - SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL)}"
            )
        final_home = _bootstrap_home_manifest(
            home,
            expected_arg0_symlink_target=binary,
            expected_root_identity=home_identity,
        )
        retained_skill_payloads = []
        for item in manifest["files"]:
            payload = (home / item["path"]).read_bytes()
            retained_skill_payloads.append(
                {
                    "path": item["path"],
                    "content_base64": base64.b64encode(payload).decode("ascii"),
                }
            )
        if (
            file_sha256(binary) != codex_sha256
            or file_sha256(sandbox) != network_sandbox_sha256
            or file_sha256(python) != python_sha256
        ):
            raise FrontierCanaryError("System-skill bootstrap executable changed during startup")
        sandbox_profile_sha256 = "sha256:" + hashlib.sha256(
            sandbox_profile.encode("utf-8")
        ).hexdigest()
        return {
            "home": home,
            "system_root": home / "skills" / ".system",
            "manifest": manifest,
            "receipt": {
                "bootstrap_kind": "unauthenticated_network_denied_codex_startup",
                "command": command,
                "environment": bootstrap_environment,
                "prompt": SYSTEM_SKILL_BOOTSTRAP_PROMPT,
                "prompt_sha256": "sha256:"
                + hashlib.sha256(SYSTEM_SKILL_BOOTSTRAP_PROMPT.encode()).hexdigest(),
                "prompt_byte_size": len(SYSTEM_SKILL_BOOTSTRAP_PROMPT.encode()),
                "model_turn_started": True,
                "network_egress_denied": True,
                "provider_exchange_observed": False,
                "auth_present": False,
                "provider_response_received": False,
                "transport_failure_class": transport_failure_class,
                "returncode": completed.returncode,
                "event_types": event_types,
                "stdout": completed.stdout or "",
                "stderr": completed.stderr or "",
                "stdout_sha256": "sha256:"
                + hashlib.sha256((completed.stdout or "").encode("utf-8")).hexdigest(),
                "stderr_sha256": "sha256:"
                + hashlib.sha256((completed.stderr or "").encode("utf-8")).hexdigest(),
                "stdout_byte_size": len((completed.stdout or "").encode("utf-8")),
                "stderr_byte_size": len((completed.stderr or "").encode("utf-8")),
                "sandbox_profile": sandbox_profile,
                "sandbox_profile_sha256": sandbox_profile_sha256,
                "host_read_denials": {
                    name: dict(value) for name, value in sorted(host_read_denials.items())
                },
                "permissions_profile_sha256": profile_sha256,
                "output_schema_sha256": file_sha256(output_schema),
                "codex_sha256": codex_sha256,
                "network_sandbox_sha256": network_sandbox_sha256,
                "python_sha256": python_sha256,
                "sandbox_platform": {
                    "sys_platform": sys.platform,
                    "sysname": os.uname().sysname,
                    "release": os.uname().release,
                    "version": os.uname().version,
                    "machine": os.uname().machine,
                },
                "network_denial_probe": network_probe,
                "initial_home": initial_home,
                "final_home": final_home,
                "manifest": manifest,
                "retained_skill_payloads": retained_skill_payloads,
                "stream_retention": {
                    "uri": "pins/agent/execution-environment-policy.json",
                    "stdout_json_pointer": "/system_skills_preflight/stdout",
                    "stderr_json_pointer": "/system_skills_preflight/stderr",
                    "skill_payloads_json_pointer": (
                        "/system_skills_preflight/retained_skill_payloads"
                    ),
                    "scope": "private_canary_evidence_not_public_distribution",
                },
            },
        }
    except BaseException:
        shutil.rmtree(home)
        raise


def _preflight_permissions_profile(
    codex_binary: Path,
    *,
    workspace: Path,
    sentinel_token: str,
    host_probe_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Prove the exact named tool policy can read only the governed snapshot."""

    binary = codex_binary.resolve()
    probes_by_path = host_probe_paths or {}
    required_probes = {
        "observed_root_unreadable",
        "ddev_binary_unreadable",
        "docker_binary_minimal_runtime_readable",
        "docker_socket_unreadable",
    }
    if set(probes_by_path) != required_probes:
        raise FrontierCanaryError(
            "Permission preflight requires exact observed-root, DDEV, Docker, and socket probes"
        )
    for name, path in probes_by_path.items():
        if not os.path.lexists(path) or not os.access(path, os.R_OK):
            raise FrontierCanaryError(f"Unsandboxed denial probe input is unreadable: {name}")
    profile_text = _permissions_profile_text(probes_by_path)
    profile_bytes = profile_text.encode("utf-8")
    home = Path(tempfile.mkdtemp(prefix="drupal-agent-canary-permission-probe-"))
    home.chmod(0o700)
    target = home.parent / f"frontier-nonsecret-auth-target-{uuid.uuid4().hex}"
    target.touch(mode=0o600)
    (home / "auth.json").symlink_to(target)
    (home / "frontier-canary-sentinel").write_text(sentinel_token, encoding="utf-8")
    (home / f"{CODEX_CONFIG_PROFILE}.config.toml").write_bytes(profile_bytes)
    marker = workspace / "governed-observation.json"
    if not marker.is_file():
        shutil.rmtree(home)
        target.unlink(missing_ok=True)
        raise FrontierCanaryError("Permission preflight workspace lacks governed-observation.json")
    git_probe_root = workspace / ".git"
    if os.path.lexists(git_probe_root):
        shutil.rmtree(home)
        target.unlink(missing_ok=True)
        raise FrontierCanaryError("Permission preflight workspace already contains .git")
    git_probe_root.mkdir()
    (git_probe_root / "frontier-canary-sentinel").write_text(
        sentinel_token,
        encoding="utf-8",
    )

    base = [
        str(binary),
        "sandbox",
        "-p",
        CODEX_CONFIG_PROFILE,
        "-P",
        CODEX_PERMISSION_PROFILE,
        "-C",
        str(workspace.resolve()),
        "--",
        "/bin/sh",
        "-c",
    ]
    probes: dict[str, tuple[str, list[str]]] = {
        "workspace_readable": ("test -r ./governed-observation.json", []),
        "auth_unreadable": ('test ! -r "$HOME/auth.json"', []),
        "sentinel_unreadable": ('test ! -r "$HOME/frontier-canary-sentinel"', []),
        "git_metadata_unreadable": (
            'test ! -r "./.git/frontier-canary-sentinel"',
            [],
        ),
    }
    probes.update(
        {
            name: (
                'test -r "$1"'
                if name == "docker_binary_minimal_runtime_readable"
                else 'test ! -r "$1"',
                ["frontier-host-probe", str(path.resolve())],
            )
            for name, path in probes_by_path.items()
        }
    )
    receipts: dict[str, Any] = {}
    try:
        if not os.access(home / "auth.json", os.R_OK) or not os.access(
            home / "frontier-canary-sentinel", os.R_OK
        ):
            raise FrontierCanaryError("Non-sandboxed permission probe inputs are not readable")
        for name, (expression, arguments) in probes.items():
            command = [*base, expression, *arguments]
            completed = run_command(
                command,
                input=None,
                cwd=workspace,
                env=_isolated_environment(home),
                text=True,
                capture_output=True,
                timeout=60,
            )
            receipts[name] = {
                "argv": command,
                "returncode": completed.returncode,
                "stdout_byte_size": len((completed.stdout or "").encode("utf-8")),
                "stderr_byte_size": len((completed.stderr or "").encode("utf-8")),
            }
            if completed.returncode != 0:
                raise FrontierCanaryError(
                    f"Named permissions profile failed {name} probe with exit "
                    f"{completed.returncode}"
                )
        return {
            "config_profile": CODEX_CONFIG_PROFILE,
            "permissions_profile": CODEX_PERMISSION_PROFILE,
            "profile_filename": f"{CODEX_CONFIG_PROFILE}.config.toml",
            "profile_text": profile_text,
            "profile_sha256": "sha256:" + hashlib.sha256(profile_bytes).hexdigest(),
            "sentinel_filename": "frontier-canary-sentinel",
            "sentinel_sha256": "sha256:"
            + hashlib.sha256(sentinel_token.encode("utf-8")).hexdigest(),
            "host_probe_paths": {
                name: str(path.resolve()) for name, path in probes_by_path.items()
            },
            "probe_receipts": receipts,
            "model_call": False,
            "resolved_policy": (
                "root denied; minimal binaries read; snapshot workspace read; temp, network, "
                "auth.json, sentinel, all .git metadata, observed root, DDEV, and Docker "
                "socket denied; Docker CLI remains readable as part of :minimal but is inert"
            ),
        }
    finally:
        shutil.rmtree(git_probe_root, ignore_errors=True)
        shutil.rmtree(home)
        target.unlink(missing_ok=True)


def _home_layout(
    home: Path,
    *,
    require_initial: bool = False,
    expected_home_identity: tuple[int, int],
    expected_auth_target: Path,
    expected_arg0_target: Path,
    expected_system_skills: dict[str, Any] | None = None,
    expected_profile_sha256: str | None = None,
    expected_sentinel_sha256: str | None = None,
    expected_model_cache_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entries: list[str] = []
    layout_entries: list[dict[str, str]] = []
    forbidden: list[str] = []
    try:
        home_stat = home.lstat()
    except OSError:
        home_stat = None
    home_identity_verified = bool(
        home_stat is not None
        and stat.S_ISDIR(home_stat.st_mode)
        and (home_stat.st_dev, home_stat.st_ino) == expected_home_identity
    )
    home_mode = oct(stat.S_IMODE(home_stat.st_mode)) if home_stat is not None else None
    home_mode_verified = home_mode == "0o700"
    if not home_identity_verified:
        forbidden.append("CODEX_HOME:identity-or-type-mismatch")
    if not home_mode_verified:
        forbidden.append("CODEX_HOME:mode-mismatch")
    model_cache_registered = model_cache_contract_valid(
        expected_model_cache_contract
    )
    if expected_model_cache_contract is not None and not model_cache_registered:
        forbidden.append("models_cache.json:invalid-preregistered-contract")
    if not home_identity_verified:
        return {
            "mode": home_mode,
            "home_identity_verified": False,
            "home_mode_verified": home_mode_verified,
            "entries": entries,
            "layout_entries": layout_entries,
            "layout_verified": False,
            "layout_sha256": None,
            "layout_document": None,
            "auth_reference": "exact target not verified",
            "auth_reference_verified": False,
            "permissions_profile_regular_file_verified": False,
            "sentinel_regular_file_verified": False,
            "permissions_profile_sha256": None,
            "sentinel_sha256": None,
            "system_skills_verified": False
            if expected_system_skills is not None
            else None,
            "system_skills_tree_sha256": None,
            "forbidden_entries": sorted(set(forbidden)),
        }
    for path in sorted(home.rglob("*"), key=lambda item: item.relative_to(home).as_posix()):
        relative = path.relative_to(home).as_posix()
        entries.append(relative)
        path_stat = path.lstat()
        mode = oct(stat.S_IMODE(path_stat.st_mode))
        if path.is_symlink():
            kind = "symlink"
        elif path.is_dir():
            kind = "directory"
        elif path.is_file():
            kind = "file"
        else:
            kind = "unsupported"
        layout_entry = {"path": relative, "kind": kind, "mode": mode}
        if kind == "file" and relative == "models_cache.json":
            layout_entry.update(
                {
                    "byte_size": path_stat.st_size,
                    "sha256": file_sha256(path),
                }
            )
        layout_entries.append(layout_entry)
        parts = Path(relative).parts
        lowered_parts = {part.lower() for part in parts}
        allowed_system = (
            relative == "skills"
            or relative == "skills/.system"
            or relative.startswith("skills/.system/")
        )
        if path.is_symlink():
            allowed_auth = relative == "auth.json"
            allowed_arg0 = bool(
                not require_initial
                and re.fullmatch(
                    r"tmp/arg0/codex-arg0[A-Za-z0-9]+/"
                    r"(?:apply_patch|applypatch|codex-execve-wrapper)",
                    relative,
                )
                and str(path.readlink()) == str(expected_arg0_target)
                and path.resolve() == expected_arg0_target
            )
            if not allowed_auth and not allowed_arg0:
                forbidden.append(f"unexpected-symlink:{relative}")
            elif allowed_auth:
                layout_entry.update(
                    {
                        "target_role": "credential_reference",
                        "target_path_sha256": "sha256:"
                        + hashlib.sha256(str(expected_auth_target).encode()).hexdigest(),
                    }
                )
            else:
                layout_entry.update(
                    {
                        "target_role": "codex_binary",
                        "target_path_sha256": "sha256:"
                        + hashlib.sha256(str(expected_arg0_target).encode()).hexdigest(),
                        "resolved_file_sha256": file_sha256(expected_arg0_target),
                    }
                )
        elif path.is_dir():
            if stat.S_IMODE(path_stat.st_mode) & 0o7022 or (
                stat.S_IMODE(path_stat.st_mode) & 0o500
            ) != 0o500:
                forbidden.append(f"unsafe-directory-mode:{relative}")
        elif path.is_file():
            forbidden_mode_mask = 0o7022 if allowed_system else 0o7133
            if (
                stat.S_IMODE(path_stat.st_mode) & forbidden_mode_mask
                or not stat.S_IMODE(path_stat.st_mode) & 0o400
                or path_stat.st_nlink != 1
            ):
                forbidden.append(f"unsafe-file-mode-or-link-count:{relative}")
            if relative == "models_cache.json" and (
                not model_cache_registered
                or mode != "0o400"
                or layout_entry["sha256"]
                != expected_model_cache_contract["file_sha256"]
                or layout_entry["byte_size"]
                != expected_model_cache_contract["byte_size"]
            ):
                forbidden.append("models_cache.json:content-or-mode-mismatch")
        else:
            forbidden.append(f"unsupported-entry:{relative}")
        if (
            ("skills" in lowered_parts and not allowed_system)
            or lowered_parts.intersection({"plugins", "memories", "apps"})
            or Path(relative).name.lower() == "config.toml"
        ):
            forbidden.append(relative)
        if (
            require_initial
            and expected_system_skills is not None
            and relative != "auth.json"
            and relative != f"{CODEX_CONFIG_PROFILE}.config.toml"
            and relative != "frontier-canary-sentinel"
            and not (model_cache_registered and relative == "models_cache.json")
            and not allowed_system
        ):
            forbidden.append(f"unexpected:{relative}")
    auth = home / "auth.json"
    auth_reference_verified = False
    if auth.is_symlink():
        try:
            auth_reference_verified = bool(
                str(auth.readlink()) == str(expected_auth_target)
                and auth.resolve(strict=True) == expected_auth_target
                and expected_auth_target.is_file()
            )
        except OSError:
            pass
    if not auth_reference_verified:
        forbidden.append("auth.json:target-mismatch")
    system_verified: bool | None = None
    system_tree_sha256: str | None = None
    if expected_system_skills is not None:
        try:
            observed_manifest = _system_skill_manifest(home)
        except FrontierCanaryError:
            observed_manifest = None
        system_verified = observed_manifest == expected_system_skills
        system_tree_sha256 = (
            observed_manifest.get("tree_sha256") if observed_manifest is not None else None
        )
        if not system_verified:
            forbidden.append("skills/.system:manifest-mismatch")
    profile = home / f"{CODEX_CONFIG_PROFILE}.config.toml"
    sentinel = home / "frontier-canary-sentinel"
    profile_regular = bool(
        os.path.lexists(profile)
        and not profile.is_symlink()
        and stat.S_ISREG(profile.lstat().st_mode)
        and stat.S_IMODE(profile.lstat().st_mode) == 0o600
    )
    sentinel_regular = bool(
        os.path.lexists(sentinel)
        and not sentinel.is_symlink()
        and stat.S_ISREG(sentinel.lstat().st_mode)
        and stat.S_IMODE(sentinel.lstat().st_mode) == 0o600
    )
    profile_sha256 = file_sha256(profile) if profile_regular else None
    sentinel_sha256 = file_sha256(sentinel) if sentinel_regular else None
    if not profile_regular:
        forbidden.append(f"{CODEX_CONFIG_PROFILE}.config.toml:type-or-mode-mismatch")
    if not sentinel_regular:
        forbidden.append("frontier-canary-sentinel:type-or-mode-mismatch")
    if expected_profile_sha256 is not None and profile_sha256 != expected_profile_sha256:
        forbidden.append(f"{CODEX_CONFIG_PROFILE}.config.toml:hash-mismatch")
    if expected_sentinel_sha256 is not None and sentinel_sha256 != expected_sentinel_sha256:
        forbidden.append("frontier-canary-sentinel:hash-mismatch")
    expected_system_paths: set[str] = set()
    if expected_system_skills is not None:
        expected_system_paths = {
            str(item["path"])
            for key in ("directories", "files")
            for item in expected_system_skills.get(key, [])
            if isinstance(item, Mapping) and isinstance(item.get("path"), str)
        }
    base_paths = {
        "auth.json",
        "frontier-canary-sentinel",
        f"{CODEX_CONFIG_PROFILE}.config.toml",
        *expected_system_paths,
    }
    if model_cache_registered:
        base_paths.add("models_cache.json")
    allowed_paths = set(base_paths)
    expected_kinds = {
        "auth.json": "symlink",
        "frontier-canary-sentinel": "file",
        f"{CODEX_CONFIG_PROFILE}.config.toml": "file",
    }
    if model_cache_registered:
        expected_kinds["models_cache.json"] = "file"
    if expected_system_skills is not None:
        expected_kinds.update(
            {
                str(item["path"]): "directory"
                for item in expected_system_skills.get("directories", [])
                if isinstance(item, Mapping) and isinstance(item.get("path"), str)
            }
        )
        expected_kinds.update(
            {
                str(item["path"]): "file"
                for item in expected_system_skills.get("files", [])
                if isinstance(item, Mapping) and isinstance(item.get("path"), str)
            }
        )
    required_runtime_paths: set[str] = set()
    if not require_initial:
        allowed_paths.update(SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL)
        allowed_paths.add("tmp/arg0")
        expected_kinds.update(
            {
                path: "file"
                for path in SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL
                if path not in {"os-tmp", "skills", "tmp"}
            }
        )
        expected_kinds.update(
            {"os-tmp": "directory", "skills": "directory", "tmp": "directory", "tmp/arg0": "directory"}
        )
        arg0_runs = {
            relative
            for relative in entries
            if re.fullmatch(r"tmp/arg0/codex-arg0[A-Za-z0-9]+", relative)
        }
        if len(arg0_runs) > 1:
            forbidden.append("ambiguous-runtime-arg0-layout")
        for arg0_run in arg0_runs:
            arg0_paths = {
                "tmp",
                "tmp/arg0",
                arg0_run,
                f"{arg0_run}/.lock",
                f"{arg0_run}/apply_patch",
                f"{arg0_run}/applypatch",
                f"{arg0_run}/codex-execve-wrapper",
            }
            allowed_paths.update(arg0_paths)
            required_runtime_paths.update(arg0_paths)
            expected_kinds.update(
                {
                    arg0_run: "directory",
                    f"{arg0_run}/.lock": "file",
                    f"{arg0_run}/apply_patch": "symlink",
                    f"{arg0_run}/applypatch": "symlink",
                    f"{arg0_run}/codex-execve-wrapper": "symlink",
                }
            )
    for relative in sorted(set(entries) - allowed_paths):
        forbidden.append(f"unexpected:{relative}")
    for relative in sorted(base_paths - set(entries)):
        forbidden.append(f"missing:{relative}")
    for relative in sorted(required_runtime_paths - set(entries)):
        forbidden.append(f"missing:{relative}")
    observed_kinds = {entry["path"]: entry["kind"] for entry in layout_entries}
    for relative in sorted(set(entries) & set(expected_kinds)):
        if observed_kinds.get(relative) != expected_kinds[relative]:
            forbidden.append(
                f"kind-mismatch:{relative}:{observed_kinds.get(relative)}"
            )
    layout_body = {
        "schema_version": "drupal_agent_readiness.runtime_home_layout.v1",
        "entries": layout_entries,
    }
    layout_sha256 = "sha256:" + hashlib.sha256(
        canonical_json_bytes(layout_body)
    ).hexdigest()
    layout_document = {**layout_body, "tree_sha256": layout_sha256}
    return {
        "mode": oct(home.stat().st_mode & 0o777),
        "home_identity_verified": home_identity_verified,
        "home_mode_verified": home_mode_verified,
        "entries": entries,
        "layout_entries": layout_entries,
        "layout_verified": not forbidden,
        "layout_sha256": layout_sha256,
        "layout_document": layout_document,
        "auth_reference": "exact target verified"
        if auth_reference_verified
        else "exact target not verified",
        "auth_reference_verified": auth_reference_verified,
        "permissions_profile_regular_file_verified": profile_regular,
        "sentinel_regular_file_verified": sentinel_regular,
        "permissions_profile_sha256": profile_sha256,
        "sentinel_sha256": sentinel_sha256,
        "system_skills_verified": system_verified,
        "system_skills_tree_sha256": system_tree_sha256,
        "forbidden_entries": sorted(set(forbidden)),
    }


def _run_isolated_codex(
    *,
    argv: list[str] | tuple[str, ...],
    prompt: str,
    workdir: Path,
    auth_file: Path,
    system_skill_seed: Path | None = None,
    system_skill_manifest: dict[str, Any] | None = None,
    permissions_profile: dict[str, Any] | None = None,
    sentinel_token: str | None = None,
    environment_policy: dict[str, Any] | None = None,
    model_cache_seed: bytes | None = None,
    model_cache_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    auth = auth_file.expanduser().resolve()
    if not auth.is_file():
        raise FrontierCanaryError("--auth-file must reference an existing credential file")
    if environment_policy is None:
        containment_policy = build_frontier_process_containment_policy(
            Path("/usr/bin/sandbox-exec")
        )
    else:
        raw_containment = environment_policy.get("process_containment")
        sandbox_path = (
            Path(str(raw_containment.get("sandbox_binary")))
            if isinstance(raw_containment, Mapping)
            else Path("/nonexistent")
        )
        containment_policy = validate_frontier_process_containment_policy(
            raw_containment,
            network_sandbox_binary=sandbox_path,
        )
    containment_policy_sha256 = "sha256:" + hashlib.sha256(
        canonical_json_bytes(containment_policy)
    ).hexdigest()
    outer_argv = [
        containment_policy["sandbox_binary"],
        "-p",
        FRONTIER_PROCESS_CONTAINMENT_PROFILE,
        *list(argv),
    ]
    containment_receipt = {
        "status": "verified",
        "policy_sha256": containment_policy_sha256,
        "sandbox_sha256": containment_policy["sandbox_sha256"],
        "child_process_creation_denied": True,
        "inner_argv": list(argv),
        "outer_argv": outer_argv,
    }
    home = Path(tempfile.mkdtemp(prefix="drupal-agent-canary-codex-home-"))
    home.chmod(0o700)
    home_stat = home.lstat()
    home_identity = (home_stat.st_dev, home_stat.st_ino)
    (home / "auth.json").symlink_to(auth)
    if (model_cache_seed is None) != (model_cache_contract is None):
        shutil.rmtree(home)
        raise FrontierCanaryError(
            "Model-cache bytes and preregistered contract must be supplied together"
        )
    if model_cache_seed is not None:
        if (
            not model_cache_contract_valid(model_cache_contract)
            or len(model_cache_seed) != model_cache_contract["byte_size"]
            or "sha256:" + hashlib.sha256(model_cache_seed).hexdigest()
            != model_cache_contract["file_sha256"]
        ):
            shutil.rmtree(home)
            raise FrontierCanaryError(
                "Model-cache seed bytes differ from the preregistered contract"
            )
        model_cache_path = home / "models_cache.json"
        model_cache_path.write_bytes(model_cache_seed)
        model_cache_path.chmod(0o400)
    if permissions_profile is None or sentinel_token is None:
        shutil.rmtree(home)
        raise FrontierCanaryError("Preregistered permissions profile and sentinel are required")
    profile_text = permissions_profile.get("profile_text")
    profile_sha256 = permissions_profile.get("profile_sha256")
    sentinel_sha256 = permissions_profile.get("sentinel_sha256")
    if not isinstance(profile_text, str) or not isinstance(profile_sha256, str):
        shutil.rmtree(home)
        raise FrontierCanaryError("Preregistered permissions profile is malformed")
    profile_path = home / f"{CODEX_CONFIG_PROFILE}.config.toml"
    profile_path.write_text(profile_text, encoding="utf-8")
    profile_path.chmod(0o600)
    sentinel_path = home / "frontier-canary-sentinel"
    sentinel_path.write_text(sentinel_token, encoding="utf-8")
    sentinel_path.chmod(0o600)
    if file_sha256(profile_path) != profile_sha256 or file_sha256(
        home / "frontier-canary-sentinel"
    ) != sentinel_sha256:
        shutil.rmtree(home)
        raise FrontierCanaryError("Runtime permissions profile or sentinel differs from preregistration")
    if system_skill_manifest is None and system_skill_seed is not None:
        shutil.rmtree(home)
        raise FrontierCanaryError("System-skill seed requires a preregistered manifest")
    if system_skill_manifest is not None:
        manifest_files = system_skill_manifest.get("files")
        if not isinstance(manifest_files, list):
            shutil.rmtree(home)
            raise FrontierCanaryError("Preregistered system-skill manifest is malformed")
        if bool(manifest_files) != (system_skill_seed is not None):
            shutil.rmtree(home)
            raise FrontierCanaryError(
                "A nonempty system-skill manifest requires a seed; an empty manifest "
                "requires the system-skill surface to remain absent"
            )
    if system_skill_seed is not None:
        if not system_skill_seed.is_dir():
            shutil.rmtree(home)
            raise FrontierCanaryError("Preregistered system-skill seed is missing")
        (home / "skills").mkdir()
        shutil.copytree(system_skill_seed, home / "skills" / ".system")
    before = _home_layout(
        home,
        require_initial=True,
        expected_home_identity=home_identity,
        expected_auth_target=auth,
        expected_arg0_target=Path(str(argv[0])).resolve(),
        expected_system_skills=system_skill_manifest,
        expected_profile_sha256=profile_sha256,
        expected_sentinel_sha256=sentinel_sha256,
        expected_model_cache_contract=model_cache_contract,
    )
    if before["forbidden_entries"]:
        shutil.rmtree(home)
        raise FrontierCanaryError("Could not establish a clean isolated CODEX_HOME")
    completed: subprocess.CompletedProcess[str] | None = None
    stdout = ""
    stderr = ""
    timed_out = False
    timeout_error: subprocess.TimeoutExpired | None = None
    runner_error: BaseException | None = None
    try:
        try:
            completed = run_command(
                outer_argv,
                input=prompt,
                cwd=workdir,
                env=_isolated_environment(home, environment_policy=environment_policy),
                text=True,
                capture_output=True,
                timeout=600,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as error:
            timed_out = True
            timeout_error = error
            stdout = process_output(error.output)
            stderr = process_output(error.stderr)
        except (OSError, subprocess.SubprocessError) as error:
            runner_error = error
            stderr = str(error)
        after = _home_layout(
            home,
            expected_home_identity=home_identity,
            expected_auth_target=auth,
            expected_arg0_target=Path(str(argv[0])).resolve(),
            expected_system_skills=system_skill_manifest,
            expected_profile_sha256=profile_sha256,
            expected_sentinel_sha256=sentinel_sha256,
            expected_model_cache_contract=model_cache_contract,
        )
    finally:
        shutil.rmtree(home)
    return {
        "completed": completed,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "timeout_error": timeout_error,
        "runner_error": runner_error,
        "runtime_home": {
            "before": before,
            "after": after,
            "process_containment": containment_receipt,
        },
    }


def _usage(events: list[dict[str, Any]]) -> dict[str, int]:
    usage: dict[str, Any] = {}
    for event in events:
        candidate = event.get("usage")
        if isinstance(candidate, dict):
            usage = candidate
    return {
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
    }


def _load_model_cache_seed(
    path: Path, *, model_selector: str
) -> tuple[bytes, dict[str, Any]]:
    """Load and content-address the exact behavior-affecting model catalog."""

    candidate = path.expanduser().absolute()
    source = candidate.resolve()
    if (
        not source.is_file()
        or candidate.is_symlink()
        or source.stat().st_nlink != 1
    ):
        raise FrontierCanaryError(
            "--model-cache-json must be one regular, nonlinked JSON file"
        )
    payload = source.read_bytes()
    if not payload:
        raise FrontierCanaryError("--model-cache-json cannot be empty")
    try:
        document = parse_json_without_duplicate_keys(
            payload.decode("utf-8"), label="model cache"
        )
    except UnicodeDecodeError as error:
        raise FrontierCanaryError("--model-cache-json must be UTF-8 JSON") from error
    models = document.get("models") if isinstance(document, Mapping) else None
    matches = (
        [
            model
            for model in models
            if isinstance(model, Mapping) and model.get("slug") == model_selector
        ]
        if isinstance(models, list)
        else []
    )
    if len(matches) != 1:
        raise FrontierCanaryError(
            "--model-cache-json must contain exactly one entry for --model-snapshot"
        )
    client_version = document.get("client_version")
    fetched_at = document.get("fetched_at")
    if client_version is not None and not isinstance(client_version, str):
        raise FrontierCanaryError("Model-cache client_version must be a string or null")
    if fetched_at is not None and not isinstance(fetched_at, str):
        raise FrontierCanaryError("Model-cache fetched_at must be a string or null")
    contract = {
        "schema_version": "drupal_agent_readiness.model_cache_contract.v1",
        "file_sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
        "selected_model_selector": model_selector,
        "selected_model_entry_sha256": "sha256:"
        + hashlib.sha256(canonical_json_bytes(matches[0])).hexdigest(),
        "catalog_client_version": client_version,
        "catalog_fetched_at": fetched_at,
        "content_role": "behavior_affecting_model_metadata",
        "bytes_retained": False,
    }
    if not model_cache_contract_valid(contract):
        raise FrontierCanaryError("Derived model-cache contract is malformed")
    return payload, contract


def _derive_substrate_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="run_frontier_canary.py derive-substrate",
        description="Derive content-addressed measurement-v1 substrate metadata from DDEV",
    )
    parser.add_argument("--site-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--codex-binary",
        type=Path,
        default=Path(shutil.which("codex") or "codex"),
        help="Codex binary used to establish the same pinned host context as the canary",
    )
    args = parser.parse_args(argv)
    host_context = _host_execution_context(args.codex_binary)
    runner = _pinned_project_runner(
        host_context,
        args.site_root,
        expected_vendor_tree_sha256=None,
    )
    substrate = derive_ddev_substrate(args.site_root, runner=runner)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json_bytes(substrate))
    print(args.output)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "derive-substrate":
        return _derive_substrate_main(sys.argv[2:])
    parser = argparse.ArgumentParser(
        description="Run a preregistered two-slot, read-only Drupal frontier canary"
    )
    parser.add_argument("--artifact-repo", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument(
        "--substrate-json",
        type=Path,
        required=True,
        help=(
            "Pinned core/components/runtime metadata; the observed Drupal site is collected "
            "outside the agent sandbox at every boundary"
        ),
    )
    parser.add_argument(
        "--capture-dir",
        type=Path,
        help="Optional directory retaining every raw live collector envelope",
    )
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument(
        "--auth-file",
        type=Path,
        required=True,
        help="Existing Codex auth.json referenced by symlink; secret bytes are never copied or logged",
    )
    parser.add_argument("--agent-version", required=True)
    parser.add_argument("--model-provider", default="openai")
    parser.add_argument("--model-id", required=True)
    parser.add_argument(
        "--model-cache-json",
        type=Path,
        required=True,
        help=(
            "Exact ambient ~/.codex/models_cache.json bytes to preregister and seed into "
            "every isolated attempt"
        ),
    )
    parser.add_argument(
        "--model-snapshot",
        required=True,
        help=(
            "Exact preregistered selector passed to Codex --model and pinned in the manifest; "
            "this does not attest the provider backend snapshot"
        ),
    )
    parser.add_argument("--registered-at", type=_parse_time)
    args = parser.parse_args()
    observed_root = args.workdir.resolve()
    artifact_root = args.artifact_repo.resolve()
    named_boundaries = {
        "observed_root": observed_root,
        "artifact_repo": artifact_root,
    }
    if args.capture_dir is not None:
        named_boundaries["capture_dir"] = args.capture_dir.resolve()
    _validate_nonoverlap_paths(named_boundaries)
    _validate_dedicated_output_directory(artifact_root, "--artifact-repo")
    if args.capture_dir is not None:
        _validate_dedicated_output_directory(args.capture_dir, "--capture-dir")
    substrate_document = json.loads(args.substrate_json.read_text(encoding="utf-8"))
    if not isinstance(substrate_document, dict):
        raise FrontierCanaryError("--substrate-json must contain one JSON object")
    auth = args.auth_file.expanduser().resolve()
    if not auth.is_file():
        raise FrontierCanaryError("--auth-file must reference an existing credential file")
    expected_auth = Path(
        expected_system_skill_host_denials()["auth_file"]["path"]
    )
    if auth != expected_auth:
        raise FrontierCanaryError(
            "--auth-file must be the ambient ~/.codex/auth.json bound by the sandbox policy"
        )
    expected_model_cache = (Path.home() / ".codex" / "models_cache.json").resolve()
    model_cache_path = args.model_cache_json.expanduser().resolve()
    if model_cache_path != expected_model_cache:
        raise FrontierCanaryError(
            "--model-cache-json must be the ambient ~/.codex/models_cache.json"
        )
    model_cache_seed, model_cache_contract = _load_model_cache_seed(
        model_cache_path,
        model_selector=args.model_snapshot,
    )
    for forbidden_root, label in (
        (args.workdir.resolve(), "observed Drupal project"),
        (args.artifact_repo.resolve(), "artifact evidence repo"),
    ):
        try:
            auth.relative_to(forbidden_root)
        except ValueError:
            pass
        else:
            raise FrontierCanaryError(f"--auth-file must be outside the {label}")
    host_context = _host_execution_context(args.codex_binary)
    expected_substrate = json.loads(args.substrate_json.read_text(encoding="utf-8"))
    project_runner = _pinned_project_runner(
        host_context,
        observed_root,
        expected_vendor_tree_sha256=expected_substrate.get("vendor_tree_sha256"),
    )

    def collect_observed_site() -> dict[str, Any]:
        if _host_execution_context(args.codex_binary) != host_context:
            raise FrontierCanaryError("Pinned host environment or top-level tools drifted")
        live_substrate = derive_ddev_substrate(observed_root, runner=project_runner)
        if live_substrate != expected_substrate:
            raise FrontierCanaryError(
                "Live code/runtime substrate drifted from --substrate-json"
            )
        return {
            "inventory": collect_live_state(observed_root, runner=project_runner),
            "site_projection": derive_ddev_site_projection(
                observed_root, runner=project_runner
            ),
            "substrate": live_substrate,
        }

    initial_observation = collect_observed_site()
    snapshot_root = Path(tempfile.mkdtemp(prefix="drupal-agent-canary-snapshot-"))
    snapshot_root.chmod(0o755)
    try:
        _validate_nonoverlap_paths(
            {**named_boundaries, "snapshot_root": snapshot_root}
        )
    except BaseException:
        shutil.rmtree(snapshot_root)
        raise
    snapshot_document = {
        "schema_version": "drupal_agent_readiness.governed_observation_snapshot.v1",
        "observation_kind": "trusted_host_collector_output",
        "claim_boundary": (
            "agent interprets this governed evidence; it does not directly inspect or operate "
            "the source Drupal site"
        ),
        "inventory_evidence": initial_observation["inventory"],
    }
    snapshot_path = snapshot_root / "governed-observation.json"
    snapshot_path.write_bytes(canonical_json_bytes(snapshot_document))
    workspace_projection = derive_agent_visible_workspace(snapshot_root)
    initial_capture = {**initial_observation, "workspace": workspace_projection}
    sentinel_token = f"frontier-canary-nonsecret-{uuid.uuid4().hex}"
    permissions_preflight = _preflight_permissions_profile(
        args.codex_binary,
        workspace=snapshot_root,
        sentinel_token=sentinel_token,
        host_probe_paths={
            "observed_root_unreadable": observed_root / ".ddev" / "config.yaml",
            "ddev_binary_unreadable": Path(host_context["host_tools"]["ddev"]["path"]),
            "docker_binary_minimal_runtime_readable": Path(
                host_context["host_tools"]["docker"]["path"]
            ),
            "docker_socket_unreadable": Path(host_context["docker_socket_path"]),
        },
    )
    host_read_denials = expected_system_skill_host_denials()
    try:
        system_skill_preflight = _preflight_system_skills(
            args.codex_binary,
            codex_sha256=host_context["host_tools"]["codex"]["sha256"],
            network_sandbox_binary=Path(
                host_context["host_tools"]["network_sandbox"]["invocation_path"]
            ),
            network_sandbox_sha256=host_context["host_tools"]["network_sandbox"][
                "sha256"
            ],
            python_binary=Path(host_context["host_tools"]["python"]["path"]),
            python_sha256=host_context["host_tools"]["python"]["sha256"],
            permissions_profile=permissions_preflight,
            host_read_denials=host_read_denials,
            workdir=snapshot_root,
            output_schema=(
                FRONTIER_INVENTORY_OUTPUT_SCHEMA_SOURCE
            ),
            model=args.model_snapshot,
        )
    except BaseException:
        shutil.rmtree(snapshot_root)
        raise
    environment_policy = {
        **ISOLATED_ENVIRONMENT_POLICY,
        **host_context,
        "model_cache": model_cache_contract,
        "permissions_preflight": permissions_preflight,
        "system_skills_preflight": system_skill_preflight["receipt"],
        "process_containment": build_frontier_process_containment_policy(
            Path(host_context["host_tools"]["network_sandbox"]["invocation_path"])
        ),
    }
    capture_count = 0
    attempt_count = 0
    invocation_id = uuid.uuid4().hex
    registration_capture_pending = True

    def collector(_slot_id: str) -> dict[str, Any]:
        nonlocal capture_count, registration_capture_pending
        capture_count += 1
        if registration_capture_pending:
            capture = initial_capture
            registration_capture_pending = False
        else:
            capture = {
                **collect_observed_site(),
                "workspace": derive_agent_visible_workspace(snapshot_root),
            }
        if args.capture_dir is not None:
            args.capture_dir.mkdir(parents=True, exist_ok=True)
            path = args.capture_dir / f"capture-{capture_count:03d}-{_slot_id}.json"
            _write_new(path, canonical_json_bytes(capture))
        return capture

    def executor(argv: list[str] | tuple[str, ...], prompt: str) -> dict[str, Any]:
        nonlocal attempt_count
        attempt_count += 1
        isolated = _run_isolated_codex(
            argv=argv,
            prompt=prompt,
            workdir=snapshot_root,
            auth_file=auth,
            system_skill_seed=system_skill_preflight["system_root"],
            system_skill_manifest=system_skill_preflight["manifest"],
            permissions_profile=permissions_preflight,
            sentinel_token=sentinel_token,
            environment_policy=environment_policy,
            model_cache_seed=model_cache_seed,
            model_cache_contract=model_cache_contract,
        )
        stdout = isolated["stdout"]
        stderr = isolated["stderr"]
        runtime_home = isolated["runtime_home"]
        completed = isolated["completed"]
        detections = _sensitive_output_detections(
            stdout,
            stderr,
            sentinel_token=sentinel_token,
        )
        if detections:
            rejection = _record_sensitive_output_rejection(
                args.artifact_repo,
                invocation_id=invocation_id,
                attempt=attempt_count,
                slot_id=f"frontier-{attempt_count:03d}",
                argv=argv,
                stdout=stdout,
                stderr=stderr,
                detections=detections,
            )
            raise FrontierCanaryError(
                "Codex output matched a credential/canary marker and was rejected before "
                f"persistence; rejection_receipt={rejection.relative_to(args.artifact_repo.resolve())}"
            )
        begun = _begin_attempt(
            args.artifact_repo,
            invocation_id=invocation_id,
            attempt=attempt_count,
            slot_id=f"frontier-{attempt_count:03d}",
            argv=argv,
            stdout=stdout,
            stderr=stderr,
            returncode=completed.returncode if completed is not None else None,
            timed_out=isolated["timed_out"],
            runtime_home=runtime_home,
            environment_policy=environment_policy,
        )
        if runtime_home["after"]["forbidden_entries"]:
            failure = (
                "Isolated CODEX_HOME acquired forbidden skills/config/plugins: "
                + ", ".join(runtime_home["after"]["forbidden_entries"])
            )
            receipt = _finalize_attempt(
                begun,
                status="failed",
                thread_id=None,
                failure=failure,
            )
            raise FrontierCanaryError(f"{failure}; attempt_receipt={receipt['uri']}")
        if isolated["timed_out"]:
            failure = (
                "Codex execution exceeded the registered 600s budget; "
                + _failure_context([], returncode=None, stderr=stderr)
            )
            receipt = _finalize_attempt(
                begun,
                status="failed",
                thread_id=None,
                failure=failure,
            )
            raise FrontierCanaryError(f"{failure}; attempt_receipt={receipt['uri']}") from isolated[
                "timeout_error"
            ]
        if isolated["runner_error"] is not None:
            failure = "Codex process failed to start; " + _failure_context(
                [], returncode=None, stderr=stderr
            )
            receipt = _finalize_attempt(
                begun,
                status="failed",
                thread_id=None,
                failure=failure,
            )
            raise FrontierCanaryError(f"{failure}; attempt_receipt={receipt['uri']}") from isolated[
                "runner_error"
            ]
        if completed is None:
            raise FrontierCanaryError("Isolated Codex runner returned no process result")
        receipt = _finalize_semantically_valid_attempt(
            begun,
            slot_id=f"frontier-{attempt_count:03d}",
            stderr=stderr,
        )
        return {"attempt_receipt": receipt}

    try:
        result = run_frontier_canary(
            artifact_repo=args.artifact_repo,
            workdir=snapshot_root,
            codex_binary=args.codex_binary,
            agent_version=args.agent_version,
            model_provider=args.model_provider,
            model_id=args.model_id,
            model_snapshot=args.model_snapshot,
            collector=collector,
            executor=executor,
            registered_at=args.registered_at,
            execution_environment_policy=environment_policy,
        )
    finally:
        shutil.rmtree(system_skill_preflight["home"])
        shutil.rmtree(snapshot_root)
    git_tool = host_context["host_tools"]["git"]
    custody = seal_frontier_evidence(
        args.artifact_repo,
        result.anchor,
        git_binary=Path(git_tool["path"]),
        git_sha256=git_tool["sha256"],
    )
    sealed_audit = audit_measurement_v1(
        result.manifest,
        list(result.runs),
        artifact_root=args.artifact_repo,
        registration_anchor=result.anchor,
    )
    if sealed_audit["errors"] or not sealed_audit["estimate_reportable"]:
        raise FrontierCanaryError("Post-run sealed evidence failed production re-audit")
    print(
        json.dumps(
            {"audit": sealed_audit, "post_run_custody": custody},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FrontierCanaryError as error:
        print(f"frontier canary failed: {error}", file=sys.stderr)
        raise SystemExit(1)
