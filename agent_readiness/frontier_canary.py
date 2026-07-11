"""Run a two-slot, read-only frontier observation against measurement v1.

The harness is deliberately small and opinionated.  It observes one exact
agent/site stack twice, never compares the observations as a Drupal treatment,
and emits the complete evidence package required by :mod:`measurement_v1`.
The collector and executor are injected so the custody boundary is explicit
and the orchestration can be tested without spending model calls.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from agent_readiness.codex_runner_utils import count_codex_tool_calls
from agent_readiness.evaluators.inventory import evaluate as evaluate_inventory
from agent_readiness.measurement_v1 import (
    GitRegistrationAnchor,
    audit_measurement_v1,
    canonical_json_bytes,
    canonical_sha256,
    file_sha256,
    load_canonical_json_file,
    model_cache_contract_valid,
    runtime_home_layout_document_valid,
    runtime_home_layout_semantically_valid,
    validate_experiment_manifest,
)


PACKAGE_ROOT = Path(__file__).resolve().parent
INVENTORY_SCHEMA_SOURCE = PACKAGE_ROOT / "schema" / "inventory-answer-v1.schema.json"
FRONTIER_INVENTORY_OUTPUT_SCHEMA_SOURCE = (
    PACKAGE_ROOT / "schema" / "inventory-answer-frontier-v1.schema.json"
)
INVENTORY_EVALUATOR_SOURCE = PACKAGE_ROOT / "evaluators" / "inventory.py"
SCORING_SOURCE = PACKAGE_ROOT / "evaluators" / "result.py"
_STATIC_EXECUTED_SOURCE_PATHS = {
    "package-init": PACKAGE_ROOT / "__init__.py",
    "evaluators-package-init": PACKAGE_ROOT / "evaluators" / "__init__.py",
    "frontier-canary": Path(__file__).resolve(),
    "measurement-v1": PACKAGE_ROOT / "measurement_v1.py",
    "evaluator-common": PACKAGE_ROOT / "evaluators" / "common.py",
    "evaluator-inventory": INVENTORY_EVALUATOR_SOURCE,
    "evaluator-result": SCORING_SOURCE,
    "drupal-state-collector": PACKAGE_ROOT / "evaluators" / "drupal_state_collector.php",
    "codex-runner-utils": PACKAGE_ROOT / "codex_runner_utils.py",
    "benchmark-experiment-schema": (
        PACKAGE_ROOT / "schema" / "benchmark-experiment-v1.schema.json"
    ),
    "benchmark-run-schema": PACKAGE_ROOT / "schema" / "benchmark-run-v1.schema.json",
}
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_MUTABLE = re.compile(
    r"(?:^|[-_.:/@])(?:latest|current|default|stable|nightly|rolling|main|master|head|tip|auto)(?:$|[-_.:/@])",
    re.IGNORECASE,
)
_MODEL_SELECTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$")
_FORBIDDEN_DIRECT_HOST_TOOL = re.compile(
    r"(?:^|[^a-z0-9_-])(?:ddev|docker)(?:$|[^a-z0-9_-])",
    re.IGNORECASE,
)
CODEX_CONFIG_PROFILE = "frontier-canary"
CODEX_PERMISSION_PROFILE = "frontier_canary_read_only"
SYSTEM_SKILL_BOOTSTRAP_SANDBOX_PROFILE = (
    "(version 1)\n"
    "(allow default)\n"
    "(deny network*)\n"
    "(deny process-fork)\n"
)
FRONTIER_PROCESS_CONTAINMENT_PROFILE = (
    "(version 1)\n"
    "(allow default)\n"
    "(deny process-fork)\n"
)
FRONTIER_PROCESS_CONTAINMENT_KIND = "darwin_seatbelt_process_fork_denied"
SYSTEM_SKILL_BOOTSTRAP_PROMPT = (
    "Initialize the preregistered agent stack. The outer operating-system sandbox "
    "denies every network operation, so no provider exchange or response is possible."
)
SYSTEM_SKILL_REQUIRED_HOST_DENIALS = (
    "auth_file",
    "user_agents",
    "user_codex_agents_file",
    "user_codex_apps",
    "user_codex_auth",
    "user_codex_config",
    "user_codex_memories",
    "user_codex_plugins",
    "user_codex_rules",
    "user_codex_skills",
    "user_config_codex",
    "user_local_share_codex",
    "user_root_agents_file",
)
SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL = frozenset(
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


def expected_system_skill_host_denials() -> dict[str, dict[str, str]]:
    """Return the only ambient user-state paths the bootstrap may name.

    The credential reference is deliberately fixed to the standard Codex
    credential path.  Accepting an arbitrary caller-supplied path would let a
    forged policy point the ``auth_file`` label at a harmless file while the
    real credential remained readable.
    """

    home = Path.home().resolve()
    codex_home = home / ".codex"
    return {
        "auth_file": {
            "path": str((codex_home / "auth.json").resolve()),
            "kind": "literal",
        },
        "user_agents": {
            "path": str((home / ".agents").resolve()),
            "kind": "subpath",
        },
        "user_codex_agents_file": {
            "path": str((codex_home / "AGENTS.md").resolve()),
            "kind": "literal",
        },
        "user_codex_apps": {
            "path": str((codex_home / "apps").resolve()),
            "kind": "subpath",
        },
        "user_codex_auth": {
            "path": str((codex_home / "auth.json").resolve()),
            "kind": "literal",
        },
        "user_codex_config": {
            "path": str((codex_home / "config.toml").resolve()),
            "kind": "literal",
        },
        "user_codex_memories": {
            "path": str((codex_home / "memories").resolve()),
            "kind": "subpath",
        },
        "user_codex_plugins": {
            "path": str((codex_home / "plugins").resolve()),
            "kind": "subpath",
        },
        "user_codex_rules": {
            "path": str((codex_home / "rules").resolve()),
            "kind": "subpath",
        },
        "user_codex_skills": {
            "path": str((codex_home / "skills").resolve()),
            "kind": "subpath",
        },
        "user_config_codex": {
            "path": str((home / ".config" / "codex").resolve()),
            "kind": "subpath",
        },
        "user_local_share_codex": {
            "path": str((home / ".local" / "share" / "codex").resolve()),
            "kind": "subpath",
        },
        "user_root_agents_file": {
            "path": str((home / "AGENTS.md").resolve()),
            "kind": "literal",
        },
    }
SYSTEM_SKILL_NETWORK_PROBE_CODE = (
    "import socket,sys\n"
    "print('DAR_NETWORK_PROBE_STARTED', flush=True)\n"
    "try:\n"
    "    socket.create_connection((sys.argv[1], int(sys.argv[2])), 2).close()\n"
    "except OSError as error:\n"
    "    print(f'DAR_NETWORK_PROBE_DENIED:{type(error).__name__}:{error.errno}', "
    "flush=True)\n"
    "    raise SystemExit(73)\n"
    "print('DAR_NETWORK_PROBE_CONNECTED', flush=True)\n"
    "raise SystemExit(0)\n"
)
SYSTEM_SKILL_NETWORK_PROBE_EXIT_CODE = 73
SYSTEM_SKILL_NETWORK_PROBE_STDOUT = (
    "DAR_NETWORK_PROBE_STARTED\n"
    "DAR_NETWORK_PROBE_DENIED:PermissionError:1\n"
)
SYSTEM_SKILL_NETWORK_PROBE_STDERR = ""
SYSTEM_SKILL_BOOTSTRAP_TRANSPORT_CLASS = "local_network_denial"
_SYSTEM_SKILL_LOCAL_NETWORK_DENIAL = re.compile(
    r"(?:failed to lookup address information|"
    r"nodename nor servname provided|"
    r"network is unreachable|"
    r"no route to host|"
    r"(?:network|socket).{0,80}(?:operation not permitted|permission denied)|"
    r"(?:operation not permitted|permission denied).{0,80}(?:network|socket))",
    re.IGNORECASE | re.DOTALL,
)
_SYSTEM_SKILL_PROVIDER_RESPONSE_TEXT = re.compile(
    r"(?:usage(?:[_ -]+limit|[_ -]+exceeded)|"
    r"rate(?:[_ -]+limit|[_ -]+limited)|"
    r"too many requests|"
    r"insufficient[_ -]+quota|"
    r"quota(?:[_ -]+exceeded)?|"
    r"(?:account|api)[_ -]+credits?|"
    r"billing(?:[_ -]+limit|[_ -]+error)?|"
    r"unauthori[sz]ed|"
    r"authentication(?:[_ -]+failed|[_ -]+required)|"
    r"invalid[_ -]+api[_ -]+key|"
    r"incorrect api key|"
    r"(?:hosted|provider|remote)?\s*model\s+(?:is\s+)?overloaded|"
    r"server\s+(?:is\s+)?overloaded|"
    r"service unavailable|"
    r"http/(?:1(?:\.0|\.1)?|2|3)\s+[1-5][0-9]{2}|"
    r"(?:status|status_code|http status|http error)\s*[:=]?\s*[1-5][0-9]{2}|"
    r"cf-ray|"
    r"request[_-]id)",
    re.IGNORECASE,
)
_SYSTEM_SKILL_PROVIDER_RESPONSE_KEYS = frozenset(
    {
        "cached_input_tokens",
        "cf_ray",
        "input_tokens",
        "output_tokens",
        "request-id",
        "request_id",
        "response_id",
        "retry_after",
        "status_code",
        "usage",
    }
)
_SYSTEM_SKILL_DNS_DENIAL_DETAIL = (
    "failed to lookup address information: nodename nor servname provided, or not known"
)
_SYSTEM_SKILL_SEND_FAILURE_DETAIL = (
    "error sending request for url (https://api.openai.com/v1/responses)"
)
_SYSTEM_SKILL_ERROR_MESSAGE = re.compile(
    r"(?:"
    r"Reconnecting\.\.\. [1-5]/5 \(stream disconnected before completion: "
    r"(?:failed to lookup address information: nodename nor servname provided, or not known|"
    r"error sending request for url \(https://api\.openai\.com/v1/responses\))\)|"
    r"stream disconnected before completion: "
    r"(?:failed to lookup address information: nodename nor servname provided, or not known|"
    r"error sending request for url \(https://api\.openai\.com/v1/responses\))"
    r")"
)
_SYSTEM_SKILL_ITEM_ERROR_MESSAGE = re.compile(
    r"Falling back from WebSockets to HTTPS transport\. "
    r"stream disconnected before completion: "
    r"failed to lookup address information: nodename nor servname provided, or not known"
)
_SYSTEM_SKILL_STDERR_LINE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ERROR "
    r"codex_api::endpoint::responses_websocket: failed to connect to websocket: "
    r"IO error: failed to lookup address information: "
    r"nodename nor servname provided, or not known, "
    r"url: wss://api\.openai\.com/v1/responses"
)
_REQUIRED_SAFE_FLAGS = (
    "--strict-config",
    "--ignore-user-config",
    "--ignore-rules",
    "--ephemeral",
    "--json",
    "--skip-git-repo-check",
)
_FORBIDDEN_ARG_PREFIXES = (
    "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-bypass-hook-trust",
    "--add-dir",
    "--sandbox",
)


class FrontierCanaryError(ValueError):
    """Raised when a canary cannot preserve its registered safety contract."""


def parse_json_without_duplicate_keys(payload: str, *, label: str) -> Any:
    """Parse one JSON value while rejecting ambiguous duplicate object keys."""

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise FrontierCanaryError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(payload, object_pairs_hook=object_pairs)
    except json.JSONDecodeError as error:
        raise FrontierCanaryError(f"{label} is malformed JSON") from error


def build_frontier_process_containment_policy(
    network_sandbox_binary: Path,
) -> dict[str, Any]:
    """Bind the macOS Seatbelt policy that forbids all agent child processes."""

    resolved = network_sandbox_binary.resolve()
    invocation = resolved
    if sys.platform != "darwin" or not invocation.is_file() or not resolved.is_file():
        raise FrontierCanaryError(
            "Frontier process containment requires a pinned Darwin sandbox-exec"
        )
    profile_sha256 = "sha256:" + hashlib.sha256(
        FRONTIER_PROCESS_CONTAINMENT_PROFILE.encode("utf-8")
    ).hexdigest()
    return {
        "kind": FRONTIER_PROCESS_CONTAINMENT_KIND,
        "sandbox_binary": str(invocation),
        "sandbox_sha256": file_sha256(resolved),
        "profile": FRONTIER_PROCESS_CONTAINMENT_PROFILE,
        "profile_sha256": profile_sha256,
        "child_process_creation": "denied_by_seatbelt_process_fork",
        "claim_boundary": (
            "Pinned Darwin Seatbelt forbids child-process creation by the Codex process; "
            "this is trusted-host containment, not a container, VM, remote attestation, "
            "or proof against pre-existing local brokers."
        ),
        "sandbox_platform": {
            "sys_platform": sys.platform,
            "sysname": os.uname().sysname,
            "release": os.uname().release,
            "version": os.uname().version,
            "machine": os.uname().machine,
        },
    }


def validate_frontier_process_containment_policy(
    policy: Any,
    *,
    network_sandbox_binary: Path,
) -> dict[str, Any]:
    expected = build_frontier_process_containment_policy(network_sandbox_binary)
    if not isinstance(policy, Mapping) or dict(policy) != expected:
        raise FrontierCanaryError("Frontier process containment policy is not exact")
    return expected


def classify_system_skill_bootstrap_transport(
    events: Sequence[Mapping[str, Any]],
    *,
    stdout: str,
    stderr: str,
) -> str:
    """Accept only a local OS-network-denial failure, never provider semantics."""

    if len(events) < 5:
        raise FrontierCanaryError(
            "System-skill bootstrap did not prove an exclusively local network denial"
        )
    first, second, *middle, last = events
    if (
        set(first) != {"type", "thread_id"}
        or first.get("type") != "thread.started"
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}", str(first.get("thread_id")))
        is None
        or dict(second) != {"type": "turn.started"}
        or set(last) != {"type", "error"}
        or last.get("type") != "turn.failed"
        or not isinstance(last.get("error"), Mapping)
        or set(last["error"]) != {"message"}
        or _SYSTEM_SKILL_ERROR_MESSAGE.fullmatch(
            str(last["error"].get("message"))
        )
        is None
    ):
        raise FrontierCanaryError(
            "System-skill bootstrap did not prove an exclusively local network denial"
        )
    saw_item_error = False
    saw_dns_denial = False
    for event in middle:
        if event.get("type") == "error":
            if (
                set(event) != {"type", "message"}
                or _SYSTEM_SKILL_ERROR_MESSAGE.fullmatch(str(event.get("message")))
                is None
            ):
                raise FrontierCanaryError(
                    "System-skill bootstrap did not prove an exclusively local network denial"
                )
            saw_dns_denial |= _SYSTEM_SKILL_DNS_DENIAL_DETAIL in str(
                event.get("message")
            )
            continue
        item = event.get("item")
        if (
            event.get("type") != "item.completed"
            or set(event) != {"type", "item"}
            or not isinstance(item, Mapping)
            or set(item) != {"id", "type", "message"}
            or item.get("type") != "error"
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}", str(item.get("id")))
            is None
            or _SYSTEM_SKILL_ITEM_ERROR_MESSAGE.fullmatch(str(item.get("message")))
            is None
        ):
            raise FrontierCanaryError(
                "System-skill bootstrap did not prove an exclusively local network denial"
            )
        saw_item_error = True
        saw_dns_denial = True
    stderr_lines = [line for line in stderr.splitlines() if line]
    serialized = f"{stdout}\n{stderr}"
    if (
        not saw_item_error
        or not saw_dns_denial
        or not stderr_lines
        or any(_SYSTEM_SKILL_STDERR_LINE.fullmatch(line) is None for line in stderr_lines)
        or _SYSTEM_SKILL_PROVIDER_RESPONSE_TEXT.search(serialized)
    ):
        raise FrontierCanaryError(
            "System-skill bootstrap did not prove an exclusively local network denial"
        )
    return SYSTEM_SKILL_BOOTSTRAP_TRANSPORT_CLASS


def build_system_skill_bootstrap_sandbox_profile(
    denials: Mapping[str, Mapping[str, str]],
) -> str:
    """Render the exact macOS bootstrap sandbox with explicit host-state denials."""

    clauses: set[tuple[str, str]] = set()
    for label, entry in denials.items():
        if not isinstance(label, str) or not label or not isinstance(entry, Mapping):
            raise FrontierCanaryError("System-skill host denial map is malformed")
        raw_path = entry.get("path")
        kind = entry.get("kind")
        if (
            not isinstance(raw_path, str)
            or not Path(raw_path).is_absolute()
            or str(Path(raw_path).resolve()) != raw_path
            or kind not in {"literal", "subpath"}
        ):
            raise FrontierCanaryError(f"System-skill host denial is invalid: {label}")
        clauses.add((kind, raw_path))
    rendered = SYSTEM_SKILL_BOOTSTRAP_SANDBOX_PROFILE
    for kind, raw_path in sorted(clauses):
        rendered += f"(deny file-read* ({kind} {json.dumps(raw_path)}))\n"
        rendered += f"(deny file-write* ({kind} {json.dumps(raw_path)}))\n"
    return rendered


Collector = Callable[[str], Mapping[str, Any]]
Executor = Callable[[Sequence[str], str], Mapping[str, Any]]
Clock = Callable[[], datetime]
CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


_EXTENSION_CAPTURE_PHP = r"""
$result = [];
foreach (['module', 'theme', 'profile'] as $kind) {
  $list = \Drupal::service('extension.list.' . $kind);
  foreach ($list->getList() as $name => $extension) {
    $info = $extension->info;
    $result[] = [
      'kind' => $kind,
      'machine_name' => $name,
      'path' => $extension->getPath(),
      'version' => $info['version'] ?? null,
    ];
  }
}
usort($result, fn($a, $b) => [$a['kind'], $a['machine_name']] <=> [$b['kind'], $b['machine_name']]);
print json_encode($result, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
""".strip()


_SITE_PROJECTION_CAPTURE_PHP = r"""
function frontier_canonicalize($value) {
  if (is_object($value)) {
    $value = (array) $value;
  }
  if (!is_array($value)) {
    if (is_string($value) && !preg_match('//u', $value)) {
      return ['__binary_base64__' => base64_encode($value)];
    }
    return $value;
  }
  $keys = array_keys($value);
  $is_list = $keys === range(0, count($value) - 1);
  if (!$is_list) {
    ksort($value, SORT_STRING);
  }
  foreach ($value as $key => $item) {
    $value[$key] = frontier_canonicalize($item);
  }
  return $value;
}
function frontier_json($value) {
  return json_encode(
    frontier_canonicalize($value),
    JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION | JSON_THROW_ON_ERROR
  );
}

$storage = \Drupal::service('config.storage');
$config_items = [];
$config_names = $storage->listAll();
sort($config_names, SORT_STRING);
foreach ($config_names as $name) {
  $data = $storage->read($name);
  $encoded = frontier_json($data === FALSE ? NULL : $data);
  $config_items[] = [
    'name' => $name,
    'byte_size' => strlen($encoded),
    'sha256' => 'sha256:' . hash('sha256', $encoded),
  ];
}

$file_sets = [];
foreach (['public', 'private'] as $scheme) {
  $uri = $scheme . '://';
  $root = \Drupal::service('file_system')->realpath($uri);
  if ($root === FALSE || !is_dir($root)) {
    $file_sets[$scheme . '_files'] = [
      'scheme' => $scheme,
      'status' => $scheme === 'private' ? 'unconfigured_or_missing' : 'missing',
      'files' => [],
    ];
    continue;
  }
  $files = [];
  $iterator = new RecursiveIteratorIterator(
    new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS),
    RecursiveIteratorIterator::LEAVES_ONLY
  );
  foreach ($iterator as $file) {
    if ($file->isLink()) {
      throw new RuntimeException('Symlinks are forbidden in the registered file projection');
    }
    if (!$file->isFile()) {
      continue;
    }
    $absolute = $file->getPathname();
    $relative = ltrim(substr($absolute, strlen(rtrim($root, DIRECTORY_SEPARATOR))), DIRECTORY_SEPARATOR);
    $files[] = [
      'path_sha256' => 'sha256:' . hash('sha256', str_replace(DIRECTORY_SEPARATOR, '/', $relative)),
      'byte_size' => $file->getSize(),
      'sha256' => 'sha256:' . hash_file('sha256', $absolute),
    ];
  }
  usort($files, fn($a, $b) => $a['path_sha256'] <=> $b['path_sha256']);
  $file_sets[$scheme . '_files'] = [
    'scheme' => $scheme,
    'status' => 'present',
    'files' => $files,
  ];
}

