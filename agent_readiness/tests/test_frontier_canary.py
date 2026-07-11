"""Focused fake-backed tests for the frontier canary."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import struct
import time
import unittest
from unittest.mock import patch

from agent_readiness.frontier_canary import (
    CODEX_CONFIG_PROFILE,
    CODEX_PERMISSION_PROFILE,
    FRONTIER_INVENTORY_OUTPUT_SCHEMA_SOURCE,
    SYSTEM_SKILL_BOOTSTRAP_SANDBOX_PROFILE,
    SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL,
    SYSTEM_SKILL_BOOTSTRAP_PROMPT,
    SYSTEM_SKILL_REQUIRED_HOST_DENIALS,
    SYSTEM_SKILL_NETWORK_PROBE_CODE,
    SYSTEM_SKILL_NETWORK_PROBE_EXIT_CODE,
    SYSTEM_SKILL_NETWORK_PROBE_STDERR,
    SYSTEM_SKILL_NETWORK_PROBE_STDOUT,
    SYSTEM_SKILL_BOOTSTRAP_TRANSPORT_CLASS,
    FrontierCanaryError,
    _parse_retained_codex_jsonl,
    build_codex_argv,
    build_frontier_process_containment_policy,
    build_system_skill_bootstrap_sandbox_profile,
    derive_agent_visible_workspace,
    derive_ddev_site_projection,
    derive_ddev_substrate,
    expected_system_skill_host_denials,
    run_frontier_canary,
    seal_frontier_evidence,
    validate_codex_argv,
)
from agent_readiness.measurement_v1 import (
    _shape_issues,
    audit_measurement_v1,
    canonical_json_bytes,
    canonical_sha256,
    file_sha256,
    model_cache_contract_valid,
)
from agent_readiness.codex_runner_utils import (
    process_output as normalize_process_output,
    run_command as run_subprocess_command,
)
from agent_readiness.scripts.run_frontier_canary import (
    ISOLATED_ENVIRONMENT_POLICY,
    _begin_attempt,
    _answer as parse_codex_answer,
    _events as parse_codex_events,
    _finalize_attempt,
    _finalize_semantically_valid_attempt,
    _load_model_cache_seed,
    _permissions_profile_text,
    _pinned_project_runner,
    _preflight_permissions_profile,
    _preflight_system_skills,
    _prove_network_denial,
    _record_sensitive_output_rejection,
    _run_isolated_codex,
    _sensitive_output_detections,
    _system_skill_manifest,
    _validate_dedicated_output_directory,
    _validate_nonoverlap_paths,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TEST_GIT_BINARY = (
    Path("/usr/bin/git")
    if Path("/usr/bin/git").is_file()
    else Path(shutil.which("git") or "git")
).resolve()


def _hash(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _fake_model_cache() -> tuple[bytes, dict]:
    selected = {"slug": "gpt-5.4-2026-07-09", "base_instructions": "pinned"}
    payload = canonical_json_bytes(
        {
            "client_version": "0.142.5",
            "fetched_at": "2026-07-10T09:00:00Z",
            "models": [selected],
        }
    )
    contract = {
        "schema_version": "drupal_agent_readiness.model_cache_contract.v1",
        "file_sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
        "selected_model_selector": "gpt-5.4-2026-07-09",
        "selected_model_entry_sha256": canonical_sha256(selected),
        "catalog_client_version": "0.142.5",
        "catalog_fetched_at": "2026-07-10T09:00:00Z",
        "content_role": "behavior_affecting_model_metadata",
        "bytes_retained": False,
    }
    assert model_cache_contract_valid(contract)
    return payload, contract


def _fake_runtime_layout_document() -> dict:
    body = {
        "schema_version": "drupal_agent_readiness.runtime_home_layout.v1",
        "entries": [],
    }
    return {**body, "tree_sha256": canonical_sha256(body)}


def _semantic_runtime_layout_document(
    system_manifest: dict,
    *,
    auth_path: str,
    model_cache_contract: dict,
) -> dict:
    entries = [
        {
            "path": "auth.json",
            "kind": "symlink",
            "mode": "0o755",
            "target_role": "credential_reference",
            "target_path_sha256": _hash(auth_path),
        },
        {
            "path": f"{CODEX_CONFIG_PROFILE}.config.toml",
            "kind": "file",
            "mode": "0o600",
        },
        {
            "path": "frontier-canary-sentinel",
            "kind": "file",
            "mode": "0o600",
        },
        {
            "path": "models_cache.json",
            "kind": "file",
            "mode": "0o400",
            "byte_size": model_cache_contract["byte_size"],
            "sha256": model_cache_contract["file_sha256"],
        },
    ]
    entries.extend(
        {
            "path": item["path"],
            "kind": "directory",
            "mode": item["mode"],
        }
        for item in system_manifest["directories"]
    )
    entries.extend(
        {"path": item["path"], "kind": "file", "mode": item["mode"]}
        for item in system_manifest["files"]
    )
    body = {
        "schema_version": "drupal_agent_readiness.runtime_home_layout.v1",
        "entries": sorted(entries, key=lambda item: item["path"]),
    }
    return {**body, "tree_sha256": canonical_sha256(body)}


def _write_malicious_timestamp_pyc(
    source: Path,
    marker: Path,
    *,
    pycache_prefix: Path | None,
) -> Path:
    previous = sys.pycache_prefix
    try:
        sys.pycache_prefix = (
            str(pycache_prefix.resolve()) if pycache_prefix is not None else None
        )
        cache = Path(importlib.util.cache_from_source(str(source.resolve())))
    finally:
        sys.pycache_prefix = previous
    source_stat = source.stat()
    code = compile(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('EXTERNAL_PYC_EXECUTED')\n",
        str(source.resolve()),
        "exec",
    )
    payload = (
        importlib.util.MAGIC_NUMBER
        + struct.pack(
            "<III",
            0,
            int(source_stat.st_mtime),
            source_stat.st_size,
        )
        + marshal.dumps(code)
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(payload)
    return cache


def _source_manifest(payload: dict) -> dict:
    result = deepcopy(payload)
    result["manifest_sha256"] = canonical_sha256(result)
    return result


def _site_projection(label: str = "initial") -> dict:
    return {
        "database": {
            "algorithm": "ddev-persistent-sql-projection-sha256-v1",
            "scope": "complete_schema_and_nonvolatile_table_data",
            "normalization": (
                "remove one terminal dump timestamp and omit data sections for the exact "
                "bounded volatile-table patterns while retaining their schema"
            ),
            "excluded_data_table_patterns": [
                "cache_*",
                "batch",
                "flood",
                "key_value_expire",
                "queue",
                "semaphore",
                "sessions",
                "watchdog",
            ],
            "excluded_data_tables": ["cache_entity"],
            "canonical_byte_size": 1234,
            "sha256": _hash(f"database-{label}"),
            "retention": "digest_and_exclusion_manifest_only_raw_sql_not_retained",
        },
        "active_config": _source_manifest(
            {
                "algorithm": "drupal-active-config-item-sha256-v1",
                "items": [
                    {"name": "system.site", "byte_size": 42, "sha256": _hash("system.site")}
                ],
                "retention": "names_sizes_and_digests_only_values_not_retained",
            }
        ),
        "public_files": _source_manifest(
            {
                "algorithm": "drupal-file-tree-content-sha256-v1",
                "scheme": "public",
                "status": "present",
                "files": [],
                "retention": (
                    "path_digests_sizes_and_content_digests_only_contents_not_retained"
                ),
            }
        ),
        "private_files": _source_manifest(
            {
                "algorithm": "drupal-file-tree-content-sha256-v1",
                "scheme": "private",
                "status": "unconfigured_or_missing",
                "files": [],
                "retention": (
                    "path_digests_sizes_and_content_digests_only_contents_not_retained"
                ),
            }
        ),
    }


def _fake_permissions_profile(token: str = "fake-nonsecret-sentinel") -> dict:
    text = _permissions_profile_text()
    return {
        "profile_text": text,
        "profile_sha256": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        "sentinel_sha256": "sha256:" + hashlib.sha256(token.encode()).hexdigest(),
    }


def _fake_probe_receipts(
    binary: Path,
    workspace: Path,
    probes: dict[str, Path],
) -> dict[str, dict]:
    prefix = [
        str(binary.resolve()),
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
    tails = {
        "workspace_readable": ["test -r ./governed-observation.json"],
        "auth_unreadable": ['test ! -r "$HOME/auth.json"'],
        "sentinel_unreadable": ['test ! -r "$HOME/frontier-canary-sentinel"'],
        "git_metadata_unreadable": [
            'test ! -r "./.git/frontier-canary-sentinel"'
        ],
        **{
            name: [
                (
                    'test -r "$1"'
                    if name == "docker_binary_minimal_runtime_readable"
                    else 'test ! -r "$1"'
                ),
                "frontier-host-probe",
                str(path.resolve()),
            ]
            for name, path in probes.items()
        },
    }
    return {
        name: {"argv": [*prefix, *tail], "returncode": 0}
        for name, tail in tails.items()
    }


def _fake_home_manifest(entries: list[dict]) -> dict:
    normalized = []
    for entry in entries:
        item = deepcopy(entry)
        item.setdefault(
            "mode",
            "0o755" if item.get("kind") in {"directory", "symlink"} else "0o600",
        )
        normalized.append(item)
    ordered = sorted(normalized, key=lambda item: item["path"])
    body = {
        "schema_version": "drupal_agent_readiness.bootstrap_home_manifest.v1",
        "root_mode": "0o700",
        "entries": ordered,
    }
    return {**body, "tree_sha256": canonical_sha256(body)}


def _rehash_bootstrap_stream(bootstrap: dict) -> None:
    events = [json.loads(line) for line in bootstrap["stdout"].splitlines() if line]
    bootstrap["event_types"] = [event.get("type", "") for event in events]
    bootstrap["stdout_sha256"] = _hash(bootstrap["stdout"])
    bootstrap["stderr_sha256"] = _hash(bootstrap["stderr"])
    bootstrap["stdout_byte_size"] = len(bootstrap["stdout"].encode())
    bootstrap["stderr_byte_size"] = len(bootstrap["stderr"].encode())


def _rehash_system_manifest(manifest: dict) -> None:
    body = {
        "schema_version": manifest["schema_version"],
        "directories": manifest["directories"],
        "files": manifest["files"],
    }
    manifest["tree_sha256"] = canonical_sha256(body)


def _fake_system_skill_preflight(
    binary: Path,
    python_binary: Path,
    workspace: Path,
    manifest: dict,
    *,
    permissions_profile_sha256: str,
    model: str = "gpt-5.4-2026-07-09",
) -> dict:
    stdout = "\n".join(
        json.dumps(event)
        for event in (
            {"type": "thread.started", "thread_id": "bootstrap-thread"},
            {"type": "turn.started"},
            {
                "type": "error",
                "message": (
                    "Reconnecting... 2/5 (stream disconnected before completion: "
                    "failed to lookup address information: nodename nor servname "
                    "provided, or not known)"
                ),
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "bootstrap-error",
                    "type": "error",
                    "message": (
                        "Falling back from WebSockets to HTTPS transport. stream "
                        "disconnected before completion: failed to lookup address "
                        "information: nodename nor servname provided, or not known"
                    ),
                },
            },
            {
                "type": "turn.failed",
                "error": {
                    "message": (
                        "stream disconnected before completion: error sending request "
                        "for url (https://api.openai.com/v1/responses)"
                    )
                },
            },
        )
    ) + "\n"
    stderr = (
        "2026-07-10T12:47:37.122963Z ERROR "
        "codex_api::endpoint::responses_websocket: failed to connect to websocket: "
        "IO error: failed to lookup address information: nodename nor servname "
        "provided, or not known, url: wss://api.openai.com/v1/responses\n"
    )
    probe_stdout = SYSTEM_SKILL_NETWORK_PROBE_STDOUT
    probe_stderr = SYSTEM_SKILL_NETWORK_PROBE_STDERR
    host_denials = expected_system_skill_host_denials()
    sandbox_profile = build_system_skill_bootstrap_sandbox_profile(host_denials)
    profile_sha256 = "sha256:" + hashlib.sha256(sandbox_profile.encode()).hexdigest()
    inner = build_codex_argv(
        binary,
        workdir=workspace,
        output_schema=FIXTURES / "inventory_answer_pass.json",
        model=model,
    )
    fake_home = (workspace.parent / "fake-system-bootstrap-home").resolve()
    fake_probe_home = (workspace.parent / "fake-network-probe-home").resolve()
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "SHELL": "/bin/sh",
        "TERM": "dumb",
        "HOME": str(fake_home),
        "CODEX_HOME": str(fake_home),
        "TMPDIR": str(fake_home / "os-tmp"),
    }
    probe_environment = {
        **environment,
        "HOME": str(fake_probe_home),
        "CODEX_HOME": str(fake_probe_home),
        "TMPDIR": str(fake_probe_home / "os-tmp"),
    }
    profile_name = f"{CODEX_CONFIG_PROFILE}.config.toml"
    initial_home = _fake_home_manifest(
        [
            {
                "path": profile_name,
                "kind": "file",
                "byte_size": 1,
                "sha256": permissions_profile_sha256,
            },
            {"path": "os-tmp", "kind": "directory", "mode": "0o700"},
        ]
    )
    system_file_paths = {item["path"] for item in manifest["files"]}
    system_directories = {item["path"] for item in manifest["directories"]}
    arg0_root = "tmp/arg0/codex-arg0TEST"
    directory_paths = {
        "os-tmp",
        "skills",
        "tmp",
        "tmp/arg0",
        arg0_root,
        *system_directories,
    }
    file_paths = (
        set(SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL)
        - {"os-tmp", "skills", "tmp"}
    ) | {
        f"{arg0_root}/.lock",
        *system_file_paths,
    }
    wrapper_paths = {
        f"{arg0_root}/apply_patch",
        f"{arg0_root}/applypatch",
        f"{arg0_root}/codex-execve-wrapper",
    }
    directory_modes = {
        item["path"]: item["mode"] for item in manifest["directories"]
    }
    final_entries = [
        {
            "path": path,
            "kind": "directory",
            "mode": directory_modes.get(path, "0o755"),
        }
        for path in directory_paths
    ]
    manifest_by_path = {item["path"]: item for item in manifest["files"]}
    for path in file_paths:
        source = manifest_by_path.get(path)
        final_entries.append(
            {
                "path": path,
                "kind": "file",
                "mode": source["mode"] if source else "0o600",
                "byte_size": source["byte_size"] if source else 1,
                "sha256": (
                    source["sha256"]
                    if source
                    else permissions_profile_sha256
                    if path == profile_name
                    else _hash(path)
                ),
            }
        )
    for path in wrapper_paths:
        final_entries.append(
            {
                "path": path,
                "kind": "symlink",
                "mode": "0o755",
                "target": str(binary.resolve()),
                "resolved_sha256": file_sha256(binary.resolve()),
            }
        )
    final_home = _fake_home_manifest(final_entries)
    retained_payloads = []
    for item in manifest["files"]:
        payload = b"x"
        if (
            item["byte_size"] != len(payload)
            or item["sha256"] != _hash(payload.decode())
        ):
            raise AssertionError("fake system manifest must describe the byte x")
        retained_payloads.append(
            {
                "path": item["path"],
                "content_base64": base64.b64encode(payload).decode(),
            }
        )
    return {
        "bootstrap_kind": "unauthenticated_network_denied_codex_startup",
        "command": [
            str(binary.resolve()),
            "-p",
            sandbox_profile,
            *inner,
        ],
        "environment": environment,
        "prompt": SYSTEM_SKILL_BOOTSTRAP_PROMPT,
        "prompt_sha256": _hash(SYSTEM_SKILL_BOOTSTRAP_PROMPT),
        "prompt_byte_size": len(SYSTEM_SKILL_BOOTSTRAP_PROMPT.encode()),
        "model_turn_started": True,
        "network_egress_denied": True,
        "provider_exchange_observed": False,
        "auth_present": False,
        "provider_response_received": False,
        "transport_failure_class": SYSTEM_SKILL_BOOTSTRAP_TRANSPORT_CLASS,
        "returncode": 1,
        "event_types": [
            "thread.started",
            "turn.started",
            "error",
            "item.completed",
            "turn.failed",
        ],
        "stdout": stdout,
        "stderr": stderr,
        "stdout_sha256": "sha256:" + hashlib.sha256(stdout.encode()).hexdigest(),
        "stderr_sha256": "sha256:" + hashlib.sha256(stderr.encode()).hexdigest(),
        "stdout_byte_size": len(stdout.encode()),
        "stderr_byte_size": len(stderr.encode()),
        "sandbox_profile": sandbox_profile,
        "sandbox_profile_sha256": profile_sha256,
        "host_read_denials": host_denials,
        "permissions_profile_sha256": permissions_profile_sha256,
        "output_schema_sha256": file_sha256(
            FIXTURES / "inventory_answer_pass.json"
        ),
        "codex_sha256": file_sha256(binary.resolve()),
        "network_sandbox_sha256": file_sha256(binary.resolve()),
        "python_sha256": file_sha256(python_binary.resolve()),
        "sandbox_platform": {
            "sys_platform": "darwin",
            "sysname": "Darwin",
            "release": "test-release",
            "version": "test-version",
            "machine": "test-machine",
        },
        "network_denial_probe": {
            "status": "verified",
            "control_connected": True,
            "sandbox_connected": False,
            "returncode": SYSTEM_SKILL_NETWORK_PROBE_EXIT_CODE,
            "argv": [
                str(binary.resolve()),
                "-p",
                sandbox_profile,
                str(python_binary.resolve()),
                "-I",
                "-S",
                "-c",
                SYSTEM_SKILL_NETWORK_PROBE_CODE,
                "127.0.0.1",
                "12345",
            ],
            "environment": probe_environment,
            "sandbox_profile": sandbox_profile,
            "sandbox_profile_sha256": profile_sha256,
            "stdout": probe_stdout,
            "stderr": probe_stderr,
            "stdout_sha256": "sha256:"
            + hashlib.sha256(probe_stdout.encode()).hexdigest(),
            "stderr_sha256": "sha256:"
            + hashlib.sha256(probe_stderr.encode()).hexdigest(),
            "stdout_byte_size": len(probe_stdout.encode()),
            "stderr_byte_size": len(probe_stderr.encode()),
        },
        "initial_home": initial_home,
        "final_home": final_home,
        "manifest": manifest,
        "retained_skill_payloads": retained_payloads,
        "stream_retention": {
            "uri": "pins/agent/execution-environment-policy.json",
            "stdout_json_pointer": "/system_skills_preflight/stdout",
            "stderr_json_pointer": "/system_skills_preflight/stderr",
            "skill_payloads_json_pointer": (
                "/system_skills_preflight/retained_skill_payloads"
            ),
            "scope": "private_canary_evidence_not_public_distribution",
        },
    }


def _bootstrap_failure_stdout() -> str:
    return "\n".join(
        json.dumps(event)
        for event in (
            {"type": "thread.started", "thread_id": "bootstrap-thread"},
            {"type": "turn.started"},
            {
                "type": "error",
                "message": (
                    "Reconnecting... 2/5 (stream disconnected before completion: "
                    "failed to lookup address information: nodename nor servname "
                    "provided, or not known)"
                ),
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "bootstrap-error",
                    "type": "error",
                    "message": (
                        "Falling back from WebSockets to HTTPS transport. stream "
                        "disconnected before completion: failed to lookup address "
                        "information: nodename nor servname provided, or not known"
                    ),
                },
            },
            {
                "type": "turn.failed",
                "error": {
                    "message": (
                        "stream disconnected before completion: error sending request "
                        "for url (https://api.openai.com/v1/responses)"
                    )
                },
            },
        )
    ) + "\n"


def _bootstrap_failure_stderr() -> str:
    return (
        "2026-07-10T12:47:37.122963Z ERROR "
        "codex_api::endpoint::responses_websocket: failed to connect to websocket: "
        "IO error: failed to lookup address information: nodename nor servname "
        "provided, or not known, url: wss://api.openai.com/v1/responses\n"
    )


def _materialize_fake_bootstrap_home(
    home: Path,
    *,
    codex_binary: Path,
    skill_payload: bytes = b"bundled system instruction\n",
) -> None:
    directory_top = {"os-tmp", "shell_snapshots", "skills", "tmp"}
    for name in SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL:
        path = home / name
        if name in directory_top:
            path.mkdir(exist_ok=True)
        elif not path.exists():
            path.write_bytes(b"x")
    skill = home / "skills" / ".system" / "core" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_bytes(skill_payload)
    arg0 = home / "tmp" / "arg0" / "codex-arg0TEST"
    arg0.mkdir(parents=True)
    (arg0 / ".lock").write_bytes(b"x")
    for name in ("apply_patch", "applypatch", "codex-execve-wrapper"):
        (arg0 / name).symlink_to(codex_binary.resolve())


class StepClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self.value
        self.value += timedelta(seconds=1)
        return value


class FakeCollector:
    def __init__(
        self,
        capture: dict,
        *,
        drift_call: int | None = None,
        drift_source: str = "inventory",
    ) -> None:
        self.capture = capture
        self.calls: list[str] = []
        self.drift_call = drift_call
        self.drift_source = drift_source

    def __call__(self, slot_id: str) -> dict:
        self.calls.append(slot_id)
        result = deepcopy(self.capture)
        if self.drift_call == len(self.calls):
            if self.drift_source == "database":
                result["site_projection"]["database"]["sha256"] = _hash(
                    "node-body-mutated"
                )
            else:
                result["inventory"]["canvas"]["page_count"] += 1
        return result


class FakeExecutor:
    def __init__(
        self,
        repo: Path,
        answer: dict,
        *,
        duplicate_id: bool = False,
        observed_model_selector: str | None = None,
        receipt_slot_id: str | None = None,
        receipt_provider_request_id: str | None = None,
        include_tool: bool = False,
        extra_thread_id: str | None = None,
        malformed_line: str | None = None,
        tool_lifecycle_events: list[dict] | None = None,
        turn_completed_events: list[dict] | None = None,
        agent_message_event_type: str = "item.completed",
        extra_usage_event: dict | None = None,
    ) -> None:
        self.repo = repo
        self.answer = answer
        self.duplicate_id = duplicate_id
        self.observed_model_selector = observed_model_selector
        self.receipt_slot_id = receipt_slot_id
        self.receipt_provider_request_id = receipt_provider_request_id
        self.include_tool = include_tool
        self.extra_thread_id = extra_thread_id
        self.malformed_line = malformed_line
        self.tool_lifecycle_events = tool_lifecycle_events
        self.turn_completed_events = turn_completed_events
        self.agent_message_event_type = agent_message_event_type
        self.extra_usage_event = extra_usage_event
        self.calls: list[tuple[tuple[str, ...], str, str]] = []
        self.invocation_id = "fakeinvocation00000000000000000001"
        self.git_binary = TEST_GIT_BINARY

    def __call__(self, argv, prompt: str) -> dict:
        commit = subprocess.run(
            [str(self.git_binary), "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        committed = subprocess.run(
            [
                str(self.git_binary),
                "-C",
                str(self.repo),
                "cat-file",
                "blob",
                f"{commit}:registry/frontier-canary-manifest.json",
            ],
            check=True,
            capture_output=True,
        ).stdout
        manifest = self.assert_canonical_manifest(committed)
        validate_codex_argv(argv)
        self.calls.append((tuple(argv), prompt, commit))
        request_number = 1 if self.duplicate_id else len(self.calls)
        thread_id = f"fake-thread-{request_number}"
        event_lines = [
            json.dumps({"type": "thread.started", "thread_id": thread_id}),
            json.dumps({"type": "turn.started"}),
        ]
        if self.extra_thread_id is not None:
            event_lines.append(
                json.dumps(
                    {"type": "thread.started", "thread_id": self.extra_thread_id}
                )
            )
        if self.malformed_line is not None:
            event_lines.append(self.malformed_line)
        if self.tool_lifecycle_events is not None:
            event_lines.extend(json.dumps(event) for event in self.tool_lifecycle_events)
        elif self.include_tool:
            event_lines.append(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "command_execution", "command": "read snapshot"},
                    }
                )
            )
        if self.extra_usage_event is not None:
            event_lines.append(json.dumps(self.extra_usage_event))
        event_lines.extend(
            [
                json.dumps(
                    {
                        "type": self.agent_message_event_type,
                        "item": {
                            "id": "item_answer",
                            "type": "agent_message",
                            "text": json.dumps(self.answer, sort_keys=True),
                        },
                    }
                ),
            ]
        )
        turn_events = self.turn_completed_events
        if turn_events is None:
            turn_events = [
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 1000,
                        "output_tokens": 200,
                        "cached_input_tokens": 10,
                    },
                }
            ]
        event_lines.extend(json.dumps(event) for event in turn_events)
        stdout = "\n".join(event_lines)
        policy_path = self.repo / "pins" / "agent" / "execution-environment-policy.json"
        environment_policy = json.loads(policy_path.read_bytes())
        system_tree = environment_policy["system_skills_preflight"]["manifest"][
            "tree_sha256"
        ]
        profile_hash = environment_policy["permissions_preflight"]["profile_sha256"]
        sentinel_hash = environment_policy["permissions_preflight"]["sentinel_sha256"]
        process_policy = environment_policy["process_containment"]
        layout_document = _semantic_runtime_layout_document(
            environment_policy["system_skills_preflight"]["manifest"],
            auth_path=environment_policy["system_skills_preflight"][
                "host_read_denials"
            ]["auth_file"]["path"],
            model_cache_contract=environment_policy["model_cache"],
        )
        home_verification = {
            "mode": "0o700",
            "home_identity_verified": True,
            "home_mode_verified": True,
            "layout_verified": True,
            "layout_sha256": layout_document["tree_sha256"],
            "layout_document": layout_document,
            "auth_reference_verified": True,
            "permissions_profile_regular_file_verified": True,
            "sentinel_regular_file_verified": True,
            "forbidden_entries": [],
            "system_skills_verified": True,
            "system_skills_tree_sha256": system_tree,
            "permissions_profile_sha256": profile_hash,
            "sentinel_sha256": sentinel_hash,
        }
        runtime_home = {
            "before": deepcopy(home_verification),
            "after": deepcopy(home_verification),
            "process_containment": {
                "status": "verified",
                "policy_sha256": canonical_sha256(process_policy),
                "sandbox_sha256": process_policy["sandbox_sha256"],
                "child_process_creation_denied": True,
                "inner_argv": list(argv),
                "outer_argv": [
                    process_policy["sandbox_binary"],
                    "-p",
                    process_policy["profile"],
                    *list(argv),
                ],
            },
        }
        begun = _begin_attempt(
            self.repo,
            invocation_id=self.invocation_id,
            attempt=len(self.calls),
            slot_id=self.receipt_slot_id or f"frontier-{len(self.calls):03d}",
            argv=argv,
            stdout=stdout,
            stderr="",
            returncode=0,
            timed_out=False,
            runtime_home=runtime_home,
            environment_policy=environment_policy,
        )
        attempt_receipt = _finalize_attempt(
            begun,
            status="succeeded",
            thread_id=thread_id,
            provider_request_id=self.receipt_provider_request_id,
            provider_request_id_status=(
                "verified_distinct"
                if self.receipt_provider_request_id is not None
                else "unverified_not_reported"
            ),
            failure=None,
        )
        result = {
            # Deliberately untrusted duplicates: the harness must derive all
            # evaluator-facing semantics from the retained stdout above.
            "answer": deepcopy(self.answer),
            "provider_request_id": "forged-provider-id",
            "thread_id": "forged-thread-id",
            "returncode": 0,
            "stdout": stdout,
            "stderr": "",
            "usage": {"input_tokens": 1000, "output_tokens": 200, "cached_input_tokens": 10},
            "tool_calls": 3,
            "attempt_receipt": attempt_receipt,
        }
        if self.observed_model_selector is not None:
            result["observed_model_selector"] = self.observed_model_selector
        return result

    @staticmethod
    def assert_canonical_manifest(payload: bytes) -> dict:
        document = json.loads(payload)
        if payload != canonical_json_bytes(document):
            raise AssertionError("manifest was not committed as canonical bytes")
        return document


class MutatingBinaryExecutor(FakeExecutor):
    def __init__(self, repo: Path, answer: dict, binary: Path) -> None:
        super().__init__(repo, answer)
        self.binary = binary

    def __call__(self, argv, prompt: str) -> dict:
        result = super().__call__(argv, prompt)
        self.binary.write_text("#!/bin/sh\nprintf 'codex-cli 0.142.5 changed\\n'\n")
        self.binary.chmod(0o755)
        return result


class MutatingSourceExecutor(FakeExecutor):
    def __init__(self, repo: Path, answer: dict, source: Path, *, delete: bool) -> None:
        super().__init__(repo, answer)
        self.source = source
        self.delete = delete

    def __call__(self, argv, prompt: str) -> dict:
        result = super().__call__(argv, prompt)
        if self.delete:
            self.source.unlink()
        else:
            self.source.write_text("mutated executed source\n", encoding="utf-8")
        return result


class SplitStreamExecutor(FakeExecutor):
    def __call__(self, argv, prompt: str) -> dict:
        result = super().__call__(argv, prompt)
        result.update(
            {
                "answer": {"forged": True},
                "stdout": json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps({"forged": True}),
                        },
                    }
                ),
                "usage": {
                    "input_tokens": 999999,
                    "output_tokens": 999999,
                    "cached_input_tokens": 0,
                },
                "tool_calls": 99,
            }
        )
        return result


class DotGitInjectingExecutor(FakeExecutor):
    def __call__(self, argv, prompt: str) -> dict:
        result = super().__call__(argv, prompt)
        workspace = Path(argv[argv.index("--cd") + 1])
        metadata = workspace / ".git"
        metadata.mkdir()
        (metadata / "agent-instruction.txt").write_text(
            "hidden unregistered instruction",
            encoding="utf-8",
        )
        return result


class FakeSubstrateRunner:
    def __init__(self, *, repo_digest: str | None = None) -> None:
        self.repo_digest = repo_digest or f"example/web@{_hash('repo-image')}"
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, cwd: Path) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        self.calls.append(command)
        if command[0].endswith("vendor/bin/drush"):
            return subprocess.CompletedProcess(command, 1, "", "host database unavailable")
        if command[:3] == ("ddev", "drush", "status"):
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "root": "/var/www/html/web",
                        "drupal-version": "11.3.11",
                        "db-driver": "mysql",
                    }
                ),
                "",
            )
        if command[:3] == ("ddev", "drush", "php:eval"):
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    [
                        {
                            "kind": "module",
                            "machine_name": "demo",
                            "path": "modules/custom/demo",
                            "version": None,
                        }
                    ]
                ),
                "",
            )
        if command == ("ddev", "exec", "php", "-r", "echo PHP_VERSION;"):
            return subprocess.CompletedProcess(command, 0, "8.3.23", "")
        if command[:3] == ("ddev", "drush", "sql:query"):
            return subprocess.CompletedProcess(command, 0, "11.4.7-MariaDB", "")
        if command[:3] == ("docker", "inspect", "--format={{.Image}}"):
            return subprocess.CompletedProcess(command, 0, _hash("local-image") + "\n", "")
        if command[:3] == ("docker", "image", "inspect"):
            return subprocess.CompletedProcess(command, 0, self.repo_digest + "\n", "")
        return subprocess.CompletedProcess(command, 127, "", "unexpected fake command")


class FakeProjectionRunner:
    def __init__(self, *, cache_value: str, body_value: str, timestamp: str) -> None:
        self.cache_value = cache_value
        self.body_value = body_value
        self.timestamp = timestamp

    def __call__(self, argv, cwd: Path) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        if command[:2] == ("ddev", "export-db"):
            dump = (
                "-- Table structure for table `cache_entity`\n"
                "CREATE TABLE `cache_entity` (`cid` varchar(255));\n"
                "-- Dumping data for table `cache_entity`\n"
                f"INSERT INTO `cache_entity` VALUES ('{self.cache_value}');\n"
                "-- Table structure for table `node__body`\n"
                "CREATE TABLE `node__body` (`body_value` text);\n"
                "-- Dumping data for table `node__body`\n"
                f"INSERT INTO `node__body` VALUES ('{self.body_value}');\n"
                f"-- Dump completed on {self.timestamp}\n"
            )
            return subprocess.CompletedProcess(command, 0, dump, "")
        if command[:3] == ("ddev", "drush", "php:eval"):
            projection = {
                "active_config": {
                    "items": [
                        {
                            "name": "system.site",
                            "byte_size": 10,
                            "sha256": _hash("system.site-value"),
                        }
                    ]
                },
                "public_files": {"scheme": "public", "status": "present", "files": []},
                "private_files": {
                    "scheme": "private",
                    "status": "unconfigured_or_missing",
                    "files": [],
                },
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(projection), "")
        return subprocess.CompletedProcess(command, 127, "", "unexpected fake command")


@unittest.skipUnless(
    sys.platform == "darwin",
    "frontier canary process containment requires a pinned macOS sandbox-exec; "
    "it is a Darwin-only harness-validation lane and cannot run on Linux CI",
)
class FrontierCanaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "artifacts"
        self.workdir = self.root / "site"
        self.workdir.mkdir()
        self.binary = self.root / "codex"
        self.binary.write_text("#!/bin/sh\nprintf 'codex-cli 0.142.5\\n'\n", encoding="utf-8")
        self.binary.chmod(0o755)
        self.git_binary = TEST_GIT_BINARY
        self.answer = json.loads((FIXTURES / "inventory_answer_pass.json").read_text())
        inventory = json.loads((FIXTURES / "inventory_state_pass.json").read_text())
        (self.workdir / "governed-observation.json").write_bytes(
            canonical_json_bytes(
                {
                    "schema_version": (
                        "drupal_agent_readiness.governed_observation_snapshot.v1"
                    ),
                    "observation_kind": "trusted_host_collector_output",
                    "claim_boundary": (
                        "agent interprets this governed evidence; it does not directly inspect "
                        "or operate the source Drupal site"
                    ),
                    "inventory_evidence": inventory,
                }
            )
        )
        self.capture = {
            "inventory": inventory,
            "site_projection": _site_projection(),
            "substrate": {
                "fixture_id": "frontier-fixture@2026-07-10",
                "core": {
                    "kind": "core",
                    "name": "drupal/core",
                    "version": "11.3.11",
                    "revision": "8d5e9d4b2a4c",
                    "tree_sha256": _hash("core-tree"),
                },
                "components": [
                    {
                        "kind": "cms",
                        "name": "drupal/cms",
                        "version": "2.1.3",
                        "revision": "f1e2d3c4b5a6",
                        "tree_sha256": _hash("cms-tree"),
                    }
                ],
                "runtime": {
                    "php_version": "8.3.23",
                    "database_driver": "mariadb",
                    "database_version": "11.4.7",
                    "os_image_digest": _hash("os-image"),
                    "container_image_digest": _hash("container-image"),
                },
                "composer_lock_sha256": _hash("composer-lock"),
                "vendor_tree_sha256": _hash("vendor-tree"),
            },
            "workspace": derive_agent_visible_workspace(self.workdir),
        }
        observed_marker = self.root / "observed-site" / ".ddev" / "config.yaml"
        observed_marker.parent.mkdir(parents=True)
        observed_marker.write_text("name: observed-site\n")
        fake_socket = self.root / "fake-docker.sock"
        fake_socket.touch()
        denied_paths = {
            "observed_root_unreadable": observed_marker,
            "ddev_binary_unreadable": self.binary,
            "docker_binary_minimal_runtime_readable": self.binary,
            "docker_socket_unreadable": fake_socket,
        }
        profile_text = _permissions_profile_text(denied_paths)
        profile_hash = "sha256:" + hashlib.sha256(profile_text.encode()).hexdigest()
        system_manifest = {
            "schema_version": "drupal_agent_readiness.system_skills_manifest.v1",
            "directories": [
                {"path": "skills", "mode": "0o755"},
                {"path": "skills/.system", "mode": "0o755"},
                {"path": "skills/.system/fake", "mode": "0o755"},
            ],
            "files": [
                {
                    "path": "skills/.system/fake/SKILL.md",
                    "mode": "0o644",
                    "byte_size": 1,
                    "sha256": _hash("x"),
                }
            ],
        }
        system_manifest["tree_sha256"] = canonical_sha256(system_manifest)
        self.execution_environment_policy = {
            "schema_version": "drupal_agent_readiness.codex_environment_policy.v1",
            "mode": "fake_executor",
            "model_cache": _fake_model_cache()[1],
            "host_tools": {
                "git": {
                    "path": str(self.git_binary),
                    "sha256": file_sha256(self.git_binary),
                },
                "python": {
                    "path": str(Path(sys.executable).resolve()),
                    "sha256": file_sha256(Path(sys.executable).resolve()),
                },
                "network_sandbox": {
                    "path": str(self.binary.resolve()),
                    "sha256": file_sha256(self.binary.resolve()),
                },
            },
            "permissions_preflight": {
                "config_profile": CODEX_CONFIG_PROFILE,
                "permissions_profile": CODEX_PERMISSION_PROFILE,
                "profile_text": profile_text,
                "profile_sha256": profile_hash,
                "sentinel_sha256": _hash("fake-sentinel"),
                "host_probe_paths": {
                    name: str(path.resolve()) for name, path in denied_paths.items()
                },
                "probe_receipts": _fake_probe_receipts(
                    self.binary,
                    self.workdir,
                    denied_paths,
                ),
            },
            "system_skills_preflight": _fake_system_skill_preflight(
                self.binary,
                Path(sys.executable).resolve(),
                self.workdir,
                system_manifest,
                permissions_profile_sha256=profile_hash,
            ),
            "process_containment": build_frontier_process_containment_policy(
                self.binary
            ),
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *, collector=None, executor=None):
        collector = collector or FakeCollector(self.capture)
        executor = executor or FakeExecutor(self.repo, self.answer)
        result = run_frontier_canary(
            artifact_repo=self.repo,
            workdir=self.workdir,
            codex_binary=self.binary,
            agent_version="0.142.5",
            model_provider="openai",
            model_id="gpt-5.4",
            model_snapshot="gpt-5.4-2026-07-09",
            collector=collector,
            executor=executor,
            registered_at=datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc),
            clock=StepClock(),
            execution_environment_policy=self.execution_environment_policy,
        )
        return result, collector, executor

    def _system_preflight_kwargs(self) -> dict:
        return {
            "codex_sha256": file_sha256(self.binary.resolve()),
            "network_sandbox_binary": self.binary.resolve(),
            "network_sandbox_sha256": file_sha256(self.binary.resolve()),
            "python_binary": Path(sys.executable).resolve(),
            "python_sha256": file_sha256(Path(sys.executable).resolve()),
            "permissions_profile": _fake_permissions_profile(),
            "host_read_denials": expected_system_skill_host_denials(),
            "workdir": self.workdir,
            "output_schema": FIXTURES / "inventory_answer_pass.json",
            "model": "gpt-5.4-2026-07-09",
        }

    def _run_with_policy(self, policy: dict, *, label: str) -> None:
        repo = self.root / f"bootstrap-policy-{label}"
        run_frontier_canary(
            artifact_repo=repo,
            workdir=self.workdir,
            codex_binary=self.binary,
            agent_version="0.142.5",
            model_provider="openai",
            model_id="gpt-5.4",
            model_snapshot="gpt-5.4-2026-07-09",
            collector=FakeCollector(self.capture),
            executor=FakeExecutor(repo, self.answer),
            registered_at=datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc),
            clock=StepClock(),
            execution_environment_policy=policy,
        )

    def test_two_fresh_slots_produce_reportable_descriptive_evidence(self) -> None:
        result, collector, executor = self._run()

        self.assertEqual(1, len(result.manifest["arms"]))
        self.assertEqual(2, len(result.manifest["execution_plan"]["attempt_roster"]))
        self.assertEqual(2, len(result.runs))
        self.assertEqual(2, len(executor.calls))
        self.assertEqual(5, len(collector.calls))
        self.assertEqual(1, len({call[2] for call in executor.calls}))
        self.assertTrue(result.audit["contract_valid"], result.audit["errors"])
        self.assertTrue(result.audit["artifacts_verified"], result.audit["errors"])
        self.assertTrue(result.audit["artifact_semantics_verified"], result.audit["errors"])
        self.assertTrue(result.audit["evidence_complete"], result.audit["errors"])
        self.assertTrue(result.audit["estimate_reportable"], result.audit["errors"])
        self.assertEqual(1.0, result.audit["analysis"]["estimate"])
        self.assertFalse(result.audit["registered_effect_rule_met"])
        self.assertEqual(
            "noncomparative_analysis_cannot_meet_effect_rule",
            result.audit["decision"]["reason"],
        )
        self.assertTrue(
            any("backend snapshot" in item for item in result.audit["limitations"])
        )
        self.assertTrue(
            any("does not measure direct Drupal" in item for item in result.audit["limitations"])
        )
        required = {
            "prompt", "render_inputs", "prompt_receipt", "model_identity_receipt",
            "execution_receipt",
            "transcript", "tool_log", "answer", "evaluator_output",
            "evaluator_receipt", "cost_trace", "behavior_trace",
            "validity_decision", "starting_state", "final_state",
            "attempt_receipt", "attempt_stdout", "attempt_stderr",
        }
        for run in result.runs:
            self.assertEqual(required, {artifact["kind"] for artifact in run["artifacts"]})
            self.assertEqual(result.manifest["reference_agent_stack"]["model"]["snapshot"], run["agent_stack"]["model"]["snapshot"])
        argv = executor.calls[0][0]
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--ignore-rules", argv)
        self.assertEqual("plugins", argv[argv.index("--disable") + 1])
        self.assertIn(("--disable", "apps"), tuple(zip(argv, argv[1:])))
        self.assertIn("--ephemeral", argv)
        self.assertIn("--json", argv)
        self.assertIn("--skip-git-repo-check", argv)
        self.assertIn("--strict-config", argv)
        self.assertEqual(CODEX_CONFIG_PROFILE, argv[argv.index("-p") + 1])
        self.assertNotIn("--ask-for-approval", argv)
        self.assertNotIn("--sandbox", argv)
        self.assertEqual("gpt-5.4-2026-07-09", argv[argv.index("--model") + 1])
        output_schema = result.manifest["reference_agent_stack"]["output_schema"]
        rubric = result.manifest["evaluation"]["rubric"]["artifact"]
        self.assertEqual("output_schema", output_schema["evidence_role"])
        self.assertEqual("agent_visible", output_schema["visibility"])
        self.assertEqual(
            (self.repo / output_schema["uri"]).resolve(),
            Path(argv[argv.index("--output-schema") + 1]),
        )
        self.assertEqual("withheld_from_agent", rubric["visibility"])
        self.assertNotEqual(output_schema["sha256"], rubric["sha256"])
        self.assertEqual("interpret.inventory_snapshot", result.manifest["task"]["id"])
        task_definition = json.loads(
            (self.repo / result.manifest["task"]["definition"]["uri"]).read_bytes()
        )
        self.assertEqual(
            "derived_from_agent_visible_evidence",
            task_definition["expected_output_provenance"],
        )
        for run in result.runs:
            self.assertIsNone(run["execution_receipt"]["provider_request_id"])
            self.assertEqual(
                "unverified_not_reported",
                run["execution_receipt"]["provider_request_id_status"],
            )
            self.assertEqual(
                "unverified_held_selector",
                run["model_identity_receipt"]["status"],
            )
        self.assertEqual(
            "descriptive_snapshot",
            result.audit["model_backend_identity"]["classification"],
        )
        self.assertFalse(
            result.audit["model_backend_identity"]["claim_grade_eligible"]
        )
        source_ids = {
            tool["id"]
            for tool in result.manifest["reference_agent_stack"]["tools"]
            if tool["id"].startswith("source-closure:")
        }
        self.assertTrue(
            {
                "source-closure:measurement-v1",
                "source-closure:benchmark-experiment-schema",
                "source-closure:benchmark-run-schema",
                "source-closure:evaluator-common",
                "source-closure:drupal-state-collector",
            }
            <= source_ids
        )

    def test_frontier_output_schema_matches_provider_strict_object_contract(self) -> None:
        schema = json.loads(
            FRONTIER_INVENTORY_OUTPUT_SCHEMA_SOURCE.read_text(encoding="utf-8")
        )

        def assert_strict_objects(value: dict, path: str = "$") -> None:
            allowed_keywords = {
                "$schema",
                "$id",
                "$defs",
                "$ref",
                "title",
                "type",
                "required",
                "properties",
                "additionalProperties",
                "enum",
                "items",
            }
            self.assertFalse(
                set(value) - allowed_keywords,
                f"{path} uses a keyword outside the pinned provider subset",
            )
            properties = value.get("properties")
            if isinstance(properties, dict):
                self.assertEqual(
                    set(properties),
                    set(value.get("required", [])),
                    f"{path} must require every declared property",
                )
                self.assertIs(
                    False,
                    value.get("additionalProperties"),
                    f"{path} must reject undeclared properties",
                )
                for key, child in properties.items():
                    assert_strict_objects(child, f"{path}.properties.{key}")
            definitions = value.get("$defs")
            if isinstance(definitions, dict):
                for key, child in definitions.items():
                    assert_strict_objects(child, f"{path}.$defs.{key}")
            items = value.get("items")
            if isinstance(items, dict):
                assert_strict_objects(items, f"{path}.items")

        assert_strict_objects(schema)
        self.assertEqual([], _shape_issues(self.answer, schema, schema, "$"))
        missing_entity_type = deepcopy(self.answer)
        del missing_entity_type["paths"]["/node"]["entity_type"]
        self.assertTrue(
            _shape_issues(missing_entity_type, schema, schema, "$"),
            "The provider fixture must exercise the same required keys as the live schema",
        )
        owner = schema["$defs"]["path_owner"]
        self.assertEqual(
            ["string", "null"], owner["properties"]["entity_type"]["type"]
        )

        argv = build_codex_argv(
            self.binary,
            workdir=self.workdir,
            output_schema=FRONTIER_INVENTORY_OUTPUT_SCHEMA_SOURCE,
            model="gpt-5.4-2026-07-09",
        )
        self.assertEqual(2, argv.count("--disable"))
        self.assertIn(("--disable", "apps"), tuple(zip(argv, argv[1:])))
        self.assertIn(("--disable", "plugins"), tuple(zip(argv, argv[1:])))

    def test_post_run_evidence_seal_commits_only_outputs_and_preserves_registration(self) -> None:
        result, _, _ = self._run()
        custody = seal_frontier_evidence(
            self.repo,
            result.anchor,
            git_binary=self.git_binary,
            git_sha256=file_sha256(self.git_binary),
            sealed_at=datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(result.anchor.commit, custody["evidence_commit"])
        self.assertTrue(custody["registration_ancestor_verified"])
        self.assertTrue(custody["repository_clean"])
        status = subprocess.run(
            [str(self.git_binary), "-C", str(self.repo), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual("", status)
        report = audit_measurement_v1(
            result.manifest,
            list(result.runs),
            artifact_root=self.repo,
            registration_anchor=result.anchor,
        )
        self.assertTrue(report["audit_valid"], report["errors"])
        self.assertEqual(
            custody["evidence_commit"],
            report["registration_anchor"]["verification_ref_commit"],
        )

    def test_tampered_answer_bytes_fail_production_reaudit(self) -> None:
        result, _, _ = self._run()
        answer_artifact = next(
            artifact for artifact in result.runs[0]["artifacts"] if artifact["kind"] == "answer"
        )
        (self.repo / answer_artifact["uri"]).write_bytes(b"{}")

        report = audit_measurement_v1(
            result.manifest,
            list(result.runs),
            artifact_root=self.repo,
            registration_anchor=result.anchor,
        )

        self.assertFalse(report["artifacts_verified"])
        self.assertFalse(report["estimate_reportable"])
        self.assertFalse(report["registered_effect_rule_met"])
        self.assertIn("artifact_hash_mismatch", {error["code"] for error in report["errors"]})

    def test_tampered_attempt_stdout_fails_production_reaudit(self) -> None:
        result, _, _ = self._run()
        stdout_artifact = next(
            artifact
            for artifact in result.runs[0]["artifacts"]
            if artifact["kind"] == "attempt_stdout"
        )
        (self.repo / stdout_artifact["uri"]).write_text("mutated stdout\n")

        report = audit_measurement_v1(
            result.manifest,
            list(result.runs),
            artifact_root=self.repo,
            registration_anchor=result.anchor,
        )

        self.assertFalse(report["artifacts_verified"])
        self.assertFalse(report["estimate_reportable"])
        self.assertIn("artifact_hash_mismatch", {error["code"] for error in report["errors"]})

    def test_evaluator_semantics_come_only_from_retained_attempt_stdout(self) -> None:
        result, _, _ = self._run(executor=SplitStreamExecutor(self.repo, self.answer))

        for run in result.runs:
            self.assertEqual(0, run["costs"]["tool_calls"])
            self.assertEqual(1000, run["costs"]["input_tokens"])
            answer_artifact = next(
                artifact for artifact in run["artifacts"] if artifact["kind"] == "answer"
            )
            retained_answer = json.loads((self.repo / answer_artifact["uri"]).read_bytes())
            self.assertEqual(self.answer, retained_answer)
            tool_log = next(
                artifact for artifact in run["artifacts"] if artifact["kind"] == "tool_log"
            )
            self.assertNotIn(
                b'"forged": true',
                (self.repo / tool_log["uri"]).read_bytes(),
            )

    def test_answer_only_understanding_is_evaluator_backed_not_skipped(self) -> None:
        result, _, _ = self._run(
            executor=FakeExecutor(self.repo, self.answer, include_tool=False)
        )

        for run in result.runs:
            self.assertEqual(0, run["costs"]["tool_calls"])
            self.assertEqual(1, len(run["behavior_events"]))
            self.assertEqual("success", run["behavior_events"][0]["result"])
            self.assertEqual(
                "schema_constrained_answer_evaluation",
                run["behavior_events"][0]["event_type"],
            )
            self.assertEqual("harness_trace", run["behavior_events"][0]["source"])
            self.assertIsNone(run["behavior_events"][0]["failure_code"])
            self.assertEqual(
                ["understand"], run["behavior_summary"]["successful_phases"]
            )
            self.assertEqual([], run["behavior_summary"]["skipped_phases"])

    def test_inline_snapshot_task_rejects_every_tool_call(self) -> None:
        for action_type in ("command_execution", "file_change", "web_search"):
            with self.subTest(action_type=action_type):
                repo = self.root / f"artifacts-action-{action_type}"
                executor = FakeExecutor(
                    repo,
                    self.answer,
                    tool_lifecycle_events=[
                        {
                            "type": "item.completed",
                            "item": {"id": "action-1", "type": action_type},
                        }
                    ],
                )
                original = self.repo
                self.repo = repo
                try:
                    with self.assertRaisesRegex(
                        FrontierCanaryError, "forbids every tool call"
                    ):
                        self._run(executor=executor)
                finally:
                    self.repo = original

    def test_codex_jsonl_rejects_duplicate_keys_and_missing_turn_start(self) -> None:
        duplicate = (
            '{"type":"thread.started","thread_id":"duplicate-thread"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"item.completed","item":'
            '{"id":"item_0","type":"command_execution",'
            '"type":"agent_message","text":"{}"}}\n'
            '{"type":"turn.failed","type":"turn.completed","usage":'
            '{"input_tokens":1,"output_tokens":1,"cached_input_tokens":0}}\n'
        )
        duplicate_path = self.root / "duplicate-keys.jsonl"
        duplicate_path.write_text(duplicate)
        with self.assertRaisesRegex(FrontierCanaryError, "duplicate key"):
            _parse_retained_codex_jsonl(duplicate_path, slot_id="duplicate-slot")
        with self.assertRaisesRegex(FrontierCanaryError, "duplicate key"):
            parse_codex_events(
                '{"type":"turn.failed","type":"turn.completed"}\n'
            )

        no_turn_start = self.root / "no-turn-start.jsonl"
        no_turn_start.write_text(
            "\n".join(
                [
                    json.dumps(
                        {"type": "thread.started", "thread_id": "no-turn-start"}
                    ),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "item_0",
                                "type": "agent_message",
                                "text": "{}",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {
                                "input_tokens": 1,
                                "output_tokens": 1,
                                "cached_input_tokens": 0,
                            },
                        }
                    ),
                ]
            )
            + "\n"
        )
        with self.assertRaisesRegex(FrontierCanaryError, "successful event grammar"):
            _parse_retained_codex_jsonl(no_turn_start, slot_id="no-turn-slot")

        hidden_item = self.root / "hidden-item-envelope.jsonl"
        hidden_item.write_text(
            "\n".join(
                [
                    json.dumps(
                        {"type": "thread.started", "thread_id": "hidden-item"}
                    ),
                    json.dumps({"type": "turn.started"}),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "action": {"type": "file_change", "path": "secret"},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "item_0",
                                "type": "agent_message",
                                "text": "{}",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {
                                "input_tokens": 1,
                                "output_tokens": 1,
                                "cached_input_tokens": 0,
                            },
                        }
                    ),
                ]
            )
            + "\n"
        )
        with self.assertRaisesRegex(FrontierCanaryError, "ambiguous item envelope"):
            _parse_retained_codex_jsonl(hidden_item, slot_id="hidden-item-slot")

    def test_read_only_state_drift_fails_closed(self) -> None:
        collector = FakeCollector(self.capture, drift_call=3)
        with self.assertRaisesRegex(FrontierCanaryError, "projection drifted"):
            self._run(collector=collector, executor=FakeExecutor(self.repo, self.answer))

    def test_duplicate_thread_identity_fails_closed(self) -> None:
        with self.assertRaisesRegex(FrontierCanaryError, "reused a Codex thread"):
            self._run(executor=FakeExecutor(self.repo, self.answer, duplicate_id=True))

    def test_multiple_thread_started_events_in_one_retained_stream_fail_closed(self) -> None:
        executor = FakeExecutor(
            self.repo,
            self.answer,
            extra_thread_id="second-thread-in-one-stream",
        )
        with self.assertRaisesRegex(FrontierCanaryError, "exactly one thread.started"):
            self._run(executor=executor)

    def test_malformed_nonempty_retained_jsonl_line_fails_closed(self) -> None:
        executor = FakeExecutor(
            self.repo,
            self.answer,
            malformed_line="not-jsonl",
        )
        with self.assertRaisesRegex(FrontierCanaryError, "JSONL line 3 is malformed"):
            self._run(executor=executor)

    def test_identified_and_anonymous_unmatched_tool_starts_fail_closed(self) -> None:
        cases = {
            "identified": {
                "type": "item.started",
                "item": {"id": "cmd-1", "type": "command_execution"},
            },
            "anonymous": {
                "type": "item.started",
                "item": {"type": "command_execution"},
            },
        }
        for name, event in cases.items():
            repo = self.root / f"artifacts-{name}"
            executor = FakeExecutor(
                repo,
                self.answer,
                tool_lifecycle_events=[event],
            )
            original = self.repo
            self.repo = repo
            try:
                with self.subTest(name=name), self.assertRaisesRegex(
                    FrontierCanaryError, "no (?:bindable )?completion"
                ):
                    self._run(executor=executor)
            finally:
                self.repo = original

    def test_duplicate_and_out_of_order_tool_lifecycles_fail_closed(self) -> None:
        cases = {
            "duplicate": [
                {
                    "type": "item.completed",
                    "item": {"id": "cmd-1", "type": "command_execution"},
                },
                {
                    "type": "item.completed",
                    "item": {"id": "cmd-1", "type": "command_execution"},
                },
            ],
            "out-of-order": [
                {
                    "type": "item.completed",
                    "item": {"id": "cmd-1", "type": "command_execution"},
                },
                {
                    "type": "item.started",
                    "item": {"id": "cmd-1", "type": "command_execution"},
                },
            ],
        }
        for name, events in cases.items():
            repo = self.root / f"artifacts-lifecycle-{name}"
            executor = FakeExecutor(
                repo,
                self.answer,
                tool_lifecycle_events=events,
            )
            original = self.repo
            self.repo = repo
            try:
                with self.subTest(name=name), self.assertRaisesRegex(
                    FrontierCanaryError, "duplicate|out of order"
                ):
                    self._run(executor=executor)
            finally:
                self.repo = original

    def test_turn_completion_is_exact_and_sole_usage_source(self) -> None:
        missing = FakeExecutor(
            self.repo,
            self.answer,
            turn_completed_events=[],
        )
        with self.assertRaisesRegex(
            FrontierCanaryError,
            "successful event grammar|exactly one turn.completed",
        ):
            self._run(executor=missing)

        repo = self.root / "artifacts-duplicate-turn"
        duplicate = FakeExecutor(
            repo,
            self.answer,
            turn_completed_events=[
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 1, "output_tokens": 1, "cached_input_tokens": 0},
                },
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 2, "output_tokens": 2, "cached_input_tokens": 0},
                },
            ],
        )
        original = self.repo
        self.repo = repo
        try:
            with self.assertRaisesRegex(FrontierCanaryError, "exactly one turn.completed"):
                self._run(executor=duplicate)
        finally:
            self.repo = original

        repo = self.root / "artifacts-reasoning-usage"
        reasoning = FakeExecutor(
            repo,
            self.answer,
            turn_completed_events=[
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 1000,
                        "output_tokens": 200,
                        "cached_input_tokens": 10,
                        "reasoning_output_tokens": 50,
                    },
                }
            ],
        )
        self.repo = repo
        try:
            result, _, _ = self._run(executor=reasoning)
            self.assertEqual(200, result.runs[0]["costs"]["output_tokens"])
        finally:
            self.repo = original

        for label, usage in (
            (
                "unknown",
                {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cached_input_tokens": 10,
                    "unregistered_tokens": 1,
                },
            ),
            (
                "reasoning-overflow",
                {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cached_input_tokens": 10,
                    "reasoning_output_tokens": 201,
                },
            ),
            (
                "cached-overflow",
                {
                    "input_tokens": 9,
                    "output_tokens": 200,
                    "cached_input_tokens": 10,
                },
            ),
            (
                "reasoning-bool",
                {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cached_input_tokens": 10,
                    "reasoning_output_tokens": True,
                },
            ),
        ):
            repo = self.root / f"artifacts-usage-{label}"
            executor = FakeExecutor(
                repo,
                self.answer,
                turn_completed_events=[{"type": "turn.completed", "usage": usage}],
            )
            self.repo = repo
            try:
                with self.subTest(label=label), self.assertRaisesRegex(
                    FrontierCanaryError,
                    "usage fields are not exact|cannot exceed|non-negative integer",
                ):
                    self._run(executor=executor)
            finally:
                self.repo = original

        repo = self.root / "artifacts-sole-usage"
        executor = FakeExecutor(
            repo,
            self.answer,
            extra_usage_event={
                "type": "usage.reported",
                "usage": {
                    "input_tokens": 999999,
                    "output_tokens": 999999,
                    "cached_input_tokens": 999999,
                },
            },
        )
        self.repo = repo
        try:
            with self.assertRaisesRegex(FrontierCanaryError, "failed or unknown event"):
                self._run(executor=executor)
        finally:
            self.repo = original

    def test_agent_message_started_is_not_a_final_answer(self) -> None:
        executor = FakeExecutor(
            self.repo,
            self.answer,
            agent_message_event_type="item.started",
        )
        with self.assertRaisesRegex(FrontierCanaryError, "no agent answer"):
            self._run(executor=executor)

    def test_retained_tool_cannot_attempt_direct_ddev_or_docker_access(self) -> None:
        for tool in ("ddev", "docker"):
            repo = self.root / f"artifacts-forbidden-{tool}"
            executor = FakeExecutor(
                repo,
                self.answer,
                tool_lifecycle_events=[
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "cmd-1",
                            "type": "command_execution",
                            "command": f"{tool} status",
                            "exit_code": 1,
                        },
                    }
                ],
            )
            original = self.repo
            self.repo = repo
            try:
                with self.subTest(tool=tool), self.assertRaisesRegex(
                    FrontierCanaryError, "forbidden direct DDEV/Docker"
                ):
                    self._run(executor=executor)
            finally:
                self.repo = original

    def test_node_body_mutation_with_identical_inventory_fails_closed(self) -> None:
        collector = FakeCollector(
            self.capture,
            drift_call=3,
            drift_source="database",
        )
        with self.assertRaisesRegex(FrontierCanaryError, "projection drifted"):
            self._run(collector=collector, executor=FakeExecutor(self.repo, self.answer))

    def test_attempt_receipt_slot_substitution_fails_closed(self) -> None:
        executor = FakeExecutor(
            self.repo,
            self.answer,
            receipt_slot_id="frontier-999",
        )
        with self.assertRaisesRegex(FrontierCanaryError, "attempt receipt run_id"):
            self._run(executor=executor)

    def test_attempt_receipt_provider_identity_substitution_fails_closed(self) -> None:
        executor = FakeExecutor(
            self.repo,
            self.answer,
            receipt_provider_request_id="substituted-provider-request",
        )
        with self.assertRaisesRegex(
            FrontierCanaryError, "attempt receipt provider_request_id"
        ):
            self._run(executor=executor)

    def test_attempt_ledger_never_overwrites_terminal_failure(self) -> None:
        arguments = {
            "artifact_repo": self.repo,
            "invocation_id": "appendonly000000000000000000000001",
            "attempt": 1,
            "slot_id": "frontier-001",
            "argv": ("codex", "exec"),
            "stdout": '{"type":"error"}\n',
            "stderr": "failed",
            "returncode": 1,
            "timed_out": False,
        }
        begun = _begin_attempt(**arguments)
        reference = _finalize_attempt(
            begun,
            status="failed",
            thread_id=None,
            failure="first failure",
        )
        receipt_path = self.repo / reference["uri"]
        original = receipt_path.read_bytes()

        with self.assertRaisesRegex(FrontierCanaryError, "cannot be overwritten"):
            _begin_attempt(**arguments)

        self.assertEqual(original, receipt_path.read_bytes())

    def test_preexisting_attempt_ledger_blocks_new_registration(self) -> None:
        orphan = self.repo / "attempts" / "orphan" / "attempt-001"
        orphan.mkdir(parents=True)
        (orphan / "codex.stdout.jsonl").write_text("orphan")
        with self.assertRaisesRegex(FrontierCanaryError, "empty dedicated directory"):
            self._run()

    def test_snapshot_rejects_root_and_nested_dot_git_metadata(self) -> None:
        root_git = self.workdir / ".git"
        root_git.mkdir()
        (root_git / "secret").write_text("hidden")
        with self.assertRaisesRegex(FrontierCanaryError, "must not contain any .git"):
            derive_agent_visible_workspace(self.workdir)
        shutil.rmtree(root_git)

        nested_git = self.workdir / "nested" / ".git"
        nested_git.mkdir(parents=True)
        (nested_git / "secret").write_text("hidden")
        with self.assertRaisesRegex(FrontierCanaryError, "forbidden .git metadata"):
            derive_agent_visible_workspace(self.workdir)

    def test_post_registration_dot_git_injection_fails_closed(self) -> None:
        executor = DotGitInjectingExecutor(self.repo, self.answer)
        with self.assertRaisesRegex(FrontierCanaryError, "must not contain any .git"):
            self._run(executor=executor)
        self.assertFalse((self.repo / "runs").exists())

    def test_artifact_repo_and_snapshot_must_not_overlap_before_writes(self) -> None:
        cases = {
            "equal": self.workdir,
            "child": self.workdir / "evidence",
            "parent": self.root,
        }
        for name, repo in cases.items():
            with self.subTest(name=name):
                original = self.repo
                self.repo = repo
                try:
                    with self.assertRaisesRegex(FrontierCanaryError, "must not overlap"):
                        self._run()
                finally:
                    self.repo = original
                self.assertFalse((self.workdir / ".git").exists())
                if name == "child":
                    self.assertFalse(repo.exists())

    def test_nonempty_artifact_repo_is_rejected_without_mutation(self) -> None:
        repo = self.root / "occupied-artifacts"
        repo.mkdir()
        marker = repo / "unrelated.txt"
        marker.write_text("preserve me")
        original = self.repo
        self.repo = repo
        try:
            with self.assertRaisesRegex(FrontierCanaryError, "empty dedicated directory"):
                self._run()
        finally:
            self.repo = original
        self.assertEqual("preserve me", marker.read_text())
        self.assertFalse((repo / ".git").exists())

    def test_cli_boundary_validator_rejects_equal_child_and_parent_paths(self) -> None:
        observed = self.root / "observed"
        observed.mkdir()
        for other in (observed, observed / "child", self.root):
            with self.subTest(other=other), self.assertRaisesRegex(
                FrontierCanaryError, "must not overlap"
            ):
                _validate_nonoverlap_paths(
                    {"observed_root": observed, "artifact_repo": other}
                )

    def test_dedicated_output_directory_rejects_preexisting_contents(self) -> None:
        empty = self.root / "empty-capture"
        empty.mkdir()
        _validate_dedicated_output_directory(empty, "--capture-dir")

        occupied = self.root / "occupied-capture"
        occupied.mkdir()
        marker = occupied / "capture-001-frontier-001.json"
        marker.write_text("preserve me")
        with self.assertRaisesRegex(FrontierCanaryError, "empty dedicated directory"):
            _validate_dedicated_output_directory(occupied, "--capture-dir")
        self.assertEqual("preserve me", marker.read_text())

    def test_isolated_bootstrap_ignores_spoofed_external_and_local_pyc(self) -> None:
        package_source = Path(__file__).resolve().parents[1]
        for kind in ("external", "local"):
            copied_root = self.root / f"pycache-{kind}" / "repo"
            copied_package = copied_root / "agent_readiness"
            shutil.copytree(
                package_source,
                copied_package,
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                    "experiments",
                    "fixtures",
                    "modules",
                    "public",
                    "ralph",
                    "recipes",
                    "runs",
                    "tools",
                ),
            )
            marker = copied_root / f"{kind}-pyc-executed"
            external_prefix = copied_root / "attacker-pycache"
            source = copied_package / "__init__.py"
            _write_malicious_timestamp_pyc(
                source,
                marker,
                pycache_prefix=external_prefix if kind == "external" else None,
            )
            environment = os.environ.copy()
            environment.pop("PYTHONPYCACHEPREFIX", None)
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            if kind == "external":
                environment.update(
                    {
                        "PYTHONPYCACHEPREFIX": str(external_prefix.resolve()),
                        "FRONTIER_CANARY_FRESH_PYCACHE": "1",
                    }
                )
            control = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        f"sys.path.insert(0, {str(copied_root.resolve())!r}); "
                        "import agent_readiness"
                    ),
                ],
                cwd=copied_root,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, control.returncode, control.stderr)
            self.assertTrue(marker.is_file(), f"{kind} malicious pyc control did not execute")
            marker.unlink()

            completed = subprocess.run(
                [
                    sys.executable,
                    str(copied_package / "scripts" / "run_frontier_canary.py"),
                    "--help",
                ],
                cwd=copied_root,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            with self.subTest(kind=kind):
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertFalse(marker.exists())
                self.assertIn("Run a preregistered", completed.stdout)

    def test_isolated_bootstrap_precedes_adjacent_stdlib_shadow(self) -> None:
        package_source = Path(__file__).resolve().parents[1]
        copied_root = self.root / "stdlib-shadow" / "repo"
        copied_package = copied_root / "agent_readiness"
        shutil.copytree(
            package_source,
            copied_package,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "experiments",
                "fixtures",
                "modules",
                "public",
                "ralph",
                "recipes",
                "runs",
                "tools",
            ),
        )
        scripts = copied_package / "scripts"
        marker = copied_root / "adjacent-argparse-executed"
        (scripts / "argparse.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('ADJACENT_STDLIB_EXECUTED')\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        control = subprocess.run(
            [sys.executable, "-c", "import argparse"],
            cwd=scripts,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, control.returncode, control.stderr)
        self.assertTrue(marker.is_file(), "adjacent argparse control did not execute")
        marker.unlink()

        completed = subprocess.run(
            [
                sys.executable,
                str(scripts / "run_frontier_canary.py"),
                "--help",
            ],
            cwd=copied_root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertFalse(marker.exists())
        self.assertIn("Run a preregistered", completed.stdout)

    def test_isolated_bootstrap_does_not_add_repo_root_stdlib_shadow(self) -> None:
        package_source = Path(__file__).resolve().parents[1]
        copied_root = self.root / "root-stdlib-shadow" / "repo"
        copied_package = copied_root / "agent_readiness"
        shutil.copytree(
            package_source,
            copied_package,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "experiments",
                "fixtures",
                "modules",
                "public",
                "ralph",
                "recipes",
                "runs",
                "tools",
            ),
        )
        marker = copied_root / "root-statistics-executed"
        (copied_root / "statistics.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('ROOT_STDLIB_EXECUTED')\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        control = subprocess.run(
            [sys.executable, "-c", "import statistics"],
            cwd=copied_root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, control.returncode, control.stderr)
        self.assertTrue(marker.is_file(), "root statistics control did not execute")
        marker.unlink()

        completed = subprocess.run(
            [
                sys.executable,
                str(copied_package / "scripts" / "run_frontier_canary.py"),
                "--help",
            ],
            cwd=copied_root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertFalse(marker.exists())
        self.assertIn("Run a preregistered", completed.stdout)

    def test_unsafe_codex_flags_are_rejected(self) -> None:
        schema = FIXTURES / "inventory_answer_pass.json"
        for extra in (
            ("--dangerously-bypass-approvals-and-sandbox",),
            ("--sandbox=workspace-write",),
            ("--add-dir", "/tmp"),
            ("-s", "danger-full-access"),
            ("-c", "sandbox_permissions=['disk-full-read-access']"),
            ("--enable", "plugins"),
        ):
            with self.subTest(extra=extra), self.assertRaises(FrontierCanaryError):
                build_codex_argv(
                    self.binary,
                    workdir=self.workdir,
                    output_schema=schema,
                    model="gpt-5.4-2026-07-09",
                    extra_args=extra,
                )

    def test_canonical_apps_disable_pair_cannot_be_mutated(self) -> None:
        schema = FIXTURES / "inventory_answer_pass.json"
        canonical = list(
            build_codex_argv(
                self.binary,
                workdir=self.workdir,
                output_schema=schema,
                model="gpt-5.4-2026-07-09",
            )
        )
        app_flag = next(
            index
            for index in range(len(canonical) - 1)
            if canonical[index : index + 2] == ["--disable", "apps"]
        )
        mutations = {
            "omitted": canonical[:app_flag] + canonical[app_flag + 2 :],
            "reordered": canonical[:app_flag]
            + ["apps", "--disable"]
            + canonical[app_flag + 2 :],
            "duplicated": canonical[:app_flag]
            + ["--disable", "apps", "--disable", "apps"]
            + canonical[app_flag + 2 :],
            "case": canonical[: app_flag + 1]
            + ["Apps"]
            + canonical[app_flag + 2 :],
            "joined": canonical[:app_flag]
            + ["--disable=apps"]
            + canonical[app_flag + 2 :],
        }
        for name, argv in mutations.items():
            with self.subTest(name=name), self.assertRaises(FrontierCanaryError):
                validate_codex_argv(argv)

    def test_flag_shaped_or_control_bearing_model_selectors_are_rejected(self) -> None:
        schema = FIXTURES / "inventory_answer_pass.json"
        for model in (
            "--foo",
            "--config=sandbox_workspace_write=true",
            "gpt-5.4\n--config=sandbox_workspace_write=true",
            "gpt-5.4 current",
        ):
            with self.subTest(model=model), self.assertRaisesRegex(
                FrontierCanaryError,
                "non-moving, explicit preregistered selector",
            ):
                build_codex_argv(
                    self.binary,
                    workdir=self.workdir,
                    output_schema=schema,
                    model=model,
                )

        argv = list(
            build_codex_argv(
                self.binary,
                workdir=self.workdir,
                output_schema=schema,
                model="gpt-5.4-2026-07-09",
            )
        )
        argv[argv.index("--model") + 1] = "--config=sandbox_workspace_write=true"
        with self.assertRaisesRegex(
            FrontierCanaryError,
            "argv model is not a non-moving, explicit preregistered selector",
        ):
            validate_codex_argv(argv)

        valid_argv = list(
            build_codex_argv(
                self.binary,
                workdir=self.workdir,
                output_schema=schema,
                model="gpt-5.4-2026-07-09",
            )
        )
        for flag, replacement in (
            ("--cd", "--config=sandbox_workspace_write=true"),
            ("--output-schema", "--profile=evil"),
        ):
            with self.subTest(flag=flag):
                argv = list(valid_argv)
                argv[argv.index(flag) + 1] = replacement
                with self.assertRaisesRegex(
                    FrontierCanaryError,
                    "is not a canonical absolute",
                ):
                    validate_codex_argv(argv)

    def test_free_agent_version_assertion_is_rejected(self) -> None:
        with self.assertRaisesRegex(FrontierCanaryError, "not requested version"):
            run_frontier_canary(
                artifact_repo=self.repo,
                workdir=self.workdir,
                codex_binary=self.binary,
                agent_version="9.9.9",
                model_provider="openai",
                model_id="gpt-5.4",
                model_snapshot="gpt-5.4-2026-07-09",
                collector=FakeCollector(self.capture),
                executor=FakeExecutor(self.repo, self.answer),
                registered_at=datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc),
                clock=StepClock(),
            )

    def test_unretained_executor_semantics_are_ignored(self) -> None:
        executor = FakeExecutor(
            self.repo,
            self.answer,
            observed_model_selector="gpt-5.4-2026-07-08",
        )
        result, _, _ = self._run(executor=executor)
        self.assertEqual(1.0, result.audit["analysis"]["estimate"])

    def test_binary_bytes_are_rechecked_after_each_executor_call(self) -> None:
        executor = MutatingBinaryExecutor(self.repo, self.answer, self.binary)
        with self.assertRaisesRegex(FrontierCanaryError, "binary bytes changed"):
            self._run(executor=executor)

    def test_running_python_must_match_the_registered_interpreter(self) -> None:
        policy = deepcopy(self.execution_environment_policy)
        policy["host_tools"]["python"] = {
            "path": str(self.binary.resolve()),
            "sha256": file_sha256(self.binary),
        }
        with self.assertRaisesRegex(FrontierCanaryError, "interpreter executing"):
            run_frontier_canary(
                artifact_repo=self.repo,
                workdir=self.workdir,
                codex_binary=self.binary,
                agent_version="0.142.5",
                model_provider="openai",
                model_id="gpt-5.4",
                model_snapshot="gpt-5.4-2026-07-09",
                collector=FakeCollector(self.capture),
                executor=FakeExecutor(self.repo, self.answer),
                registered_at=datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc),
                clock=StepClock(),
                execution_environment_policy=policy,
            )

    def test_executed_source_deletion_and_substitution_fail_at_boundary(self) -> None:
        for delete in (False, True):
            label = "deleted" if delete else "substituted"
            repo = self.root / f"source-closure-{label}"
            source = self.root / f"executed-{label}.py"
            source.write_text("registered executed source\n", encoding="utf-8")
            original_repo = self.repo
            self.repo = repo
            executor = MutatingSourceExecutor(repo, self.answer, source, delete=delete)
            try:
                with patch(
                    "agent_readiness.frontier_canary._executed_source_paths",
                    return_value={"test-executed-source": source},
                ), self.subTest(label=label), self.assertRaisesRegex(
                    FrontierCanaryError, "Executed source closure drifted"
                ):
                    self._run(executor=executor)
            finally:
                self.repo = original_repo

    def test_pinned_project_runner_ignores_path_ddev_and_docker_shims(self) -> None:
        pinned = self.root / "pinned-host-tools"
        shims = self.root / "host-tool-shims"
        pinned.mkdir()
        shims.mkdir()
        markers: list[Path] = []
        host_tools = {}
        for name in ("ddev", "docker"):
            binary = pinned / name
            binary.write_text(
                f"#!/bin/sh\nprintf 'pinned-{name}\\n'\n", encoding="utf-8"
            )
            binary.chmod(0o755)
            host_tools[name] = {
                "path": str(binary.resolve()),
                "sha256": file_sha256(binary),
            }
            marker = self.root / f"{name}-shim-ran"
            markers.append(marker)
            shim = shims / name
            shim.write_text(
                f"#!/bin/sh\nprintf shim > {marker}\nexit 97\n", encoding="utf-8"
            )
            shim.chmod(0o755)
        socket = self.root / "runner-docker.sock"
        socket.touch()
        runner = _pinned_project_runner(
            {
                "host_tools": host_tools,
                "inherited_environment": {"PATH": str(shims)},
                "docker_socket_path": str(socket),
            },
            self.workdir,
            expected_vendor_tree_sha256=None,
        )

        self.assertEqual("pinned-ddev", runner(["ddev", "--version"], self.workdir).stdout.strip())
        self.assertEqual("pinned-docker", runner(["docker", "--version"], self.workdir).stdout.strip())
        self.assertFalse(any(marker.exists() for marker in markers))

    def test_semantically_invalid_stdout_is_finalized_failed(self) -> None:
        valid_answer = json.dumps(self.answer)
        cases = {
            "missing-turn": [
                {"type": "thread.started", "thread_id": "thread-missing-turn"},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": valid_answer},
                },
            ],
            "out-of-order": [
                {"type": "thread.started", "thread_id": "thread-out-of-order"},
                {
                    "type": "item.completed",
                    "item": {"id": "cmd-1", "type": "command_execution"},
                },
                {
                    "type": "item.started",
                    "item": {"id": "cmd-1", "type": "command_execution"},
                },
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": valid_answer},
                },
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cached_input_tokens": 0,
                    },
                },
            ],
        }
        for index, (label, events) in enumerate(cases.items(), start=1):
            repo = self.root / f"semantic-ledger-{label}"
            begun = _begin_attempt(
                repo,
                invocation_id=f"semanticledger{index:020d}",
                attempt=1,
                slot_id="frontier-001",
                argv=("codex", "exec"),
                stdout="\n".join(json.dumps(event) for event in events) + "\n",
                stderr="",
                returncode=0,
                timed_out=False,
            )
            with self.subTest(label=label), self.assertRaises(FrontierCanaryError):
                _finalize_semantically_valid_attempt(
                    begun, slot_id="frontier-001", stderr=""
                )
            receipt = json.loads(
                (begun["attempt_dir"] / "attempt-receipt.json").read_bytes()
            )
            self.assertEqual("failed", receipt["status"])

    def test_registration_ignores_path_git_shim_and_inherited_git_controls(self) -> None:
        shim_dir = self.root / "git-shim"
        shim_dir.mkdir()
        marker = self.root / "git-shim-ran"
        shim = shim_dir / "git"
        shim.write_text(
            "#!/bin/sh\nprintf shim > " + str(marker) + "\nexit 97\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
        hostile_environment = {
            "PATH": str(shim_dir),
            "GIT_CONFIG_SYSTEM": str(self.root / "hostile-system-config"),
            "GIT_CONFIG_GLOBAL": str(self.root / "hostile-global-config"),
            "GIT_NO_REPLACE_OBJECTS": "0",
            "GIT_REPLACE_REF_BASE": "refs/replace/frontier-hostile",
        }
        with patch.dict(os.environ, hostile_environment, clear=False):
            result, _, _ = self._run()

        self.assertFalse(marker.exists())
        self.assertRegex(result.anchor.commit, r"^[0-9a-f]{40}$")
        hooks = self.repo / ".git" / "hooks"
        self.assertFalse(hooks.exists() and any(hooks.iterdir()))

    def test_ddev_substrate_is_derived_from_code_runtime_and_image_bytes(self) -> None:
        site = self.root / "derived-site"
        (site / "vendor" / "composer").mkdir(parents=True)
        (site / "web" / "core").mkdir(parents=True)
        (site / "web" / "modules" / "custom" / "demo").mkdir(parents=True)
        (site / "web" / "modules" / "contrib" / "disabled").mkdir(parents=True)
        (site / ".ddev").mkdir()
        (site / "web" / "core" / "lib.php").write_text("<?php // core\n")
        (site / "web" / "modules" / "custom" / "demo" / "demo.info.yml").write_text(
            "name: Demo\ntype: module\n"
        )
        (site / "web" / "modules" / "contrib" / "disabled" / "disabled.info.yml").write_text(
            "name: Disabled\ntype: module\n"
        )
        (site / ".ddev" / "config.yaml").write_text("name: frontier-fixture\n")
        (site / "composer.lock").write_text(
            json.dumps(
                {
                    "packages": [
                        {
                            "name": "drupal/core",
                            "version": "11.3.11",
                            "source": {"reference": "abc123core"},
                        },
                        {
                            "name": "example/demo",
                            "version": "dev-main",
                            "source": {"reference": "abc123demo"},
                        },
                        {
                            "name": "drupal/disabled",
                            "version": "1.2.3",
                            "type": "drupal-module",
                            "source": {"reference": "abc123disabled"},
                        },
                    ],
                    "packages-dev": [],
                }
            )
        )
        (site / "vendor" / "composer" / "installed.json").write_text(
            json.dumps(
                {
                    "packages": [
                        {
                            "name": "drupal/core",
                            "version": "11.3.11",
                            "install-path": "../../web/core",
                            "source": {"reference": "abc123core"},
                        },
                        {
                            "name": "example/demo",
                            "version": "dev-main",
                            "install-path": "../../web/modules/custom/demo",
                            "source": {"reference": "abc123demo"},
                        },
                        {
                            "name": "drupal/disabled",
                            "version": "1.2.3",
                            "type": "drupal-module",
                            "install-path": "../../web/modules/contrib/disabled",
                            "source": {"reference": "abc123disabled"},
                        },
                    ]
                }
            )
        )
        runner = FakeSubstrateRunner()

        substrate = derive_ddev_substrate(site, runner=runner)

        self.assertEqual("11.3.11", substrate["core"]["version"])
        self.assertEqual("abc123core", substrate["core"]["revision"])
        by_name = {item["name"]: item for item in substrate["components"]}
        self.assertEqual({"example/demo", "drupal/disabled"}, set(by_name))
        self.assertTrue(by_name["example/demo"]["version"].startswith("tree-"))
        self.assertEqual("abc123demo", by_name["example/demo"]["revision"])
        self.assertEqual("abc123disabled", by_name["drupal/disabled"]["revision"])
        self.assertEqual("8.3.23", substrate["runtime"]["php_version"])
        self.assertEqual("mysql", substrate["runtime"]["database_driver"])
        self.assertEqual("11.4.7-MariaDB", substrate["runtime"]["database_version"])
        self.assertEqual(_hash("local-image"), substrate["runtime"]["container_image_digest"])
        self.assertEqual(_hash("repo-image"), substrate["runtime"]["os_image_digest"])
        self.assertEqual("sha256:" + hashlib.sha256((site / "composer.lock").read_bytes()).hexdigest(), substrate["composer_lock_sha256"])
        self.assertIn(("ddev", "exec", "php", "-r", "echo PHP_VERSION;"), runner.calls)
        self.assertTrue(any(call[:3] == ("ddev", "drush", "sql:query") for call in runner.calls))

    def test_ddev_substrate_fails_without_registry_image_digest(self) -> None:
        site = self.root / "broken-derived-site"
        (site / "vendor" / "composer").mkdir(parents=True)
        (site / "web" / "core").mkdir(parents=True)
        (site / "web" / "modules" / "custom" / "demo").mkdir(parents=True)
        (site / ".ddev").mkdir()
        (site / "web" / "core" / "core.txt").write_text("core")
        (site / "web" / "modules" / "custom" / "demo" / "demo.info.yml").write_text("name: Demo\n")
        (site / ".ddev" / "config.yaml").write_text("name: broken\n")
        (site / "composer.lock").write_text('{"packages":[],"packages-dev":[]}')
        (site / "vendor" / "composer" / "installed.json").write_text('{"packages":[]}')
        runner = FakeSubstrateRunner(repo_digest="<no value>")
        with self.assertRaisesRegex(FrontierCanaryError, "registry digest"):
            derive_ddev_substrate(site, runner=runner)

    def test_persistent_database_projection_ignores_cache_and_timestamp_not_node_body(self) -> None:
        first = derive_ddev_site_projection(
            self.workdir,
            runner=FakeProjectionRunner(
                cache_value="cache-a",
                body_value="original body",
                timestamp="2026-07-10 10:00:00",
            ),
        )
        transient_change = derive_ddev_site_projection(
            self.workdir,
            runner=FakeProjectionRunner(
                cache_value="cache-b",
                body_value="original body",
                timestamp="2026-07-10 10:00:01",
            ),
        )
        node_change = derive_ddev_site_projection(
            self.workdir,
            runner=FakeProjectionRunner(
                cache_value="cache-b",
                body_value="mutated body",
                timestamp="2026-07-10 10:00:02",
            ),
        )

        self.assertEqual(first["database"]["sha256"], transient_change["database"]["sha256"])
        self.assertNotEqual(first["database"]["sha256"], node_change["database"]["sha256"])
        self.assertEqual(["cache_entity"], first["database"]["excluded_data_tables"])
        self.assertNotIn("original body", json.dumps(first))

    def test_ddev_substrate_rejects_external_extension_symlink(self) -> None:
        site = self.root / "symlink-derived-site"
        outside = self.root / "outside-demo"
        (site / "vendor" / "composer").mkdir(parents=True)
        (site / "web" / "core").mkdir(parents=True)
        (site / "web" / "modules" / "custom").mkdir(parents=True)
        (site / ".ddev").mkdir()
        outside.mkdir()
        (outside / "demo.info.yml").write_text("name: Outside Demo\n")
        (site / "web" / "modules" / "custom" / "demo").symlink_to(outside)
        (site / "web" / "core" / "core.txt").write_text("core")
        (site / ".ddev" / "config.yaml").write_text("name: symlink\n")
        (site / "composer.lock").write_text('{"packages":[],"packages-dev":[]}')
        (site / "vendor" / "composer" / "installed.json").write_text('{"packages":[]}')

        with self.assertRaisesRegex(FrontierCanaryError, "escapes project"):
            derive_ddev_substrate(site, runner=FakeSubstrateRunner())

    def test_error_only_codex_attempt_is_durable_classified_and_unresolved(self) -> None:
        stdout = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "thread-usage-limit"}),
                json.dumps(
                    {
                        "type": "error",
                        "message": "You've hit your usage limit; try again at 2:54 AM",
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.failed",
                        "error": {"message": "You've hit your usage limit"},
                    }
                ),
            ]
        )
        events = parse_codex_events(stdout)
        with self.assertRaisesRegex(
            FrontierCanaryError, "classification=codex_usage_limit"
        ) as raised:
            parse_codex_answer(events, returncode=1, stderr="usage exhausted")
        begun = _begin_attempt(
            self.repo,
            invocation_id="usagefailure00000000000000000001",
            attempt=1,
            slot_id="frontier-001",
            argv=("codex", "exec"),
            stdout=stdout,
            stderr="usage exhausted",
            returncode=1,
            timed_out=False,
        )
        reference = _finalize_attempt(
            begun,
            status="failed",
            thread_id="thread-usage-limit",
            failure=str(raised.exception),
        )
        receipt_path = self.repo / reference["uri"]

        raw_receipt = receipt_path.read_bytes()
        receipt = json.loads(raw_receipt)
        self.assertEqual(canonical_json_bytes(receipt), raw_receipt)
        self.assertEqual("codex_usage_limit", receipt["classification"])
        self.assertEqual("failed", receipt["status"])
        self.assertIn("usage limit", receipt["failure"])
        self.assertEqual(stdout, (receipt_path.parent / "codex.stdout.jsonl").read_text())
        self.assertEqual("usage exhausted", (receipt_path.parent / "codex.stderr.txt").read_text())
        self.assertFalse((self.repo / "runs").exists())

    def test_isolated_codex_home_exposes_only_auth_reference_and_no_secret(self) -> None:
        auth = self.root / "auth.json"
        secret = "super-secret-auth-token"
        auth.write_text(json.dumps({"token": secret}))
        token = "fake-nonsecret-sentinel"
        permissions = _fake_permissions_profile(token)
        observed: dict[str, object] = {}

        def fake_run(command, **kwargs):
            home = Path(kwargs["env"]["CODEX_HOME"])
            observed["home"] = home
            observed["env"] = kwargs["env"]
            self.assertEqual(home, Path(kwargs["env"]["HOME"]))
            self.assertEqual(0o700, home.stat().st_mode & 0o777)
            self.assertTrue((home / "auth.json").is_symlink())
            self.assertEqual(
                [
                    "auth.json",
                    "frontier-canary-sentinel",
                    f"{CODEX_CONFIG_PROFILE}.config.toml",
                ],
                sorted(path.name for path in home.iterdir()),
            )
            return subprocess.CompletedProcess(command, 0, "{}\n", "")

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", fake_run
        ):
            result = _run_isolated_codex(
                argv=("codex", "exec"),
                prompt="prompt",
                workdir=self.workdir,
                auth_file=auth,
                permissions_profile=permissions,
                sentinel_token=token,
            )

        self.assertFalse(Path(observed["home"]).exists())
        self.assertEqual(
            [
                "auth.json",
                "frontier-canary-sentinel",
                f"{CODEX_CONFIG_PROFILE}.config.toml",
            ],
            result["runtime_home"]["before"]["entries"],
        )
        self.assertEqual([], result["runtime_home"]["after"]["forbidden_entries"])
        serialized = json.dumps(
            {
                "layout": result["runtime_home"],
                "policy": ISOLATED_ENVIRONMENT_POLICY,
            },
            sort_keys=True,
        )
        self.assertNotIn(secret, serialized)
        self.assertNotIn(str(auth), serialized)
        allowed = set(ISOLATED_ENVIRONMENT_POLICY["inherited_environment_keys"])
        self.assertLessEqual(set(observed["env"]) - {"CODEX_HOME", "HOME"}, allowed)

    def test_isolated_codex_home_reports_injected_plugin_tree(self) -> None:
        auth = self.root / "auth-plugin.json"
        auth.write_text("{}")
        token = "fake-nonsecret-sentinel"
        permissions = _fake_permissions_profile(token)

        def fake_run(command, **kwargs):
            plugin = Path(kwargs["env"]["CODEX_HOME"]) / "plugins" / "bad"
            plugin.mkdir(parents=True)
            (plugin / "SKILL.md").write_text("hidden instruction")
            return subprocess.CompletedProcess(command, 0, "{}\n", "")

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", fake_run
        ):
            result = _run_isolated_codex(
                argv=("codex", "exec"),
                prompt="prompt",
                workdir=self.workdir,
                auth_file=auth,
                permissions_profile=permissions,
                sentinel_token=token,
            )

        self.assertIn("plugins", result["runtime_home"]["after"]["forbidden_entries"])

    def test_runtime_home_identity_auth_target_and_regular_files_fail_closed(self) -> None:
        mutations = (
            "home_mode",
            "auth_target",
            "auth_relative_alias",
            "profile_symlink",
            "profile_mode",
            "sentinel_symlink",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                auth = self.root / f"auth-runtime-{mutation}.json"
                auth.write_text("{}")
                other_auth = self.root / f"other-auth-{mutation}.json"
                other_auth.write_text("{}")
                token = f"fake-nonsecret-sentinel-{mutation}"
                permissions = _fake_permissions_profile(token)
                external_profile = self.root / f"external-profile-{mutation}"
                external_profile.write_text(permissions["profile_text"])
                external_sentinel = self.root / f"external-sentinel-{mutation}"
                external_sentinel.write_text(token)

                def fake_run(command, **kwargs):
                    home = Path(kwargs["env"]["CODEX_HOME"])
                    if mutation == "home_mode":
                        home.chmod(0o777)
                    elif mutation == "auth_target":
                        (home / "auth.json").unlink()
                        (home / "auth.json").symlink_to(other_auth.resolve())
                    elif mutation == "auth_relative_alias":
                        link = home / "auth.json"
                        link.unlink()
                        link.symlink_to(os.path.relpath(auth.resolve(), home))
                    elif mutation == "profile_symlink":
                        profile = home / f"{CODEX_CONFIG_PROFILE}.config.toml"
                        profile.unlink()
                        profile.symlink_to(external_profile.resolve())
                    elif mutation == "profile_mode":
                        (home / f"{CODEX_CONFIG_PROFILE}.config.toml").chmod(0o644)
                    else:
                        sentinel = home / "frontier-canary-sentinel"
                        sentinel.unlink()
                        sentinel.symlink_to(external_sentinel.resolve())
                    return subprocess.CompletedProcess(command, 0, "{}\n", "")

                with patch(
                    "agent_readiness.scripts.run_frontier_canary.run_command",
                    fake_run,
                ):
                    result = _run_isolated_codex(
                        argv=(str(self.binary.resolve()), "exec"),
                        prompt="prompt",
                        workdir=self.workdir,
                        auth_file=auth,
                        permissions_profile=permissions,
                        sentinel_token=token,
                    )

                after = result["runtime_home"]["after"]
                self.assertTrue(after["forbidden_entries"])
                if mutation == "home_mode":
                    self.assertFalse(after["home_mode_verified"])
                elif mutation.startswith("auth_"):
                    self.assertFalse(after["auth_reference_verified"])
                elif mutation.startswith("profile_"):
                    self.assertFalse(
                        after["permissions_profile_regular_file_verified"]
                    )
                else:
                    self.assertFalse(after["sentinel_regular_file_verified"])

    def test_runtime_process_containment_denies_fork_in_the_real_os_sandbox(self) -> None:
        auth = self.root / "auth-process-containment.json"
        auth.write_text("{}")
        token = "fake-nonsecret-process-containment"
        code = (
            "import os,sys\n"
            "print('DAR_FORK_PROBE_STARTED', flush=True)\n"
            "try:\n"
            "    os.fork()\n"
            "except PermissionError as error:\n"
            "    print(f'DAR_FORK_PROBE_DENIED:{error.errno}', flush=True)\n"
            "    raise SystemExit(0)\n"
            "print('DAR_FORK_PROBE_ALLOWED', flush=True)\n"
            "raise SystemExit(91)\n"
        )
        result = _run_isolated_codex(
            argv=(str(Path(sys.executable).resolve()), "-I", "-S", "-c", code),
            prompt="",
            workdir=self.workdir,
            auth_file=auth,
            permissions_profile=_fake_permissions_profile(token),
            sentinel_token=token,
        )

        self.assertIsNotNone(result["completed"])
        self.assertEqual(0, result["completed"].returncode)
        self.assertEqual(
            "DAR_FORK_PROBE_STARTED\nDAR_FORK_PROBE_DENIED:1\n",
            result["stdout"],
        )
        self.assertNotIn("DAR_FORK_PROBE_ALLOWED", result["stdout"])
        self.assertEqual(
            "verified",
            result["runtime_home"]["process_containment"]["status"],
        )

    def test_system_skill_preflight_is_network_denied_and_manifests_exact_bytes(self) -> None:
        observed: dict[str, object] = {}

        def fake_run(command, **kwargs):
            observed["command"] = command
            observed["input"] = kwargs["input"]
            home = Path(kwargs["env"]["CODEX_HOME"])
            _materialize_fake_bootstrap_home(home, codex_binary=self.binary)
            return subprocess.CompletedProcess(
                command, 1, _bootstrap_failure_stdout(), _bootstrap_failure_stderr()
            )

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", fake_run
        ), patch(
            "agent_readiness.scripts.run_frontier_canary._prove_network_denial",
            return_value={"status": "verified"},
        ):
            preflight = _preflight_system_skills(
                self.binary, **self._system_preflight_kwargs()
            )
        try:
            command = observed["command"]
            self.assertEqual(str(self.binary.resolve()), command[0])
            self.assertEqual("-p", command[1])
            self.assertEqual(str(self.binary.resolve()), command[3])
            self.assertIn("--skip-git-repo-check", command)
            self.assertEqual(SYSTEM_SKILL_BOOTSTRAP_PROMPT, observed["input"])
            manifest = preflight["manifest"]
            self.assertEqual(1, len(manifest["files"]))
            self.assertEqual("skills/.system/core/SKILL.md", manifest["files"][0]["path"])
            self.assertEqual(
                _hash("bundled system instruction\n"),
                manifest["files"][0]["sha256"],
            )
            receipt = preflight["receipt"]
            self.assertTrue(receipt["model_turn_started"])
            self.assertTrue(receipt["network_egress_denied"])
            self.assertFalse(receipt["provider_exchange_observed"])
            self.assertFalse(receipt["provider_response_received"])
            self.assertNotIn("model_call", receipt)
            self.assertEqual(1, len(receipt["retained_skill_payloads"]))
        finally:
            shutil.rmtree(preflight["home"])

    def test_system_skill_preflight_rejects_missing_bundled_skills(self) -> None:
        def fake_run(command, **kwargs):
            home = Path(kwargs["env"]["CODEX_HOME"])
            _materialize_fake_bootstrap_home(home, codex_binary=self.binary)
            shutil.rmtree(home / "skills")
            return subprocess.CompletedProcess(
                command, 1, _bootstrap_failure_stdout(), _bootstrap_failure_stderr()
            )

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", fake_run
        ), patch(
            "agent_readiness.scripts.run_frontier_canary._prove_network_denial",
            return_value={"status": "verified"},
        ), self.assertRaisesRegex(FrontierCanaryError, "skills outside"):
            _preflight_system_skills(
                self.binary, **self._system_preflight_kwargs()
            )

    def test_system_skill_preflight_rejects_provider_transport_evidence(self) -> None:
        def fake_run(command, **kwargs):
            home = Path(kwargs["env"]["CODEX_HOME"])
            _materialize_fake_bootstrap_home(home, codex_binary=self.binary)
            events = [
                json.loads(line)
                for line in _bootstrap_failure_stdout().splitlines()
                if line
            ]
            events[2]["message"] = "HTTP error: 401 Unauthorized request_id=req-1"
            stdout = "\n".join(json.dumps(event) for event in events) + "\n"
            return subprocess.CompletedProcess(
                command, 1, stdout, _bootstrap_failure_stderr()
            )

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", fake_run
        ), patch(
            "agent_readiness.scripts.run_frontier_canary._prove_network_denial",
            return_value={"status": "verified"},
        ), self.assertRaisesRegex(
            FrontierCanaryError,
            "exclusively local network denial",
        ):
            _preflight_system_skills(
                self.binary, **self._system_preflight_kwargs()
            )

    def test_system_skill_preflight_rejects_nested_usage_limit_response(self) -> None:
        def fake_run(command, **kwargs):
            home = Path(kwargs["env"]["CODEX_HOME"])
            _materialize_fake_bootstrap_home(home, codex_binary=self.binary)
            events = [
                {"type": "thread.started", "thread_id": "usage-limit"},
                {"type": "turn.started"},
                {
                    "type": "error",
                    "message": "You've hit your usage limit; try again later",
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "usage-error",
                        "type": "error",
                        "error": {"message": "rate_limit_exceeded"},
                    },
                },
                {
                    "type": "turn.failed",
                    "error": {"message": "You've hit your usage limit"},
                },
            ]
            stdout = "\n".join(json.dumps(event) for event in events) + "\n"
            return subprocess.CompletedProcess(
                command,
                1,
                stdout,
                _bootstrap_failure_stderr(),
            )

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", fake_run
        ), patch(
            "agent_readiness.scripts.run_frontier_canary._prove_network_denial",
            return_value={"status": "verified"},
        ), self.assertRaisesRegex(
            FrontierCanaryError,
            "exclusively local network denial",
        ):
            _preflight_system_skills(
                self.binary, **self._system_preflight_kwargs()
            )

    def test_system_skill_preflight_rejects_file_or_symlink_root(self) -> None:
        target = self.root / "preflight-system-symlink-target"
        target.write_text("not a directory\n")

        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                def fake_run(command, **kwargs):
                    home = Path(kwargs["env"]["CODEX_HOME"])
                    _materialize_fake_bootstrap_home(home, codex_binary=self.binary)
                    skills = home / "skills"
                    system_root = skills / ".system"
                    shutil.rmtree(system_root)
                    if kind == "file":
                        system_root.write_text("not a directory\n")
                    else:
                        system_root.symlink_to(target)
                    return subprocess.CompletedProcess(
                        command,
                        1,
                        _bootstrap_failure_stdout(),
                        _bootstrap_failure_stderr(),
                    )

                with patch(
                    "agent_readiness.scripts.run_frontier_canary.run_command",
                    fake_run,
                ), patch(
                    "agent_readiness.scripts.run_frontier_canary._prove_network_denial",
                    return_value={"status": "verified"},
                ), self.assertRaisesRegex(
                    FrontierCanaryError,
                    "real directory|created symlinks|skills outside",
                ):
                    _preflight_system_skills(
                        self.binary, **self._system_preflight_kwargs()
                    )

    def test_system_skill_preflight_rejects_file_or_symlink_parent(self) -> None:
        target = self.root / "preflight-skills-symlink-target"
        target.mkdir()

        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                def fake_run(command, **kwargs):
                    home = Path(kwargs["env"]["CODEX_HOME"])
                    _materialize_fake_bootstrap_home(home, codex_binary=self.binary)
                    skills = home / "skills"
                    shutil.rmtree(skills)
                    if kind == "file":
                        skills.write_text("not a directory\n")
                    else:
                        skills.symlink_to(target, target_is_directory=True)
                    return subprocess.CompletedProcess(
                        command,
                        1,
                        _bootstrap_failure_stdout(),
                        _bootstrap_failure_stderr(),
                    )

                with patch(
                    "agent_readiness.scripts.run_frontier_canary.run_command",
                    fake_run,
                ), patch(
                    "agent_readiness.scripts.run_frontier_canary._prove_network_denial",
                    return_value={"status": "verified"},
                ), self.assertRaisesRegex(
                    FrontierCanaryError,
                    "real directory|created symlinks|skills outside",
                ):
                    _preflight_system_skills(
                        self.binary, **self._system_preflight_kwargs()
                    )

    def test_system_skill_preflight_rejects_symlinked_ephemeral_layout(self) -> None:
        target = self.root / "preflight-tmp-symlink-target"
        target.mkdir()

        for kind in ("tmp", "arg0"):
            with self.subTest(kind=kind):
                def fake_run(command, **kwargs):
                    home = Path(kwargs["env"]["CODEX_HOME"])
                    _materialize_fake_bootstrap_home(home, codex_binary=self.binary)
                    if kind == "tmp":
                        shutil.rmtree(home / "tmp")
                        (home / "tmp").symlink_to(target, target_is_directory=True)
                    else:
                        shutil.rmtree(home / "tmp" / "arg0")
                        (home / "tmp" / "arg0").symlink_to(
                            target, target_is_directory=True
                        )
                    return subprocess.CompletedProcess(
                        command,
                        1,
                        _bootstrap_failure_stdout(),
                        _bootstrap_failure_stderr(),
                    )

                with patch(
                    "agent_readiness.scripts.run_frontier_canary.run_command",
                    fake_run,
                ), patch(
                    "agent_readiness.scripts.run_frontier_canary._prove_network_denial",
                    return_value={"status": "verified"},
                ), self.assertRaisesRegex(
                    FrontierCanaryError,
                    "unregistered symlink",
                ):
                    _preflight_system_skills(
                        self.binary, **self._system_preflight_kwargs()
                    )

    def test_network_denial_probe_rejects_a_successful_loopback_connection(self) -> None:
        observed: list[list[str]] = []

        def blocked(command, **kwargs):
            observed.append(command)
            return subprocess.CompletedProcess(
                command,
                SYSTEM_SKILL_NETWORK_PROBE_EXIT_CODE,
                SYSTEM_SKILL_NETWORK_PROBE_STDOUT,
                SYSTEM_SKILL_NETWORK_PROBE_STDERR,
            )

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", blocked
        ):
            receipt = _prove_network_denial(
                self.binary,
                sandbox_profile=SYSTEM_SKILL_BOOTSTRAP_SANDBOX_PROFILE,
                network_sandbox_sha256=file_sha256(self.binary),
                python_binary=Path(sys.executable).resolve(),
                python_sha256=file_sha256(Path(sys.executable).resolve()),
            )
        self.assertEqual("verified", receipt["status"])
        self.assertFalse(receipt["sandbox_connected"])
        self.assertEqual(SYSTEM_SKILL_NETWORK_PROBE_CODE, observed[0][7])

        def never_started(command, **kwargs):
            return subprocess.CompletedProcess(
                command, 127, "", "sandbox failed before python startup"
            )

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", never_started
        ), self.assertRaisesRegex(
            FrontierCanaryError,
            "exact in-sandbox denial proof",
        ):
            _prove_network_denial(
                self.binary,
                sandbox_profile=SYSTEM_SKILL_BOOTSTRAP_SANDBOX_PROFILE,
                network_sandbox_sha256=file_sha256(self.binary),
                python_binary=Path(sys.executable).resolve(),
                python_sha256=file_sha256(Path(sys.executable).resolve()),
            )

        def connected(command, **kwargs):
            with socket.create_connection((command[8], int(command[9])), timeout=2):
                pass
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", connected
        ), self.assertRaisesRegex(FrontierCanaryError, "allowed a loopback"):
            _prove_network_denial(
                self.binary,
                sandbox_profile=SYSTEM_SKILL_BOOTSTRAP_SANDBOX_PROFILE,
                network_sandbox_sha256=file_sha256(self.binary),
                python_binary=Path(sys.executable).resolve(),
                python_sha256=file_sha256(Path(sys.executable).resolve()),
            )

    def test_timeout_cleanup_is_bounded_and_does_not_duplicate_output(self) -> None:
        child_pid_path = self.root / "same-group-child.pid"
        code = (
            "import os,pathlib,time\n"
            "print('PART', flush=True)\n"
            "pid=os.fork()\n"
            "if pid == 0:\n"
            f"    pathlib.Path({str(child_pid_path)!r}).write_text(str(os.getpid()))\n"
            "    time.sleep(10)\n"
            "    os._exit(0)\n"
            "os._exit(0)\n"
        )
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            run_subprocess_command(
                [str(Path(sys.executable).resolve()), "-I", "-S", "-c", code],
                input=None,
                text=True,
                capture_output=True,
                cwd=self.workdir,
                env={"PATH": "/usr/bin:/bin"},
                timeout=0.2,
            )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.0)
        self.assertEqual(1, normalize_process_output(caught.exception.output).count("PART"))

    def test_timeout_pipe_drain_is_bounded_even_for_setsid_escape(self) -> None:
        child_pid_path = self.root / "setsid-child.pid"
        code = (
            "import os,pathlib,time\n"
            "print('PART', flush=True)\n"
            "pid=os.fork()\n"
            "if pid == 0:\n"
            "    os.setsid()\n"
            f"    pathlib.Path({str(child_pid_path)!r}).write_text(str(os.getpid()))\n"
            "    time.sleep(10)\n"
            "    os._exit(0)\n"
            "os._exit(0)\n"
        )
        started = time.monotonic()
        try:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                run_subprocess_command(
                    [str(Path(sys.executable).resolve()), "-I", "-S", "-c", code],
                    input=None,
                    text=True,
                    capture_output=True,
                    cwd=self.workdir,
                    env={"PATH": "/usr/bin:/bin"},
                    timeout=0.2,
                )
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 2.0)
            self.assertEqual(
                1,
                normalize_process_output(caught.exception.output).count("PART"),
            )
        finally:
            if child_pid_path.is_file():
                try:
                    os.kill(int(child_pid_path.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_system_skill_bootstrap_policy_tampering_fails_closed(self) -> None:
        cases = (
            "http_status",
            "provider_request_id",
            "usage_limit",
            "provider_overloaded",
            "duplicate_json_key",
            "successful_turn",
            "agent_message",
            "tool_event",
            "environment_injection",
            "prompt_substitution",
            "sandbox_profile_drift",
            "host_denial_identity_drift",
            "manifest_tree_forgery",
            "manifest_unsafe_mode",
            "manifest_duplicate",
            "manifest_traversal",
            "payload_substitution",
            "home_injection",
            "final_profile_drift",
            "network_probe_ambiguity",
            "network_probe_never_started",
            "wrapper_target_alias",
            "process_containment_profile_drift",
            "output_schema_substitution",
        )
        for label in cases:
            with self.subTest(label=label):
                policy = deepcopy(self.execution_environment_policy)
                bootstrap = policy["system_skills_preflight"]
                if label in {
                    "http_status",
                    "provider_request_id",
                    "usage_limit",
                    "provider_overloaded",
                    "duplicate_json_key",
                    "successful_turn",
                    "agent_message",
                    "tool_event",
                }:
                    events = [
                        json.loads(line)
                        for line in bootstrap["stdout"].splitlines()
                        if line
                    ]
                    if label == "http_status":
                        events[2]["message"] = "HTTP error: 401 Unauthorized"
                    elif label == "provider_request_id":
                        events[2]["message"] = "request_id=req-forged"
                    elif label == "usage_limit":
                        events[2]["message"] = "You've hit your usage limit"
                    elif label == "provider_overloaded":
                        events[2]["message"] = (
                            "The hosted model is overloaded; try again later"
                        )
                    elif label == "duplicate_json_key":
                        bootstrap["stdout"] = bootstrap["stdout"].replace(
                            '{"type": "turn.started"}',
                            '{"type":"turn.completed","type":"turn.started"}',
                            1,
                        )
                        _rehash_bootstrap_stream(bootstrap)
                        events = None
                    elif label == "successful_turn":
                        events.append({"type": "turn.completed", "usage": {"input_tokens": 1}})
                    elif label == "agent_message":
                        events.append(
                            {
                                "type": "item.completed",
                                "item": {"type": "agent_message", "text": "{}"},
                            }
                        )
                    else:
                        events.append(
                            {
                                "type": "item.completed",
                                "item": {"type": "command_execution", "command": "id"},
                            }
                        )
                    if events is not None:
                        bootstrap["stdout"] = "\n".join(
                            json.dumps(event) for event in events
                        ) + "\n"
                        _rehash_bootstrap_stream(bootstrap)
                elif label == "environment_injection":
                    bootstrap["environment"]["HTTPS_PROXY"] = "http://attacker.invalid"
                elif label == "prompt_substitution":
                    bootstrap["prompt"] = "different prompt"
                    bootstrap["prompt_sha256"] = _hash("different prompt")
                    bootstrap["prompt_byte_size"] = len("different prompt")
                elif label == "sandbox_profile_drift":
                    bootstrap["sandbox_profile"] = "(version 1)\n(allow default)\n"
                    bootstrap["sandbox_profile_sha256"] = _hash(
                        bootstrap["sandbox_profile"]
                    )
                elif label == "host_denial_identity_drift":
                    forged = {
                        key: {
                            "path": str((Path("/private/tmp") / key).resolve()),
                            "kind": value["kind"],
                        }
                        for key, value in bootstrap["host_read_denials"].items()
                    }
                    profile = build_system_skill_bootstrap_sandbox_profile(forged)
                    bootstrap["host_read_denials"] = forged
                    bootstrap["sandbox_profile"] = profile
                    bootstrap["sandbox_profile_sha256"] = _hash(profile)
                    bootstrap["command"][2] = profile
                    probe = bootstrap["network_denial_probe"]
                    probe["sandbox_profile"] = profile
                    probe["sandbox_profile_sha256"] = _hash(profile)
                    probe["argv"][2] = profile
                elif label == "manifest_tree_forgery":
                    bootstrap["manifest"]["tree_sha256"] = _hash("forged-tree")
                elif label == "manifest_unsafe_mode":
                    bootstrap["manifest"]["directories"][0]["mode"] = "0o777"
                    _rehash_system_manifest(bootstrap["manifest"])
                elif label == "manifest_duplicate":
                    bootstrap["manifest"]["files"].append(
                        deepcopy(bootstrap["manifest"]["files"][0])
                    )
                    bootstrap["retained_skill_payloads"].append(
                        deepcopy(bootstrap["retained_skill_payloads"][0])
                    )
                    _rehash_system_manifest(bootstrap["manifest"])
                elif label == "manifest_traversal":
                    bootstrap["manifest"]["files"][0]["path"] = (
                        "skills/.system/../escaped"
                    )
                    bootstrap["retained_skill_payloads"][0]["path"] = (
                        "skills/.system/../escaped"
                    )
                    _rehash_system_manifest(bootstrap["manifest"])
                elif label == "payload_substitution":
                    bootstrap["retained_skill_payloads"][0]["content_base64"] = (
                        base64.b64encode(b"y").decode()
                    )
                elif label == "home_injection":
                    entries = bootstrap["final_home"]["entries"]
                    entries.append(
                        {
                            "path": "os-tmp/plugins",
                            "kind": "file",
                            "byte_size": 1,
                            "sha256": _hash("x"),
                        }
                    )
                    bootstrap["final_home"] = _fake_home_manifest(entries)
                elif label == "final_profile_drift":
                    profile = next(
                        entry
                        for entry in bootstrap["final_home"]["entries"]
                        if entry["path"]
                        == f"{CODEX_CONFIG_PROFILE}.config.toml"
                    )
                    profile["mode"] = "0o666"
                    profile["sha256"] = _hash("forged-final-profile")
                    bootstrap["final_home"] = _fake_home_manifest(
                        bootstrap["final_home"]["entries"]
                    )
                elif label == "network_probe_ambiguity":
                    bootstrap["network_denial_probe"]["sandbox_connected"] = True
                elif label == "network_probe_never_started":
                    probe = bootstrap["network_denial_probe"]
                    probe["returncode"] = 127
                    probe["stdout"] = ""
                    probe["stderr"] = "sandbox failed before python startup"
                    probe["stdout_sha256"] = _hash(probe["stdout"])
                    probe["stderr_sha256"] = _hash(probe["stderr"])
                    probe["stdout_byte_size"] = len(probe["stdout"].encode())
                    probe["stderr_byte_size"] = len(probe["stderr"].encode())
                elif label == "wrapper_target_alias":
                    wrapper = next(
                        entry
                        for entry in bootstrap["final_home"]["entries"]
                        if entry.get("kind") == "symlink"
                    )
                    wrapper["target"] = str(self.root / "codex-alias")
                    body = {
                        "schema_version": bootstrap["final_home"]["schema_version"],
                        "root_mode": bootstrap["final_home"]["root_mode"],
                        "entries": bootstrap["final_home"]["entries"],
                    }
                    bootstrap["final_home"]["tree_sha256"] = canonical_sha256(body)
                elif label == "process_containment_profile_drift":
                    policy["process_containment"]["profile"] = (
                        "(version 1)\n(allow default)\n"
                    )
                    policy["process_containment"]["profile_sha256"] = _hash(
                        policy["process_containment"]["profile"]
                    )
                elif label == "output_schema_substitution":
                    bootstrap["output_schema_sha256"] = _hash("other-schema")

                with self.assertRaisesRegex(
                    FrontierCanaryError,
                    "System-skill bootstrap|Retained system-skill|process containment",
                ):
                    self._run_with_policy(policy, label=label)

    def test_isolated_codex_keeps_preregistered_absent_system_surface_absent(self) -> None:
        absent_home = self.root / "absent-system-home"
        absent_home.mkdir()
        manifest = _system_skill_manifest(absent_home)
        auth = self.root / "auth-absent-system.json"
        auth.write_text("{}")
        token = "fake-nonsecret-sentinel"

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command",
            return_value=subprocess.CompletedProcess(
                ["codex", "exec"], 0, "{}\n", ""
            ),
        ):
            result = _run_isolated_codex(
                argv=("codex", "exec"),
                prompt="prompt",
                workdir=self.workdir,
                auth_file=auth,
                system_skill_seed=None,
                system_skill_manifest=manifest,
                permissions_profile=_fake_permissions_profile(token),
                sentinel_token=token,
            )

        self.assertTrue(
            result["runtime_home"]["before"]["system_skills_verified"]
        )
        self.assertTrue(
            result["runtime_home"]["after"]["system_skills_verified"]
        )
        self.assertNotIn("skills", result["runtime_home"]["before"]["entries"])

    def test_absent_system_surface_rejects_runtime_file_or_symlink_injection(self) -> None:
        absent_home = self.root / "absent-system-injection-home"
        absent_home.mkdir()
        manifest = _system_skill_manifest(absent_home)
        target = self.root / "runtime-system-symlink-target"
        target.write_text("not a directory\n")

        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                auth = self.root / f"auth-absent-system-{kind}.json"
                auth.write_text("{}")
                token = f"fake-nonsecret-sentinel-{kind}"

                def fake_run(command, **kwargs):
                    skills = Path(kwargs["env"]["CODEX_HOME"]) / "skills"
                    skills.mkdir()
                    system_root = skills / ".system"
                    if kind == "file":
                        system_root.write_text("injected\n")
                    else:
                        system_root.symlink_to(target)
                    return subprocess.CompletedProcess(command, 0, "{}\n", "")

                with patch(
                    "agent_readiness.scripts.run_frontier_canary.run_command",
                    fake_run,
                ):
                    result = _run_isolated_codex(
                        argv=("codex", "exec"),
                        prompt="prompt",
                        workdir=self.workdir,
                        auth_file=auth,
                        system_skill_seed=None,
                        system_skill_manifest=manifest,
                        permissions_profile=_fake_permissions_profile(token),
                        sentinel_token=token,
                    )

                self.assertFalse(
                    result["runtime_home"]["after"]["system_skills_verified"]
                )
                self.assertIn(
                    "skills/.system:manifest-mismatch",
                    result["runtime_home"]["after"]["forbidden_entries"],
                )

    def test_runtime_home_rejects_arbitrary_post_run_file(self) -> None:
        absent_home = self.root / "absent-arbitrary-home"
        absent_home.mkdir()
        manifest = _system_skill_manifest(absent_home)
        auth = self.root / "auth-arbitrary-home.json"
        auth.write_text("{}")
        token = "fake-nonsecret-arbitrary-home-sentinel"

        def fake_run(command, **kwargs):
            home = Path(kwargs["env"]["CODEX_HOME"])
            (home / "unregistered-payload").write_text("unregistered\n")
            return subprocess.CompletedProcess(command, 0, "{}\n", "")

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command",
            fake_run,
        ):
            result = _run_isolated_codex(
                argv=("codex", "exec"),
                prompt="prompt",
                workdir=self.workdir,
                auth_file=auth,
                system_skill_seed=None,
                system_skill_manifest=manifest,
                permissions_profile=_fake_permissions_profile(token),
                sentinel_token=token,
            )

        after = result["runtime_home"]["after"]
        self.assertFalse(after["layout_verified"])
        self.assertIn(
            "unexpected:unregistered-payload",
            after["forbidden_entries"],
        )

    def test_runtime_home_requires_exact_preregistered_model_cache_bytes(self) -> None:
        absent_home = self.root / "absent-model-cache-home"
        absent_home.mkdir()
        manifest = _system_skill_manifest(absent_home)
        auth = self.root / "auth-model-cache-home.json"
        auth.write_text("{}")
        token = "fake-nonsecret-model-cache-home-sentinel"
        model_cache_seed, model_cache_contract = _fake_model_cache()

        def stable_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, "{}\n", "")

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command",
            stable_run,
        ):
            result = _run_isolated_codex(
                argv=("codex", "exec"),
                prompt="prompt",
                workdir=self.workdir,
                auth_file=auth,
                system_skill_seed=None,
                system_skill_manifest=manifest,
                permissions_profile=_fake_permissions_profile(token),
                sentinel_token=token,
                model_cache_seed=model_cache_seed,
                model_cache_contract=model_cache_contract,
            )

        self.assertTrue(result["runtime_home"]["before"]["layout_verified"])
        self.assertTrue(result["runtime_home"]["after"]["layout_verified"])
        self.assertEqual([], result["runtime_home"]["after"]["forbidden_entries"])
        cache_entry = next(
            entry
            for entry in result["runtime_home"]["after"]["layout_document"]["entries"]
            if entry["path"] == "models_cache.json"
        )
        self.assertEqual(model_cache_contract["file_sha256"], cache_entry["sha256"])
        self.assertEqual(model_cache_contract["byte_size"], cache_entry["byte_size"])

        for case in ("content", "mode", "app-cache"):
            def mutated_run(command, **kwargs):
                home = Path(kwargs["env"]["CODEX_HOME"])
                model_cache = home / "models_cache.json"
                if case == "content":
                    model_cache.chmod(0o600)
                    model_cache.write_text("not-json\n")
                    model_cache.chmod(0o400)
                elif case == "mode":
                    model_cache.chmod(0o600)
                else:
                    cache = home / "cache" / "codex_apps_tools"
                    cache.mkdir(parents=True)
                    (cache / ("a" * 32 + ".json")).write_text("{}\n")
                return subprocess.CompletedProcess(command, 0, "{}\n", "")

            with self.subTest(case=case), patch(
                "agent_readiness.scripts.run_frontier_canary.run_command",
                mutated_run,
            ):
                rejected = _run_isolated_codex(
                    argv=("codex", "exec"),
                    prompt="prompt",
                    workdir=self.workdir,
                    auth_file=auth,
                    system_skill_seed=None,
                    system_skill_manifest=manifest,
                    permissions_profile=_fake_permissions_profile(token),
                    sentinel_token=token,
                    model_cache_seed=model_cache_seed,
                    model_cache_contract=model_cache_contract,
                )
                self.assertFalse(
                    rejected["runtime_home"]["after"]["layout_verified"]
                )

        with self.assertRaisesRegex(FrontierCanaryError, "seed bytes differ"):
            _run_isolated_codex(
                argv=("codex", "exec"),
                prompt="prompt",
                workdir=self.workdir,
                auth_file=auth,
                system_skill_seed=None,
                system_skill_manifest=manifest,
                permissions_profile=_fake_permissions_profile(token),
                sentinel_token=token,
                model_cache_seed=b"{}",
                model_cache_contract=model_cache_contract,
            )

    def test_model_cache_seed_requires_unambiguous_selected_model(self) -> None:
        path = self.root / "models_cache.json"
        payload, expected = _fake_model_cache()
        path.write_bytes(payload)
        observed_payload, observed = _load_model_cache_seed(
            path, model_selector="gpt-5.4-2026-07-09"
        )
        self.assertEqual(payload, observed_payload)
        self.assertEqual(expected, observed)

        for label, raw in (
            ("invalid", b"not-json"),
            ("duplicate-key", b'{"models":[],"models":[]}'),
            ("missing-model", b'{"models":[]}'),
        ):
            path.write_bytes(raw)
            with self.subTest(label=label), self.assertRaises(FrontierCanaryError):
                _load_model_cache_seed(
                    path, model_selector="gpt-5.4-2026-07-09"
                )

    def test_runtime_home_binds_allowed_paths_to_kinds_targets_and_safe_modes(self) -> None:
        absent_home = self.root / "absent-runtime-kind-home"
        absent_home.mkdir()
        manifest = _system_skill_manifest(absent_home)

        for case in ("state-directory", "wrapper-files", "special-mode"):
            with self.subTest(case=case):
                auth = self.root / f"auth-runtime-{case}.json"
                auth.write_text("{}")
                token = f"fake-nonsecret-runtime-{case}"

                def fake_run(command, **kwargs):
                    home = Path(kwargs["env"]["CODEX_HOME"])
                    if case == "state-directory":
                        (home / "installation_id").mkdir()
                    elif case == "special-mode":
                        state = home / "installation_id"
                        state.write_text("id\n")
                        state.chmod(0o1600)
                    else:
                        arg0 = home / "tmp" / "arg0" / "codex-arg0PWN"
                        arg0.mkdir(parents=True)
                        (arg0 / ".lock").write_text("lock\n")
                        for name in (
                            "apply_patch",
                            "applypatch",
                            "codex-execve-wrapper",
                        ):
                            (arg0 / name).write_text("not a symlink\n")
                    return subprocess.CompletedProcess(command, 0, "{}\n", "")

                with patch(
                    "agent_readiness.scripts.run_frontier_canary.run_command",
                    fake_run,
                ):
                    result = _run_isolated_codex(
                        argv=("codex", "exec"),
                        prompt="prompt",
                        workdir=self.workdir,
                        auth_file=auth,
                        system_skill_seed=None,
                        system_skill_manifest=manifest,
                        permissions_profile=_fake_permissions_profile(token),
                        sentinel_token=token,
                    )

                after = result["runtime_home"]["after"]
                self.assertFalse(after["layout_verified"])
                if case == "state-directory":
                    self.assertIn(
                        "kind-mismatch:installation_id:directory",
                        after["forbidden_entries"],
                    )
                elif case == "special-mode":
                    self.assertIn(
                        "unsafe-file-mode-or-link-count:installation_id",
                        after["forbidden_entries"],
                    )
                else:
                    self.assertTrue(
                        any(
                            entry.startswith("kind-mismatch:")
                            and entry.endswith(":file")
                            for entry in after["forbidden_entries"]
                        )
                    )

    def test_absent_system_surface_rejects_runtime_file_or_symlink_parent(self) -> None:
        absent_home = self.root / "absent-skills-parent-home"
        absent_home.mkdir()
        manifest = _system_skill_manifest(absent_home)
        target = self.root / "runtime-skills-parent-target"
        target.mkdir()

        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                auth = self.root / f"auth-absent-skills-parent-{kind}.json"
                auth.write_text("{}")
                token = f"fake-nonsecret-parent-sentinel-{kind}"

                def fake_run(command, **kwargs):
                    skills = Path(kwargs["env"]["CODEX_HOME"]) / "skills"
                    if kind == "file":
                        skills.write_text("injected\n")
                    else:
                        skills.symlink_to(target, target_is_directory=True)
                    return subprocess.CompletedProcess(command, 0, "{}\n", "")

                with patch(
                    "agent_readiness.scripts.run_frontier_canary.run_command",
                    fake_run,
                ):
                    result = _run_isolated_codex(
                        argv=("codex", "exec"),
                        prompt="prompt",
                        workdir=self.workdir,
                        auth_file=auth,
                        system_skill_seed=None,
                        system_skill_manifest=manifest,
                        permissions_profile=_fake_permissions_profile(token),
                        sentinel_token=token,
                    )

                self.assertFalse(
                    result["runtime_home"]["after"]["system_skills_verified"]
                )
                self.assertIn(
                    "skills/.system:manifest-mismatch",
                    result["runtime_home"]["after"]["forbidden_entries"],
                )

    def test_permissions_preflight_uses_exact_named_profile_for_all_probes(self) -> None:
        commands: list[list[str]] = []
        socket = self.root / "docker.sock"
        socket.touch()
        observed_marker = self.root / "live-site" / ".ddev" / "config.yaml"
        observed_marker.parent.mkdir(parents=True)
        observed_marker.write_text("name: live-site\n")
        denied_paths = {
            "observed_root_unreadable": observed_marker,
            "ddev_binary_unreadable": self.binary,
            "docker_binary_minimal_runtime_readable": self.binary,
            "docker_socket_unreadable": socket,
        }

        def fake_run(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", fake_run
        ):
            receipt = _preflight_permissions_profile(
                self.binary,
                workspace=self.workdir,
                sentinel_token="registered-nonsecret-sentinel",
                host_probe_paths=denied_paths,
            )

        self.assertEqual(8, len(commands))
        for command in commands:
            self.assertEqual(CODEX_CONFIG_PROFILE, command[command.index("-p") + 1])
            self.assertEqual(CODEX_PERMISSION_PROFILE, command[command.index("-P") + 1])
        self.assertEqual(
            {
                "workspace_readable",
                "auth_unreadable",
                "sentinel_unreadable",
                "git_metadata_unreadable",
                "observed_root_unreadable",
                "ddev_binary_unreadable",
                "docker_binary_minimal_runtime_readable",
                "docker_socket_unreadable",
            },
            set(receipt["probe_receipts"]),
        )
        self.assertIn('":root" = "deny"', receipt["profile_text"])
        self.assertIn('"/**/auth.json" = "deny"', receipt["profile_text"])
        self.assertIn('"/**/.git" = "deny"', receipt["profile_text"])
        self.assertIn('"/**/.git/**" = "deny"', receipt["profile_text"])
        for path in denied_paths.values():
            self.assertIn(
                f'{json.dumps(str(path.resolve()))} = "deny"',
                receipt["profile_text"],
            )
        self.assertFalse((self.workdir / ".git").exists())

    def test_sensitive_stream_is_rejected_without_raw_bytes_or_hash(self) -> None:
        sentinel = "registered-nonsecret-sentinel"
        secret_shaped = 'prefix {"access_token":"not-a-real-secret"} ' + sentinel
        detections = _sensitive_output_detections(
            secret_shaped,
            "",
            sentinel_token=sentinel,
        )
        path = _record_sensitive_output_rejection(
            self.repo,
            invocation_id="securityreject00000000000000000001",
            attempt=1,
            slot_id="frontier-001",
            argv=("codex", "exec"),
            stdout=secret_shaped,
            stderr="",
            detections=detections,
        )

        retained = path.read_text(encoding="utf-8")
        self.assertNotIn(sentinel, retained)
        self.assertNotIn("not-a-real-secret", retained)
        self.assertFalse((path.parent / "codex.stdout.jsonl").exists())
        self.assertFalse((path.parent / "codex.stderr.txt").exists())
        document = json.loads(retained)
        self.assertFalse(document["raw_bytes_retained"])
        self.assertFalse(document["raw_bytes_hashed"])
        self.assertIn("nonsecret_canary_token", document["detections"])

    def test_system_skill_byte_mutation_fails_exact_home_verification(self) -> None:
        seed_home = self.root / "system-seed"
        skill = seed_home / "skills" / ".system" / "core" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("registered bytes\n")
        manifest = _system_skill_manifest(seed_home)
        auth = self.root / "auth-system.json"
        auth.write_text("{}")
        token = "fake-nonsecret-sentinel"
        permissions = _fake_permissions_profile(token)

        def fake_run(command, **kwargs):
            runtime_skill = (
                Path(kwargs["env"]["CODEX_HOME"])
                / "skills"
                / ".system"
                / "core"
                / "SKILL.md"
            )
            runtime_skill.write_text("mutated bytes\n")
            return subprocess.CompletedProcess(command, 0, "{}\n", "")

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", fake_run
        ):
            result = _run_isolated_codex(
                argv=("codex", "exec"),
                prompt="prompt",
                workdir=self.workdir,
                auth_file=auth,
                system_skill_seed=seed_home / "skills" / ".system",
                system_skill_manifest=manifest,
                permissions_profile=permissions,
                sentinel_token=token,
            )

        self.assertTrue(result["runtime_home"]["before"]["system_skills_verified"])
        self.assertFalse(result["runtime_home"]["after"]["system_skills_verified"])
        self.assertIn(
            "skills/.system:manifest-mismatch",
            result["runtime_home"]["after"]["forbidden_entries"],
        )

    def test_system_skill_mode_mutation_fails_exact_home_verification(self) -> None:
        for target_name in ("skills", "system", "nested", "file"):
            with self.subTest(target=target_name):
                seed_home = self.root / f"mode-seed-{target_name}"
                skill = seed_home / "skills" / ".system" / "core" / "SKILL.md"
                skill.parent.mkdir(parents=True)
                skill.write_text("registered bytes\n")
                manifest = _system_skill_manifest(seed_home)
                auth = self.root / f"auth-mode-{target_name}.json"
                auth.write_text("{}")
                token = f"fake-nonsecret-mode-{target_name}"

                def fake_run(command, **kwargs):
                    runtime = Path(kwargs["env"]["CODEX_HOME"])
                    targets = {
                        "skills": runtime / "skills",
                        "system": runtime / "skills" / ".system",
                        "nested": runtime / "skills" / ".system" / "core",
                        "file": runtime
                        / "skills"
                        / ".system"
                        / "core"
                        / "SKILL.md",
                    }
                    targets[target_name].chmod(0o777)
                    return subprocess.CompletedProcess(command, 0, "{}\n", "")

                with patch(
                    "agent_readiness.scripts.run_frontier_canary.run_command",
                    fake_run,
                ):
                    result = _run_isolated_codex(
                        argv=(str(self.binary.resolve()), "exec"),
                        prompt="prompt",
                        workdir=self.workdir,
                        auth_file=auth,
                        system_skill_seed=seed_home / "skills" / ".system",
                        system_skill_manifest=manifest,
                        permissions_profile=_fake_permissions_profile(token),
                        sentinel_token=token,
                    )

                self.assertTrue(
                    result["runtime_home"]["before"]["system_skills_verified"]
                )
                self.assertFalse(
                    result["runtime_home"]["after"]["system_skills_verified"]
                )
                self.assertIn(
                    "skills/.system:manifest-mismatch",
                    result["runtime_home"]["after"]["forbidden_entries"],
                )

    def test_changed_seed_mode_is_rejected_before_execution(self) -> None:
        seed_home = self.root / "mode-seed-before"
        skill = seed_home / "skills" / ".system" / "core" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("registered bytes\n")
        manifest = _system_skill_manifest(seed_home)
        skill.chmod(0o755)
        auth = self.root / "auth-mode-before.json"
        auth.write_text("{}")
        token = "fake-nonsecret-mode-before"

        with self.assertRaisesRegex(FrontierCanaryError, "clean isolated CODEX_HOME"):
            _run_isolated_codex(
                argv=(str(self.binary.resolve()), "exec"),
                prompt="prompt",
                workdir=self.workdir,
                auth_file=auth,
                system_skill_seed=seed_home / "skills" / ".system",
                system_skill_manifest=manifest,
                permissions_profile=_fake_permissions_profile(token),
                sentinel_token=token,
            )

    def test_system_skill_tree_rejects_unregistered_ephemeral_outputs(self) -> None:
        seed_home = self.root / "stable-system-seed"
        skill = seed_home / "skills" / ".system" / "core" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("registered bytes\n")
        manifest = _system_skill_manifest(seed_home)
        auth = self.root / "auth-stable-system.json"
        auth.write_text("{}")
        token = "fake-nonsecret-sentinel"
        permissions = _fake_permissions_profile(token)

        def fake_run(command, **kwargs):
            output = Path(kwargs["env"]["CODEX_HOME"]) / "sessions" / "ephemeral.json"
            output.parent.mkdir()
            output.write_text("{}")
            return subprocess.CompletedProcess(command, 0, "{}\n", "")

        with patch(
            "agent_readiness.scripts.run_frontier_canary.run_command", fake_run
        ):
            result = _run_isolated_codex(
                argv=("codex", "exec"),
                prompt="prompt",
                workdir=self.workdir,
                auth_file=auth,
                system_skill_seed=seed_home / "skills" / ".system",
                system_skill_manifest=manifest,
                permissions_profile=permissions,
                sentinel_token=token,
            )

        self.assertTrue(result["runtime_home"]["after"]["system_skills_verified"])
        self.assertFalse(result["runtime_home"]["after"]["layout_verified"])
        self.assertEqual(
            ["unexpected:sessions", "unexpected:sessions/ephemeral.json"],
            result["runtime_home"]["after"]["forbidden_entries"],
        )

    def test_final_attempt_receipt_retains_dynamic_system_skill_manifest(self) -> None:
        manifest = {
            "schema_version": "drupal_agent_readiness.system_skills_manifest.v1",
            "directories": [
                {"path": "skills", "mode": "0o755"},
                {"path": "skills/.system", "mode": "0o755"},
                {"path": "skills/.system/core", "mode": "0o755"},
            ],
            "files": [
                {
                    "path": "skills/.system/core/SKILL.md",
                    "mode": "0o644",
                    "byte_size": 1,
                    "sha256": _hash("x"),
                }
            ],
            "tree_sha256": _hash("tree"),
        }
        permissions = _fake_permissions_profile()
        policy = {
            **ISOLATED_ENVIRONMENT_POLICY,
            "system_skills_preflight": {"manifest": manifest},
            "permissions_preflight": permissions,
            "process_containment": build_frontier_process_containment_policy(
                self.binary
            ),
        }
        arguments = {
            "artifact_repo": self.repo,
            "invocation_id": "dynamicpolicy00000000000000000001",
            "attempt": 1,
            "slot_id": "frontier-001",
            "argv": ("codex", "exec"),
            "stdout": "{}\n",
            "stderr": "",
            "returncode": 0,
            "timed_out": False,
            "runtime_home": {
                "before": {
                    "mode": "0o700",
                    "home_identity_verified": True,
                    "home_mode_verified": True,
                    "layout_verified": True,
                    "layout_sha256": _fake_runtime_layout_document()["tree_sha256"],
                    "layout_document": _fake_runtime_layout_document(),
                    "auth_reference_verified": True,
                    "permissions_profile_regular_file_verified": True,
                    "sentinel_regular_file_verified": True,
                    "forbidden_entries": [],
                    "system_skills_verified": True,
                    "system_skills_tree_sha256": _hash("tree"),
                    "permissions_profile_sha256": permissions["profile_sha256"],
                    "sentinel_sha256": permissions["sentinel_sha256"],
                },
                "after": {
                    "mode": "0o700",
                    "home_identity_verified": True,
                    "home_mode_verified": True,
                    "layout_verified": True,
                    "layout_sha256": _fake_runtime_layout_document()["tree_sha256"],
                    "layout_document": _fake_runtime_layout_document(),
                    "auth_reference_verified": True,
                    "permissions_profile_regular_file_verified": True,
                    "sentinel_regular_file_verified": True,
                    "forbidden_entries": [],
                    "system_skills_verified": True,
                    "system_skills_tree_sha256": _hash("tree"),
                    "permissions_profile_sha256": permissions["profile_sha256"],
                    "sentinel_sha256": permissions["sentinel_sha256"],
                },
                "process_containment": {
                    "status": "verified",
                    "policy_sha256": canonical_sha256(
                        policy["process_containment"]
                    ),
                    "sandbox_sha256": policy["process_containment"][
                        "sandbox_sha256"
                    ],
                    "child_process_creation_denied": True,
                    "inner_argv": ["codex", "exec"],
                    "outer_argv": [
                        policy["process_containment"]["sandbox_binary"],
                        "-p",
                        policy["process_containment"]["profile"],
                        "codex",
                        "exec",
                    ],
                },
            },
            "environment_policy": policy,
        }
        begun = _begin_attempt(**arguments)
        reference = _finalize_attempt(
            begun,
            status="succeeded",
            thread_id="thread-dynamic-policy",
            failure=None,
        )
        receipt_path = self.repo / reference["uri"]
        receipt = json.loads(receipt_path.read_bytes())
        self.assertEqual(
            "sha256:" + hashlib.sha256(canonical_json_bytes(policy)).hexdigest(),
            receipt["environment_policy_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
