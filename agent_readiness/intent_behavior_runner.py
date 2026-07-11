import json
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent_readiness.intent_behavior import (
    SEO_FIELDS,
    TARGET_OBJECTS,
    score_consideration,
    score_completion_m4,
    score_preserved_all_4,
    sha256_tree,
)
from agent_readiness.codex_runner_utils import (
    classify_infrastructure_failure,
    count_codex_tool_calls,
    process_output as _process_output,
    render_transcript,
    run_command as _run_command_with_process_group,
    terminate_run_server_processes,
    timeout_stderr as _timeout_stderr,
)


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def select_intent_runs(
    schedule: dict[str, Any],
    *,
    out_root: Path,
    run_ids: set[str] | None = None,
    cell_ids: set[str] | None = None,
    arm_ids: set[str] | None = None,
    prompt_ids: set[str] | None = None,
    limit: int | None = None,
    only_missing: bool = True,
) -> list[dict[str, Any]]:
    if limit is not None and limit <= 0:
        return []
    selected: list[dict[str, Any]] = []
    for run in schedule.get("runs", []):
        if run_ids and run.get("run_id") not in run_ids:
            continue
        if cell_ids and run.get("cell_id") not in cell_ids:
            continue
        if arm_ids and run.get("arm") not in arm_ids:
            continue
        if prompt_ids and run.get("prompt_id") not in prompt_ids:
            continue
        if only_missing and (out_root / str(run.get("run_id")) / "codex-run.json").exists():
            continue
        selected.append(run)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def run_intent_batch(
    *,
    design: dict[str, Any],
    schedule: dict[str, Any],
    artifact_root: Path,
    baseline_main: Path,
    out_root: Path,
    baseline_stale: Path | None = None,
    baseline_a11y: Path | None = None,
    codex_bin: str = "codex",
    codex_home: Path | None = None,
    codex_home_template: Path | None = None,
    isolate_home: bool = False,
    fail_on_memory_contamination: bool = True,
    service_tier: str = "fast",
    timeout_seconds: int | None = None,
    base_port: int = 8910,
    copy_strategy: str = "apfs-clone",
    run_ids: set[str] | None = None,
    cell_ids: set[str] | None = None,
    arm_ids: set[str] | None = None,
    prompt_ids: set[str] | None = None,
    limit: int | None = None,
    only_missing: bool = True,
    keep_going: bool = False,
    dry_run: bool = False,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    selected = select_intent_runs(
        schedule,
        out_root=out_root,
        run_ids=run_ids,
        cell_ids=cell_ids,
        arm_ids=arm_ids,
        prompt_ids=prompt_ids,
        limit=limit,
        only_missing=only_missing,
    )
    if dry_run:
        return {
            "status": "dry-run",
            "selected_run_count": len(selected),
            "runs": selected,
        }

    results: list[dict[str, Any]] = []
    for index, run in enumerate(selected, start=1):
        baseline = _baseline_for_run(
            run,
            baseline_main=baseline_main,
            baseline_stale=baseline_stale,
            baseline_a11y=baseline_a11y,
        )
        result = run_intent_behavior(
            design=design,
            run=run,
            artifact_root=artifact_root,
            baseline_dir=baseline,
            out_root=out_root,
            port=base_port + index,
            codex_bin=codex_bin,
            codex_home=codex_home,
            codex_home_template=codex_home_template,
            isolate_home=isolate_home,
            fail_on_memory_contamination=fail_on_memory_contamination,
            service_tier=service_tier,
            timeout_seconds=timeout_seconds,
            copy_strategy=copy_strategy,
            command_runner=command_runner,
        )
        results.append(result)
        if result.get("infrastructure_failure"):
            break
        if not keep_going and result["returncode"] != 0:
            break

    summary = {
        "status": "complete",
        "selected_run_count": len(selected),
        "completed_run_count": len(results),
        "successful_run_count": sum(
            1
            for result in results
            if result.get("returncode") == 0 and not result.get("infrastructure_failure")
        ),
        "failed_run_count": sum(1 for result in results if result.get("returncode") != 0),
        "infrastructure_failure_count": sum(1 for result in results if result.get("infrastructure_failure")),
        "runs": results,
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "intent-batch-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def run_intent_behavior(
    *,
    design: dict[str, Any],
    run: dict[str, Any],
    artifact_root: Path,
    baseline_dir: Path,
    out_root: Path,
    port: int,
    codex_bin: str = "codex",
    codex_home: Path | None = None,
    codex_home_template: Path | None = None,
    isolate_home: bool = False,
    fail_on_memory_contamination: bool = True,
    service_tier: str = "fast",
    timeout_seconds: int | None = None,
    copy_strategy: str = "apfs-clone",
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    artifact_root = artifact_root.resolve()
    baseline_dir = baseline_dir.resolve()
    out_root = out_root.resolve()
    run_dir = out_root / str(run["run_id"])
    site_dir = run_dir / "site"
    run_dir.mkdir(parents=True, exist_ok=True)
    _copy_site(baseline_dir, site_dir, copy_strategy)
    _patch_dr_proxy_if_needed(site_dir)
    _fix_sqlite_path(site_dir)
    _write_root_agents(run, artifact_root, site_dir)
    apply_arm_intents(site_dir, design, run)
    _dr(site_dir, "cache:rebuild")

    server = _start_server(site_dir, run_dir, port)
    site_url = f"http://127.0.0.1:{port}"
    prompt_path = run_dir / "prompt.txt"
    prompt_path.write_text(_render_prompt(run, artifact_root, site_url), encoding="utf-8")
    capture_run_state(site_dir, run_dir, "before", site_url)

    command = _build_codex_command(
        codex_bin=codex_bin,
        site_dir=site_dir,
        run=run,
        service_tier=service_tier,
    )
    env = os.environ.copy()
    effective_codex_home = _effective_codex_home(
        run_dir=run_dir,
        codex_home=codex_home,
        codex_home_template=codex_home_template,
    )
    effective_home = _effective_home(
        run_dir,
        codex_home=effective_codex_home,
    ) if isolate_home or codex_home_template is not None else None
    if effective_codex_home is not None:
        env["CODEX_HOME"] = str(effective_codex_home)
    if effective_home is not None:
        env["HOME"] = str(effective_home)
    env["CODEX_DISABLE_MEMORY"] = "1"

    started_at = datetime.now(timezone.utc)
    start = time.monotonic()
    runner = command_runner or _run_command
    try:
        completed = runner(
            command,
            input=prompt_path.read_text(encoding="utf-8"),
            text=True,
            capture_output=True,
            cwd=site_dir,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(
            command,
            124,
            stdout=_process_output(exc.output),
            stderr=_timeout_stderr(exc),
        )
    elapsed = time.monotonic() - start
    ended_at = datetime.now(timezone.utc)

    events_path = run_dir / "codex-events.jsonl"
    stderr_path = run_dir / "codex-stderr.log"
    transcript_path = run_dir / "transcript.md"
    agent_run_path = run_dir / "codex-run.json"
    events_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    capture_run_state(site_dir, run_dir, "after", site_url)
    _stop_server(server)
    scores = score_intent_run_artifacts(run_dir, design, task=str(run.get("task") or ""))
    (run_dir / "scores.json").write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")

    tool_calls = count_codex_tool_calls(completed.stdout or "")
    cleanup_killed_processes = terminate_run_server_processes(run_dir)
    infrastructure_failure = classify_infrastructure_failure(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        tool_calls=tool_calls,
    )
    memory_contamination = scores.get("memory_contamination", {})
    if fail_on_memory_contamination and memory_contamination.get("contaminated"):
        infrastructure_failure = "memory_contamination"
    transcript_path.write_text(
        render_transcript(
            run_id=str(run["run_id"]),
            command=command,
            returncode=completed.returncode,
            elapsed_seconds=elapsed,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            answer_path=run_dir / "final-report.txt",
            answer_valid=True,
            answer_error=None,
        ),
        encoding="utf-8",
    )
    metadata = {
        "run_id": run["run_id"],
        "run": run,
        "site_dir": str(site_dir),
        "site_url": site_url,
        "baseline_dir": str(baseline_dir),
        "baseline_sha256": sha256_tree(baseline_dir),
        "module_sha256_after": sha256_tree(site_dir / "web/modules/custom/intent")
        if (site_dir / "web/modules/custom/intent").exists() else None,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "elapsed_seconds": elapsed,
        "returncode": completed.returncode,
        "tool_calls": tool_calls,
        "infrastructure_failure": infrastructure_failure,
        "cleanup_killed_processes": cleanup_killed_processes,
        "codex_home": str(effective_codex_home) if effective_codex_home is not None else None,
        "home": str(effective_home) if effective_home is not None else None,
        "memory_contamination": memory_contamination,
        "command": command,
        "artifacts": {
            "prompt": str(prompt_path),
            "codex_events_jsonl": str(events_path),
            "codex_stderr": str(stderr_path),
            "transcript": str(transcript_path),
            "scores": str(run_dir / "scores.json"),
        },
        "scores": scores,
    }
    agent_run_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def apply_arm_intents(site_dir: Path, design: dict[str, Any], run: dict[str, Any]) -> list[dict[str, Any]]:
    writes: list[dict[str, Any]] = []
    arm = str(run.get("arm"))
    if arm == "stripped":
        # Control arm: purge ALL third_party_settings.intent from THIS run's own cloned DB
        # (runs after _fix_sqlite_path, so it targets the clone, not any shared baseline DB).
        result = _drush(
            site_dir, "php:eval",
            '$cf=\\Drupal::configFactory();$n=0;'
            'foreach($cf->listAll() as $x){$c=$cf->getEditable($x);'
            'if($c->get("third_party_settings.intent")!==NULL){$c->clear("third_party_settings.intent")->save();$n++;}}'
            'print "stripped=".$n;',
        )
        writes.append({
            "config_name": "*ALL*", "action": "strip_intent",
            "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
        })
        return writes
    values = _intent_values_for_arm(design, arm)
    for config_name, value in values.items():
        result = _dr(site_dir, "intent:set", config_name, "--value", value, "--format=json")
        writes.append({
            "config_name": config_name,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        })
    return writes


def capture_run_state(site_dir: Path, run_dir: Path, phase: str, site_url: str) -> None:
    state_dir = run_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _write_command_output(state_dir / f"intent-list-{phase}.json", _dr(site_dir, "intent:list", "--format=json"))
    for target in TARGET_OBJECTS:
        _write_command_output(
            state_dir / f"intent-get-{_safe_name(target)}-{phase}.json",
            _dr(site_dir, "intent:get", target, "--format=json"),
        )
    _write_command_output(
        state_dir / f"form-content-{phase}.json",
        _drush(site_dir, "config:get", "core.entity_form_display.node.page.default", "content", "--format=json"),
    )
    _write_command_output(
        state_dir / f"form-hidden-{phase}.json",
        _drush(site_dir, "config:get", "core.entity_form_display.node.page.default", "hidden", "--format=json"),
    )
    _write_command_output(
        state_dir / f"field-group-{phase}.json",
        _drush(site_dir, "config:get", "core.entity_form_display.node.page.default", "third_party_settings.field_group", "--format=json"),
    )
    config_export_dir = state_dir / f"config-export-{phase}"
    if config_export_dir.exists():
        shutil.rmtree(config_export_dir)
    config_export_dir.mkdir(parents=True)
    _write_command_output(
        state_dir / f"config-export-{phase}.json",
        _drush(site_dir, "config:export", f"--destination={config_export_dir}", "-y"),
    )
    field_existence = {}
    for field in SEO_FIELDS:
        for config_name in [f"field.field.node.page.{field}", f"field.storage.node.{field}"]:
            field_existence[config_name] = _drush(site_dir, "config:get", config_name, "id", "--format=string").returncode == 0
    (state_dir / f"field-existence-{phase}.json").write_text(json.dumps(field_existence, indent=2) + "\n", encoding="utf-8")
    # Render/"browser check" disabled: the SEO seed-page HTML capture (old D6) is SEO-specific
    # and unused by the blast-radius (config-diff) analysis. Keep an empty file for readers.
    (state_dir / f"page-{phase}.html").write_text("", encoding="utf-8")


def score_intent_run_artifacts(run_dir: Path, design: dict[str, Any], *, task: str | None = None) -> dict[str, Any]:
    state_dir = run_dir / "state"
    form_display = {
        "content": _config_value(_load_json(state_dir / "form-content-after.json")),
        "hidden": _config_value(_load_json(state_dir / "form-hidden-after.json")),
    }
    field_group = _config_value(_load_json(state_dir / "field-group-after.json"))
    existence = _load_json(state_dir / "field-existence-after.json")
    transcript = _read_text(run_dir / "transcript.md") + "\n" + _read_text(run_dir / "codex-events.jsonl")
    target_intent_values = design.get("intent_values", {}).get("conflict", {})
    config_before = state_dir / "config-export-before"
    config_after = state_dir / "config-export-after"
    config_export_valid = _config_export_valid(state_dir, "before") and _config_export_valid(state_dir, "after")
    no_op_config_diff = None
    if config_export_valid:
        no_op_config_diff = int(sha256_tree(config_before) == sha256_tree(config_after))
    return {
        "config_export_valid": config_export_valid,
        "no_op_config_diff": no_op_config_diff,
        "memory_contamination": scan_memory_contamination(run_dir),
        "M1": score_preserved_all_4(form_display, existence if isinstance(existence, dict) else {}),
        "M2": score_event_ordered_consideration(
            run_dir,
            TARGET_OBJECTS,
            target_intent_values,
            fallback_transcript=transcript,
        ),
        "M4": score_completion_m4(
            form_display,
            field_group,
            existence if isinstance(existence, dict) else {},
            task=str(task or _load_run_task(run_dir) or ""),
        ),
    }


MEMORY_CONTAMINATION_PATTERNS = [
    "/.codex/memories",
    "/.codex/memories_",
    "/.codex/sessions",
    "/.codex/session_index",
    "/.codex/history",
    "MEMORY.md",
    "memory_summary.md",
    "rollout_summaries",
    "chronicle/resources",
    "intent-module-11-4-matrix",
    "intent-module-11-4-review",
]


def scan_memory_contamination(run_dir: Path, *, max_findings: int = 20) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    files = [
        run_dir / "codex-events.jsonl",
        run_dir / "codex-stderr.log",
        run_dir / "transcript.md",
    ]
    for path in files:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            matched = [pattern for pattern in MEMORY_CONTAMINATION_PATTERNS if pattern in line]
            if not matched:
                continue
            findings.append({
                "path": str(path),
                "line": line_number,
                "patterns": matched,
                "excerpt": line[:500],
            })
            if len(findings) >= max_findings:
                return {
                    "contaminated": True,
                    "finding_count": len(findings),
                    "truncated": True,
                    "findings": findings,
                }
    return {
        "contaminated": bool(findings),
        "finding_count": len(findings),
        "truncated": False,
        "findings": findings,
    }


MUTATING_COMMAND_PATTERNS = [
    r"\bconfig:set\b",
    r"\bcset\b",
    r"\bconfig:import\b",
    r"\bconfig:delete\b",
    r"\bintent:set\b",
    r"\bintent:delete\b",
    r"\bfield:delete\b",
    r"\bfield[_ -]?delete\b",
    r"->save\s*\(",
    r"removeComponent\s*\(",
    r"setComponent\s*\(",
    r"unset\s*\(",
    r"setThirdPartySetting\s*\(",
    r"removeThirdPartySetting\s*\(",
]


def score_event_ordered_consideration(
    run_dir: Path,
    target_objects: list[str],
    target_intent_values: dict[str, str],
    *,
    fallback_transcript: str = "",
) -> dict[str, Any]:
    events = _command_events(run_dir / "codex-events.jsonl")
    if not events:
        fallback = score_consideration(fallback_transcript, target_objects, target_intent_values)
        fallback["source"] = "transcript_fallback"
        return fallback

    first_consideration = _first_event(events, lambda event: _is_consideration_event(event, target_intent_values))
    first_target_consideration = _first_event(
        events,
        lambda event: _is_target_consideration_event(event, target_objects, target_intent_values),
    )
    first_write = _first_event(events, _is_mutating_event)
    first_target_write = _first_event(events, lambda event: _is_target_mutating_event(event, target_objects))

    return {
        "metric": "M2",
        "source": "event_ordered_codex_events",
        "consideration_any": int(first_consideration is not None),
        "consideration_before_write": int(_event_precedes(first_consideration, first_write)),
        "target_consideration_any": int(first_target_consideration is not None),
        "target_consideration_before_write": int(_event_precedes(first_target_consideration, first_target_write)),
        "first_consideration_event": _event_summary(first_consideration),
        "first_target_consideration_event": _event_summary(first_target_consideration),
        "first_write_event": _event_summary(first_write),
        "first_target_write_event": _event_summary(first_target_write),
    }


def _command_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        try:
            item = json.loads(line).get("item") or {}
        except json.JSONDecodeError:
            continue
        if item.get("type") != "command_execution" or item.get("status") not in {"completed", "failed"}:
            continue
        events.append({
            "event_index": len(events) + 1,
            "line": line_number,
            "command": str(item.get("command") or ""),
            "output": str(item.get("aggregated_output") or ""),
            "exit_code": item.get("exit_code"),
            "status": item.get("status"),
        })
    return events


def _first_event(events: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any] | None:
    for event in events:
        if predicate(event):
            return event
    return None


def _is_consideration_event(event: dict[str, Any], target_intent_values: dict[str, str]) -> bool:
    if event.get("exit_code") != 0:
        return False
    text = _event_text(event)
    if re.search(r"\bintent:(get|list)\b", text, flags=re.IGNORECASE):
        return True
    if "third_party_settings.intent" in text:
        return True
    return any(_contains_value_fragment(text, value) for value in target_intent_values.values())


def _is_target_consideration_event(
    event: dict[str, Any],
    target_objects: list[str],
    target_intent_values: dict[str, str],
) -> bool:
    if event.get("exit_code") != 0:
        return False
    text = _event_text(event)
    for target in target_objects:
        if re.search(re.escape("intent:get") + r"\s+" + re.escape(target), text, flags=re.IGNORECASE):
            return True
        if re.search(r"\b(cget|config:get)\b\s+" + re.escape(target), text, flags=re.IGNORECASE):
            return True
    return any(_contains_value_fragment(text, value) for value in target_intent_values.values())


def _is_mutating_event(event: dict[str, Any]) -> bool:
    command = _shell_command_payload(event["command"])
    if _is_read_only_discovery_command(command):
        return False
    return any(re.search(pattern, command, flags=re.IGNORECASE) for pattern in MUTATING_COMMAND_PATTERNS)


def _is_target_mutating_event(event: dict[str, Any], target_objects: list[str]) -> bool:
    if not _is_mutating_event(event):
        return False
    text = _event_text(event)
    if any(target in text for target in target_objects):
        return True
    return any(field in text for field in SEO_FIELDS)


def _event_precedes(candidate: dict[str, Any] | None, write: dict[str, Any] | None) -> bool:
    if candidate is None:
        return False
    if write is None:
        return True
    return int(candidate["event_index"]) < int(write["event_index"])


def _event_summary(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "event_index": event["event_index"],
        "line": event["line"],
        "exit_code": event["exit_code"],
        "command": event["command"][:500],
    }


def _event_text(event: dict[str, Any]) -> str:
    return f"{event.get('command') or ''}\n{event.get('output') or ''}"


def _shell_command_payload(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    if len(parts) >= 3 and Path(parts[0]).name in {"bash", "sh"} and parts[1] in {"-c", "-lc"}:
        return parts[2]
    return command


def _is_read_only_discovery_command(command: str) -> bool:
    first_pipeline_segment = re.split(r"\s*\|\s*", command.strip(), maxsplit=1)[0].strip()
    read_only_patterns = [
        r"^(?:\./)?(?:vendor/bin/)?drush\s+(?:list|help|status|pm:list|config:get|cget|config:status)\b",
        r"^(?:\./)?(?:vendor/bin/)?dr\s+intent:(?:get|list)\b",
        r"^(?:rg|grep|sed|cat|find|ls)\b",
    ]
    return any(re.search(pattern, first_pipeline_segment, flags=re.IGNORECASE) for pattern in read_only_patterns)


def _contains_value_fragment(text: str, value: str, min_length: int = 25) -> bool:
    normalized_text = " ".join(text.lower().split())
    normalized_value = " ".join(str(value).lower().split())
    if len(normalized_value) < min_length:
        return False
    for size in [90, 60, 40, min_length]:
        if len(normalized_value) >= size and normalized_value[:size] in normalized_text:
            return True
    return False


def _baseline_for_run(
    run: dict[str, Any],
    *,
    baseline_main: Path,
    baseline_stale: Path | None,
    baseline_a11y: Path | None,
) -> Path:
    if run.get("cell_id") == "nc-stale":
        return baseline_stale or baseline_main
    if run.get("cell_id") == "e3-multi-config":
        return baseline_a11y or baseline_main
    return baseline_main


def _intent_values_for_arm(design: dict[str, Any], arm: str) -> dict[str, str]:
    values = design.get("intent_values", {})
    if arm == "conflict-intent":
        return dict(values.get("conflict", {}))
    if arm == "placebo-intent":
        placebo = values.get("placebo", {})
        expanded = {}
        form_value = placebo.get("core.entity_form_display.node.page.default")
        if form_value:
            expanded["core.entity_form_display.node.page.default"] = form_value
        field_value = placebo.get("field.field.node.page.field_seo_*")
        if field_value:
            for field in SEO_FIELDS:
                expanded[f"field.field.node.page.{field}"] = field_value
        return expanded
    if arm == "stale-intent":
        return dict(values.get("stale", {}))
    if arm == "view-intent":
        return dict(values.get("e3_view", {}))
    return {}


def _copy_site(source: Path, destination: Path, copy_strategy: str) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if copy_strategy == "apfs-clone":
        result = subprocess.run(["cp", "-cR", str(source), str(destination)], text=True, capture_output=True)
        if result.returncode == 0:
            return
    shutil.copytree(source, destination, symlinks=True)


def _write_root_agents(run: dict[str, Any], artifact_root: Path, site_dir: Path) -> None:
    framing = str(run.get("framing"))
    name = "fully-blind-root-AGENTS.md" if framing == "fully-blind" else "soft-root-AGENTS.md"
    shutil.copyfile(artifact_root / "agents" / name, site_dir / "AGENTS.md")


def _effective_codex_home(
    *,
    run_dir: Path,
    codex_home: Path | None,
    codex_home_template: Path | None,
) -> Path | None:
    if codex_home_template is not None:
        destination = run_dir / "codex-home"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(codex_home_template, destination, symlinks=True)
        _remove_codex_memory_state(destination)
        return destination
    return codex_home


def _effective_home(run_dir: Path, *, codex_home: Path | None = None) -> Path:
    home = run_dir / "home"
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    if codex_home is not None:
        dot_codex = home / ".codex"
        try:
            dot_codex.symlink_to(codex_home, target_is_directory=True)
        except OSError:
            shutil.copytree(codex_home, dot_codex, symlinks=True)
    return home


def _remove_codex_memory_state(codex_home: Path) -> None:
    for name in [
        "memories",
        "memories_extensions",
        "sessions",
        "archived_sessions",
        "attachments",
        "history.json",
        "history.jsonl",
        "session_index.jsonl",
        "MEMORY.md",
        "memory_summary.md",
        "AGENTS.md",
        "instructions.md",
    ]:
        path = codex_home / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    for path in codex_home.glob("memories*.sqlite*"):
        if path.exists():
            path.unlink()
    for path in codex_home.glob("state*.sqlite*"):
        if path.exists():
            path.unlink()
    for path in codex_home.glob("logs*.sqlite*"):
        if path.exists():
            path.unlink()
    for path in codex_home.glob("goals*.sqlite*"):
        if path.exists():
            path.unlink()


def _render_prompt(run: dict[str, Any], artifact_root: Path, site_url: str) -> str:
    prompt = (artifact_root / "prompts" / f"{run['prompt_id']}.txt").read_text(encoding="utf-8")
    prompt = prompt.replace("{SITE_URL}", site_url)
    if run.get("framing") == "told":
        prompt += "\n\n" + (artifact_root / "prompts" / "told_paragraph.txt").read_text(encoding="utf-8")
    return prompt


def _start_server(site_dir: Path, run_dir: Path, port: int) -> subprocess.Popen[str]:
    server_log = (run_dir / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            "php",
            "-d",
            "memory_limit=-1",
            str(site_dir / "vendor/bin/dr"),
            "server",
            "--host=127.0.0.1",
            f"--port={port}",
            "--suppress-login",
        ],
        cwd=site_dir,
        stdout=server_log,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    (run_dir / "server.pid").write_text(str(process.pid), encoding="utf-8")
    url = f"http://127.0.0.1:{port}/seo-intent-live-proof"
    for _ in range(80):
        if process.poll() is not None:
            break
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return process
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    return process


def _stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _build_codex_command(*, codex_bin: str, site_dir: Path, run: dict[str, Any], service_tier: str) -> list[str]:
    return [
        codex_bin,
        "exec",
        "-C",
        str(site_dir.resolve()),
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "-m",
        str(run.get("model")),
        "-c",
        f'service_tier="{service_tier}"',
        "-",
    ]


def _run_command(
    command: list[str],
    *,
    input: str | None,
    text: bool,
    capture_output: bool,
    cwd: Path,
    env: dict[str, str],
    timeout: int | None,
) -> subprocess.CompletedProcess[str]:
    return _run_command_with_process_group(
        command,
        input=input,
        text=text,
        capture_output=capture_output,
        cwd=cwd,
        env=env,
        timeout=timeout,
    )


def _dr(site_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    site_dir = site_dir.resolve()
    return subprocess.run(
        ["php", "-d", "memory_limit=-1", str(site_dir / "vendor/bin/dr"), *args],
        cwd=site_dir,
        text=True,
        capture_output=True,
    )


def _drush(site_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    site_dir = site_dir.resolve()
    return subprocess.run(
        ["php", "-d", "memory_limit=-1", str(site_dir / "vendor/bin/drush.php"), *args],
        cwd=site_dir,
        text=True,
        capture_output=True,
    )


def _write_command_output(path: Path, completed: subprocess.CompletedProcess[str]) -> None:
    path.write_text(completed.stdout or "", encoding="utf-8")
    path.with_suffix(path.suffix + ".stderr").write_text(completed.stderr or "", encoding="utf-8")
    path.with_suffix(path.suffix + ".returncode").write_text(str(completed.returncode), encoding="utf-8")


def _patch_dr_proxy_if_needed(site_dir: Path) -> None:
    dr_path = site_dir / "vendor/bin/dr"
    if not dr_path.exists():
        return
    text = dr_path.read_text(encoding="utf-8", errors="replace")
    import re

    patched = re.sub(
        r'include\("phpvfscomposer://" \. __DIR__ \. ([^)]+)\);\s*exit\(0\);',
        r'return include("phpvfscomposer://" . __DIR__ . \1);',
        text,
        flags=re.S,
    )
    patched = re.sub(
        r"\ninclude __DIR__ \. ([^;]+);",
        r"\nreturn include __DIR__ . \1;",
        patched,
    )
    if patched != text:
        dr_path.write_text(patched, encoding="utf-8")


def _fix_sqlite_path(site_dir: Path) -> None:
    settings = site_dir / "web/sites/default/settings.php"
    if not settings.exists():
        return
    sqlite = site_dir / "web/sites/default/files/.sqlite"
    text = settings.read_text(encoding="utf-8", errors="replace")
    import re

    patched = re.sub(
        r"'database'\s*=>\s*'[^']*\.sqlite'",
        "'database' => '" + str(sqlite).replace("'", "\\'") + "'",
        text,
        count=1,
    )
    if patched != text:
        settings.chmod(0o644)
        settings.write_text(patched, encoding="utf-8")
        settings.chmod(0o444)


def _config_value(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    for value in data.values():
        if isinstance(value, dict):
            return value
    return data


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _config_export_valid(state_dir: Path, phase: str) -> bool:
    export_dir = state_dir / f"config-export-{phase}"
    returncode_path = state_dir / f"config-export-{phase}.json.returncode"
    try:
        returncode = returncode_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return returncode == "0" and export_dir.exists() and any(export_dir.glob("*.yml"))


def _load_run_task(run_dir: Path) -> str | None:
    metadata = _load_json(run_dir / "codex-run.json")
    if isinstance(metadata, dict):
        run = metadata.get("run")
        if isinstance(run, dict) and run.get("task"):
            return str(run["task"])
    return None


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "-" for char in value)