print frontier_json([
  'active_config' => ['items' => $config_items],
  'public_files' => $file_sets['public_files'],
  'private_files' => $file_sets['private_files'],
]);
""".strip()

_DUMP_COMPLETED_FOOTER = re.compile(
    rb"(?:\r?\n)?-- Dump completed on \d{4}-\d{2}-\d{2}[ \t]+\d{1,2}:\d{2}:\d{2}\r?\n?\Z"
)
_VOLATILE_DATABASE_TABLE_PATTERNS = (
    "cache_*",
    "batch",
    "flood",
    "key_value_expire",
    "queue",
    "semaphore",
    "sessions",
    "watchdog",
)
_SQL_DATA_SECTION = re.compile(
    rb"(?ms)^-- Dumping data for table `([^`]+)`\r?\n.*?(?=^-- Table structure for table `|\Z)"
)


@dataclass(frozen=True)
class FrontierCanaryResult:
    """Materialized canary evidence and its production audit."""

    manifest: dict[str, Any]
    runs: tuple[dict[str, Any], dict[str, Any]]
    audit: dict[str, Any]
    anchor: GitRegistrationAnchor
    manifest_path: Path
    run_paths: tuple[Path, Path]
    audit_path: Path


def build_codex_argv(
    codex_binary: Path,
    *,
    workdir: Path,
    output_schema: Path,
    model: str,
    extra_args: Sequence[str] = (),
) -> tuple[str, ...]:
    """Build and independently validate the only Codex invocation we permit."""

    if not codex_binary.is_file():
        raise FrontierCanaryError(f"Codex binary is not a file: {codex_binary}")
    if not workdir.is_dir():
        raise FrontierCanaryError(f"Canary workdir is not a directory: {workdir}")
    if not output_schema.is_file():
        raise FrontierCanaryError(f"Output schema is not a file: {output_schema}")
    if not model or _MODEL_SELECTOR.fullmatch(model) is None or _MUTABLE.search(model):
        raise FrontierCanaryError("Model must be a non-moving, explicit preregistered selector")
    _reject_unsafe_extra_args(extra_args)
    argv = (
        str(codex_binary.resolve()),
        "exec",
        "-p",
        CODEX_CONFIG_PROFILE,
        "--strict-config",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "plugins",
        "--disable",
        "apps",
        "--ephemeral",
        "--json",
        "--skip-git-repo-check",
        "--cd",
        str(workdir.resolve()),
        "--output-schema",
        str(output_schema.resolve()),
        "--model",
        model,
        *tuple(extra_args),
        "-",
    )
    validate_codex_argv(argv)
    return argv


def validate_codex_argv(argv: Sequence[str]) -> None:
    """Fail closed if an invocation can write, widen scope, or load user config."""

    values = tuple(str(value) for value in argv)
    expected_shape = (
        len(values) in {21, 23}
        and len(values) > 1
        and values[1:14]
        == (
            "exec",
            "-p",
            CODEX_CONFIG_PROFILE,
            "--strict-config",
            "--ignore-user-config",
            "--ignore-rules",
            "--disable",
            "plugins",
            "--disable",
            "apps",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
        )
        and values[14] == "--cd"
        and values[16] == "--output-schema"
        and values[18] == "--model"
        and values[-1] == "-"
        and (len(values) == 21 or values[20:22] == ("--color", "never"))
    )
    if not expected_shape:
        raise FrontierCanaryError(
            "Codex argv does not match the canonical named-permissions invocation shape"
        )
    path_contracts = (
        ("binary", values[0], "file"),
        ("workdir", values[15], "directory"),
        ("output schema", values[17], "file"),
    )
    for label, raw_path, kind in path_contracts:
        path = Path(raw_path)
        exists_as_expected = path.is_dir() if kind == "directory" else path.is_file()
        if (
            not path.is_absolute()
            or str(path.resolve()) != raw_path
            or not exists_as_expected
        ):
            raise FrontierCanaryError(
                f"Codex argv {label} is not a canonical absolute {kind} path"
            )
    model = values[19]
    if _MODEL_SELECTOR.fullmatch(model) is None or _MUTABLE.search(model):
        raise FrontierCanaryError(
            "Codex argv model is not a non-moving, explicit preregistered selector"
        )
    for flag in _REQUIRED_SAFE_FLAGS:
        if values.count(flag) != 1:
            raise FrontierCanaryError(f"Codex argv must contain exactly one {flag}")
    if values.count("-p") != 1 or values[values.index("-p") + 1] != CODEX_CONFIG_PROFILE:
        raise FrontierCanaryError("Codex must load the exact preregistered config profile")
    if "--sandbox" in values or "-s" in values:
        raise FrontierCanaryError(
            "Legacy sandbox flags must not override the named permissions profile"
        )
    for value in values:
        lowered = value.lower()
        if any(lowered == prefix or lowered.startswith(prefix + "=") for prefix in _FORBIDDEN_ARG_PREFIXES):
            raise FrontierCanaryError(f"Forbidden Codex argument: {value}")
        if lowered in {"workspace-write", "danger-full-access", "-s"}:
            raise FrontierCanaryError(f"Writable or overriding sandbox argument: {value}")
        if lowered.startswith("--sandbox="):
            raise FrontierCanaryError(f"Sandbox override is forbidden: {value}")
        if lowered in {"-c", "--config", "--profile"}:
            raise FrontierCanaryError(f"Config/profile override is forbidden: {value}")


def _validated_bootstrap_home_manifest(
    manifest: Any, *, label: str
) -> list[Mapping[str, Any]]:
    if not isinstance(manifest, Mapping):
        raise FrontierCanaryError(f"System-skill bootstrap {label} home manifest is missing")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or any(
        not isinstance(entry, Mapping) for entry in entries
    ):
        raise FrontierCanaryError(f"System-skill bootstrap {label} home entries are malformed")
    paths = [entry.get("path") for entry in entries]
    canonical_paths = all(
        isinstance(path, str)
        and path
        and not path.startswith("/")
        and "\\" not in path
        and not any(part in {"", ".", ".."} for part in path.split("/"))
        and not any(ord(character) < 32 or ord(character) == 127 for character in path)
        for path in paths
    )
    if (
        manifest.get("schema_version")
        != "drupal_agent_readiness.bootstrap_home_manifest.v1"
        or manifest.get("root_mode") != "0o700"
        or not canonical_paths
        or paths != sorted(paths)
        or len(paths) != len(set(paths))
        or any(
            entry.get("kind") not in {"file", "directory", "symlink"}
            or re.fullmatch(r"0o[0-7]{3,4}", str(entry.get("mode"))) is None
            or oct(int(str(entry.get("mode")), 8)) != entry.get("mode")
            or (
                entry.get("kind") == "directory"
                and set(entry) != {"path", "kind", "mode"}
            )
            or (
                entry.get("kind") == "file"
                and (
                    set(entry) != {"path", "kind", "mode", "byte_size", "sha256"}
                    or not isinstance(entry.get("byte_size"), int)
                    or entry.get("byte_size") < 0
                    or not _SHA256.fullmatch(str(entry.get("sha256")))
                )
            )
            or (
                entry.get("kind") == "symlink"
                and (
                    set(entry)
                    != {"path", "kind", "mode", "target", "resolved_sha256"}
                    or not isinstance(entry.get("target"), str)
                    or not Path(entry["target"]).is_absolute()
                    or not _SHA256.fullmatch(str(entry.get("resolved_sha256")))
                )
            )
            for entry in entries
        )
    ):
        raise FrontierCanaryError(f"System-skill bootstrap {label} home manifest is invalid")
    body = {
        "schema_version": "drupal_agent_readiness.bootstrap_home_manifest.v1",
        "root_mode": "0o700",
        "entries": entries,
    }
    expected_tree = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    if manifest.get("tree_sha256") != expected_tree:
        raise FrontierCanaryError(f"System-skill bootstrap {label} home tree hash is invalid")
    return entries


def _validate_bootstrap_home_layouts(
    bootstrap: Mapping[str, Any],
    *,
    system_files: list[Mapping[str, Any]],
    system_directories: list[Mapping[str, Any]],
    permissions_profile_sha256: str,
    codex_binary: Path,
) -> None:
    initial = _validated_bootstrap_home_manifest(
        bootstrap.get("initial_home"), label="initial"
    )
    initial_by_path = {entry["path"]: entry for entry in initial}
    profile_name = f"{CODEX_CONFIG_PROFILE}.config.toml"
    if (
        set(initial_by_path) != {profile_name, "os-tmp"}
        or initial_by_path[profile_name].get("kind") != "file"
        or initial_by_path[profile_name].get("sha256")
        != permissions_profile_sha256
        or initial_by_path[profile_name].get("mode") != "0o600"
        or initial_by_path["os-tmp"].get("kind") != "directory"
        or initial_by_path["os-tmp"].get("mode") != "0o700"
    ):
        raise FrontierCanaryError("System-skill bootstrap initial home layout is not exact")
    final = _validated_bootstrap_home_manifest(
        bootstrap.get("final_home"), label="final"
    )
    final_by_path = {entry["path"]: entry for entry in final}
    top_level = {path.split("/", 1)[0] for path in final_by_path}
    if top_level != SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL:
        raise FrontierCanaryError("System-skill bootstrap final top-level layout is not exact")
    system_paths = {item["path"] for item in system_directories}
    system_file_paths = {item["path"] for item in system_files}
    for path in system_file_paths:
        parent = Path(path).parent
        while parent.as_posix() not in {".", ""}:
            system_paths.add(parent.as_posix())
            parent = parent.parent
    arg0_runs = {
        path
        for path, entry in final_by_path.items()
        if entry.get("kind") == "directory"
        and re.fullmatch(r"tmp/arg0/codex-arg0[A-Za-z0-9]+", path)
    }
    if len(arg0_runs) != 1:
        raise FrontierCanaryError("System-skill bootstrap arg0 layout is ambiguous")
    arg0_run = next(iter(arg0_runs))
    tmp_paths = {
        "tmp",
        "tmp/arg0",
        arg0_run,
        f"{arg0_run}/.lock",
        f"{arg0_run}/apply_patch",
        f"{arg0_run}/applypatch",
        f"{arg0_run}/codex-execve-wrapper",
    }
    expected_paths = (
        set(SYSTEM_SKILL_BOOTSTRAP_FINAL_TOP_LEVEL)
        | system_paths
        | system_file_paths
        | tmp_paths
    )
    if set(final_by_path) != expected_paths:
        raise FrontierCanaryError("System-skill bootstrap final nested layout is not exact")
    directory_paths = {
        "os-tmp",
        "skills",
        "skills/.system",
        "tmp",
        "tmp/arg0",
        arg0_run,
    } | (system_paths - system_file_paths)
    wrapper_paths = {
        f"{arg0_run}/apply_patch",
        f"{arg0_run}/applypatch",
        f"{arg0_run}/codex-execve-wrapper",
    }
    if any(
        (entry.get("kind") == "directory") != (path in directory_paths)
        for path, entry in final_by_path.items()
    ):
        raise FrontierCanaryError("System-skill bootstrap home entry kinds are inconsistent")
    initial_profile = initial_by_path[profile_name]
    final_profile = final_by_path[profile_name]
    if (
        final_profile.get("kind") != "file"
        or final_profile.get("mode") != initial_profile.get("mode")
        or final_profile.get("byte_size") != initial_profile.get("byte_size")
        or final_profile.get("sha256") != initial_profile.get("sha256")
    ):
        raise FrontierCanaryError(
            "System-skill bootstrap final permissions profile is not byte-identical"
        )
    if any(
        final_by_path[path].get("kind") != "symlink"
        or final_by_path[path].get("target") != str(codex_binary.resolve())
        or final_by_path[path].get("resolved_sha256") != file_sha256(codex_binary)
        for path in wrapper_paths
    ) or any(
        entry.get("kind") == "symlink" and path not in wrapper_paths
        for path, entry in final_by_path.items()
    ):
        raise FrontierCanaryError("System-skill bootstrap wrapper symlinks are not exact")
    for path, entry in final_by_path.items():
        if path in wrapper_paths or path in system_file_paths or path in system_paths:
            continue
        try:
            mode = int(str(entry.get("mode")), 8)
        except ValueError as error:
            raise FrontierCanaryError(
                "System-skill bootstrap final home mode is invalid"
            ) from error
        if entry.get("kind") == "directory":
            unsafe = mode & 0o022 or mode & 0o500 != 0o500
        else:
            unsafe = mode & 0o022 or mode & 0o400 != 0o400
        if unsafe:
            raise FrontierCanaryError(
                f"System-skill bootstrap final home has unsafe mode: {path}"
            )
    for item in system_files:
        retained = final_by_path[item["path"]]
        if (
            retained.get("byte_size") != item["byte_size"]
            or retained.get("sha256") != item["sha256"]
            or retained.get("mode") != item["mode"]
        ):
            raise FrontierCanaryError(
                "System-skill bootstrap final home differs from the retained skill manifest"
            )
    for item in system_directories:
        retained = final_by_path[item["path"]]
        if retained.get("kind") != "directory" or retained.get("mode") != item["mode"]:
            raise FrontierCanaryError(
                "System-skill bootstrap final directory modes differ from the manifest"
            )


def _validate_system_skill_bootstrap(
    environment_policy: Mapping[str, Any],
    *,
    codex_binary: Path,
    workdir: Path,
    model_snapshot: str,
    network_sandbox_binary: Path,
    python_binary: Path,
) -> None:
    bootstrap = environment_policy.get("system_skills_preflight")
    if not isinstance(bootstrap, Mapping):
        raise FrontierCanaryError("Execution environment lacks system-skill bootstrap evidence")
    host_denials = bootstrap.get("host_read_denials")
    if (
        not isinstance(host_denials, Mapping)
        or set(host_denials) != set(SYSTEM_SKILL_REQUIRED_HOST_DENIALS)
        or dict(host_denials) != expected_system_skill_host_denials()
    ):
        raise FrontierCanaryError(
            "System-skill bootstrap host-state denial identities are not exact"
        )
    expected_profile = build_system_skill_bootstrap_sandbox_profile(host_denials)
    expected_profile_sha256 = "sha256:" + hashlib.sha256(
        expected_profile.encode("utf-8")
    ).hexdigest()
    bootstrap_stdout = bootstrap.get("stdout")
    bootstrap_stderr = bootstrap.get("stderr")
    if not isinstance(bootstrap_stdout, str) or not isinstance(bootstrap_stderr, str):
        raise FrontierCanaryError("System-skill bootstrap raw streams are missing")
    bootstrap_events = [
        parse_json_without_duplicate_keys(
            line,
            label=f"System-skill bootstrap JSONL line {line_number}",
        )
        for line_number, line in enumerate(bootstrap_stdout.splitlines(), start=1)
        if line.strip()
    ]
    if any(not isinstance(event, Mapping) for event in bootstrap_events):
        raise FrontierCanaryError("System-skill bootstrap JSONL contains a non-object")
    observed_event_types = [str(event.get("type", "")) for event in bootstrap_events]
    allowed_events = all(
        event.get("type") in {"thread.started", "turn.started", "error", "turn.failed"}
        or (
            event.get("type") == "item.completed"
            and isinstance(event.get("item"), Mapping)
            and event["item"].get("type") == "error"
        )
        for event in bootstrap_events
    )
    transport_failure_class = classify_system_skill_bootstrap_transport(
        bootstrap_events,
        stdout=bootstrap_stdout,
        stderr=bootstrap_stderr,
    )
    prompt = bootstrap.get("prompt")
    event_types = bootstrap.get("event_types")
    if (
        bootstrap.get("bootstrap_kind")
        != "unauthenticated_network_denied_codex_startup"
        or "model_call" in bootstrap
        or bootstrap.get("model_turn_started") is not True
        or bootstrap.get("network_egress_denied") is not True
        or bootstrap.get("provider_exchange_observed") is not False
        or bootstrap.get("auth_present") is not False
        or bootstrap.get("provider_response_received") is not False
        or bootstrap.get("transport_failure_class") != transport_failure_class
        or prompt != SYSTEM_SKILL_BOOTSTRAP_PROMPT
        or bootstrap.get("prompt_sha256")
        != "sha256:" + hashlib.sha256(SYSTEM_SKILL_BOOTSTRAP_PROMPT.encode()).hexdigest()
        or bootstrap.get("prompt_byte_size")
        != len(SYSTEM_SKILL_BOOTSTRAP_PROMPT.encode())
        or bootstrap.get("sandbox_profile_sha256") != expected_profile_sha256
        or bootstrap.get("sandbox_profile") != expected_profile
        or bootstrap.get("codex_sha256") != file_sha256(codex_binary)
        or bootstrap.get("network_sandbox_sha256")
        != file_sha256(network_sandbox_binary)
        or bootstrap.get("python_sha256") != file_sha256(python_binary)
        or not isinstance(bootstrap.get("returncode"), int)
        or bootstrap.get("returncode") == 0
        or not isinstance(event_types, list)
        or event_types != observed_event_types
        or event_types.count("thread.started") != 1
        or event_types.count("turn.started") != 1
        or event_types.count("turn.failed") != 1
        or not allowed_events
        or count_codex_tool_calls(bootstrap_stdout) != 0
        or bootstrap.get("stdout_sha256")
        != "sha256:" + hashlib.sha256(bootstrap_stdout.encode("utf-8")).hexdigest()
        or bootstrap.get("stderr_sha256")
        != "sha256:" + hashlib.sha256(bootstrap_stderr.encode("utf-8")).hexdigest()
        or bootstrap.get("stdout_byte_size") != len(bootstrap_stdout.encode("utf-8"))
        or bootstrap.get("stderr_byte_size") != len(bootstrap_stderr.encode("utf-8"))
    ):
        raise FrontierCanaryError(
            "System-skill bootstrap lacks exact unauthenticated network-denial evidence"
        )
    command = bootstrap.get("command")
    bootstrap_environment = bootstrap.get("environment")
    bootstrap_home = (
        bootstrap_environment.get("HOME")
        if isinstance(bootstrap_environment, Mapping)
        else None
    )
    expected_environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "SHELL": "/bin/sh",
        "TERM": "dumb",
        "HOME": bootstrap_home,
        "CODEX_HOME": bootstrap_home,
        "TMPDIR": f"{bootstrap_home}/os-tmp" if isinstance(bootstrap_home, str) else None,
    }
    if (
        not isinstance(command, list)
        or len(command) < 4
        or Path(str(command[0])).resolve() != network_sandbox_binary
        or command[1:3] != ["-p", expected_profile]
        or not isinstance(bootstrap_environment, Mapping)
        or dict(bootstrap_environment) != expected_environment
        or not isinstance(bootstrap_home, str)
        or not Path(bootstrap_home).is_absolute()
        or str(Path(bootstrap_home).resolve()) != bootstrap_home
    ):
        raise FrontierCanaryError("System-skill bootstrap command is not the registered sandbox")
    validate_codex_argv(tuple(str(item) for item in command[3:]))
    inner = tuple(str(item) for item in command[3:])
    if (
        Path(inner[0]).resolve() != codex_binary
        or Path(inner[15]).resolve() != workdir
        or inner[19] != model_snapshot
    ):
        raise FrontierCanaryError("System-skill bootstrap differs from the registered Codex stack")
    probe = bootstrap.get("network_denial_probe")
    probe_argv = probe.get("argv") if isinstance(probe, Mapping) else None
    probe_stdout = probe.get("stdout") if isinstance(probe, Mapping) else None
    probe_stderr = probe.get("stderr") if isinstance(probe, Mapping) else None
    probe_environment = probe.get("environment") if isinstance(probe, Mapping) else None
    probe_home = (
        probe_environment.get("HOME")
        if isinstance(probe_environment, Mapping)
        else None
    )
    expected_probe_environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "SHELL": "/bin/sh",
        "TERM": "dumb",
        "HOME": probe_home,
        "CODEX_HOME": probe_home,
        "TMPDIR": f"{probe_home}/os-tmp" if isinstance(probe_home, str) else None,
    }
    if (
        not isinstance(probe, Mapping)
        or probe.get("status") != "verified"
        or probe.get("control_connected") is not True
        or probe.get("sandbox_connected") is not False
        or probe.get("returncode") != SYSTEM_SKILL_NETWORK_PROBE_EXIT_CODE
        or probe.get("sandbox_profile_sha256") != expected_profile_sha256
        or probe.get("sandbox_profile") != expected_profile
        or not isinstance(probe_environment, Mapping)
        or dict(probe_environment) != expected_probe_environment
        or not isinstance(probe_home, str)
        or not Path(probe_home).is_absolute()
        or str(Path(probe_home).resolve()) != probe_home
        or not isinstance(probe_stdout, str)
        or not isinstance(probe_stderr, str)
        or probe_stdout != SYSTEM_SKILL_NETWORK_PROBE_STDOUT
        or probe_stderr != SYSTEM_SKILL_NETWORK_PROBE_STDERR
        or probe.get("stdout_sha256")
        != "sha256:" + hashlib.sha256(probe_stdout.encode("utf-8")).hexdigest()
        or probe.get("stderr_sha256")
        != "sha256:" + hashlib.sha256(probe_stderr.encode("utf-8")).hexdigest()
        or probe.get("stdout_byte_size") != len(probe_stdout.encode("utf-8"))
        or probe.get("stderr_byte_size") != len(probe_stderr.encode("utf-8"))
        or not isinstance(probe_argv, list)
        or len(probe_argv) < 4
        or Path(str(probe_argv[0])).resolve() != network_sandbox_binary
        or probe_argv[1:3] != ["-p", expected_profile]
        or Path(str(probe_argv[3])).resolve() != python_binary
        or probe_argv[4:8]
        != ["-I", "-S", "-c", SYSTEM_SKILL_NETWORK_PROBE_CODE]
        or len(probe_argv) != 10
        or probe_argv[8] != "127.0.0.1"
        or not str(probe_argv[9]).isdigit()
    ):
        raise FrontierCanaryError("System-skill bootstrap network-denial probe is invalid")
    platform = bootstrap.get("sandbox_platform")
    if (
        not isinstance(platform, Mapping)
        or platform.get("sys_platform") != "darwin"
        or any(
            not isinstance(platform.get(name), str) or not platform.get(name)
            for name in ("sysname", "release", "version", "machine")
        )
    ):
        raise FrontierCanaryError("System-skill bootstrap platform evidence is incomplete")
    manifest = bootstrap.get("manifest")
    files = manifest.get("files") if isinstance(manifest, Mapping) else None
    directories = manifest.get("directories") if isinstance(manifest, Mapping) else None
    paths = [item.get("path") for item in files] if isinstance(files, list) else []
    directory_paths = (
        [item.get("path") for item in directories]
        if isinstance(directories, list)
        else []
    )
    canonical_directory_paths = all(
        isinstance(path, str)
        and path
        and not path.startswith("/")
        and "\\" not in path
        and not any(part in {"", ".", ".."} for part in path.split("/"))
        and not any(ord(character) < 32 or ord(character) == 127 for character in path)
        for path in directory_paths
    )
    canonical_paths = all(
        isinstance(path, str)
        and path.startswith("skills/.system/")
        and not path.startswith("/")
        and "\\" not in path
        and not any(part in {"", ".", ".."} for part in path.split("/"))
        and not any(ord(character) < 32 or ord(character) == 127 for character in path)
        for path in paths
    )
    manifest_body = {
        "schema_version": "drupal_agent_readiness.system_skills_manifest.v1",
        "directories": directories,
        "files": files,
    }
    expected_tree_sha256 = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(manifest_body)).hexdigest()
        if isinstance(files, list)
        else None
    )
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schema_version")
        != "drupal_agent_readiness.system_skills_manifest.v1"
        or set(manifest) != {"schema_version", "directories", "files", "tree_sha256"}
        or not isinstance(directories, list)
        or not isinstance(files, list)
        or not files
        or not canonical_directory_paths
        or directory_paths[:2] != ["skills", "skills/.system"]
        or directory_paths != sorted(directory_paths)
        or len(directory_paths) != len(set(directory_paths))
        or set(directory_paths) & set(paths)
        or any(
            parent.as_posix() not in set(directory_paths)
            for path in [*directory_paths[1:], *paths]
            for parent in [Path(path).parent]
            if parent.as_posix() not in {".", ""}
        )
        or any(
            not isinstance(item, Mapping)
            or set(item) != {"path", "mode"}
            or not isinstance(item.get("path"), str)
            or item["path"] not in {"skills", "skills/.system"}
            and not item["path"].startswith("skills/.system/")
            or re.fullmatch(r"0o[0-7]{3,4}", str(item.get("mode"))) is None
            or int(str(item.get("mode")), 8) & 0o7022
            or int(str(item.get("mode")), 8) & 0o500 != 0o500
            for item in directories
        )
        or not canonical_paths
        or paths != sorted(paths)
        or len(paths) != len(set(paths))
        or manifest.get("tree_sha256") != expected_tree_sha256
        or any(
            not isinstance(item, Mapping)
            or set(item) != {"path", "mode", "byte_size", "sha256"}
            or re.fullmatch(r"0o[0-7]{3,4}", str(item.get("mode"))) is None
            or int(str(item.get("mode")), 8) & 0o7022
            or not int(str(item.get("mode")), 8) & 0o400
            or not isinstance(item.get("byte_size"), int)
            or item.get("byte_size") < 0
            or not _SHA256.fullmatch(str(item.get("sha256")))
            for item in files
        )
    ):
        raise FrontierCanaryError("System-skill bootstrap manifest is incomplete")
    permissions_profile_sha256 = (
        environment_policy.get("permissions_preflight", {}).get("profile_sha256")
        if isinstance(environment_policy.get("permissions_preflight"), Mapping)
        else None
    )
    if (
        not isinstance(permissions_profile_sha256, str)
        or bootstrap.get("permissions_profile_sha256")
        != permissions_profile_sha256
        or bootstrap.get("output_schema_sha256") != file_sha256(Path(inner[17]))
    ):
        raise FrontierCanaryError(
            "System-skill bootstrap permissions or output schema pin is invalid"
        )
    _validate_bootstrap_home_layouts(
        bootstrap,
        system_files=files,
        system_directories=directories,
        permissions_profile_sha256=permissions_profile_sha256,
        codex_binary=codex_binary,
    )
    payloads = bootstrap.get("retained_skill_payloads")
    if (
        not isinstance(payloads, list)
        or any(not isinstance(item, Mapping) for item in payloads)
        or [item.get("path") for item in payloads] != paths
    ):
        raise FrontierCanaryError("System-skill bootstrap did not retain every skill payload")
    import base64

    for manifest_item, payload_item in zip(files, payloads, strict=True):
        if not isinstance(payload_item, Mapping) or set(payload_item) != {
            "path",
            "content_base64",
        }:
            raise FrontierCanaryError("Retained system-skill payload is malformed")
        try:
            payload = base64.b64decode(payload_item["content_base64"], validate=True)
        except (ValueError, TypeError) as error:
            raise FrontierCanaryError("Retained system-skill payload is not base64") from error
        if (
            payload_item["path"] != manifest_item["path"]
            or len(payload) != manifest_item["byte_size"]
            or "sha256:" + hashlib.sha256(payload).hexdigest()
            != manifest_item["sha256"]
        ):
            raise FrontierCanaryError("Retained system-skill bytes differ from their manifest")
    if bootstrap.get("stream_retention") != {
        "uri": "pins/agent/execution-environment-policy.json",
        "stdout_json_pointer": "/system_skills_preflight/stdout",
        "stderr_json_pointer": "/system_skills_preflight/stderr",
        "skill_payloads_json_pointer": (
            "/system_skills_preflight/retained_skill_payloads"
        ),
        "scope": "private_canary_evidence_not_public_distribution",
    }:
        raise FrontierCanaryError("System-skill bootstrap retention location is not exact")


def derive_ddev_substrate(
    site_root: Path,
    *,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Derive fail-closed, content-addressed substrate pins from a DDEV site.

    The helper reads code bytes directly from the host checkout, asks bootstrapped
    Drupal for the installed non-core extensions, and resolves the running DDEV
    web container to both its local image ID and registry content digest.  It
    refuses missing paths, moving version labels, symlinks, or unpinned images.
    """

    root = site_root.resolve()
    run = runner or _default_command_runner
    composer_lock = root / "composer.lock"
    installed_json = root / "vendor" / "composer" / "installed.json"
    ddev_config = root / ".ddev" / "config.yaml"
    for path in (composer_lock, installed_json, ddev_config):
        if not path.is_file():
            raise FrontierCanaryError(f"Cannot derive substrate; required file is missing: {path}")

    installed_document = _load_unique_json(installed_json)
    installed_packages = _installed_packages(installed_document)
    lock_document = _load_unique_json(composer_lock)
    lock_packages = _lock_packages(lock_document)
    package_by_name = {package["name"]: package for package in (*lock_packages, *installed_packages) if isinstance(package.get("name"), str)}

    # This helper is specifically for DDEV.  Host Drush can return a superficially
    # successful status while still being unable to bootstrap because the DB
    # hostname exists only on DDEV's network, so use DDEV for both calls.
    drush_prefix = ["ddev", "drush"]
    status = _json_stdout(
        _run_checked(run, [*drush_prefix, "status", "--format=json"], root),
        "DDEV Drush status",
    )
    drupal_root = _host_project_path(root, _status_value(status, "root", "drupal-root"))
    core_path = drupal_root / "core"
    if not core_path.is_dir():
        raise FrontierCanaryError(f"Drush root does not contain Drupal core: {core_path}")
    extension_rows = _json_stdout(
        _run_checked(run, [*drush_prefix, "php:eval", _EXTENSION_CAPTURE_PHP], root),
        "installed extension capture",
    )
    if not isinstance(extension_rows, list):
        raise FrontierCanaryError("Installed extension capture did not return an array")

    core_tree = _tree_sha256(core_path)
    core_package = package_by_name.get("drupal/core", {})
    core_version = _immutable_version(
        _status_value(status, "drupal-version", "drupal_version")
        or core_package.get("version"),
        core_tree,
    )
    core_revision = _package_revision(core_package, core_tree)
    core = {
        "kind": "core",
        "name": "drupal/core",
        "version": core_version,
        "revision": core_revision,
        "tree_sha256": core_tree,
    }
    install_paths = _package_install_paths(root, installed_packages)
    components: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for index, row in enumerate(extension_rows):
        if not isinstance(row, Mapping):
            raise FrontierCanaryError(f"Extension row {index} is not an object")
        kind = row.get("kind")
        machine_name = row.get("machine_name")
        relative_path = row.get("path")
        if kind not in {"module", "theme", "profile"}:
            raise FrontierCanaryError(f"Extension row {index} has invalid kind")
        if not isinstance(machine_name, str) or not machine_name:
            raise FrontierCanaryError(f"Extension row {index} has no machine name")
        if not isinstance(relative_path, str) or not relative_path:
            raise FrontierCanaryError(f"Extension row {index} has no code path")
        code_path = _host_project_path(drupal_root, relative_path)
        try:
            code_path.relative_to(core_path)
        except ValueError:
            pass
        else:
            # Core extensions are already content-addressed by the core tree.
            continue
        if code_path in seen_paths:
            raise FrontierCanaryError(f"Multiple installed extensions resolve to {code_path}")
        seen_paths.add(code_path)
        if not code_path.is_dir():
            raise FrontierCanaryError(f"Installed extension path is missing: {code_path}")
        tree = _tree_sha256(code_path)
        package = install_paths.get(code_path.resolve(), {})
        name = package.get("name") or f"custom/{kind}/{machine_name}"
        components.append(
            {
                "kind": kind,
                "name": name,
                "version": _immutable_version(row.get("version") or package.get("version"), tree),
                "revision": _package_revision(package, tree),
                "tree_sha256": tree,
            }
        )
    composer_kinds = {
        "drupal-module": "module",
        "drupal-theme": "theme",
        "drupal-profile": "profile",
    }
    for code_path, package in sorted(
        install_paths.items(), key=lambda item: item[0].as_posix()
    ):
        kind = composer_kinds.get(package.get("type"))
        if kind is None or code_path in seen_paths:
            continue
        try:
            code_path.relative_to(core_path)
        except ValueError:
            pass
        else:
            continue
        if not code_path.is_dir():
            raise FrontierCanaryError(f"Installed Composer extension path is missing: {code_path}")
        seen_paths.add(code_path)
        tree = _tree_sha256(code_path)
        components.append(
            {
                "kind": kind,
                "name": package["name"],
                "version": _immutable_version(package.get("version"), tree),
                "revision": _package_revision(package, tree),
                "tree_sha256": tree,
            }
        )
    components.sort(key=lambda item: (item["kind"], item["name"]))
    identities = [(item["kind"], item["name"]) for item in components]
    if len(identities) != len(set(identities)):
        raise FrontierCanaryError("Derived extension identities are not unique")

    project_name = _ddev_project_name(ddev_config)
    web_container = f"ddev-{project_name}-web"
    image_id = _run_checked(
        run, ["docker", "inspect", "--format={{.Image}}", web_container], root
    ).stdout.strip()
    if not _SHA256.fullmatch(image_id):
        raise FrontierCanaryError("DDEV web container did not resolve to an immutable image ID")
    repo_digest_text = _run_checked(
        run,
        ["docker", "image", "inspect", "--format={{index .RepoDigests 0}}", image_id],
        root,
    ).stdout.strip()
    repo_digest = repo_digest_text.rsplit("@", 1)[-1]
    if not _SHA256.fullmatch(repo_digest):
        raise FrontierCanaryError("DDEV web image has no immutable registry digest")
    php_version = _run_checked(
        run, ["ddev", "exec", "php", "-r", "echo PHP_VERSION;"], root
    ).stdout.strip()
    if not php_version or _MUTABLE.search(php_version):
        raise FrontierCanaryError("DDEV PHP runtime did not report an immutable version")
    database_driver = _required_status_string(status, "db-driver", "db_driver")
    database_version = _run_checked(
        run,
        [
            "ddev",
            "drush",
            "sql:query",
            "SELECT VERSION()",
            "--extra=--skip-column-names",
        ],
        root,
    ).stdout.strip()
    if not database_version or _MUTABLE.search(database_version):
        raise FrontierCanaryError("DDEV database did not report an immutable version")
    composer_hash = file_sha256(composer_lock)
    vendor_tree = _tree_sha256(root / "vendor")
    fixture_identity = _declared_hash(
        "|".join((project_name, composer_hash, core_tree, image_id, repo_digest))
    )
    substrate = {
        "fixture_id": f"ddev-{project_name}@{fixture_identity.removeprefix('sha256:')[:16]}",
        "core": core,
        "components": components,
        "runtime": {
            "php_version": php_version,
            "database_driver": database_driver,
            "database_version": database_version,
            "os_image_digest": repo_digest,
            "container_image_digest": image_id,
        },
        "composer_lock_sha256": composer_hash,
        "vendor_tree_sha256": vendor_tree,
    }
    _validate_substrate(substrate)
    return substrate


