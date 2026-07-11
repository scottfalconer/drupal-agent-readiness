"""Process and transcript utilities shared by Codex experiment runners."""

import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Callable


_PROCESS_CLEANUP_GRACE_SECONDS = 0.5


def run_command(
    command: list[str],
    *,
    input: str | None,
    text: bool,
    capture_output: bool,
    cwd: Path,
    env: dict[str, str],
    timeout: int | None,
) -> subprocess.CompletedProcess[str]:
    """Run a command in its own process group and clean up on timeout."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=text,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        stdout = exc.output
        stderr = exc.stderr
        try:
            drained_stdout, drained_stderr = process.communicate(
                timeout=_PROCESS_CLEANUP_GRACE_SECONDS
            )
        except subprocess.TimeoutExpired as drain_error:
            stdout = _latest_process_output(stdout, drain_error.output)
            stderr = _latest_process_output(stderr, drain_error.stderr)
            _close_process_pipes(process)
            try:
                process.wait(timeout=_PROCESS_CLEANUP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=_PROCESS_CLEANUP_GRACE_SECONDS)
        else:
            stdout = _latest_process_output(stdout, drained_stdout)
            stderr = _latest_process_output(stderr, drained_stderr)
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=stdout,
            stderr=stderr,
        ) from exc
    _kill_residual_process_group(process.pid)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def terminate_run_server_processes(
    run_dir: Path,
    *,
    process_lister: Callable[[], list[tuple[int, str]]] | None = None,
    killer: Callable[[int], None] | None = None,
) -> list[int]:
    """Terminate leftover PHP servers whose command refers to one run directory."""
    lister = process_lister or _list_processes
    kill_pid = killer or _terminate_pid
    run_dir_candidates = {str(run_dir), str(run_dir.resolve())}
    killed: list[int] = []
    for pid, command in lister():
        if not any(run_dir_text in command for run_dir_text in run_dir_candidates):
            continue
        if not _is_run_server_command(command):
            continue
        kill_pid(pid)
        killed.append(pid)
    return killed


def count_codex_tool_calls(stdout: str) -> int:
    """Count active Codex items, failing closed on ambiguous JSON objects."""

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    total = 0
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line, object_pairs_hook=unique_object)
        except (json.JSONDecodeError, ValueError):
            # A malformed or ambiguous retained event cannot establish the
            # absence of an action, so classify it conservatively.
            total += 1
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", ""))
        if item_type not in {"", "agent_message", "reasoning", "error"}:
            total += 1
    return total


def classify_infrastructure_failure(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    tool_calls: int,
) -> str | None:
    """Classify known runner failures without relabeling agent task failures."""
    if returncode == 0:
        return None
    combined = f"{stdout}\n{stderr}".lower()
    if "invalid_json_schema" in combined or "invalid schema for response_format" in combined:
        return "codex_invalid_output_schema"
    if "selected model is at capacity" in combined or "model is at capacity" in combined:
        return "codex_model_capacity"
    if "usage limit" in combined or "purchase more credits" in combined:
        return "codex_usage_limit"
    if tool_calls > 0:
        return None
    return None


def render_transcript(
    *,
    run_id: str,
    command: list[str],
    returncode: int,
    elapsed_seconds: float,
    stdout: str,
    stderr: str,
    answer_path: Path,
    answer_valid: bool,
    answer_error: str | None,
) -> str:
    """Render stable human-readable metadata around raw Codex output."""
    lines = [
        f"# Codex transcript: {run_id}",
        "",
        f"- returncode: {returncode}",
        f"- elapsed_seconds: {elapsed_seconds:.3f}",
        f"- answer_json: {answer_path}",
        f"- answer_valid_json: {str(answer_valid).lower()}",
    ]
    if answer_error:
        lines.append(f"- answer_error: {answer_error}")
    lines.extend([
        "",
        "## Command",
        "",
        "```text",
        " ".join(command),
        "```",
        "",
        "## Codex JSONL stdout",
        "",
        "```jsonl",
        stdout.rstrip(),
        "```",
        "",
        "## Codex stderr",
        "",
        "```text",
        stderr.rstrip(),
        "```",
        "",
    ])
    return "\n".join(lines)


def process_output(value: str | bytes | None) -> str:
    """Normalize subprocess timeout output to text."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def timeout_stderr(exc: subprocess.TimeoutExpired) -> str:
    """Retain stderr and add an explicit timeout message."""
    stderr = process_output(exc.stderr).rstrip()
    message = f"Command timed out after {exc.timeout:g} seconds"
    if stderr:
        return f"{stderr}\n{message}\n"
    return f"{message}\n"


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        process.terminate()
    if process.poll() is None:
        try:
            process.wait(timeout=_PROCESS_CLEANUP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
    _kill_residual_process_group(process.pid)
    if process.poll() is None:
        process.kill()
        process.wait(timeout=_PROCESS_CLEANUP_GRACE_SECONDS)


def _kill_residual_process_group(process_group_id: int) -> None:
    """Best-effort cleanup for the original group; this is not job containment."""

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _close_process_pipes(process: subprocess.Popen[str]) -> None:
    for pipe in (process.stdin, process.stdout, process.stderr):
        if pipe is None:
            continue
        try:
            pipe.close()
        except OSError:
            pass


def _latest_process_output(
    first: str | bytes | None,
    latest: str | bytes | None,
) -> str | bytes | None:
    """Use cumulative subprocess output without duplicating the first snapshot."""

    return latest if latest is not None else first


def _combine_process_output(
    first: str | bytes | None,
    second: str | bytes | None,
) -> str | bytes | None:
    if first in (None, b"", ""):
        return second
    if second in (None, b"", ""):
        return first
    if isinstance(first, bytes) != isinstance(second, bytes):
        return process_output(first) + process_output(second)
    return first + second


def _list_processes() -> list[tuple[int, str]]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        text=True,
        capture_output=True,
        check=False,
    )
    processes: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        processes.append((pid, parts[1]))
    return processes


def _is_run_server_command(command: str) -> bool:
    return "php -S " in command or "drush.php runserver" in command


def _terminate_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