def derive_ddev_site_projection(
    site_root: Path,
    *,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Hash persistent Drupal state without retaining values or contents."""

    root = site_root.resolve()
    run = runner or _default_command_runner
    database_completed = _run_checked(
        run,
        ["ddev", "export-db", "--gzip=false", "--skip-hooks"],
        root,
    )
    if not isinstance(database_completed.stdout, str):
        raise FrontierCanaryError("DDEV database export did not return text")
    raw_dump = database_completed.stdout.encode("utf-8")
    matches = list(_DUMP_COMPLETED_FOOTER.finditer(raw_dump))
    if len(matches) != 1:
        raise FrontierCanaryError(
            "DDEV database export requires exactly one terminal dump-completed footer"
        )
    without_footer = raw_dump[: matches[0].start()] + b"\n"
    omitted_tables: list[str] = []

    def normalize_section(match: re.Match[bytes]) -> bytes:
        table = match.group(1).decode("utf-8", errors="strict")
        volatile = table.startswith("cache_") or table in {
            "batch",
            "flood",
            "key_value_expire",
            "queue",
            "semaphore",
            "sessions",
            "watchdog",
        }
        if not volatile:
            return match.group(0)
        omitted_tables.append(table)
        return (
            f"-- Dumping data for table `{table}`\n"
            f"-- Data omitted by persistent-state projection for `{table}`\n\n"
        ).encode("utf-8")

    canonical_dump = _SQL_DATA_SECTION.sub(normalize_section, without_footer)
    database_payload = {
        "algorithm": "ddev-persistent-sql-projection-sha256-v1",
        "scope": "complete_schema_and_nonvolatile_table_data",
        "normalization": (
            "remove one terminal dump timestamp and omit data sections for the exact "
            "bounded volatile-table patterns while retaining their schema"
        ),
        "excluded_data_table_patterns": list(_VOLATILE_DATABASE_TABLE_PATTERNS),
        "excluded_data_tables": sorted(omitted_tables),
        "canonical_byte_size": len(canonical_dump),
        "sha256": "sha256:" + hashlib.sha256(canonical_dump).hexdigest(),
        "retention": "digest_and_exclusion_manifest_only_raw_sql_not_retained",
    }

    projection_completed = _run_checked(
        run,
        ["ddev", "drush", "php:eval", _SITE_PROJECTION_CAPTURE_PHP],
        root,
    )
    projection = _json_stdout(projection_completed, "Drupal site projection")
    if not isinstance(projection, Mapping) or set(projection) != {
        "active_config",
        "public_files",
        "private_files",
    }:
        raise FrontierCanaryError("Drupal site projection has the wrong sources")

    active_config = _canonical_projection_source(
        projection["active_config"],
        label="active_config",
        algorithm="drupal-active-config-item-sha256-v1",
        retention="names_sizes_and_digests_only_values_not_retained",
    )
    public_files = _canonical_projection_source(
        projection["public_files"],
        label="public_files",
        algorithm="drupal-file-tree-content-sha256-v1",
        retention="path_digests_sizes_and_content_digests_only_contents_not_retained",
    )
    private_files = _canonical_projection_source(
        projection["private_files"],
        label="private_files",
        algorithm="drupal-file-tree-content-sha256-v1",
        retention="path_digests_sizes_and_content_digests_only_contents_not_retained",
    )
    result = {
        "database": database_payload,
        "active_config": active_config,
        "public_files": public_files,
        "private_files": private_files,
    }
    _validate_site_projection(result)
    return result


def derive_agent_visible_workspace(site_root: Path) -> dict[str, Any]:
    """Content-address the workspace bytes exposed to the read-only agent."""

    root = site_root.resolve()
    if not root.is_dir():
        raise FrontierCanaryError(f"Agent-visible workspace is not a directory: {root}")
    if os.path.lexists(root / ".git"):
        raise FrontierCanaryError(
            "Agent-visible snapshot must not contain any .git entry"
        )
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if ".git" in Path(relative).parts:
            raise FrontierCanaryError(
                f"Agent-visible snapshot contains forbidden .git metadata: {relative}"
            )
        mode = oct(path.lstat().st_mode & 0o777)
        if path.is_symlink():
            target = os.readlink(path)
            resolved = path.resolve()
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise FrontierCanaryError(
                    f"Agent-visible workspace symlink escapes the registered root: {relative}"
                ) from error
            entries.append(
                {
                    "path": relative,
                    "type": "symlink",
                    "mode": mode,
                    "target": target,
                }
            )
        elif path.is_dir():
            entries.append({"path": relative, "type": "directory", "mode": mode})
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": mode,
                    "byte_size": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
        else:
            raise FrontierCanaryError(
                f"Unsupported agent-visible workspace entry: {relative}"
            )
    payload = {
        "algorithm": "agent-visible-workspace-tree-sha256-v1",
        "excluded": [],
        "entries": entries,
    }
    payload["tree_sha256"] = canonical_sha256(payload)
    return payload


def _canonical_projection_source(
    value: Any,
    *,
    label: str,
    algorithm: str,
    retention: str,
) -> dict[str, Any]:
    source = _canonical_mapping(value, f"{label} projection")
    payload = {
        "algorithm": algorithm,
        **source,
        "retention": retention,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def run_frontier_canary(
    *,
    artifact_repo: Path,
    workdir: Path,
    codex_binary: Path,
    agent_version: str,
    model_provider: str,
    model_id: str,
    model_snapshot: str,
    collector: Collector,
    executor: Executor,
    registered_at: datetime | None = None,
    clock: Clock | None = None,
    extra_codex_args: Sequence[str] = (),
    execution_environment_policy: Mapping[str, Any] | None = None,
) -> FrontierCanaryResult:
    """Materialize, execute, and audit one registered two-slot observation.

    ``collector(slot_id)`` runs outside the model sandbox and returns inventory,
    persistent-state, code/runtime, and governed-snapshot pins.  The model sees
    the snapshot inline in the canonical prompt; ``workdir`` remains a pinned,
    dedicated custody boundary but no agent tool may read it.  This lane measures
    evidence interpretation and custody, not direct Drupal operation.
    """

    now = clock or (lambda: datetime.now(timezone.utc))
    repo = artifact_repo.resolve()
    target = workdir.resolve()
    binary = codex_binary.resolve()
    if _paths_overlap(repo, target):
        raise FrontierCanaryError(
            "Artifact repository and agent snapshot workspace must not overlap"
        )
    if repo.exists() and (
        not repo.is_dir() or any(repo.iterdir())
    ):
        raise FrontierCanaryError(
            "Artifact repository must be absent or an empty dedicated directory"
        )
    if not agent_version or _MUTABLE.search(agent_version):
        raise FrontierCanaryError("Agent version must be an immutable explicit version")
    _verify_agent_version(binary, agent_version)
    if not model_snapshot or _MUTABLE.search(model_snapshot):
        raise FrontierCanaryError("Model selector must be an explicit preregistered value")
    environment_policy = _canonical_mapping(
        execution_environment_policy
        or {
            "mode": "injected_executor",
            "credential_handling": "owned by injected executor and not inspected by harness",
        },
        "execution environment policy",
    )
    git_binary, git_sha256 = _registered_host_tool(environment_policy, "git")
    python_binary, python_sha256 = _registered_host_tool(environment_policy, "python")
    network_sandbox_binary, network_sandbox_sha256 = _registered_host_tool(
        environment_policy, "network_sandbox"
    )
    if python_binary != Path(sys.executable).resolve():
        raise FrontierCanaryError(
            "Pinned Python binary is not the interpreter executing the canary"
        )
    _validate_system_skill_bootstrap(
        environment_policy,
        codex_binary=binary,
        workdir=target,
        model_snapshot=model_snapshot,
        network_sandbox_binary=network_sandbox_binary,
        python_binary=python_binary,
    )
    validate_frontier_process_containment_policy(
        environment_policy.get("process_containment"),
        network_sandbox_binary=network_sandbox_binary,
    )
    source_paths = _executed_source_paths(collector, executor)
    source_hashes = _snapshot_source_hashes(source_paths)
    _prepare_repo(repo, git_binary=git_binary, git_sha256=git_sha256)
    _assert_source_hashes(source_paths, source_hashes, "registration setup")

    registration_capture = _canonical_capture(collector("frontier-001"))
    _assert_source_hashes(source_paths, source_hashes, "registration capture")
    if derive_agent_visible_workspace(target) != registration_capture["workspace"]:
        raise FrontierCanaryError(
            "Registered agent-visible workspace projection does not match the snapshot"
        )
    try:
        snapshot = load_canonical_json_file(target / "governed-observation.json")
    except (OSError, ValueError) as error:
        raise FrontierCanaryError("Governed observation snapshot is not canonical JSON") from error
    if not isinstance(snapshot, Mapping) or set(snapshot) != {
        "schema_version",
        "observation_kind",
        "claim_boundary",
        "inventory_evidence",
    }:
        raise FrontierCanaryError("Governed observation snapshot has the wrong fields")
    if snapshot.get("schema_version") != (
        "drupal_agent_readiness.governed_observation_snapshot.v1"
    ) or snapshot.get("inventory_evidence") != registration_capture["inventory"]:
        raise FrontierCanaryError("Governed snapshot is not bound to collector inventory truth")
    expected_system_tree = (
        environment_policy.get("system_skills_preflight", {})
        .get("manifest", {})
        .get("tree_sha256")
    )
    if not isinstance(expected_system_tree, str) or not _SHA256.fullmatch(
        expected_system_tree
    ):
        raise FrontierCanaryError(
            "Execution environment policy must preregister the exact system-skill tree"
        )
    permissions = environment_policy.get("permissions_preflight")
    if not isinstance(permissions, Mapping):
        raise FrontierCanaryError("Execution environment policy lacks permissions preflight")
    profile_text = permissions.get("profile_text")
    profile_sha256 = permissions.get("profile_sha256")
    if (
        permissions.get("config_profile") != CODEX_CONFIG_PROFILE
        or permissions.get("permissions_profile") != CODEX_PERMISSION_PROFILE
        or not isinstance(profile_text, str)
        or "sha256:" + hashlib.sha256(profile_text.encode("utf-8")).hexdigest()
        != profile_sha256
    ):
        raise FrontierCanaryError("Execution permissions profile bytes are not exact")
    probe_receipts = permissions.get("probe_receipts")
    if not isinstance(probe_receipts, Mapping) or set(probe_receipts) != {
        "workspace_readable",
        "auth_unreadable",
        "sentinel_unreadable",
        "git_metadata_unreadable",
        "observed_root_unreadable",
        "ddev_binary_unreadable",
        "docker_binary_minimal_runtime_readable",
        "docker_socket_unreadable",
    } or any(
        not isinstance(receipt, Mapping) or receipt.get("returncode") != 0
        for receipt in probe_receipts.values()
    ):
        raise FrontierCanaryError("Execution permissions profile denial probes did not pass")
    host_probe_paths = permissions.get("host_probe_paths")
    host_probe_names = {
        "observed_root_unreadable",
        "ddev_binary_unreadable",
        "docker_binary_minimal_runtime_readable",
        "docker_socket_unreadable",
    }
    if not isinstance(host_probe_paths, Mapping) or set(host_probe_paths) != host_probe_names:
        raise FrontierCanaryError("Execution permissions host probe paths are incomplete")
    exact_denial_lines = {
        f'{json.dumps(str(Path(path).resolve()))} = "deny"'
        for path in host_probe_paths.values()
        if isinstance(path, str) and Path(path).is_absolute()
    }
    if len(exact_denial_lines) != len(set(host_probe_paths.values())) or any(
        line not in profile_text.splitlines() for line in exact_denial_lines
    ):
        raise FrontierCanaryError(
            "Execution permissions profile does not explicitly deny every registered host path"
        )
    probe_prefix = [
        str(binary),
        "sandbox",
        "-p",
        CODEX_CONFIG_PROFILE,
        "-P",
        CODEX_PERMISSION_PROFILE,
        "-C",
        str(target),
        "--",
        "/bin/sh",
        "-c",
    ]
    expected_probe_tails = {
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
                str(Path(path).resolve()),
            ]
            for name, path in host_probe_paths.items()
            if isinstance(path, str) and Path(path).is_absolute()
        },
    }
    if set(expected_probe_tails) != set(probe_receipts) or any(
        receipt.get("argv") != [*probe_prefix, *expected_probe_tails[name]]
        for name, receipt in probe_receipts.items()
    ):
        raise FrontierCanaryError("Execution permissions probe receipts are not exact")
    store = _EvidenceStore(repo)
    registration_time = _aware_time(registered_at or (now() - timedelta(seconds=1)))
    manifest = _build_manifest(
        store=store,
        capture=registration_capture,
        workdir=target,
        codex_binary=binary,
        agent_version=agent_version,
        model_provider=model_provider,
        model_id=model_id,
        model_snapshot=model_snapshot,
        collector=collector,
        executor=executor,
        execution_environment_policy=environment_policy,
        executed_source_paths=source_paths,
        registered_at=registration_time,
    )
    _assert_manifest_source_closure(manifest, source_paths)
    manifest_issues = validate_experiment_manifest(manifest)
    if manifest_issues:
        rendered = "; ".join(f"{item.code}@{item.path}" for item in manifest_issues)
        raise FrontierCanaryError(f"Generated manifest violates measurement v1: {rendered}")
    manifest_path = store.write_json(
        manifest["registration"]["manifest_path"], manifest, replace=False
    )
    anchor = _commit_registration(
        repo,
        manifest,
        registration_time,
        git_binary=git_binary,
        git_sha256=git_sha256,
    )

    argv = build_codex_argv(
        binary,
        workdir=target,
        output_schema=repo / manifest["reference_agent_stack"]["output_schema"]["uri"],
        # The invoked identifier is the exact preregistered selector.  Codex
        # does not thereby attest the provider's backend model snapshot.
        model=model_snapshot,
        extra_args=extra_codex_args,
    )
    prompt = _render_prompt(repo, manifest)
    runs: list[dict[str, Any]] = []
    run_paths: list[Path] = []
    thread_ids: set[str] = set()
    for index, slot_id in enumerate(("frontier-001", "frontier-002"), start=1):
        _assert_host_tool_identity(python_binary, python_sha256, "Python")
        _assert_host_tool_identity(
            network_sandbox_binary, network_sandbox_sha256, "network sandbox"
        )
        _assert_manifest_source_closure(manifest, source_paths)
        starting_capture = _canonical_capture(collector(slot_id))
        _assert_manifest_source_closure(manifest, source_paths)
        _assert_host_tool_identity(python_binary, python_sha256, "Python")
        if derive_agent_visible_workspace(target) != starting_capture["workspace"]:
            raise FrontierCanaryError(
                f"{slot_id}: live snapshot workspace differs from its registered projection"
            )
        if starting_capture != registration_capture:
            raise FrontierCanaryError(f"{slot_id}: starting capture drifted from registration")
        started_at = _aware_time(now())
        if started_at <= registration_time:
            raise FrontierCanaryError("Execution timestamp must follow the registration commit")
        _assert_binary_identity(binary, manifest)
        execution = _canonical_mapping(executor(argv, prompt), "executor result")
        _assert_binary_identity(binary, manifest)
        _assert_host_tool_identity(
            network_sandbox_binary, network_sandbox_sha256, "network sandbox"
        )
        _assert_manifest_source_closure(manifest, source_paths)
        final_capture = _canonical_capture(collector(slot_id))
        _assert_manifest_source_closure(manifest, source_paths)
        if derive_agent_visible_workspace(target) != final_capture["workspace"]:
            raise FrontierCanaryError(
                f"{slot_id}: live snapshot workspace differs from its final projection"
            )
        completed_at = _aware_time(now())
        if final_capture != starting_capture:
            raise FrontierCanaryError(
                f"{slot_id}: registered persistent-state or snapshot projection drifted"
            )
        attempt = _validated_attempt_bundle(
            root=store.root,
            execution=execution,
            manifest=manifest,
            run_id=f"run-{slot_id}",
            slot_id=slot_id,
            argv=argv,
        )
        bound_execution = _retained_codex_execution(attempt, slot_id=slot_id)
        bound_execution["attempt_receipt"] = execution["attempt_receipt"]
        thread_id = bound_execution["thread_id"]
        if thread_id in thread_ids:
            raise FrontierCanaryError("Retained JSONL reused a Codex thread identity")
        thread_ids.add(thread_id)
        run = _build_run(
            store=store,
            manifest=manifest,
            slot_id=slot_id,
            index=index,
            capture=starting_capture,
            final_capture=final_capture,
            execution=bound_execution,
            argv=argv,
            started_at=started_at,
            completed_at=completed_at,
            now=now,
        )
        path = store.write_json(f"runs/{run['run_id']}/run-result.json", run, replace=False)
        runs.append(run)
        run_paths.append(path)

    _assert_manifest_source_closure(manifest, source_paths)
    _assert_host_tool_identity(python_binary, python_sha256, "Python")
    audit = audit_measurement_v1(
        manifest,
        runs,
        artifact_root=repo,
        registration_anchor=anchor,
    )
    _assert_manifest_source_closure(manifest, source_paths)
    _assert_host_tool_identity(python_binary, python_sha256, "Python")
    if audit["errors"]:
        codes = ", ".join(f"{error['code']}@{error['path']}" for error in audit["errors"])
        raise FrontierCanaryError(f"Generated evidence failed measurement v1 audit: {codes}")
    if not audit["estimate_reportable"]:
        raise FrontierCanaryError("Frontier canary did not yield a reportable estimate")
    if audit["registered_effect_rule_met"]:
        raise FrontierCanaryError("Frontier observation was incorrectly promoted to an effect")
    audit["limitations"].append(
        "The exact preregistered model selector was passed to Codex --model, but that selector "
        "is not a provider-attested backend snapshot; backend identity remains unverified unless "
        "the retained JSONL transcript supplies it."
    )
    audit["limitations"].extend(
        [
            "Codex JSONL reports a thread identity but no distinct provider request identity; "
            "provider_request_id is therefore retained as null and explicitly unverified.",
            "The retained instruction artifact is an operator prompt envelope embedded in stdin. "
            "Behavior-affecting model-catalog bytes are preregistered by digest and held unchanged, "
            "but those bytes are not retained and the remaining compiled system/developer "
            "instruction surface is unverified.",
            "The agent interprets a governed snapshot produced by a trusted host collector. "
            "This canary does not measure direct Drupal/DDEV discovery or operation.",
            "The governed snapshot contains the inventory evidence used for evaluation; success "
            "measures faithful evidence interpretation and schema compliance, not independent discovery.",
            "Before/after digests detect net persistent-state drift; they cannot prove no transient "
            "write occurred. Database data for the exact registered volatile table patterns is "
            "excluded (schema retained), and raw database, config, or file contents are not retained.",
            "The observed vendor tree and top-level host executables are drift-pinned, but the "
            "remaining Drupal bootstrap/runtime, settings, DDEV composition, dynamic libraries, "
            "container-daemon internals, and nested host toolchains remain trusted and unattested. "
            "The trusted collector snapshot cannot support a claim-grade Drupal improvement.",
        ]
    )
    audit_path = store.write_json("audit/measurement-v1-report.json", audit, replace=False)
    return FrontierCanaryResult(
        manifest=manifest,
        runs=(runs[0], runs[1]),
        audit=audit,
        anchor=anchor,
        manifest_path=manifest_path,
        run_paths=(run_paths[0], run_paths[1]),
        audit_path=audit_path,
    )


class _EvidenceStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def write_bytes(self, relative: str, payload: bytes, *, replace: bool = False) -> Path:
        path = self._path(relative)
        if path.exists() and not replace:
            raise FrontierCanaryError(f"Refusing to overwrite evidence: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def write_json(self, relative: str, document: Any, *, replace: bool = False) -> Path:
        return self.write_bytes(relative, canonical_json_bytes(document), replace=replace)

    def pin_bytes(self, relative: str, payload: bytes, media_type: str) -> dict[str, Any]:
        path = self.write_bytes(relative, payload)
        return {
            "uri": relative,
            "sha256": file_sha256(path),
            "media_type": media_type,
            "byte_size": path.stat().st_size,
        }

    def pin_json(self, relative: str, document: Any) -> dict[str, Any]:
        return self.pin_bytes(relative, canonical_json_bytes(document), "application/json")

    def pin_source(self, relative: str, source: Path, media_type: str) -> dict[str, Any]:
        if not source.is_file():
            raise FrontierCanaryError(f"Pinned source is not a file: {source}")
        return self.pin_bytes(relative, source.read_bytes(), media_type)

    def _path(self, relative: str) -> Path:
        if not relative or "\\" in relative:
            raise FrontierCanaryError(f"Unsafe evidence path: {relative!r}")
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise FrontierCanaryError(f"Evidence path escapes artifact repo: {relative}") from error
        return candidate


def _build_manifest(
    *,
    store: _EvidenceStore,
    capture: Mapping[str, Any],
    workdir: Path,
    codex_binary: Path,
    agent_version: str,
    model_provider: str,
    model_id: str,
    model_snapshot: str,
    collector: Collector,
    executor: Executor,
    execution_environment_policy: Mapping[str, Any],
    executed_source_paths: Mapping[str, Path],
    registered_at: datetime,
) -> dict[str, Any]:
    model_cache_contract = execution_environment_policy.get("model_cache")
    if (
        not model_cache_contract_valid(model_cache_contract)
        or model_cache_contract["selected_model_selector"] != model_snapshot
    ):
        raise FrontierCanaryError(
            "Execution environment must preregister behavior-affecting model-cache bytes"
        )
    drupal_state, runtime = _materialize_drupal_state(store, capture)
    protocol = store.pin_json(
        "pins/protocol/frontier-canary-v1.json",
        {
            "lane": "frontier_observation",
            "roster": ["frontier-001", "frontier-002"],
            "rule": (
                "one immutable read-only invocation per slot; registered persistent-state "
                "projection drift aborts"
            ),
        },
    )
    registry_design = store.pin_json(
        "pins/governance/frontier-canary-design.json",
        {
            "claim": (
                "schema-constrained interpretation success for the exact agent-visible "
                "inventory snapshot in this two-slot roster"
            ),
            "effect_decision": "forbidden",
            "version": "1.0.0",
        },
    )
    task_definition = store.pin_json(
        "pins/task/interpret-inventory-snapshot-v1.json",
        {
            "id": "interpret.inventory_snapshot",
            "objective": (
                "Interpret the trusted host collector's governed Drupal observation embedded "
                "in the canonical prompt envelope and return the registered inventory schema."
            ),
            "write_policy": "no writes",
            "tool_policy": "no tool calls; child-process creation is denied",
            "direct_drupal_access": False,
            "expected_output_provenance": "derived_from_agent_visible_evidence",
            "ground_truth_visibility_scope": (
                "reference artifact bytes withheld; equivalent inventory values are intentionally "
                "present in the agent-visible canonical prompt envelope"
            ),
        },
    )
    task_prompt_text = (
        "Interpret only the governed_observation.inventory_evidence object embedded in the "
        "canonical prompt envelope and return one JSON object matching the supplied inventory "
        "schema. Do not invoke a tool. The source Drupal site is outside your boundary. Do not "
        "access other host paths or external systems and do not attempt any write.\n"
    )
    task_prompt = _role_pin(
        store.pin_bytes("pins/task/prompt.md", task_prompt_text.encode(), "text/markdown"),
        "task_prompt",
        "agent_visible",
        ["agent", "harness", "auditor"],
    )
    ground_truth = _role_pin(
        store.pin_json("pins/task/expected-output-reference.json", capture["inventory"]),
        "ground_truth",
        "withheld_from_agent",
        ["evaluator", "auditor"],
    )
    system_prompt_text = (
        "# Retained operator prompt envelope\n\n"
        "This text is embedded in the JSON document delivered on stdin. It is not Codex's "
        "built-in system or developer prompt, which this harness cannot retain or attest.\n\n"
        "Act as a governed Drupal-evidence interpreter. Treat only the inline governed observation "
        "as evidence, do not infer absent surfaces, and never invoke a tool or attempt a write or "
        "network request.\n"
    )
    system_prompt = _role_pin(
        store.pin_bytes(
            "pins/agent/operator-prompt-envelope.md",
            system_prompt_text.encode(),
            "text/markdown",
        ),
        "system_prompt",
        "agent_visible",
        ["agent", "harness", "auditor"],
    )
    renderer = store.pin_json(
        "pins/prompt/canonical-envelope-renderer.json",
        {"algorithm": "canonical_operator_prompt_envelope_v1", "version": "1.0.0"},
    )
    render_inputs = _role_pin(
        store.pin_json(
            "pins/prompt/render-inputs.json",
            {
                "snapshot_file": "governed-observation.json",
                "snapshot_delivery": "inline_canonical_prompt_envelope",
                "answer_schema": "drupal_agent_readiness.inventory_answer.v1",
                "read_only": True,
                "direct_drupal_access": False,
            },
        ),
        "render_inputs",
        "agent_visible",
        ["agent", "harness", "auditor"],
    )
    agent_artifact = store.pin_source(
        "pins/agent/codex-binary", codex_binary, "application/octet-stream"
    )
    harness_artifact = store.pin_source(
        "pins/harness/frontier_canary.py", Path(__file__).resolve(), "text/x-python"
    )
    collector_artifact = store.pin_source(
        "pins/collector/collector-source.py",
        _callable_source_path(collector, "collector"),
        "text/x-python",
    )
    executor_artifact = store.pin_source(
        "pins/agent/executor-source.py",
        _callable_source_path(executor, "executor"),
        "text/x-python",
    )
    process_runner_artifact = store.pin_source(
        "pins/agent/codex-runner-utils.py",
        PACKAGE_ROOT / "codex_runner_utils.py",
        "text/x-python",
    )
    source_closure_tools = [
        {
            "id": f"source-closure:{source_id}",
            "version": "1.0.0",
            "artifact": store.pin_source(
                f"pins/source-closure/{source_id}.source",
                source_path,
                _source_media_type(source_path),
            ),
        }
        for source_id, source_path in sorted(executed_source_paths.items())
    ]
    environment_policy_artifact = store.pin_json(
        "pins/agent/execution-environment-policy.json",
        execution_environment_policy,
    )
    inference_parameters = store.pin_json(
        "pins/agent/inference-parameters.json",
        {
            "ephemeral": True,
            "ignore_project_and_user_rules": True,
            "output": "jsonl",
            "plugins": "disabled with canonical --disable plugins",
            "apps": "disabled with canonical --disable apps",
            "provider_backend_identity": (
                "unverified unless Codex JSONL reports a backend snapshot; the exact "
                "preregistered selector is passed to --model"
            ),
            "provider_request_identity": "unverified unless a distinct backend request ID is reported",
            "built_in_instruction_surface": (
                "behavior-affecting model catalog bytes are preregistered by digest and held "
                "unchanged; the remaining compiled instruction surface is unverified"
            ),
            "execution_environment_policy_sha256": environment_policy_artifact["sha256"],
            "sandbox": "named root-deny snapshot-read-only permissions profile",
        },
    )
    governed_snapshot = store.pin_source(
        "pins/snapshot/governed-observation.json",
        workdir / "governed-observation.json",
        "application/json",
    )
    collector_output_schema = store.pin_json(
        "pins/collector/governed-snapshot-schema.json",
        {
            "schema_version": "drupal_agent_readiness.governed_observation_snapshot.v1",
            "required": [
                "schema_version",
                "observation_kind",
                "claim_boundary",
                "inventory_evidence",
            ],
            "inventory_schema": "drupal_agent_readiness.inventory_answer.v1",
            "additional_properties": False,
        },
    )
    permission_policy = store.pin_json(
        "pins/agent/read-only-permissions.json",
        {
            "filesystem": "root denied; minimal runtime read; snapshot workspace read-only",
            "network": False,
            "additional_writable_directories": [],
            "credentials": "all auth.json and canary sentinel paths denied",
        },
    )
    vendor_toolchain = store.pin_json(
        "pins/collector/observed-project-vendor-tree.json",
        {
            "algorithm": "drupal-agent-readiness-tree-v1",
            "scope": "observed_project_vendor_tree",
            "tree_sha256": capture["substrate"]["vendor_tree_sha256"],
            "claim_boundary": (
                "drift detector only; the remaining Drupal bootstrap and host runtime are "
                "trusted and unattested"
            ),
        },
    )
    agent_output_schema = _role_pin(
        store.pin_json(
            "pins/agent/inventory-answer-output-v1.schema.json",
            json.loads(
                FRONTIER_INVENTORY_OUTPUT_SCHEMA_SOURCE.read_text(encoding="utf-8")
            ),
        ),
        "output_schema",
        "agent_visible",
        ["agent", "harness", "auditor"],
    )
    evaluation_rubric = _role_pin(
        store.pin_json(
            "pins/evaluation/inventory-interpretation-rubric.json",
            {
                "kind": "schema_constrained_snapshot_interpretation",
                "agent_output_schema_sha256": agent_output_schema["sha256"],
                "expected_output_provenance": "derived_from_agent_visible_evidence",
                "verdict": "exact inventory evaluator pass and registered shape pass",
            },
        ),
        "evaluation_rubric",
        "withheld_from_agent",
        ["harness", "evaluator", "auditor"],
    )
    evaluator = _role_pin(
        store.pin_source(
            "pins/evaluation/inventory.py", INVENTORY_EVALUATOR_SOURCE, "text/x-python"
        ),
        "evaluator_implementation",
        "withheld_from_agent",
        ["harness", "evaluator", "auditor"],
    )
    scoring = _role_pin(
        store.pin_source("pins/evaluation/result.py", SCORING_SOURCE, "text/x-python"),
        "scoring_implementation",
        "withheld_from_agent",
        ["harness", "evaluator", "auditor"],
    )
    receipt_contract = store.pin_json(
        "pins/evaluation/receipt-contract.json",
        {
            "issuer": "frontier-canary-harness",
            "inputs": ["answer", "ground_truth", "final_state", "tool_log"],
            "output": "evaluator_output",
        },
    )
    no_treatment = store.pin_json(
        "pins/treatment/no-treatment.json",
        {"kind": "none", "description": "frontier observation; no Drupal treatment"},
    )
    generalization = store.pin_bytes(
        "pins/analysis/generalization-boundary.md",
        (
            b"Only the two registered interpretations of this exact governed snapshot by this "
            b"agent, operator envelope, and permissions profile. This is not direct Drupal "
            b"discovery or operation evidence.\n"
        ),
        "text/markdown",
    )
    independence = store.pin_bytes(
        "pins/analysis/independence-basis.md",
        b"The two observations may be correlated and are not population samples.\n",
        "text/markdown",
    )
    sample_rationale = store.pin_bytes(
        "pins/analysis/sample-size-rationale.md",
        b"Two slots are a smoke canary for pipeline operability, not an effect-powered study.\n",
        "text/markdown",
    )
    exclusion_policy = store.pin_bytes(
        "pins/analysis/exclusions.md",
        b"Exclude only preregistered infrastructure failure or budget breach; any exclusion blocks reporting.\n",
        "text/markdown",
    )
    manifest: dict[str, Any] = {
        "schema_version": "drupal_agent_readiness.benchmark_experiment.v1",
        "experiment_id": "inventory-snapshot-interpretation-frontier-canary@v1",
        "registered_at": _iso(registered_at),
        "registration": {
            "manifest_path": "registry/frontier-canary-manifest.json",
            "protocol": protocol,
        },
        "governance": {
            "coverage_claim_id": "coverage.inventory-snapshot-interpretation.frontier-canary",
            "task_family_id": "task-family.inventory-snapshot-interpretation",
            "improvement_record_id": (
                "improvement.inventory-snapshot-interpretation.frontier-canary"
            ),
            "registry_design": {
                "id": "frontier-canary-design",
                "version": "1.0.0",
                "artifact": registry_design,
            },
        },
        "lane": "frontier_observation",
        "task": {
            "id": "interpret.inventory_snapshot",
            "version": "1.0.0",
            "lifecycle_stages": ["understand"],
            "definition": task_definition,
            "prompt": task_prompt,
            "ground_truth": ground_truth,
        },
        "prompt_composition": {
            "algorithm": "canonical_operator_prompt_envelope_v1",
            "renderer": {
                "id": "canonical-prompt-envelope",
                "version": "1.0.0",
                "artifact": renderer,
            },
            "render_inputs": render_inputs,
        },
        "reference_agent_stack": {
            "agent": {"id": "codex-cli", "version": agent_version, "artifact": agent_artifact},
            "model": {
                "provider": model_provider,
                "id": model_id,
                "snapshot": model_snapshot,
                "inference_parameters": inference_parameters,
                "backend_identity_contract": {
                    "mode": "held_selector",
                    "expected_backend_identity": None,
                    "attestation_contract": None,
                    "local_model_artifact": None,
                    "runner_attestation_contract": None,
                    "required_invocation_argument": None,
                },
            },
            "harness": {
                "id": "frontier-canary-harness",
                "version": "1.0.0",
                "artifact": harness_artifact,
            },
            "system_prompt": system_prompt,
            "output_schema": agent_output_schema,
            "tools": [
                {
                    "id": "governed-observation-snapshot",
                    "version": "1.0.0",
                    "artifact": governed_snapshot,
                },
                {
                    "id": "collector-output-schema",
                    "version": "1.0.0",
                    "artifact": collector_output_schema,
                },
                {"id": "executor-adapter", "version": "1.0.0", "artifact": executor_artifact},
                {"id": "process-runner", "version": "1.0.0", "artifact": process_runner_artifact},
                {
                    "id": "observed-project-vendor-tree",
                    "version": "1.0.0",
                    "artifact": vendor_toolchain,
                },
                {
                    "id": "execution-environment-policy",
                    "version": "1.0.0",
                    "artifact": environment_policy_artifact,
                },
                *source_closure_tools,
            ],
            "permissions": {
                "profile_id": CODEX_PERMISSION_PROFILE,
                "policy": permission_policy,
                "allowed_capabilities": ["inline_prompt_input"],
                "denied_capabilities": [
                    "tool_calls",
                    "child_process_creation",
                    "filesystem_read",
                    "filesystem_write",
                    "network",
                    "additional_directory",
                ],
                "network_access": False,
                "filesystem_scope": "none",
            },
        },
        "substrate": {
            "substrate_id": "clean",
            "starting_site_seed": deepcopy(drupal_state["site"]),
            "owner_attestation": None,
            "runtime": runtime,
        },
        "state_capture": {
            "collector": {
                "id": "injected-state-collector",
                "version": "1.0.0",
                "artifact": collector_artifact,
            },
            "protocol": protocol,
        },
        "arms": [
            {
                "arm_id": "observation",
                "role": "observation",
                "treatment": {"id": "no-change", "kind": "none", "artifact": no_treatment},
                "drupal_state": drupal_state,
            }
        ],
        "evaluation": {
            "evaluator": {"id": "inventory-evaluator", "version": "1.0.0", "artifact": evaluator},
            "rubric": {
                "id": "inventory-snapshot-interpretation-rubric",
                "version": "1.0.0",
                "artifact": evaluation_rubric,
            },
            "scoring": {"id": "binary-inventory-success", "version": "1.0.0", "artifact": scoring},
            "verdict_metric_id": "task_success",
            "assurance": {
                "mode": "trusted_execution_receipt",
                "receipt_contract": receipt_contract,
                "trusted_issuer": {
                    "id": "frontier-canary-harness",
                    "version": "1.0.0",
                    "artifact": harness_artifact,
                },
            },
        },
        "budget": {
            "wall_time_ms": 600000,
            "input_tokens": 100000,
            "output_tokens": 20000,
            "tool_calls": 100,
            "human_interventions": 0,
            "cost_microusd": 5000000,
        },
        "cost_measurement": {"mode": "unavailable", "price_schedule": None},
        "outcome_metrics": [
            {
                "metric_id": "task_success",
                "kind": "binary",
                "unit": "proportion",
                "direction": "higher_is_better",
                "denominator_unit": "task_attempt",
                "aggregation": "proportion",
            },
            {
                "metric_id": "persistent_state_drift_rate",
                "kind": "rate",
                "unit": "proportion",
                "direction": "lower_is_better",
                "denominator_unit": "task_attempt",
                "aggregation": "proportion",
            },
        ],
        "comparison": {
            "mode": "unpaired_observation",
            "order_policy": "not_applicable",
            "assignment_seed_sha256": _declared_hash("frontier-canary-order-v1"),
            "allowed_changed_paths": [],
        },
        "execution_plan": {
            "attempt_roster": [
                {
                    "index": index,
                    "pair_id": None,
                    "unit_id": f"frontier-unit-{index:03d}",
                    "executions": [{"slot_id": slot, "arm_id": "observation", "order": 1}],
                }
                for index, slot in enumerate(("frontier-001", "frontier-002"), start=1)
            ],
            "stopping_rule": {
                "kind": "fixed_census",
                "required_resolved_slots": 2,
                "allow_replacements": False,
                "on_exclusion": "no_claim",
            },
        },
        "inference_scope": {
            "kind": "registered_roster_only",
            "target_population": None,
            "generalization_boundary": generalization,
        },
        "sampling_design": {
            "sampling_unit": "included_run",
            "selection_method": "fixed_registered_census",
            "independence_assumption": "correlated_or_unknown",
            "independence_basis": independence,
        },
        "claim_plan": {
            "claim_class": "descriptive",
            "primary_metric_id": "task_success",
            "estimand": "mean_observed_value",
            "planned_denominator": 2,
            "denominator_unit": "included_run",
            "confidence": {
                "method": "none",
                "level": 0.95,
                "tail": "none",
            },
            "minimum_favorable_effect": 0,
            "decision_rule": "descriptive_only",
            "sample_size_rationale": sample_rationale,
            "guardrails": [
                {
                    "guardrail_id": "no-persistent-state-drift",
                    "source": {
                        "kind": "outcome_metric",
                        "metric_id": "persistent_state_drift_rate",
                    },
                    "rules": [{"statistic": "maximum_all", "operator": "at_most", "threshold": 0}],
                },
                {
                    "guardrail_id": "zero-human-interventions",
                    "source": {"kind": "cost", "metric_id": "human_interventions"},
                    "rules": [{"statistic": "maximum_all", "operator": "at_most", "threshold": 0}],
                },
            ],
        },
        "exclusion_policy": {
            "locked_at": _iso(registered_at),
            "policy": exclusion_policy,
            "codes": [
                {"code": "budget_exceeded", "description": "Instrumented budget breach."},
                {"code": "infrastructure_failure", "description": "Harness failure independent of behavior."},
            ],
        },
    }
    return manifest


def _materialize_drupal_state(
    store: _EvidenceStore, capture: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    substrate = capture["substrate"]
    projection = capture["site_projection"]
    core = deepcopy(substrate["core"])
    components = deepcopy(substrate["components"])
    runtime = deepcopy(substrate["runtime"])
    database = store.pin_json(
        "pins/state/site/database-full-dump-digest.json",
        projection["database"],
    )
    active_config = store.pin_json(
        "pins/state/site/active-config-item-digests.json",
        projection["active_config"],
    )
    public_files = store.pin_json(
        "pins/state/site/public-file-content-digests.json",
        projection["public_files"],
    )
    private_files = store.pin_json(
        "pins/state/site/private-file-content-digests.json",
        projection["private_files"],
    )
    fixture_id = substrate["fixture_id"]
    site_manifest_document = {
        "schema_version": "drupal_agent_readiness.site_state_manifest.v1",
        "fixture_id": fixture_id,
        "database_sha256": database["sha256"],
        "active_config_sha256": active_config["sha256"],
        "public_files_sha256": public_files["sha256"],
        "private_files_sha256": private_files["sha256"],
    }
    site_manifest = store.pin_json(
        "pins/state/site/site-state-manifest.json", site_manifest_document
    )
    site = {
        **{key: value for key, value in site_manifest_document.items() if key != "schema_version"},
        "composite_sha256": site_manifest["sha256"],
        "sources": {
            "database": database,
            "active_config": active_config,
            "public_files": public_files,
            "private_files": private_files,
        },
        "manifest": site_manifest,
    }

    composer_lock = store.pin_json(
        "pins/state/code/composer-lock-observation.json",
        {"kind": "composer-lock-observation", "sha256": substrate["composer_lock_sha256"]},
    )
    extensions = store.pin_json(
        "pins/state/code/extensions-observation.json",
        {"kind": "extensions-observation", "components": components},
    )
    codebase = store.pin_json(
        "pins/state/code/agent-visible-workspace-tree.json",
        capture["workspace"],
    )
    code_manifest_document = {
        "schema_version": "drupal_agent_readiness.code_state_manifest.v1",
        "core": core,
        "components": components,
        "composer_lock_sha256": composer_lock["sha256"],
        "extensions_manifest_sha256": extensions["sha256"],
        "codebase_tree_sha256": codebase["sha256"],
    }
    code_manifest = store.pin_json(
        "pins/state/code/code-state-manifest.json", code_manifest_document
    )
    code = {
        **{key: value for key, value in code_manifest_document.items() if key != "schema_version"},
        "sources": {
            "composer_lock": composer_lock,
            "extensions_manifest": extensions,
            "codebase": codebase,
        },
        "manifest": code_manifest,
    }
    return {"code": code, "site": site}, runtime


def _build_run(
    *,
    store: _EvidenceStore,
    manifest: Mapping[str, Any],
    slot_id: str,
    index: int,
    capture: Mapping[str, Any],
    final_capture: Mapping[str, Any],
    execution: Mapping[str, Any],
    argv: Sequence[str],
    started_at: datetime,
    completed_at: datetime,
    now: Clock,
) -> dict[str, Any]:
    if execution.get("returncode") != 0:
        raise FrontierCanaryError(f"{slot_id}: executor returned {execution.get('returncode')!r}")
    observed_selector = execution.get("observed_model_selector")
    if observed_selector is not None and observed_selector != manifest["reference_agent_stack"]["model"]["snapshot"]:
        raise FrontierCanaryError(f"{slot_id}: observed model selector differs from registration")
    answer = execution.get("answer")
    if not isinstance(answer, Mapping):
        raise FrontierCanaryError(f"{slot_id}: executor answer must be a JSON object")
    answer = _canonical_mapping(answer, "executor answer")
    usage = _usage(execution.get("usage"))
    tool_calls = _nonnegative_int(execution.get("tool_calls"), "tool_calls")
    if completed_at < started_at:
        raise FrontierCanaryError(f"{slot_id}: completion precedes start")
    validity_at = _aware_time(now())
    evaluation_started = _aware_time(now())
    shape_failures = _inventory_shape_failures(answer)
    evaluation = evaluate_inventory(deepcopy(capture["inventory"]), deepcopy(answer))
    passed = not shape_failures and evaluation.passed
    evaluation_completed = _aware_time(now())
    recorded_at = _aware_time(now())
    _assert_monotonic(
        started_at,
        completed_at,
        validity_at,
        evaluation_started,
        evaluation_completed,
        recorded_at,
    )
    prefix = f"run-{slot_id}"
    arm = manifest["arms"][0]
    timestamps = {
        "started_at": _iso(started_at),
        "completed_at": _iso(completed_at),
        "evaluation_started_at": _iso(evaluation_started),
        "evaluation_completed_at": _iso(evaluation_completed),
        "recorded_at": _iso(recorded_at),
    }
    costs = {
        "source": "harness_instrumentation",
        "cost_status": "unavailable",
        "price_schedule_sha256": None,
        "measurement_artifact_id": f"{prefix}-cost",
        "wall_time_ms": max(0, int((completed_at - started_at).total_seconds() * 1000)),
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cached_input_tokens": usage["cached_input_tokens"],
        **(
            {"reasoning_output_tokens": usage["reasoning_output_tokens"]}
            if "reasoning_output_tokens" in usage
            else {}
        ),
        "tool_calls": tool_calls,
        "human_interventions": 0,
        "cost_microusd": None,
    }
    validity = {
        "status": "included",
        "exclusion_code": None,
        "decided_at": _iso(validity_at),
        "decision_source": "automatic_preregistered_gate",
        "decision_basis_artifact_id": f"{prefix}-validity",
    }
    retained_tool_events = execution.get("tool_events")
    if not isinstance(retained_tool_events, list):
        raise FrontierCanaryError(f"{slot_id}: retained tool-event trace is missing")
    if retained_tool_events:
        raise FrontierCanaryError(
            f"{slot_id}: answer-only snapshot interpretation cannot retain tool events"
        )
    events = [
        {
            "sequence": 1,
            "phase": "understand",
            "event_type": "schema_constrained_answer_evaluation",
            "started_at": _iso(completed_at),
            "ended_at": _iso(completed_at),
            "source": "harness_trace",
            "source_artifact_id": f"{prefix}-behavior",
            "result": "success" if passed else "failure",
            "failure_code": None if passed else "inventory_evaluator_failed",
        }
    ]
    failures = [event for event in events if event["result"] == "failure"]
    successes = [event for event in events if event["result"] == "success"]
    skipped = [event for event in events if event["result"] == "skipped"]
    summary = {
        "event_count": len(events),
        "phases_observed": ["understand"],
        "successful_phases": ["understand"] if successes else [],
        "failed_phases": ["understand"] if failures else [],
        "skipped_phases": ["understand"] if skipped else [],
        "failure_count": len(failures),
        "recovery_attempted": False,
        "recovery_succeeded": None,
    }
    persistent_state_drift = int(
        capture["site_projection"] != final_capture["site_projection"]
        or capture["workspace"] != final_capture["workspace"]
    )
    outcomes = {
        "evaluator_passed": passed,
        "evaluated_by_sha256": manifest["evaluation"]["evaluator"]["artifact"]["sha256"],
        "evaluator_artifact_id": f"{prefix}-evaluator",
        "metrics": [
            {
                "metric_id": "task_success",
                "numerator": int(passed),
                "denominator": 1,
                "value": float(passed),
                "unit": "proportion",
                "source_artifact_id": f"{prefix}-evaluator",
            },
            {
                "metric_id": "persistent_state_drift_rate",
                "numerator": persistent_state_drift,
                "denominator": 1,
                "value": float(persistent_state_drift),
                "unit": "proportion",
                "source_artifact_id": f"{prefix}-evaluator",
            },
        ],
    }
    state_capture = {
        "collector_sha256": manifest["state_capture"]["collector"]["artifact"]["sha256"],
        "starting": {"invocation_id": f"{prefix}-state-start", "captured_at": _iso(started_at)},
        "final": {"invocation_id": f"{prefix}-state-final", "captured_at": _iso(completed_at)},
    }
    claim = manifest["claim_plan"]
    run: dict[str, Any] = {
        "schema_version": "drupal_agent_readiness.benchmark_run.v1",
        "run_id": prefix,
        "experiment_id": manifest["experiment_id"],
        "experiment_manifest_sha256": canonical_sha256(manifest),
        "governance": deepcopy(manifest["governance"]),
        "lane": "frontier_observation",
        "task": deepcopy(manifest["task"]),
        "arm": {
            "arm_id": arm["arm_id"],
            "role": "observation",
            "treatment_sha256": arm["treatment"]["artifact"]["sha256"],
            "drupal_state": deepcopy(arm["drupal_state"]),
        },
        "final_drupal_state": deepcopy(arm["drupal_state"]),
        "attempt": {
            "roster_slot_id": slot_id,
            "index": index,
            "unit_id": f"frontier-unit-{index:03d}",
            "pair_id": None,
            "order_in_pair": None,
        },
        "timestamps": timestamps,
        "agent_stack": deepcopy(manifest["reference_agent_stack"]),
        "substrate": deepcopy(manifest["substrate"]),
        "state_capture": state_capture,
        "evaluation": deepcopy(manifest["evaluation"]),
        "budget": deepcopy(manifest["budget"]),
        "costs": costs,
        "validity": validity,
        "behavior_events": events,
        "behavior_summary": summary,
        "artifacts": [],
        "outcomes": outcomes,
        "claim_context": {
            "claim_class": claim["claim_class"],
            "primary_metric_id": claim["primary_metric_id"],
            "estimand": claim["estimand"],
            "planned_denominator": claim["planned_denominator"],
            "denominator_unit": claim["denominator_unit"],
            "confidence": deepcopy(claim["confidence"]),
            "minimum_favorable_effect": claim["minimum_favorable_effect"],
            "decision_rule": claim["decision_rule"],
            "inference_scope": deepcopy(manifest["inference_scope"]),
            "sampling_design": deepcopy(manifest["sampling_design"]),
            "guardrails": deepcopy(claim["guardrails"]),
        },
    }
    _materialize_run_artifacts(
        store=store,
        run=run,
        manifest=manifest,
        answer=answer,
        execution=execution,
        argv=argv,
        shape_failures=shape_failures,
    )
    return run


def _validated_attempt_bundle(
    *,
    root: Path,
    execution: Mapping[str, Any],
    manifest: Mapping[str, Any],
    run_id: str,
    slot_id: str,
    argv: Sequence[str],
) -> dict[str, Any]:
    reference = execution.get("attempt_receipt")
    if not isinstance(reference, Mapping):
        raise FrontierCanaryError(f"{slot_id}: executor omitted retained attempt receipt")

    def retained_pin(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise FrontierCanaryError(f"{slot_id}: {label} pin is missing")
        uri = value.get("uri")
        digest = value.get("sha256")
        size = value.get("byte_size")
        if not isinstance(uri, str) or not uri or "\\" in uri:
            raise FrontierCanaryError(f"{slot_id}: {label} URI is unsafe")
        path = (root / uri).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise FrontierCanaryError(f"{slot_id}: {label} escapes artifact root") from error
        if not path.is_file():
            raise FrontierCanaryError(f"{slot_id}: retained {label} is missing")
        if not isinstance(digest, str) or file_sha256(path) != digest:
            raise FrontierCanaryError(f"{slot_id}: retained {label} hash mismatch")
        if type(size) is not int or path.stat().st_size != size:
            raise FrontierCanaryError(f"{slot_id}: retained {label} size mismatch")
        return {"uri": uri, "sha256": digest, "byte_size": size, "path": path}

    receipt_pin = retained_pin(reference, "attempt receipt")
    try:
        receipt = load_canonical_json_file(receipt_pin["path"])
    except (OSError, ValueError) as error:
        raise FrontierCanaryError(f"{slot_id}: attempt receipt is not canonical JSON") from error
    if not isinstance(receipt, Mapping):
        raise FrontierCanaryError(f"{slot_id}: attempt receipt is not an object")
    expected = {
        "schema_version": "drupal_agent_readiness.frontier_attempt_receipt.v1",
        "run_id": run_id,
        "roster_slot_id": slot_id,
        "argv": list(argv),
        "status": "succeeded",
        "returncode": 0,
        "timed_out": False,
        "provider_request_id": None,
        "provider_request_id_status": "unverified_not_reported",
    }
    expected_receipt_keys = {
        *expected,
        "attempt_id",
        "thread_id",
        "environment_policy_sha256",
        "runtime_home_verification",
        "process_containment",
        "stdout_artifact_id",
        "stdout_sha256",
        "stderr_artifact_id",
        "stderr_sha256",
    }
    if set(receipt) != expected_receipt_keys:
        raise FrontierCanaryError(f"{slot_id}: attempt receipt keys are not exact")
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise FrontierCanaryError(f"{slot_id}: attempt receipt {field} is not bound to the run")
    home = receipt.get("runtime_home_verification")
    if not isinstance(home, Mapping) or home != {
        "before_home_mode": "0o700",
        "after_home_mode": "0o700",
        "before_home_identity_verified": True,
        "after_home_identity_verified": True,
        "before_home_mode_verified": True,
        "after_home_mode_verified": True,
        "before_layout_verified": True,
        "after_layout_verified": True,
        "before_layout_sha256": home.get("before_layout_sha256")
        if isinstance(home, Mapping)
        else None,
        "after_layout_sha256": home.get("after_layout_sha256")
        if isinstance(home, Mapping)
        else None,
        "before_layout_document": home.get("before_layout_document")
        if isinstance(home, Mapping)
        else None,
        "after_layout_document": home.get("after_layout_document")
        if isinstance(home, Mapping)
        else None,
        "before_auth_reference_verified": True,
        "after_auth_reference_verified": True,
        "before_profile_regular_file_verified": True,
        "after_profile_regular_file_verified": True,
        "before_sentinel_regular_file_verified": True,
        "after_sentinel_regular_file_verified": True,
        "before_forbidden_entries": [],
        "after_forbidden_entries": [],
        "before_system_skills_verified": True,
        "after_system_skills_verified": True,
        "system_skills_tree_sha256": home.get("system_skills_tree_sha256") if isinstance(home, Mapping) else None,
        "before_permissions_profile_sha256": home.get(
            "before_permissions_profile_sha256"
        ) if isinstance(home, Mapping) else None,
        "after_permissions_profile_sha256": home.get(
            "after_permissions_profile_sha256"
        ) if isinstance(home, Mapping) else None,
        "before_sentinel_sha256": home.get("before_sentinel_sha256")
        if isinstance(home, Mapping)
        else None,
        "after_sentinel_sha256": home.get("after_sentinel_sha256")
        if isinstance(home, Mapping)
        else None,
    }:
        raise FrontierCanaryError(f"{slot_id}: runtime-home/system-skill verification failed")
    if (
        not _SHA256.fullmatch(str(home.get("system_skills_tree_sha256")))
        or not _SHA256.fullmatch(str(home.get("before_layout_sha256")))
        or not _SHA256.fullmatch(str(home.get("after_layout_sha256")))
        or not runtime_home_layout_document_valid(home.get("before_layout_document"))
        or not runtime_home_layout_document_valid(home.get("after_layout_document"))
        or home["before_layout_document"]["tree_sha256"]
        != home.get("before_layout_sha256")
        or home["after_layout_document"]["tree_sha256"]
        != home.get("after_layout_sha256")
    ):
        raise FrontierCanaryError(f"{slot_id}: system-skill tree hash is missing")
    inference_path = root / manifest["reference_agent_stack"]["model"]["inference_parameters"]["uri"]
    inference = load_canonical_json_file(inference_path)
    if receipt.get("environment_policy_sha256") != inference.get(
        "execution_environment_policy_sha256"
    ):
        raise FrontierCanaryError(f"{slot_id}: attempt environment policy is not preregistered")
    policy_tool = next(
        (
            tool
            for tool in manifest["reference_agent_stack"]["tools"]
            if tool["id"] == "execution-environment-policy"
        ),
        None,
    )
    if policy_tool is None:
        raise FrontierCanaryError(f"{slot_id}: execution environment policy artifact is missing")
    policy = load_canonical_json_file(root / policy_tool["artifact"]["uri"])
    model_cache_contract = (
        policy.get("model_cache") if isinstance(policy, Mapping) else None
    )
    if (
        not model_cache_contract_valid(model_cache_contract)
        or model_cache_contract["selected_model_selector"]
        != manifest["reference_agent_stack"]["model"]["snapshot"]
    ):
        raise FrontierCanaryError(
            f"{slot_id}: behavior-affecting model cache is not preregistered"
        )
    process_policy = policy.get("process_containment") if isinstance(policy, Mapping) else None
    process_binary = (
        Path(str(process_policy.get("sandbox_binary")))
        if isinstance(process_policy, Mapping)
        else Path("/nonexistent")
    )
    validated_process_policy = validate_frontier_process_containment_policy(
        process_policy,
        network_sandbox_binary=process_binary,
    )
    process_policy_sha256 = canonical_sha256(validated_process_policy)
    process_receipt = receipt.get("process_containment")
    expected_outer_argv = [
        validated_process_policy["sandbox_binary"],
        "-p",
        FRONTIER_PROCESS_CONTAINMENT_PROFILE,
        *list(argv),
    ]
    if not isinstance(process_receipt, Mapping) or dict(process_receipt) != {
        "status": "verified",
        "policy_sha256": process_policy_sha256,
        "sandbox_sha256": validated_process_policy["sandbox_sha256"],
        "child_process_creation_denied": True,
        "inner_argv": list(argv),
        "outer_argv": expected_outer_argv,
    }:
        raise FrontierCanaryError(f"{slot_id}: process-containment receipt is not exact")
    expected_system_tree = (
        policy.get("system_skills_preflight", {}).get("manifest", {}).get("tree_sha256")
        if isinstance(policy, Mapping)
        else None
    )
    if home.get("system_skills_tree_sha256") != expected_system_tree:
        raise FrontierCanaryError(f"{slot_id}: system-skill tree differs from preregistration")
    expected_profile = policy.get("permissions_preflight", {}).get("profile_sha256")
    expected_sentinel = policy.get("permissions_preflight", {}).get("sentinel_sha256")
    if (
        home.get("before_permissions_profile_sha256") != expected_profile
        or home.get("after_permissions_profile_sha256") != expected_profile
        or home.get("before_sentinel_sha256") != expected_sentinel
        or home.get("after_sentinel_sha256") != expected_sentinel
    ):
        raise FrontierCanaryError(
            f"{slot_id}: permissions profile/sentinel differs from preregistration"
        )
    system_preflight = policy.get("system_skills_preflight")
    system_manifest = (
        system_preflight.get("manifest")
        if isinstance(system_preflight, Mapping)
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
    if not isinstance(auth_path, str) or not all(
        runtime_home_layout_semantically_valid(
            home.get(f"{phase}_layout_document"),
            phase=phase,
            system_manifest=system_manifest,
            auth_target_path_sha256="sha256:"
            + hashlib.sha256(auth_path.encode()).hexdigest(),
            codex_target_path_sha256="sha256:"
            + hashlib.sha256(str(Path(argv[0]).resolve()).encode()).hexdigest(),
            codex_file_sha256=manifest["reference_agent_stack"]["agent"][
                "artifact"
            ]["sha256"],
            model_cache_contract=model_cache_contract,
        )
        for phase in ("before", "after")
    ):
        raise FrontierCanaryError(
            f"{slot_id}: runtime-home layout does not match the registered path contract"
        )
    stdout_pin = retained_pin(reference.get("stdout"), "attempt stdout")
    stderr_pin = retained_pin(reference.get("stderr"), "attempt stderr")
    if (
        receipt.get("stdout_sha256") != stdout_pin["sha256"]
        or receipt.get("stderr_sha256") != stderr_pin["sha256"]
        or receipt.get("stdout_artifact_id") != f"{run_id}-attempt-stdout"
        or receipt.get("stderr_artifact_id") != f"{run_id}-attempt-stderr"
    ):
        raise FrontierCanaryError(f"{slot_id}: attempt raw-log binding mismatch")
    retained = _parse_retained_codex_jsonl(stdout_pin["path"], slot_id=slot_id)
    if receipt.get("thread_id") != retained["thread_id"]:
        raise FrontierCanaryError(
            f"{slot_id}: attempt receipt thread_id is not bound to retained JSONL"
        )
    return {
        "receipt": receipt,
        "receipt_pin": receipt_pin,
        "stdout_pin": stdout_pin,
        "stderr_pin": stderr_pin,
        "retained_execution": retained,
    }


def _parse_retained_codex_jsonl(path: Path, *, slot_id: str) -> dict[str, Any]:
    try:
        text = path.read_bytes().decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as error:
        raise FrontierCanaryError(f"{slot_id}: retained Codex stdout is not UTF-8") from error
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        event = parse_json_without_duplicate_keys(
            line,
            label=f"{slot_id}: retained Codex JSONL line {line_number}",
        )
        if not isinstance(event, dict):
            raise FrontierCanaryError(
                f"{slot_id}: retained Codex JSONL line {line_number} is not an object"
            )
        events.append(event)
    if len(events) < 4:
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL is shorter than the successful event grammar"
        )
    if (
        set(events[0]) != {"type", "thread_id"}
        or events[0].get("type") != "thread.started"
        or dict(events[1]) != {"type": "turn.started"}
        or set(events[-1]) != {"type", "usage"}
        or events[-1].get("type") != "turn.completed"
    ):
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL violates ordered successful-turn grammar"
        )
    allowed_event_types = {
        "thread.started",
        "turn.started",
        "item.started",
        "item.completed",
        "turn.completed",
    }
    if any(event.get("type") not in allowed_event_types for event in events):
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL contains a failed or unknown event"
        )
    if [index for index, event in enumerate(events) if event.get("type") == "thread.started"] != [0]:
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL requires exactly one thread.started identity in the leading position"
        )
    if [index for index, event in enumerate(events) if event.get("type") == "turn.started"] != [1]:
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL requires exactly one ordered turn.started event"
        )
    if [index for index, event in enumerate(events) if event.get("type") == "turn.completed"] != [
        len(events) - 1
    ]:
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL requires exactly one turn.completed event"
        )
    if any(
        set(event) != {"type", "item"}
        or not isinstance(event.get("item"), Mapping)
        for event in events
        if event.get("type") in {"item.started", "item.completed"}
    ):
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL has an ambiguous item envelope"
        )
    started = [
        event.get("thread_id")
        for event in events
        if event.get("type") == "thread.started"
    ]
    if len(started) != 1 or not isinstance(started[0], str) or not started[0]:
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL requires exactly one thread.started identity"
        )
    all_thread_ids = {
        value
        for event in events
        for value in (event.get("thread_id"),)
        if isinstance(value, str) and value
    }
    if all_thread_ids != {started[0]}:
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL contains multiple thread identities"
        )
    messages: list[str] = []
    for event in events:
        item = event.get("item")
        if (
            event.get("type") != "item.completed"
            or not isinstance(item, Mapping)
            or item.get("type") != "agent_message"
        ):
            continue
        content = item.get("text") or item.get("content")
        if isinstance(content, str):
            messages.append(content)
    agent_events = [
        (index, event, event.get("item"))
        for index, event in enumerate(events)
        if isinstance(event.get("item"), Mapping)
        and event["item"].get("type") == "agent_message"
    ]
    exact_agent_message = bool(
        len(agent_events) == 1
        and agent_events[0][0] == len(events) - 2
        and agent_events[0][1].get("type") == "item.completed"
        and set(agent_events[0][1]) == {"type", "item"}
        and set(agent_events[0][2]) == {"id", "type", "text"}
        and isinstance(agent_events[0][2].get("id"), str)
        and bool(agent_events[0][2].get("id"))
        and isinstance(agent_events[0][2].get("text"), str)
    )
    if not messages or not exact_agent_message:
        raise FrontierCanaryError(f"{slot_id}: retained Codex JSONL has no agent answer")
    reasoning_events = [
        (event, event.get("item"))
        for event in events
        if isinstance(event.get("item"), Mapping)
        and event["item"].get("type") == "reasoning"
    ]
    if any(
        event.get("type") != "item.completed"
        or set(event) != {"type", "item"}
        or set(item) != {"id", "type", "text"}
        or not isinstance(item.get("id"), str)
        or not item.get("id")
        or not isinstance(item.get("text"), str)
        for event, item in reasoning_events
    ):
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL has an ambiguous reasoning item"
        )
    answer = parse_json_without_duplicate_keys(
        messages[-1],
        label=f"{slot_id}: retained Codex agent answer",
    )
    if not isinstance(answer, Mapping):
        raise FrontierCanaryError(f"{slot_id}: retained Codex answer is not an object")
    completed_turns = [event for event in events if event.get("type") == "turn.completed"]
    if len(completed_turns) != 1:
        raise FrontierCanaryError(
            f"{slot_id}: retained Codex JSONL requires exactly one turn.completed event"
        )
    usage_value = completed_turns[0].get("usage")
    if not isinstance(usage_value, Mapping):
        raise FrontierCanaryError(
            f"{slot_id}: sole turn.completed event lacks usage"
        )
    usage = _usage(usage_value)
    completed_tools: list[tuple[int, Mapping[str, Any], str]] = []
    identified_lifecycles: dict[str, list[tuple[int, str, Mapping[str, Any]]]] = {}
    for event_index, event in enumerate(events):
        item = event.get("item")
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type", ""))
        is_tool = item_type not in {"agent_message", "reasoning"}
        if not is_tool:
            continue
        invocation_fields = {
            key: item[key]
            for key in ("command", "cmd", "arguments", "input", "name")
            if key in item
        }
        if invocation_fields and _FORBIDDEN_DIRECT_HOST_TOOL.search(
            json.dumps(invocation_fields, sort_keys=True, default=str)
        ):
            raise FrontierCanaryError(
                f"{slot_id}: retained tool attempted forbidden direct DDEV/Docker access"
            )
        lifecycle = str(event.get("type", ""))
        lifecycle_kind = (
            "started"
            if lifecycle.endswith(".started")
            else "completed"
            if lifecycle.endswith(".completed")
            else None
        )
        if lifecycle_kind is None:
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            identified_lifecycles.setdefault(item_id, []).append(
                (event_index, lifecycle_kind, item)
            )
        else:
            if lifecycle_kind == "started":
                raise FrontierCanaryError(
                    f"{slot_id}: anonymous retained tool start has no bindable completion"
                )
            completed_tools.append((event_index, item, lifecycle))

    for item_id, lifecycle_events in identified_lifecycles.items():
        starts = [entry for entry in lifecycle_events if entry[1] == "started"]
        completions = [entry for entry in lifecycle_events if entry[1] == "completed"]
        if len(starts) > 1 or len(completions) > 1:
            raise FrontierCanaryError(
                f"{slot_id}: duplicate retained tool lifecycle event for {item_id}"
            )
        if starts and not completions:
            raise FrontierCanaryError(
                f"{slot_id}: retained tool start for {item_id} has no completion"
            )
        if starts and completions and starts[0][0] > completions[0][0]:
            raise FrontierCanaryError(
                f"{slot_id}: retained tool lifecycle for {item_id} is out of order"
            )
        if completions:
            index, _, completed_item = completions[0]
            completed_tools.append((index, completed_item, "item.completed"))

    tool_records: list[dict[str, Any]] = []
    for _, item, lifecycle in sorted(completed_tools, key=lambda entry: entry[0]):
        item_type = str(item.get("type", ""))
        exit_code = item.get("exit_code")
        failed = (
            item.get("status") in {"failed", "error"}
            or (type(exit_code) is int and exit_code != 0)
            or "fail" in lifecycle
            or "error" in lifecycle
        )
        tool_records.append(
            {
                "event_type": f"retained_{item_type}",
                "result": "failure" if failed else "success",
                "failure_code": "tool_failure" if failed else None,
            }
        )
    if tool_records:
        raise FrontierCanaryError(
            f"{slot_id}: registered inline-snapshot task forbids every tool call"
        )
    return {
        "answer": _canonical_mapping(answer, "retained Codex answer"),
        "provider_request_id": None,
        "provider_request_id_status": "unverified_not_reported",
        "thread_id": started[0],
        "returncode": 0,
        "usage": usage,
        "tool_calls": len(tool_records),
        "tool_events": tool_records,
    }


def _retained_codex_execution(
    attempt: Mapping[str, Any], *, slot_id: str
) -> dict[str, Any]:
    retained = attempt.get("retained_execution")
    if not isinstance(retained, Mapping):
        raise FrontierCanaryError(f"{slot_id}: retained execution semantics are missing")
    return deepcopy(dict(retained))


def _materialize_run_artifacts(
    *,
    store: _EvidenceStore,
    run: dict[str, Any],
    manifest: Mapping[str, Any],
    answer: Mapping[str, Any],
    execution: Mapping[str, Any],
    argv: Sequence[str],
    shape_failures: Sequence[str],
) -> None:
    prefix = run["run_id"]
    base = f"runs/{prefix}/artifacts"

    attempt = _validated_attempt_bundle(
        root=store.root,
        execution=execution,
        manifest=manifest,
        run_id=prefix,
        slot_id=run["attempt"]["roster_slot_id"],
        argv=argv,
    )

    def add(kind: str, artifact_id: str, payload: bytes, media_type: str) -> dict[str, Any]:
        suffix = ".json" if media_type == "application/json" else ".txt"
        relative = f"{base}/{artifact_id}{suffix}"
        path = store.write_bytes(relative, payload)
        artifact = {
            "artifact_id": artifact_id,
            "kind": kind,
            "uri": relative,
            "sha256": file_sha256(path),
            "media_type": media_type,
            "byte_size": path.stat().st_size,
        }
        run["artifacts"].append(artifact)
        return artifact

    def add_retained(
        kind: str,
        artifact_id: str,
        pin: Mapping[str, Any],
        media_type: str,
    ) -> dict[str, Any]:
        artifact = {
            "artifact_id": artifact_id,
            "kind": kind,
            "uri": pin["uri"],
            "sha256": pin["sha256"],
            "media_type": media_type,
            "byte_size": pin["byte_size"],
        }
        run["artifacts"].append(artifact)
        return artifact

    prompt_bytes = _prompt_bytes(store.root, manifest)
    render_inputs_bytes = (
        store.root / manifest["prompt_composition"]["render_inputs"]["uri"]
    ).read_bytes()
    retained_stdout = attempt["stdout_pin"]["path"].read_bytes()
    tool_log = (
        canonical_json_bytes(
            {
                "run_id": prefix,
                "thread_id": execution["thread_id"],
                "provider_request_id": execution["provider_request_id"],
                "provider_request_id_status": execution[
                    "provider_request_id_status"
                ],
                "tool_calls": run["costs"]["tool_calls"],
                "semantic_source": "retained_attempt_stdout",
                "retained_stdout_sha256": attempt["stdout_pin"]["sha256"],
            }
        )
        + b"\n"
        + retained_stdout
    )
    add("prompt", f"{prefix}-prompt", prompt_bytes, "application/json")
    add("render_inputs", f"{prefix}-render-inputs", render_inputs_bytes, "application/json")
    add(
        "transcript",
        f"{prefix}-transcript",
        (
            f"run_id={prefix}\nargv={json.dumps(list(argv))}\n"
            f"attempt_receipt={attempt['receipt_pin']['uri']}\n"
            f"answer_shape_failures={json.dumps(list(shape_failures))}\n"
        ).encode("utf-8"),
        "text/plain",
    )
    add_retained(
        "attempt_receipt",
        f"{prefix}-attempt-receipt",
        attempt["receipt_pin"],
        "application/json",
    )
    add_retained(
        "attempt_stdout",
        attempt["receipt"]["stdout_artifact_id"],
        attempt["stdout_pin"],
        "text/plain",
    )
    add_retained(
        "attempt_stderr",
        attempt["receipt"]["stderr_artifact_id"],
        attempt["stderr_pin"],
        "text/plain",
    )
    add("tool_log", f"{prefix}-tools", tool_log, "application/jsonl")
    add("answer", f"{prefix}-answer", canonical_json_bytes(answer), "application/json")

    state = run["state_capture"]
    starting_state = {
        "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
        "run_id": prefix,
        "moment": "starting",
        "arm_id": run["arm"]["arm_id"],
        "roster_slot_id": run["attempt"]["roster_slot_id"],
        "unit_id": run["attempt"]["unit_id"],
        "collector_sha256": state["collector_sha256"],
        "collector_invocation_id": state["starting"]["invocation_id"],
        "captured_at": state["starting"]["captured_at"],
        "drupal_state": run["arm"]["drupal_state"],
    }
    final_state = {
        "schema_version": "drupal_agent_readiness.drupal_state_attestation.v1",
        "run_id": prefix,
        "moment": "final",
        "arm_id": run["arm"]["arm_id"],
        "roster_slot_id": run["attempt"]["roster_slot_id"],
        "unit_id": run["attempt"]["unit_id"],
        "collector_sha256": state["collector_sha256"],
        "collector_invocation_id": state["final"]["invocation_id"],
        "captured_at": state["final"]["captured_at"],
        "drupal_state": run["final_drupal_state"],
    }
    semantic = {
        "cost_trace": run["costs"],
        "behavior_trace": {"events": run["behavior_events"], "summary": run["behavior_summary"]},
        "evaluator_output": run["outcomes"],
        "validity_decision": run["validity"],
        "starting_state": starting_state,
        "final_state": final_state,
    }
    semantic_ids = {
        "cost_trace": f"{prefix}-cost",
        "behavior_trace": f"{prefix}-behavior",
        "evaluator_output": f"{prefix}-evaluator",
        "validity_decision": f"{prefix}-validity",
        "starting_state": f"{prefix}-starting",
        "final_state": f"{prefix}-final",
    }
    for kind, document in semantic.items():
        add(kind, semantic_ids[kind], canonical_json_bytes(document), "application/json")

    by_kind = {artifact["kind"]: artifact for artifact in run["artifacts"]}
    delivery = {
        "source": "harness_instrumentation",
        "invocation_id": f"{prefix}-prompt-delivery",
        "delivered_at": run["timestamps"]["started_at"],
        "task_id": run["task"]["id"],
        "task_version": run["task"]["version"],
        "task_prompt_sha256": run["task"]["prompt"]["sha256"],
        "system_prompt_sha256": run["agent_stack"]["system_prompt"]["sha256"],
        "renderer_sha256": manifest["prompt_composition"]["renderer"]["artifact"]["sha256"],
        "render_inputs_artifact_id": by_kind["render_inputs"]["artifact_id"],
        "render_inputs_sha256": by_kind["render_inputs"]["sha256"],
        "rendered_prompt_artifact_id": by_kind["prompt"]["artifact_id"],
        "rendered_prompt_sha256": by_kind["prompt"]["sha256"],
        "receipt_artifact_id": f"{prefix}-prompt-receipt",
        "recipient": {
            "agent_id": run["agent_stack"]["agent"]["id"],
            "model_provider": run["agent_stack"]["model"]["provider"],
            "model_id": run["agent_stack"]["model"]["id"],
            "model_snapshot": run["agent_stack"]["model"]["snapshot"],
        },
    }
    run["prompt_delivery"] = delivery
    prompt_receipt = {
        "schema_version": "drupal_agent_readiness.prompt_delivery_receipt.v1",
        "run_id": prefix,
        **delivery,
    }
    add(
        "prompt_receipt",
        delivery["receipt_artifact_id"],
        canonical_json_bytes(prompt_receipt),
        "application/json",
    )
    by_kind = {artifact["kind"]: artifact for artifact in run["artifacts"]}
    model = run["agent_stack"]["model"]
    model_identity_receipt = {
        "status": "unverified_held_selector",
        "source": "declared_selector_only",
        "model_provider": model["provider"],
        "model_id": model["id"],
        "declared_selector": model["snapshot"],
        "backend_identity": None,
        "provider_request_id": execution["provider_request_id"],
        "attestation_contract_sha256": None,
        "local_model_artifact_sha256": None,
        "runner_attestation_contract_sha256": None,
        "observed_at": run["timestamps"]["completed_at"],
        "receipt_artifact_id": f"{prefix}-model-identity-receipt",
    }
    run["model_identity_receipt"] = model_identity_receipt
    add(
        "model_identity_receipt",
        model_identity_receipt["receipt_artifact_id"],
        canonical_json_bytes(
            {
                "schema_version": (
                    "drupal_agent_readiness.model_identity_receipt.v1"
                ),
                "run_id": prefix,
                **model_identity_receipt,
            }
        ),
        "application/json",
    )
    by_kind = {artifact["kind"]: artifact for artifact in run["artifacts"]}
    execution_receipt = {
        "source": "harness_instrumentation",
        "invocation_id": attempt["receipt"]["attempt_id"],
        "provider_request_id": execution["provider_request_id"],
        "provider_request_id_status": execution["provider_request_id_status"],
        "argv": list(argv),
        "thread_id": execution["thread_id"],
        "started_at": run["timestamps"]["started_at"],
        "completed_at": run["timestamps"]["completed_at"],
        "roster_slot_id": run["attempt"]["roster_slot_id"],
        "harness_sha256": run["agent_stack"]["harness"]["artifact"]["sha256"],
        "prompt_receipt_sha256": by_kind["prompt_receipt"]["sha256"],
        "artifact_hashes": {
            kind: by_kind[kind]["sha256"]
            for kind in (
                "prompt",
                "render_inputs",
                "transcript",
                "tool_log",
                "answer",
                "starting_state",
                "final_state",
                "cost_trace",
                "behavior_trace",
                "validity_decision",
                "attempt_receipt",
                "model_identity_receipt",
            )
        },
        "receipt_artifact_id": f"{prefix}-execution-receipt",
    }
    run["execution_receipt"] = execution_receipt
    add(
        "execution_receipt",
        execution_receipt["receipt_artifact_id"],
        canonical_json_bytes(
            {
                "schema_version": "drupal_agent_readiness.execution_receipt.v1",
                "run_id": prefix,
                **execution_receipt,
            }
        ),
        "application/json",
    )
    by_kind = {artifact["kind"]: artifact for artifact in run["artifacts"]}
    issuer = run["evaluation"]["assurance"]["trusted_issuer"]
    evaluator_receipt = {
        "source": "independent_evaluator_harness",
        "issuer_id": issuer["id"],
        "issuer_version": issuer["version"],
        "issuer_sha256": issuer["artifact"]["sha256"],
        "invocation_id": f"{prefix}-evaluation",
        "started_at": run["timestamps"]["evaluation_started_at"],
        "completed_at": run["timestamps"]["evaluation_completed_at"],
        "exit_code": 0,
        "input_hashes": {
            "answer": by_kind["answer"]["sha256"],
            "ground_truth": run["task"]["ground_truth"]["sha256"],
            "final_state": by_kind["final_state"]["sha256"],
            "tool_log": by_kind["tool_log"]["sha256"],
        },
        "evaluator_sha256": run["evaluation"]["evaluator"]["artifact"]["sha256"],
        "output_artifact_id": by_kind["evaluator_output"]["artifact_id"],
        "output_sha256": by_kind["evaluator_output"]["sha256"],
        "receipt_artifact_id": f"{prefix}-evaluator-receipt",
    }
    run["evaluator_receipt"] = evaluator_receipt
    add(
        "evaluator_receipt",
        evaluator_receipt["receipt_artifact_id"],
        canonical_json_bytes(
            {
                "schema_version": "drupal_agent_readiness.evaluator_receipt.v1",
                "run_id": prefix,
                **evaluator_receipt,
            }
        ),
        "application/json",
    )


def _registered_host_tool(
    environment_policy: Mapping[str, Any], name: str
) -> tuple[Path, str]:
    host_tools = environment_policy.get("host_tools")
    tool = host_tools.get(name) if isinstance(host_tools, Mapping) else None
    path_value = tool.get("path") if isinstance(tool, Mapping) else None
    expected_sha256 = tool.get("sha256") if isinstance(tool, Mapping) else None
    if (
        not isinstance(path_value, str)
        or not Path(path_value).is_absolute()
        or not isinstance(expected_sha256, str)
        or not _SHA256.fullmatch(expected_sha256)
    ):
        raise FrontierCanaryError(f"Execution environment lacks an exact {name} binary pin")
    path = Path(path_value).resolve()
    if not path.is_file() or file_sha256(path) != expected_sha256:
        raise FrontierCanaryError(f"Pinned {name} binary bytes do not match the policy")
    return path, expected_sha256


def _assert_host_tool_identity(path: Path, expected_sha256: str, name: str) -> None:
    if not path.is_file() or file_sha256(path) != expected_sha256:
        raise FrontierCanaryError(f"Pinned {name} binary changed during execution")


def _executed_source_paths(
    collector: Collector, executor: Executor
) -> dict[str, Path]:
    paths = dict(_STATIC_EXECUTED_SOURCE_PATHS)
    paths["collector-adapter"] = _callable_source_path(collector, "collector")
    paths["executor-adapter"] = _callable_source_path(executor, "executor")
    return {name: path.resolve() for name, path in paths.items()}


def _snapshot_source_hashes(paths: Mapping[str, Path]) -> dict[str, str]:
    if not paths or any(
        not isinstance(name, str)
        or re.fullmatch(r"[a-z][a-z0-9-]*", name) is None
        for name in paths
    ):
        raise FrontierCanaryError("Executed source closure has invalid identifiers")
    hashes: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise FrontierCanaryError(f"Executed source closure file is missing: {name}")
        hashes[name] = file_sha256(path)
    return hashes


def _assert_source_hashes(
    paths: Mapping[str, Path], expected: Mapping[str, str], boundary: str
) -> None:
    if set(paths) != set(expected):
        raise FrontierCanaryError("Executed source closure membership drifted")
    for name, path in paths.items():
        if not path.is_file() or file_sha256(path) != expected[name]:
            raise FrontierCanaryError(
                f"Executed source closure drifted at {boundary}: {name}"
            )


def _assert_manifest_source_closure(
    manifest: Mapping[str, Any], paths: Mapping[str, Path]
) -> None:
    tools = manifest.get("reference_agent_stack", {}).get("tools", [])
    registered = {
        tool["id"].removeprefix("source-closure:"): tool["artifact"]["sha256"]
        for tool in tools
        if isinstance(tool, Mapping)
        and isinstance(tool.get("id"), str)
        and tool["id"].startswith("source-closure:")
        and isinstance(tool.get("artifact"), Mapping)
    }
    if set(registered) != set(paths):
        raise FrontierCanaryError("Registered executed source closure is incomplete")
    _assert_source_hashes(paths, registered, "registered execution boundary")


def _source_media_type(path: Path) -> str:
    if path.suffix == ".py":
        return "text/x-python"
    if path.suffix == ".php":
        return "text/x-php"
    return "text/plain"


def _git_environment(**overrides: str) -> dict[str, str]:
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    environment.update(overrides)
    return environment


def _run_pinned_git(
    git_binary: Path,
    git_sha256: str,
    arguments: Sequence[str],
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    if file_sha256(git_binary) != git_sha256:
        raise FrontierCanaryError("Pinned Git binary changed during registration")
    command = [
        str(git_binary),
        "--no-replace-objects",
        "-c",
        "core.hooksPath=/dev/null",
        *arguments,
    ]
    completed = subprocess.run(
        command,
        env=kwargs.pop("env", _git_environment()),
        **kwargs,
    )
    if file_sha256(git_binary) != git_sha256:
        raise FrontierCanaryError("Pinned Git binary changed during registration")
    return completed


def _prepare_repo(repo: Path, *, git_binary: Path, git_sha256: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    protected = ("pins", "registry", "runs", "audit", "attempts")
    existing = [name for name in protected if (repo / name).exists()]
    if existing:
        raise FrontierCanaryError(f"Artifact repo already contains canary paths: {existing}")
    if not (repo / ".git").exists():
        with tempfile.TemporaryDirectory(
            prefix="frontier-canary-empty-git-template-"
        ) as template:
            _run_pinned_git(
                git_binary,
                git_sha256,
                ["init", "-q", f"--template={template}", str(repo)],
                check=True,
            )
    staged = _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(repo), "diff", "--cached", "--quiet"],
        check=False,
    )
    if staged.returncode != 0:
        raise FrontierCanaryError("Artifact repo index must be clean before registration")
    _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(repo), "config", "user.name", "Frontier Canary Registry"],
        check=True,
    )
    _run_pinned_git(
        git_binary,
        git_sha256,
        [
            "-C",
            str(repo),
            "config",
            "user.email",
            "frontier-canary@example.invalid",
        ],
        check=True,
    )


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left in right.parents or right in left.parents


def _commit_registration(
    repo: Path,
    manifest: Mapping[str, Any],
    registered_at: datetime,
    *,
    git_binary: Path,
    git_sha256: str,
) -> GitRegistrationAnchor:
    manifest_path = manifest["registration"]["manifest_path"]
    _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(repo), "add", "--", "pins", manifest_path],
        check=True,
    )
    environment = _git_environment(
        GIT_AUTHOR_DATE=registered_at.isoformat(),
        GIT_COMMITTER_DATE=registered_at.isoformat(),
    )
    _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(repo), "commit", "-q", "-m", "Register frontier canary"],
        check=True,
        env=environment,
    )
    commit = _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return GitRegistrationAnchor(repo_path=repo, commit=commit, manifest_path=manifest_path)


def seal_frontier_evidence(
    repo: Path,
    anchor: GitRegistrationAnchor,
    *,
    git_binary: Path,
    git_sha256: str,
    sealed_at: datetime | None = None,
) -> dict[str, Any]:
    """Commit the complete post-run evidence tree without rewriting registration."""

    root = repo.resolve()
    moment = _aware_time(sealed_at or datetime.now(timezone.utc))
    custody_path = root / "audit" / "post-run-custody.json"
    if custody_path.exists():
        raise FrontierCanaryError("Post-run custody receipt already exists")
    receipt = {
        "schema_version": "drupal_agent_readiness.frontier_post_run_custody.v1",
        "registration_commit": anchor.commit,
        "sealed_at": _iso(moment),
        "included_roots": ["attempts", "audit", "runs"],
        "claim_boundary": (
            "local Git content identity and ancestry; independent publication or third-party "
            "custody is not proven"
        ),
    }
    custody_path.parent.mkdir(parents=True, exist_ok=True)
    custody_path.write_bytes(canonical_json_bytes(receipt))
    status = _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(root), "status", "--porcelain=v1", "-uall"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    paths = [line[3:] for line in status if len(line) >= 4]
    if not paths or any(
        not any(path == prefix or path.startswith(prefix + "/") for prefix in ("attempts", "audit", "runs"))
        for path in paths
    ):
        raise FrontierCanaryError(
            "Post-run evidence repository contains files outside attempts/audit/runs"
        )
    _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(root), "add", "--", "attempts", "audit", "runs"],
        check=True,
    )
    environment = _git_environment(
        GIT_AUTHOR_DATE=moment.isoformat(),
        GIT_COMMITTER_DATE=moment.isoformat(),
    )
    _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(root), "commit", "-q", "-m", "Seal frontier canary evidence"],
        check=True,
        env=environment,
    )
    evidence_commit = _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(root), "rev-parse", "HEAD^{commit}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    evidence_tree = _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(root), "rev-parse", "HEAD^{tree}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    ancestry = _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(root), "merge-base", "--is-ancestor", anchor.commit, evidence_commit],
        check=False,
    )
    remaining = _run_pinned_git(
        git_binary,
        git_sha256,
        ["-C", str(root), "status", "--porcelain=v1", "-uall"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if ancestry.returncode != 0 or remaining:
        raise FrontierCanaryError("Post-run evidence seal is not clean or registration-ancestral")
    return {
        **receipt,
        "evidence_commit": evidence_commit,
        "evidence_tree": evidence_tree,
        "registration_ancestor_verified": True,
        "repository_clean": True,
    }


def _canonical_capture(value: Mapping[str, Any]) -> dict[str, Any]:
    capture = _canonical_mapping(value, "collector capture")
    if set(capture) != {"inventory", "site_projection", "substrate", "workspace"}:
        raise FrontierCanaryError(
            "Collector capture requires exactly inventory, site_projection, substrate, and workspace"
        )
    if not isinstance(capture["inventory"], Mapping):
        raise FrontierCanaryError("Collector inventory must be a JSON object")
    _validate_site_projection(capture["site_projection"])
    _validate_workspace_projection(capture["workspace"])
    _validate_substrate(capture["substrate"])
    return capture


def _validate_substrate(substrate: Any) -> None:
    if not isinstance(substrate, Mapping):
        raise FrontierCanaryError("Collector substrate must be a JSON object")
    required = {
        "fixture_id",
        "core",
        "components",
        "runtime",
        "composer_lock_sha256",
        "vendor_tree_sha256",
    }
    if set(substrate) != required:
        raise FrontierCanaryError(f"Collector substrate requires exactly {sorted(required)}")
    if not isinstance(substrate["fixture_id"], str) or not substrate["fixture_id"]:
        raise FrontierCanaryError("Collector fixture_id must be non-empty")
    _validate_component(substrate["core"], core=True)
    components = substrate["components"]
    if not isinstance(components, list):
        raise FrontierCanaryError("Collector components must be an array")
    for component in components:
        _validate_component(component, core=False)
    ordering = [(item["kind"], item["name"]) for item in components]
    if ordering != sorted(ordering) or len(ordering) != len(set(ordering)):
        raise FrontierCanaryError("Collector components must be unique and canonically sorted")
    if not _SHA256.fullmatch(str(substrate["composer_lock_sha256"])):
        raise FrontierCanaryError("composer_lock_sha256 is not a canonical SHA-256")
    if not _SHA256.fullmatch(str(substrate["vendor_tree_sha256"])):
        raise FrontierCanaryError("vendor_tree_sha256 is not a canonical SHA-256")
    runtime = substrate["runtime"]
    if not isinstance(runtime, Mapping) or set(runtime) != {
        "php_version",
        "database_driver",
        "database_version",
        "os_image_digest",
        "container_image_digest",
    }:
        raise FrontierCanaryError("Collector runtime metadata is incomplete")
    for field in ("php_version", "database_driver", "database_version"):
        if not isinstance(runtime[field], str) or not runtime[field] or _MUTABLE.search(runtime[field]):
            raise FrontierCanaryError(f"Runtime {field} must be an immutable explicit value")
    for field in ("os_image_digest", "container_image_digest"):
        if not _SHA256.fullmatch(str(runtime[field])):
            raise FrontierCanaryError(f"Runtime {field} is not a canonical SHA-256")


def _validate_site_projection(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "database",
        "active_config",
        "public_files",
        "private_files",
    }:
        raise FrontierCanaryError("Site projection must bind database, config, and file sources")
    database = value["database"]
    if not isinstance(database, Mapping) or set(database) != {
        "algorithm",
        "scope",
        "normalization",
        "excluded_data_table_patterns",
        "excluded_data_tables",
        "canonical_byte_size",
        "sha256",
        "retention",
    }:
        raise FrontierCanaryError("Database projection manifest is incomplete")
    if database.get("scope") != "complete_schema_and_nonvolatile_table_data":
        raise FrontierCanaryError("Database projection scope is not the persistent projection")
    if database.get("excluded_data_table_patterns") != list(
        _VOLATILE_DATABASE_TABLE_PATTERNS
    ):
        raise FrontierCanaryError("Database volatile-table exclusions are not exact")
    excluded_tables = database.get("excluded_data_tables")
    if not isinstance(excluded_tables, list) or excluded_tables != sorted(
        set(excluded_tables)
    ) or any(not isinstance(item, str) or not item for item in excluded_tables):
        raise FrontierCanaryError("Database excluded table manifest is invalid")
    if type(database.get("canonical_byte_size")) is not int or database["canonical_byte_size"] < 0:
        raise FrontierCanaryError("Database projection byte size is invalid")
    if not _SHA256.fullmatch(str(database.get("sha256"))):
        raise FrontierCanaryError("Database projection digest is invalid")
    for label in ("active_config", "public_files", "private_files"):
        source = value[label]
        if not isinstance(source, Mapping):
            raise FrontierCanaryError(f"{label} projection must be an object")
        manifest_hash = source.get("manifest_sha256")
        without_hash = {key: item for key, item in source.items() if key != "manifest_sha256"}
        if not _SHA256.fullmatch(str(manifest_hash)) or canonical_sha256(without_hash) != manifest_hash:
            raise FrontierCanaryError(f"{label} projection manifest hash is invalid")
    config = value["active_config"]
    items = config.get("items")
    if not isinstance(items, list):
        raise FrontierCanaryError("Active-config projection items must be an array")
    config_names: list[str] = []
    for item in items:
        if not isinstance(item, Mapping) or set(item) != {"name", "byte_size", "sha256"}:
            raise FrontierCanaryError("Active-config projection item is malformed")
        if not isinstance(item["name"], str) or not item["name"]:
            raise FrontierCanaryError("Active-config projection name is invalid")
        if type(item["byte_size"]) is not int or item["byte_size"] < 0:
            raise FrontierCanaryError("Active-config projection size is invalid")
        if not _SHA256.fullmatch(str(item["sha256"])):
            raise FrontierCanaryError("Active-config projection digest is invalid")
        config_names.append(item["name"])
    if config_names != sorted(config_names) or len(config_names) != len(set(config_names)):
        raise FrontierCanaryError("Active-config projection names must be unique and sorted")
    for label, expected_scheme in (("public_files", "public"), ("private_files", "private")):
        source = value[label]
        if source.get("scheme") != expected_scheme or source.get("status") not in {
            "present",
            "missing",
            "unconfigured_or_missing",
        }:
            raise FrontierCanaryError(f"{label} projection status is invalid")
        files = source.get("files")
        if not isinstance(files, list):
            raise FrontierCanaryError(f"{label} projection files must be an array")
        order: list[str] = []
        for item in files:
            if not isinstance(item, Mapping) or set(item) != {
                "path_sha256",
                "byte_size",
                "sha256",
            }:
                raise FrontierCanaryError(f"{label} file projection is malformed")
            if not _SHA256.fullmatch(str(item["path_sha256"])) or not _SHA256.fullmatch(
                str(item["sha256"])
            ):
                raise FrontierCanaryError(f"{label} file projection digest is invalid")
            if type(item["byte_size"]) is not int or item["byte_size"] < 0:
                raise FrontierCanaryError(f"{label} file projection size is invalid")
            order.append(item["path_sha256"])
        if order != sorted(order) or len(order) != len(set(order)):
            raise FrontierCanaryError(f"{label} file paths must be unique and sorted")


def _validate_workspace_projection(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "algorithm",
        "excluded",
        "entries",
        "tree_sha256",
    }:
        raise FrontierCanaryError("Agent-visible workspace projection is incomplete")
    expected_hash = canonical_sha256(
        {key: item for key, item in value.items() if key != "tree_sha256"}
    )
    if value.get("tree_sha256") != expected_hash:
        raise FrontierCanaryError("Agent-visible workspace tree hash is invalid")
    if value.get("excluded") != []:
        raise FrontierCanaryError("Agent-visible workspace exclusions are not exact")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise FrontierCanaryError("Agent-visible workspace entries must be an array")
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise FrontierCanaryError("Agent-visible workspace entry is malformed")
        path = entry.get("path")
        if not isinstance(path, str) or not path or path == ".git" or path.startswith(".git/"):
            raise FrontierCanaryError("Agent-visible workspace path is unsafe")
        if entry.get("type") not in {"directory", "file", "symlink"}:
            raise FrontierCanaryError("Agent-visible workspace type is invalid")
        if not isinstance(entry.get("mode"), str):
            raise FrontierCanaryError("Agent-visible workspace mode is missing")
        if entry["type"] == "file" and (
            type(entry.get("byte_size")) is not int
            or not _SHA256.fullmatch(str(entry.get("sha256")))
        ):
            raise FrontierCanaryError("Agent-visible workspace file pin is invalid")
        if entry["type"] == "symlink" and not isinstance(entry.get("target"), str):
            raise FrontierCanaryError("Agent-visible workspace symlink target is missing")
        paths.append(path)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise FrontierCanaryError("Agent-visible workspace paths must be unique and sorted")


def _validate_component(value: Any, *, core: bool) -> None:
    if not isinstance(value, Mapping):
        raise FrontierCanaryError("Drupal component pin must be an object")
    if set(value) != {"kind", "name", "version", "revision", "tree_sha256"}:
        raise FrontierCanaryError("Drupal component pin has the wrong fields")
    if core and (value["kind"], value["name"]) != ("core", "drupal/core"):
        raise FrontierCanaryError("Core pin must identify drupal/core")
    if not core and value["kind"] not in {"cms", "profile", "module", "theme"}:
        raise FrontierCanaryError("Extension component kind is invalid")
    for field in ("name", "version", "revision"):
        if not isinstance(value[field], str) or not value[field] or _MUTABLE.search(value[field]):
            raise FrontierCanaryError(f"Component {field} must be immutable and non-empty")
    if not _SHA256.fullmatch(str(value["tree_sha256"])):
        raise FrontierCanaryError("Component tree_sha256 is not a canonical SHA-256")


def _canonical_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FrontierCanaryError(f"{label} must be a mapping")
    try:
        return json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError) as error:
        raise FrontierCanaryError(f"{label} is not canonical JSON: {error}") from error


def _callable_source_path(value: Callable[..., Any], label: str) -> Path:
    try:
        source = inspect.getsourcefile(value)
    except TypeError:
        source = None
    if source is None and not inspect.isfunction(value):
        source = inspect.getsourcefile(type(value))
    if source is None:
        raise FrontierCanaryError(f"Cannot pin {label} source")
    path = Path(source).resolve()
    if not path.is_file():
        raise FrontierCanaryError(f"Cannot pin {label} source: {path}")
    return path


def _verify_agent_version(binary: Path, expected: str) -> None:
    try:
        completed = subprocess.run(
            [str(binary), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise FrontierCanaryError(f"Could not probe pinned Codex binary: {error}") from error
    observed = completed.stdout.strip()
    if expected not in observed.split():
        raise FrontierCanaryError(
            f"Pinned Codex binary reported {observed!r}, not requested version {expected!r}"
        )


def _assert_binary_identity(binary: Path, manifest: Mapping[str, Any]) -> None:
    expected = manifest["reference_agent_stack"]["agent"]["artifact"]["sha256"]
    if not binary.is_file() or file_sha256(binary) != expected:
        raise FrontierCanaryError("Pinned Codex binary bytes changed after registration")


def _default_command_runner(
    argv: Sequence[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_command(
    runner: CommandRunner, argv: Sequence[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    try:
        completed = runner(tuple(str(item) for item in argv), cwd)
    except (OSError, subprocess.SubprocessError) as error:
        raise FrontierCanaryError(f"Substrate command failed to start: {argv!r}: {error}") from error
    if not isinstance(completed, subprocess.CompletedProcess):
        raise FrontierCanaryError("Substrate command runner must return subprocess.CompletedProcess")
    return completed


def _run_checked(
    runner: CommandRunner, argv: Sequence[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    completed = _run_command(runner, argv, cwd)
    if completed.returncode != 0:
        raise FrontierCanaryError(
            f"Substrate command failed ({completed.returncode}): {argv!r}: {completed.stderr.strip()}"
        )
    return completed


def _json_stdout(completed: subprocess.CompletedProcess[str], label: str) -> Any:
    try:
        return json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise FrontierCanaryError(f"{label} did not emit valid JSON: {error}") from error


def _load_unique_json(path: Path) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise FrontierCanaryError(f"Duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=object_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FrontierCanaryError(f"Cannot parse {path}: {error}") from error


def _installed_packages(document: Any) -> list[dict[str, Any]]:
    packages = document.get("packages") if isinstance(document, Mapping) else document
    if not isinstance(packages, list) or any(not isinstance(item, dict) for item in packages):
        raise FrontierCanaryError("vendor/composer/installed.json has no package list")
    return packages


def _lock_packages(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, Mapping):
        raise FrontierCanaryError("composer.lock must be one JSON object")
    packages = [*document.get("packages", []), *document.get("packages-dev", [])]
    if any(not isinstance(item, dict) for item in packages):
        raise FrontierCanaryError("composer.lock package list is malformed")
    return packages


def _package_install_paths(
    root: Path, packages: Sequence[Mapping[str, Any]]
) -> dict[Path, Mapping[str, Any]]:
    result: dict[Path, Mapping[str, Any]] = {}
    for package in packages:
        raw = package.get("install-path")
        if not isinstance(raw, str) or not raw:
            continue
        path = (root / "vendor" / "composer" / raw).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise FrontierCanaryError(f"Composer install path escapes the project: {raw}") from error
        if path in result:
            raise FrontierCanaryError(f"Composer packages share install path {path}")
        result[path] = package
    return result


def _package_revision(package: Mapping[str, Any], tree_hash: str) -> str:
    candidates = [
        package.get("source", {}).get("reference") if isinstance(package.get("source"), Mapping) else None,
        package.get("dist", {}).get("reference") if isinstance(package.get("dist"), Mapping) else None,
        package.get("reference"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate and not _MUTABLE.search(candidate):
            return candidate
    return tree_hash.removeprefix("sha256:")


def _immutable_version(value: Any, tree_hash: str) -> str:
    if isinstance(value, str) and value and not _MUTABLE.search(value):
        return value
    return f"tree-{tree_hash.removeprefix('sha256:')[:16]}"


def _tree_sha256(root: Path) -> str:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise FrontierCanaryError(f"Cannot hash missing code tree: {resolved}")
    digest = hashlib.sha256(b"drupal-agent-readiness-tree-v1\0")
    entries = sorted(resolved.rglob("*"), key=lambda item: item.relative_to(resolved).as_posix())
    if not entries:
        raise FrontierCanaryError(f"Cannot pin an empty code tree: {resolved}")
    for path in entries:
        relative = path.relative_to(resolved).as_posix().encode("utf-8")
        if path.is_symlink():
            raise FrontierCanaryError(f"Symlinks are not accepted in pinned code trees: {path}")
        if path.is_dir():
            digest.update(b"D\0" + relative + b"\0")
            continue
        if not path.is_file():
            raise FrontierCanaryError(f"Unsupported filesystem entry in code tree: {path}")
        payload = path.read_bytes()
        digest.update(b"F\0" + relative + b"\0" + str(len(payload)).encode("ascii") + b"\0")
        digest.update(payload)
    return "sha256:" + digest.hexdigest()


def _status_value(status: Any, *names: str) -> Any:
    if not isinstance(status, Mapping):
        raise FrontierCanaryError("Drush status is not a JSON object")
    for name in names:
        value = status.get(name)
        if value not in (None, ""):
            return value
    return None


def _required_status_string(status: Any, *names: str) -> str:
    value = _status_value(status, *names)
    if not isinstance(value, str) or not value or _MUTABLE.search(value):
        raise FrontierCanaryError(f"Drush status omitted immutable field {names[0]}")
    return value


def _host_project_path(host_root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw:
        raise FrontierCanaryError("Drupal reported an empty code path")
    path = Path(raw)
    if path.is_absolute():
        container_root = Path("/var/www/html")
        try:
            path = host_root / path.relative_to(container_root)
        except ValueError:
            pass
    else:
        path = host_root / path
    resolved = path.resolve()
    allowed_root = host_root.resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as error:
        raise FrontierCanaryError(f"Reported code path escapes project: {raw}") from error
    return resolved


def _ddev_project_name(config: Path) -> str:
    for line in config.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*name\s*:\s*['\"]?([A-Za-z0-9._-]+)['\"]?\s*$", line)
        if match:
            return match.group(1)
    raise FrontierCanaryError(".ddev/config.yaml does not declare a safe project name")


def _render_prompt(root: Path, manifest: Mapping[str, Any]) -> str:
    return _prompt_bytes(root, manifest).decode("utf-8")


def _prompt_bytes(root: Path, manifest: Mapping[str, Any]) -> bytes:
    task = (root / manifest["task"]["prompt"]["uri"]).read_text(encoding="utf-8")
    system = (
        root / manifest["reference_agent_stack"]["system_prompt"]["uri"]
    ).read_text(encoding="utf-8")
    inputs = json.loads(
        (root / manifest["prompt_composition"]["render_inputs"]["uri"]).read_bytes()
    )
    governed_observation = load_canonical_json_file(
        root / "pins" / "snapshot" / "governed-observation.json"
    )
    return canonical_json_bytes(
        {
            "schema_version": "drupal_agent_readiness.prompt_envelope.v1",
            "task_prompt": task,
            "operator_prompt_envelope": system,
            "render_inputs": inputs,
            "governed_observation": governed_observation,
        }
    )


def _role_pin(
    pin: Mapping[str, Any], evidence_role: str, visibility: str, audience: list[str]
) -> dict[str, Any]:
    return {**pin, "evidence_role": evidence_role, "visibility": visibility, "audience": audience}


def _inventory_shape_failures(answer: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    expected_top = {"command_runner", "provenance", "paths", "canvas", "content_model", "pathauto"}
    if set(answer) != expected_top:
        failures.append("answer.keys")
    if answer.get("command_runner") not in {"vendor/bin/drush", "ddev drush", "vendor/bin/dr"}:
        failures.append("command_runner.schema")
    expected_nested = {
        "provenance": {"project_name", "project_version", "site_template", "active_config_source", "config_sync_status"},
        "paths": {"/blog", "/node", "/home"},
        "canvas": {"page_count", "embedded_listings"},
        "content_model": {"bundles", "moderation_enabled"},
        "pathauto": {"enabled", "patterns"},
    }
    for key, keys in expected_nested.items():
        value = answer.get(key)
        if not isinstance(value, Mapping) or set(value) != keys:
            failures.append(f"{key}.schema")
    paths = answer.get("paths")
    if isinstance(paths, Mapping):
        for path, owner in paths.items():
            if not isinstance(owner, Mapping):
                failures.append(f"paths.{path}.schema")
                continue
            if set(owner) != {"claimed", "owner_kind", "entity_type"}:
                failures.append(f"paths.{path}.schema")
            if type(owner.get("claimed")) is not bool or owner.get("owner_kind") not in {"entity", "view", "route", "unclaimed"}:
                failures.append(f"paths.{path}.types")
            entity_type = owner.get("entity_type")
            if owner.get("owner_kind") == "entity":
                if not isinstance(entity_type, str) or not entity_type:
                    failures.append(f"paths.{path}.entity_type")
            elif "entity_type" in owner and entity_type is not None:
                failures.append(f"paths.{path}.entity_type")
    for key, field in (("canvas", "embedded_listings"), ("content_model", "bundles"), ("pathauto", "patterns")):
        value = answer.get(key)
        items = value.get(field) if isinstance(value, Mapping) else None
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items) or len(items) != len(set(items)):
            failures.append(f"{key}.{field}.schema")
    canvas = answer.get("canvas")
    if not isinstance(canvas, Mapping) or type(canvas.get("page_count")) is not int or canvas.get("page_count", -1) < 0:
        failures.append("canvas.page_count.schema")
    content = answer.get("content_model")
    pathauto = answer.get("pathauto")
    if not isinstance(content, Mapping) or type(content.get("moderation_enabled")) is not bool:
        failures.append("content_model.moderation_enabled.schema")
    if not isinstance(pathauto, Mapping) or type(pathauto.get("enabled")) is not bool:
        failures.append("pathauto.enabled.schema")
    return sorted(set(failures))


def _usage(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise FrontierCanaryError("Executor usage must be an object")
    base_fields = {"input_tokens", "output_tokens", "cached_input_tokens"}
    fields = set(value)
    if fields != base_fields and fields != {*base_fields, "reasoning_output_tokens"}:
        raise FrontierCanaryError("Executor usage fields are not exact")
    normalized = {
        field: _nonnegative_int(value.get(field), f"usage.{field}")
        for field in ("input_tokens", "output_tokens", "cached_input_tokens")
    }
    if normalized["cached_input_tokens"] > normalized["input_tokens"]:
        raise FrontierCanaryError(
            "usage.cached_input_tokens cannot exceed usage.input_tokens"
        )
    if "reasoning_output_tokens" in value:
        reasoning = _nonnegative_int(
            value.get("reasoning_output_tokens"),
            "usage.reasoning_output_tokens",
        )
        if reasoning > normalized["output_tokens"]:
            raise FrontierCanaryError(
                "usage.reasoning_output_tokens cannot exceed usage.output_tokens"
            )
        normalized["reasoning_output_tokens"] = reasoning
    return normalized


def _nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise FrontierCanaryError(f"{label} must be a non-negative integer")
    return value


def _required_string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise FrontierCanaryError(f"Executor {field} must be a non-empty string")
    return result


def _reject_unsafe_extra_args(values: Sequence[str]) -> None:
    if tuple(values) not in {(), ("--color", "never")}:
        raise FrontierCanaryError("Only the pinned optional '--color never' pair is permitted")
    for value in values:
        lowered = str(value).lower()
        if lowered in {"--sandbox", "-s", "--add-dir", "--ignore-user-config", "--ignore-rules", "--disable", "-c", "--config"}:
            raise FrontierCanaryError(f"Extra arguments cannot override custody flag {value}")
        if any(lowered == prefix or lowered.startswith(prefix + "=") for prefix in _FORBIDDEN_ARG_PREFIXES):
            raise FrontierCanaryError(f"Forbidden Codex argument: {value}")
        if lowered in {"workspace-write", "danger-full-access"} or lowered.startswith("--sandbox="):
            raise FrontierCanaryError(f"Writable sandbox argument: {value}")
        if lowered.startswith("-c") and "sandbox" in lowered:
            raise FrontierCanaryError(f"Sandbox config override is forbidden: {value}")


def _declared_hash(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _aware_time(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FrontierCanaryError("Canary timestamps must be timezone-aware datetimes")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return _aware_time(value).isoformat().replace("+00:00", "Z")


def _assert_monotonic(*values: datetime) -> None:
    if any(left > right for left, right in zip(values, values[1:])):
        raise FrontierCanaryError("Canary clock produced non-monotonic timestamps")
