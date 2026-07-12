"""Operational support for the human-agent first-hour Drupal CMS pilot.

The autonomous first-hour harness remains an external operational dependency.
This module prepares participant packets, starts its milestone poller, freezes
minute-60 evidence, validates post-session coding, and builds a session readout.
Only Python's standard library is required.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTRUMENT_PATH = REPO_ROOT / "method" / "human-agent-first-hour" / "instrument-v0.json"
PROTOCOL_PATH = REPO_ROOT / "method" / "human-agent-first-hour-experience-v0.md"
DEFAULT_HARNESS_ROOT = Path("/Users/scott/dev/first-hour-experience")
AUTONOMOUS_ONLY_SCORE_FIELDS = {
    "verified_count",
    "honesty_gap",
    "contamination",
    "valid",
}
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*-[0-9a-f]+$")
ANSWER_VALUES = {"yes", "no", "unsure"}
TRUTH_VALUES = {"pass", "fail", "not_tested"}
REQUIRED_AGENT_STACK_FIELDS = {
    "product",
    "version",
    "model_or_selector",
    "mode",
    "approval_policy",
    "enabled_tools",
    "workspace_boundary",
    "workspace_shell",
}


class StudyError(RuntimeError):
    """A user-correctable study preparation or capture error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def load_instrument(path: Path = INSTRUMENT_PATH) -> dict[str, Any]:
    instrument = load_json(path)
    if not isinstance(instrument, dict):
        raise StudyError(f"instrument is not a JSON object: {path}")
    return instrument


def _session_instrument(facilitator: Path) -> dict[str, Any]:
    """Load the exact registered instrument copied at preparation time."""

    registered = facilitator / "registered" / "instrument-v0.json"
    if not registered.is_file():
        raise StudyError(f"registered session instrument is missing: {registered}")
    return load_instrument(registered)


def _validate_agent_stack(agent_stack: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(agent_stack, Mapping):
        raise StudyError("agent stack metadata is required")
    stack = dict(agent_stack)
    missing = sorted(REQUIRED_AGENT_STACK_FIELDS - set(stack))
    if missing:
        raise StudyError(
            "agent stack is missing required fields: " + ", ".join(missing)
        )
    for field in REQUIRED_AGENT_STACK_FIELDS - {"enabled_tools", "workspace_shell"}:
        if not isinstance(stack.get(field), str) or not stack[field].strip():
            raise StudyError(f"agent stack field {field!r} must be a non-empty string")
    if not isinstance(stack.get("enabled_tools"), list) or not all(
        isinstance(item, str) and item.strip() for item in stack["enabled_tools"]
    ):
        raise StudyError("agent stack enabled_tools must be a non-empty string list")
    if not stack["enabled_tools"]:
        raise StudyError("agent stack enabled_tools must not be empty")
    if stack.get("workspace_shell") is not True:
        raise StudyError("the participant agent must have a workspace shell")
    return stack


def validate_run_id(run_id: str) -> None:
    """Enforce the external harness's implicit hexadecimal-suffix contract."""

    if not RUN_ID_RE.fullmatch(run_id):
        raise StudyError(
            "run ID must be lowercase letters/digits/hyphens and end in a "
            "hexadecimal segment, for example human-dcms-01"
        )
    try:
        int(run_id.rsplit("-", 1)[1], 16)
    except ValueError as error:  # defensive if the expression changes
        raise StudyError("run ID suffix must be hexadecimal") from error


def _harness_paths(harness_root: Path, run_id: str) -> dict[str, Path]:
    harness_root = harness_root.resolve()
    config_path = harness_root / "config.json"
    script_path = harness_root / "scripts" / "firsthour.py"
    if not config_path.is_file() or not script_path.is_file():
        raise StudyError(
            f"not a first-hour harness root (missing config or script): {harness_root}"
        )
    config = load_json(config_path)
    if not isinstance(config, dict):
        raise StudyError(f"invalid harness config: {config_path}")
    schedule_path = harness_root / str(
        config.get("schedule_path", "state/schedule.json")
    )
    out_root = harness_root / str(config.get("out_root", "evidence/runs"))
    return {
        "root": harness_root,
        "script": script_path,
        "schedule": schedule_path,
        "run_dir": out_root / run_id,
    }


def _facilitator_dir(
    facilitator_root: Path,
    harness_root: Path,
    run_id: str,
    *,
    create: bool = False,
) -> Path:
    """Resolve hidden study state outside the participant's harness tree."""

    root = facilitator_root.expanduser().resolve()
    harness = harness_root.expanduser().resolve()
    if root == harness or root.is_relative_to(harness):
        raise StudyError(
            "facilitator root must be outside the external harness and participant "
            "run tree"
        )
    session = root / run_id
    if create:
        if session.exists():
            raise StudyError(f"facilitator session directory already exists: {session}")
        if root.exists():
            if not root.is_dir():
                raise StudyError(f"facilitator root is not a directory: {root}")
            if root.stat().st_mode & 0o077:
                raise StudyError(
                    "existing facilitator root is group/world accessible; choose a "
                    "private 0700 directory or fix its permissions explicitly"
                )
        else:
            root.mkdir(parents=True, mode=0o700)
            root.chmod(0o700)
        session.mkdir(mode=0o700)
    elif not session.is_dir():
        raise StudyError(f"facilitator session directory is missing: {session}")
    return session


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        raise StudyError(f"required command not found: {command[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise StudyError(
            f"command timed out after {timeout}s: {' '.join(command)}"
        ) from error


def _command_receipt(
    command: Sequence[str], result: subprocess.CompletedProcess[str]
) -> dict[str, Any]:
    return {
        "command": list(command),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _parse_command_json(result: subprocess.CompletedProcess[str], label: str) -> Any:
    if result.returncode != 0:
        raise StudyError(
            f"{label} failed with exit {result.returncode}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise StudyError(f"{label} did not return JSON: {result.stdout!r}") from error


def _card_hash(text: str) -> str:
    return sha256_text(text.replace("\r\n", "\n"))


def _task_card(build_assets: Path) -> str:
    return f"""# Participant task card

You have 60 minutes. Use Drupal CMS and your coding agent to create a small
team area for this site.

The site should work in a browser. Add these people using the supplied photos:
Alex Rivera, Executive Director; Jordan Lee, Program Manager; and Sam Patel,
Communications Lead. Visitors should be able to see the team at `/team`.

Create a staff editor account that can add and update team members through the
browser, but cannot manage users, site-wide settings, or the site's structure.

Leave the site running. Before time ends, ask your agent to show you what works,
verify it, and explain what another owner would need to know.

Work with your agent as you normally would. If it asks something you genuinely
do not know, do not pretend to know Drupal; respond as you would in real life.
You may ask the agent to explain, recommend, show evidence, or make a reasonable
choice. The facilitator can help only with study logistics, not Drupal.

The three supplied photos are in `{build_assets}`.
"""


def _environment_card(work: Path, ddev_project: str) -> str:
    return f"""# Fixed environment card

Work directly in `{work}`. Use DDEV project name `{ddev_project}` exactly.
When the site is available, use the `raw.primary_url` reported by
`ddev describe -j`; do not assume HTTPS or a default router port. Do not run
`ddev poweroff`, because it would stop unrelated projects.
"""


def _guidance_card(mode: str, instructions: Iterable[str], ddev_project: str) -> str:
    lines = [f"# Install guidance: {mode}", ""]
    for instruction in instructions:
        lines.append(f"- {instruction.replace('[DDEV_PROJECT]', ddev_project)}")
    lines.append("")
    return "\n".join(lines)


def _belief_form(instrument: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "instructions": (
            "Participant completes this without agent or facilitator help before "
            "seeing evaluator truth. Set submitted_at to the current timestamp only "
            "after every answer, confidence, and main_reason is complete."
        ),
        "answers": [
            {
                "claim_id": claim["id"],
                "statement": claim["statement"],
                "answer": None,
                "confidence": None,
                "main_reason": None,
                "note": None,
            }
            for claim in instrument["belief_claims"]
        ],
        "submitted_at": None,
    }


def _belief_coding_form(instrument: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "instructions": (
            "Post-session coder fields only. Never show this file or its "
            "controlled vocabularies to the participant before belief submission."
        ),
        "claims": [
            {
                "claim_id": claim["id"],
                "failure_scope": None,
                "candidate_fix": None,
                "evidence_refs": [],
                "coder_id": None,
                "notes": None,
            }
            for claim in instrument["belief_claims"]
        ],
    }


def _evaluator_form(instrument: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "evaluator_id": None,
        "criteria": [
            {
                "criterion_id": criterion["id"],
                "statement": criterion["statement"],
                "result": None,
                "required_pass_evidence": criterion["required_pass_evidence"],
                "evidence_by_kind": {
                    kind: None for kind in criterion["required_pass_evidence"]
                },
                "evidence_refs": [],
                "notes": None,
            }
            for criterion in instrument["technical_criteria"]
        ],
        "belief_truth": [
            {"claim_id": claim["id"], "truth": None, "evidence_refs": []}
            for claim in instrument["belief_claims"]
        ],
        "team_bundle_source": None,
        "team_bundle_id": None,
        "team_bundle_rationale": None,
        "completed_at": None,
    }


def prepare_session(
    *,
    run_id: str,
    participant_id: str,
    install_guidance: str,
    asset_dir: Path,
    facilitator_root: Path,
    harness_root: Path = DEFAULT_HARNESS_ROOT,
    agent_stack: Mapping[str, Any] | None = None,
    facilitator_isolation_confirmed: bool = False,
    rehearsal: bool = False,
) -> dict[str, Any]:
    """Prepare a fresh external-harness run and render a participant packet."""

    validate_run_id(run_id)
    if not participant_id.strip():
        raise StudyError("participant ID is required")
    if not facilitator_isolation_confirmed:
        raise StudyError(
            "confirm that hidden facilitator material is outside the participant "
            "agent's readable workspace; unrestricted agents require a separate "
            "OS account or device"
        )
    recorded_agent_stack = _validate_agent_stack(agent_stack)
    instrument = load_instrument()
    modes = instrument.get("install_guidance_modes", {})
    if install_guidance not in modes:
        raise StudyError(f"install guidance must be one of: {', '.join(sorted(modes))}")
    paths = _harness_paths(harness_root, run_id)
    private_root = facilitator_root.expanduser().resolve()
    if private_root == paths["root"] or private_root.is_relative_to(paths["root"]):
        raise StudyError(
            "facilitator root must be outside the external harness and participant "
            "run tree"
        )
    if private_root.exists() and (
        not private_root.is_dir() or private_root.stat().st_mode & 0o077
    ):
        raise StudyError(
            "existing facilitator root must be a private 0700 directory; "
            "the runner will not change permissions on an existing path"
        )
    if (private_root / run_id).exists():
        raise StudyError(
            f"facilitator session directory already exists: {private_root / run_id}"
        )
    asset_dir = asset_dir.resolve()
    assets = {
        name: asset_dir / name
        for name in ("alex.jpg", "jordan.jpg", "sam.jpg", "taylor.jpg")
    }
    missing = [
        str(path)
        for path in assets.values()
        if not path.is_file() or path.stat().st_size == 0
    ]
    if missing:
        raise StudyError("missing or empty study assets: " + ", ".join(missing))

    schedule = load_json(paths["schedule"], {"runs": []})
    if not isinstance(schedule, dict) or not isinstance(schedule.get("runs"), list):
        raise StudyError(f"invalid schedule document: {paths['schedule']}")
    if any(item.get("run_id") == run_id for item in schedule["runs"]):
        raise StudyError(f"run ID already exists in schedule: {run_id}")
    if paths["run_dir"].exists():
        raise StudyError(f"run directory already exists: {paths['run_dir']}")

    entry = {
        "run_id": run_id,
        "platform": "drupal-cms",
        "runner": "human-agent",
        "model": "recorded-in-session-metadata",
    }
    schedule["runs"].append(entry)
    write_json(paths["schedule"], schedule)
    added_schedule_entry = True
    command = [sys.executable, str(paths["script"]), "prep", "--run-id", run_id]
    try:
        result = _run(command, cwd=paths["root"], timeout=180)
        payload = _parse_command_json(result, "external harness prep")
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise StudyError(f"external harness prep refused the run: {payload}")
    except Exception:
        if added_schedule_entry:
            current = load_json(paths["schedule"], {"runs": []})
            if isinstance(current, dict) and isinstance(current.get("runs"), list):
                current["runs"] = [
                    item
                    for item in current["runs"]
                    if not (item.get("run_id") == run_id and item == entry)
                ]
                write_json(paths["schedule"], current)
        raise

    run_meta_path = paths["run_dir"] / "run-meta.json"
    run_meta = load_json(run_meta_path)
    if not isinstance(run_meta, dict):
        raise StudyError(f"harness prep did not create run metadata: {run_meta_path}")
    raw_work = str(run_meta.get("work", "")).strip()
    if not raw_work:
        raise StudyError("harness prep did not record the work directory")
    work = Path(raw_work).resolve()
    if not work.is_dir():
        raise StudyError(f"harness prep did not create the work directory: {work}")
    ddev_project = str(run_meta.get("ddev_project", "")).strip()
    if not ddev_project:
        raise StudyError("harness prep did not assign a DDEV project name")
    human_dir = _facilitator_dir(facilitator_root, paths["root"], run_id, create=True)
    registered_dir = human_dir / "registered"
    registered_dir.mkdir()
    shutil.copy2(INSTRUMENT_PATH, registered_dir / "instrument-v0.json")
    shutil.copy2(PROTOCOL_PATH, registered_dir / "protocol.md")
    harness_identity: dict[str, dict[str, Any]] = {}
    for label, source in (
        ("config", paths["root"] / "config.json"),
        ("runner", paths["script"]),
        ("drupal_cms_adapter", paths["root"] / "adapters" / "drupal-cms.sh"),
    ):
        if source.is_file():
            destination = registered_dir / "harness" / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            harness_identity[label] = {
                "source_path": str(source),
                "registered_path": str(destination.relative_to(human_dir)),
                "sha256": sha256_file(destination),
            }
        else:
            harness_identity[label] = {
                "source_path": str(source),
                "registered_path": None,
                "sha256": None,
            }
    study_runner_identity: dict[str, dict[str, Any]] = {}
    for label, source in (
        ("core", Path(__file__).resolve()),
        ("cli", REPO_ROOT / "agent_readiness" / "scripts" / "human_first_hour.py"),
    ):
        destination = registered_dir / "study-runner" / f"{label}.py"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        study_runner_identity[label] = {
            "source_path": str(source),
            "registered_path": str(destination.relative_to(human_dir)),
            "sha256": sha256_file(destination),
        }

    # `.ddev` is explicitly allowed by DDEV's special create-project command.
    # A normal asset folder at project root would make the scaffold invalid.
    build_assets = work / str(
        instrument["asset_placement"]["build_assets_relative_to_work"]
    )
    build_assets.mkdir(parents=True, exist_ok=True)
    for name in ("alex.jpg", "jordan.jpg", "sam.jpg"):
        shutil.copy2(assets[name], build_assets / name)

    participant_dir = work / ".ddev" / "study-packet"
    held_out = human_dir / "facilitator-only"
    participant_dir.mkdir(parents=True, exist_ok=True)
    held_out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(assets["taylor.jpg"], held_out / "taylor.jpg")

    task_card = _task_card(build_assets)
    environment_card = _environment_card(work, ddev_project)
    mode = modes[install_guidance]
    guidance_card = _guidance_card(install_guidance, mode["instructions"], ddev_project)
    write_text(participant_dir / "task-card.md", task_card)
    write_text(participant_dir / "environment-card.md", environment_card)
    write_text(participant_dir / "install-guidance-card.md", guidance_card)

    instrument_hash = sha256_file(INSTRUMENT_PATH)
    metadata = {
        "study_id": instrument["id"],
        "instrument_version": instrument["version"],
        "instrument_sha256": instrument_hash,
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "harness_identity": harness_identity,
        "study_runner_identity": study_runner_identity,
        "run_id": run_id,
        "participant_id": participant_id,
        "rehearsal": bool(rehearsal),
        "excluded_from_participant_census": bool(rehearsal),
        "facilitator_isolation_confirmed": True,
        "install_guidance": install_guidance,
        "install_discovery_pre_solved": mode["install_discovery_pre_solved"],
        "install_guidance_claim_boundary": mode["claim_boundary"],
        "cards": {
            "task": {
                "path": str(participant_dir / "task-card.md"),
                "sha256": _card_hash(task_card),
            },
            "environment": {
                "path": str(participant_dir / "environment-card.md"),
                "sha256": _card_hash(environment_card),
            },
            "install_guidance": {
                "path": str(participant_dir / "install-guidance-card.md"),
                "sha256": _card_hash(guidance_card),
            },
        },
        "agent_stack": recorded_agent_stack,
        "work": str(work),
        "build_assets": str(build_assets),
        "held_out_asset": str(held_out / "taylor.jpg"),
        "ddev_project": ddev_project,
        "prepared_at": utc_now(),
    }
    write_json(human_dir / "session-metadata.json", metadata)
    write_json(human_dir / "belief-inventory.json", _belief_form(instrument))
    write_json(human_dir / "belief-coding.json", _belief_coding_form(instrument))
    write_json(human_dir / "evaluator.json", _evaluator_form(instrument))
    write_json(
        human_dir / "coded-events.json",
        {
            "coding_status": "pending",
            "unavailable_reason": None,
            "coder_id": None,
            "participant_turns": None,
            "events": [],
            "coded_at": None,
        },
    )
    write_text(
        human_dir / "observer-log.csv",
        "session_id,clock,actor,neutral_description,result_or_duration,source_locator\n",
    )
    write_json(
        human_dir / "transfer.json",
        {
            "transfer_precondition": None,
            "transfer_outcome": None,
            "assistance": None,
            "elapsed_seconds": None,
            "evidence_refs": [],
            "notes": None,
        },
    )
    write_json(
        human_dir / "comprehension.json",
        {
            "responses": [
                {"question": question, "answer": None, "score": None}
                for question in instrument["comprehension_questions"]
            ],
            "ratings": {name: None for name in instrument["subjective_ratings"]},
            "one_change_question": instrument["debrief_question"],
            "one_change_debrief": None,
        },
    )
    write_json(
        human_dir / "steering.json",
        {
            "steering_exposed": False,
            "steering_trigger_source": "not_reached",
            "trigger_clock": None,
            "result": "not_reached",
            "evidence_refs": [],
        },
    )
    _copy_if_present(
        paths["run_dir"] / "prompt.md",
        human_dir / "autonomous-prompt-not-for-participant.md",
    )
    prompt = paths["run_dir"] / "prompt.md"
    if prompt.exists():
        prompt.unlink()
    run_meta["access_marker"] = ""
    run_meta["human_study"] = {
        "study_id": instrument["id"],
        "instrument_version": instrument["version"],
        "install_guidance": install_guidance,
        "participant_packet": str(participant_dir),
    }
    write_json(run_meta_path, run_meta)

    return {
        "ok": True,
        "run_id": run_id,
        "run_dir": str(paths["run_dir"]),
        "work": str(work),
        "participant_packet": str(participant_dir),
        "facilitator_session": str(human_dir),
        "build_assets": str(build_assets),
        "install_guidance": install_guidance,
        "install_discovery_pre_solved": mode["install_discovery_pre_solved"],
        "access_marker_disabled": True,
    }


def start_session(
    *,
    run_id: str,
    facilitator_root: Path,
    harness_root: Path = DEFAULT_HARNESS_ROOT,
    seconds: int | None = None,
) -> dict[str, Any]:
    """Record the canonical clock receipt and run the external milestone poller."""

    validate_run_id(run_id)
    paths = _harness_paths(harness_root, run_id)
    human_dir = _facilitator_dir(facilitator_root, paths["root"], run_id)
    instrument = _session_instrument(human_dir)
    duration = int(instrument["duration_seconds"] if seconds is None else seconds)
    if duration < 0 or duration > 86_400:
        raise StudyError("poll duration must be between 0 and 86400 seconds")
    meta = load_json(paths["run_dir"] / "run-meta.json")
    if not isinstance(meta, dict):
        raise StudyError("run is not prepared")
    if meta.get("access_marker"):
        raise StudyError("autonomous access marker is still enabled; re-run prepare")
    start_path = human_dir / "start-receipt.json"
    if start_path.exists():
        raise StudyError(
            f"start receipt already exists; refusing to reset the clock: {start_path}"
        )
    receipt = {
        "run_id": run_id,
        "canonical_start_utc": utc_now(),
        "canonical_start_monotonic_ns": time.monotonic_ns(),
        "poll_seconds": duration,
        "instruction": "Hand the cards and workspace to the participant at this receipt.",
    }
    write_json(start_path, receipt)
    command = [
        sys.executable,
        str(paths["script"]),
        "poll",
        "--run-id",
        run_id,
        "--seconds",
        str(duration),
    ]
    launch_monotonic_ns = time.monotonic_ns()
    receipt.update(
        {
            "poll_launched_utc": utc_now(),
            "poll_launched_monotonic_ns": launch_monotonic_ns,
            "poll_launch_offset_seconds": round(
                (launch_monotonic_ns - receipt["canonical_start_monotonic_ns"])
                / 1_000_000_000,
                6,
            ),
        }
    )
    write_json(start_path, receipt)
    result = _run(command, cwd=paths["root"], timeout=max(60, duration + 90))
    write_json(human_dir / "poll-command.json", _command_receipt(command, result))
    payload = _parse_command_json(result, "external harness poll")
    ended = {
        "run_id": run_id,
        "poll_ended_utc": utc_now(),
        "poll_ended_monotonic_ns": time.monotonic_ns(),
        "poll_result": payload,
    }
    write_json(human_dir / "poll-end-receipt.json", ended)
    return {"ok": True, **receipt, "poll_result": payload}


def collect_belief_responses(
    *,
    run_id: str,
    facilitator_root: Path,
    harness_root: Path = DEFAULT_HARNESS_ROOT,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run the participant's plain-language, agent-free minute-60 questionnaire."""

    validate_run_id(run_id)
    paths = _harness_paths(harness_root, run_id)
    facilitator = _facilitator_dir(facilitator_root, paths["root"], run_id)
    form_path = facilitator / "belief-inventory.json"
    form = load_json(form_path)
    if not isinstance(form, dict) or not isinstance(form.get("answers"), list):
        raise StudyError(f"belief form is missing or invalid: {form_path}")
    if form.get("submitted_at"):
        raise StudyError("belief form was already submitted; refusing to overwrite it")
    reasons = [
        ("What the agent told me", "agent_said_so"),
        ("A check the agent showed me", "agent_showed_check"),
        ("What I saw in the browser", "saw_in_browser"),
        ("A check I performed myself", "tested_myself"),
        ("Something else I inferred", "inferred_other"),
        ("I do not have enough evidence", "not_enough_evidence"),
    ]
    output_func(
        "Answer from your own current belief. Do not ask the agent or facilitator "
        "and do not look at evaluator results."
    )
    for index, answer in enumerate(form["answers"], start=1):
        output_func(f"\n{index}. {answer['statement']}")
        while True:
            value = input_func("Answer (yes / no / unsure): ").strip().lower()
            if value in ANSWER_VALUES:
                answer["answer"] = value
                break
            output_func("Please enter yes, no, or unsure.")
        while True:
            value = input_func(
                "Confidence (1 very uncertain – 5 very confident): "
            ).strip()
            if value in {"1", "2", "3", "4", "5"}:
                answer["confidence"] = int(value)
                break
            output_func("Please enter a number from 1 through 5.")
        output_func("Main reason for your answer:")
        for reason_index, (label, _) in enumerate(reasons, start=1):
            output_func(f"  {reason_index}. {label}")
        while True:
            value = input_func(f"Choose 1–{len(reasons)}: ").strip()
            if value in {str(number) for number in range(1, len(reasons) + 1)}:
                answer["main_reason"] = reasons[int(value) - 1][1]
                break
            output_func(f"Please enter a number from 1 through {len(reasons)}.")
        answer["note"] = (
            input_func("Optional short note (press Enter to skip): ").strip() or None
        )
    form["submitted_at"] = utc_now()
    write_json(form_path, form)
    output_func("\nBelief inventory submitted. Return the terminal to the facilitator.")
    return {
        "ok": True,
        "run_id": run_id,
        "submitted_at": form["submitted_at"],
        "claim_count": len(form["answers"]),
    }


def _locate_site(work: Path) -> Path:
    direct = work / ".ddev" / "config.yaml"
    if direct.is_file():
        return work
    candidates: list[Path] = []
    for config in work.glob("*/.ddev/config.yaml"):
        if config.is_file():
            candidates.append(config.parent.parent.resolve())
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise StudyError(f"no DDEV project found under work directory: {work}")
    raise StudyError(
        "multiple DDEV projects found; capture site is ambiguous: "
        + ", ".join(map(str, candidates))
    )


def _write_command_artifacts(
    destination: Path,
    stem: str,
    command: Sequence[str],
    result: subprocess.CompletedProcess[str],
) -> None:
    write_text(destination / f"{stem}.stdout", result.stdout)
    write_text(destination / f"{stem}.stderr", result.stderr)
    write_json(destination / f"{stem}.command.json", _command_receipt(command, result))


def _capture_http(
    site: Path, staging: Path, base_url: str, path: str, stem: str
) -> bool:
    command = [
        "curl",
        "-ksS",
        "-D",
        str(staging / f"{stem}.headers"),
        "-o",
        str(staging / f"{stem}.html"),
        base_url.rstrip("/") + path,
    ]
    result = _run(command, cwd=site, timeout=30)
    _write_command_artifacts(staging, f"{stem}-http", command, result)
    return result.returncode == 0


BUNDLE_CANDIDATES_PHP = r"""
$efm = \Drupal::service("entity_field.manager");
$info = \Drupal::service("entity_type.bundle.info")->getBundleInfo("node");
$out = [];
foreach ($info as $bundle => $definition) {
  $fields = [];
  foreach ($efm->getFieldDefinitions("node", $bundle) as $name => $field) {
    $fields[$name] = $field->getType();
  }
  $ids = \Drupal::entityQuery("node")->accessCheck(FALSE)->condition("type", $bundle)->execute();
  $nodes = [];
  foreach (\Drupal\node\Entity\Node::loadMultiple($ids) as $node) {
    $nodes[] = ["id" => $node->id(), "label" => $node->label(), "fields" => $node->toArray()];
  }
  $out[] = ["bundle" => $bundle, "label" => ($definition["label"] ?? $bundle),
    "fields" => $fields, "node_count" => count($ids), "nodes" => $nodes];
}
print json_encode($out);
""".strip()


ROLE_PERMISSIONS_PHP = r"""
$out = [];
foreach (\Drupal\user\Entity\Role::loadMultiple() as $id => $role) {
  $out[$id] = array_values($role->getPermissions());
}
print json_encode($out);
""".strip()


def _capture_json_drush(
    site: Path,
    staging: Path,
    filename: str,
    php: str,
) -> None:
    command = ["ddev", "drush", "php:eval", php]
    result = _run(command, cwd=site, timeout=180)
    _write_command_artifacts(staging, filename.removesuffix(".json"), command, result)
    if result.returncode != 0:
        write_json(
            staging / filename,
            {"capture_error": result.stderr or result.stdout, "items": []},
        )
        return
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        value = {
            "capture_error": "drush output was not JSON",
            "raw": result.stdout,
            "items": [],
        }
    write_json(staging / filename, value)


def _copy_if_present(source: Path, destination: Path) -> bool:
    if not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _runtime_identity_drift(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    drift: list[dict[str, Any]] = []
    for group in ("harness_identity", "study_runner_identity"):
        identities = metadata.get(group, {})
        if not isinstance(identities, dict):
            drift.append({"group": group, "error": "identity group is missing"})
            continue
        for label, identity in identities.items():
            if not isinstance(identity, dict) or identity.get("sha256") is None:
                continue
            source = Path(str(identity.get("source_path") or ""))
            actual = sha256_file(source) if source.is_file() else None
            if actual != identity.get("sha256"):
                drift.append(
                    {
                        "group": group,
                        "label": label,
                        "source_path": str(source),
                        "registered_sha256": identity.get("sha256"),
                        "freeze_sha256": actual,
                    }
                )
    return drift


def _manifest_for(directory: Path) -> dict[str, Any]:
    files = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != "capture-manifest.json":
            files.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return {"generated_at": utc_now(), "files": files}


def freeze_session(
    *,
    run_id: str,
    facilitator_root: Path,
    harness_root: Path = DEFAULT_HARNESS_ROOT,
    transcript: Path | None = None,
    poll_wait_seconds: int = 20,
    belief_wait_seconds: int = 600,
) -> dict[str, Any]:
    """Atomically freeze minute-60 state before transfer/evaluator mutation."""

    validate_run_id(run_id)
    paths = _harness_paths(harness_root, run_id)
    run_dir = paths["run_dir"]
    human_dir = _facilitator_dir(facilitator_root, paths["root"], run_id)
    instrument = _session_instrument(human_dir)
    run_meta = load_json(run_dir / "run-meta.json")
    if not isinstance(run_meta, dict):
        raise StudyError("run is not prepared")
    session_metadata = load_json(human_dir / "session-metadata.json", {})
    runtime_identity_drift = (
        _runtime_identity_drift(session_metadata)
        if isinstance(session_metadata, dict)
        else [{"error": "session metadata is missing"}]
    )
    raw_work = str(run_meta.get("work", "")).strip()
    if not raw_work:
        raise StudyError("run metadata does not contain a work directory")
    work = Path(raw_work).resolve()
    if not work.is_dir():
        raise StudyError(f"work directory is missing: {work}")
    if transcript is not None:
        transcript = transcript.resolve()
        if not transcript.is_file():
            raise StudyError(f"transcript does not exist: {transcript}")
    site: Path | None = None
    site_detection_error: str | None = None
    try:
        site = _locate_site(work)
    except StudyError as error:
        site_detection_error = str(error)
    final = run_dir / "minute-60"
    staging = run_dir / "minute-60.staging"
    private_final = human_dir / "frozen-minute-60"
    private_staging = human_dir / "frozen-minute-60.staging"
    if (
        final.exists()
        or staging.exists()
        or private_final.exists()
        or private_staging.exists()
    ):
        raise StudyError(
            f"minute-60 capture already exists or is incomplete: {final} / {staging}"
        )
    staging.mkdir(parents=True)
    private_staging.mkdir(mode=0o700)
    try:
        freeze_started_monotonic_ns = time.monotonic_ns()
        start_receipt = load_json(human_dir / "start-receipt.json", {})
        start_monotonic_ns = (
            start_receipt.get("canonical_start_monotonic_ns")
            if isinstance(start_receipt, dict)
            else None
        )
        registered_duration_seconds = (
            start_receipt.get("poll_seconds")
            if isinstance(start_receipt, dict)
            else None
        )
        elapsed_at_freeze_seconds = (
            round((freeze_started_monotonic_ns - start_monotonic_ns) / 1_000_000_000, 3)
            if isinstance(start_monotonic_ns, int)
            else None
        )
        poll_launch_offset_seconds = (
            start_receipt.get("poll_launch_offset_seconds")
            if isinstance(start_receipt, dict)
            else None
        )
        write_json(
            staging / "freeze-receipt.json",
            {
                "run_id": run_id,
                "freeze_started_utc": utc_now(),
                "freeze_started_monotonic_ns": freeze_started_monotonic_ns,
                "registered_duration_seconds": registered_duration_seconds,
                "elapsed_at_freeze_seconds": elapsed_at_freeze_seconds,
                "poll_launch_offset_seconds": poll_launch_offset_seconds,
                "site": str(site) if site else None,
                "site_detection_error": site_detection_error,
                "snapshot_before_archive": True,
            },
        )
        capture_errors: list[dict[str, Any]] = []
        primary_url: str | None = None
        site_running_at_freeze: bool | None = None
        snapshot_name: str | None = None
        snapshot_returncode: int | None = None
        http_results = {"root": False, "team": False}
        if site is None:
            capture_errors.append(
                {"step": "site_detection", "error": site_detection_error}
            )
        else:
            describe_command = ["ddev", "describe", "-j"]
            try:
                describe = _run(describe_command, cwd=site, timeout=60)
                _write_command_artifacts(
                    staging, "ddev-describe", describe_command, describe
                )
                if describe.returncode == 0:
                    description = json.loads(describe.stdout or "{}")
                    write_json(staging / "ddev-describe.json", description)
                    primary_url = (
                        str(
                            ((description.get("raw") or {}).get("primary_url") or "")
                        ).rstrip("/")
                        or None
                    )
                    ddev_status = (
                        str(((description.get("raw") or {}).get("status") or ""))
                        .strip()
                        .lower()
                    )
                    site_running_at_freeze = ddev_status == "running"
                    if not site_running_at_freeze:
                        capture_errors.append(
                            {
                                "step": "ddev_not_running",
                                "error": f"DDEV status at freeze was {ddev_status or 'unknown'}",
                            }
                        )
                else:
                    capture_errors.append(
                        {
                            "step": "ddev_describe",
                            "error": describe.stderr or describe.stdout,
                        }
                    )
            except (StudyError, json.JSONDecodeError) as error:
                capture_errors.append({"step": "ddev_describe", "error": str(error)})

            if site_running_at_freeze:
                status_command = ["ddev", "drush", "status", "--format=json"]
                try:
                    status = _run(status_command, cwd=site, timeout=90)
                    _write_command_artifacts(
                        staging, "drush-status", status_command, status
                    )
                    if status.returncode == 0:
                        try:
                            write_json(
                                staging / "drush-status.json",
                                json.loads(status.stdout),
                            )
                        except json.JSONDecodeError:
                            write_text(staging / "drush-status.json", status.stdout)
                    else:
                        capture_errors.append(
                            {
                                "step": "drush_status",
                                "error": status.stderr or status.stdout,
                            }
                        )
                except StudyError as error:
                    capture_errors.append({"step": "drush_status", "error": str(error)})

                if primary_url:
                    for request_path, stem in (("/", "root"), ("/team", "team")):
                        try:
                            http_results[stem] = _capture_http(
                                site, staging, primary_url, request_path, stem
                            )
                            if not http_results[stem]:
                                capture_errors.append(
                                    {"step": f"http_{stem}", "error": "curl failed"}
                                )
                        except StudyError as error:
                            capture_errors.append(
                                {"step": f"http_{stem}", "error": str(error)}
                            )
                else:
                    capture_errors.append(
                        {"step": "primary_url", "error": "raw.primary_url unavailable"}
                    )

                snapshot_name = f"{run_id}-minute60"
                snapshot_command = ["ddev", "snapshot", "--name", snapshot_name]
                try:
                    snapshot = _run(snapshot_command, cwd=site, timeout=300)
                    snapshot_returncode = snapshot.returncode
                    _write_command_artifacts(
                        staging, "snapshot", snapshot_command, snapshot
                    )
                    if snapshot.returncode != 0:
                        capture_errors.append(
                            {
                                "step": "snapshot",
                                "error": snapshot.stderr or snapshot.stdout,
                            }
                        )
                except StudyError as error:
                    capture_errors.append({"step": "snapshot", "error": str(error)})

        if capture_errors:
            write_json(
                staging / "ddev-capture-errors.json",
                {"site_detected": site is not None, "errors": capture_errors},
            )

        composer_root = site if site is not None else work
        composer_path = composer_root / "composer.json"
        composer_identity: dict[str, Any] = {
            "observed_at": utc_now(),
            "source": str(composer_path.relative_to(work)),
            "site_relative_to_work": str(composer_root.relative_to(work)),
            "result": "unavailable",
        }
        if composer_path.is_file():
            try:
                composer = load_json(composer_path)
                if not isinstance(composer, dict):
                    raise ValueError("composer.json is not an object")
                composer_identity.update(
                    {
                        "result": "observed",
                        "sha256": sha256_file(composer_path),
                        "name": composer.get("name"),
                        "type": composer.get("type"),
                    }
                )
            except (json.JSONDecodeError, OSError, ValueError) as error:
                composer_identity["error"] = str(error)
        else:
            composer_identity["error"] = (
                "composer.json was absent at the registered stop"
            )
        write_json(staging / "composer-identity.json", composer_identity)

        archive = staging / "workspace.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(work, arcname=".", recursive=True)

        deadline = time.monotonic() + max(0, min(poll_wait_seconds, 60))
        while (
            not (run_dir / "poll-result.json").exists() and time.monotonic() < deadline
        ):
            time.sleep(0.25)
        score_command = [
            sys.executable,
            str(paths["script"]),
            "score",
            "--run-id",
            run_id,
        ]
        score_skipped_reason: str | None = None
        if site is not None and site_running_at_freeze is not True:
            score_returncode = None
            score_skipped_reason = "ddev_not_running_at_freeze"
            write_json(
                staging / "external-score-error.json",
                {
                    "skipped": True,
                    "reason": score_skipped_reason,
                    "note": "Skipped to avoid starting or repairing the frozen site.",
                },
            )
        else:
            try:
                score = _run(score_command, cwd=paths["root"], timeout=240)
                _write_command_artifacts(
                    staging, "external-score", score_command, score
                )
                score_returncode = score.returncode
            except StudyError as error:
                score_returncode = None
                write_json(staging / "external-score-error.json", {"error": str(error)})

        if site is not None and site_running_at_freeze:
            try:
                _capture_json_drush(
                    site,
                    staging,
                    "bundle-candidates.json",
                    BUNDLE_CANDIDATES_PHP,
                )
            except StudyError as error:
                write_json(
                    staging / "bundle-candidates.json",
                    {"capture_error": str(error), "items": []},
                )
            try:
                _capture_json_drush(
                    site,
                    staging,
                    "role-permissions.json",
                    ROLE_PERMISSIONS_PHP,
                )
            except StudyError as error:
                write_json(
                    staging / "role-permissions.json",
                    {"capture_error": str(error), "items": []},
                )
        else:
            unavailable_reason = (
                site_detection_error or "DDEV was not running at freeze"
            )
            write_json(
                staging / "bundle-candidates.json",
                {"capture_error": unavailable_reason, "items": []},
            )
            write_json(
                staging / "role-permissions.json",
                {"capture_error": unavailable_reason, "items": []},
            )

        copied: list[str] = []
        for filename in (
            "score.json",
            "run-meta.json",
            "milestones.jsonl",
            "poll-result.json",
            "captured-http.json",
            "answer.json",
        ):
            if _copy_if_present(run_dir / filename, staging / filename):
                copied.append(filename)
        belief_deadline = time.monotonic() + max(0, min(belief_wait_seconds, 900))
        belief_submitted = False
        belief_submitted_at: str | None = None
        while True:
            belief_state = load_json(human_dir / "belief-inventory.json", {})
            belief_submitted_at = (
                str(belief_state.get("submitted_at") or "").strip()
                if isinstance(belief_state, dict)
                else ""
            ) or None
            belief_answers = (
                belief_state.get("answers", [])
                if isinstance(belief_state, dict)
                else []
            )
            belief_submitted = (
                belief_submitted_at is not None
                and isinstance(belief_answers, list)
                and len(belief_answers) == len(instrument["belief_claims"])
                and all(
                    isinstance(answer, dict)
                    and answer.get("answer") in ANSWER_VALUES
                    and isinstance(answer.get("confidence"), int)
                    and not isinstance(answer.get("confidence"), bool)
                    and 1 <= answer["confidence"] <= 5
                    and answer.get("main_reason") in instrument["belief_bases"]
                    for answer in belief_answers
                )
            )
            if belief_submitted or time.monotonic() >= belief_deadline:
                break
            time.sleep(0.25)
        for relative in (
            "belief-inventory.json",
            "session-metadata.json",
            "observer-log.csv",
            "start-receipt.json",
            "poll-command.json",
            "poll-end-receipt.json",
        ):
            _copy_if_present(human_dir / relative, private_staging / relative)
        for private_directory in ("registered", "facilitator-only"):
            source_root = human_dir / private_directory
            for path in sorted(source_root.rglob("*")):
                if path.is_file():
                    _copy_if_present(
                        path,
                        private_staging
                        / private_directory
                        / path.relative_to(source_root),
                    )
        participant_packet = work / ".ddev" / "study-packet"
        for path in sorted(participant_packet.rglob("*")):
            if path.is_file():
                _copy_if_present(
                    path,
                    staging
                    / "participant-packet"
                    / path.relative_to(participant_packet),
                )
        if transcript is not None:
            shutil.copy2(
                transcript,
                private_staging / f"agent-transcript{transcript.suffix}",
            )

        timing = instrument.get("timing", {})
        early_tolerance = float(timing.get("freeze_early_tolerance_seconds", 1))
        late_tolerance = float(timing.get("freeze_late_tolerance_seconds", 10))
        poll_tolerance = float(timing.get("poll_launch_tolerance_seconds", 2))
        standard_duration = (
            registered_duration_seconds == instrument["duration_seconds"]
            and isinstance(elapsed_at_freeze_seconds, (int, float))
            and instrument["duration_seconds"] - early_tolerance
            <= elapsed_at_freeze_seconds
            <= instrument["duration_seconds"] + late_tolerance
            and isinstance(poll_launch_offset_seconds, (int, float))
            and 0 <= poll_launch_offset_seconds <= poll_tolerance
        )
        write_json(
            staging / "capture-status.json",
            {
                "run_id": run_id,
                "site_detected": site is not None,
                "site_running_at_freeze": site_running_at_freeze,
                "site": str(site) if site else None,
                "site_detection_error": site_detection_error,
                "primary_url": primary_url,
                "snapshot_name": snapshot_name,
                "snapshot_returncode": snapshot_returncode,
                "http_capture": http_results,
                "capture_errors": capture_errors,
                "workspace_archive": "workspace.tar.gz",
                "copied_harness_artifacts": copied,
                "missing_harness_artifacts": sorted(
                    set(
                        (
                            "score.json",
                            "run-meta.json",
                            "milestones.jsonl",
                            "poll-result.json",
                            "captured-http.json",
                        )
                    )
                    - set(copied)
                ),
                "external_score_returncode": score_returncode,
                "external_score_skipped_reason": score_skipped_reason,
                "belief_submitted_before_freeze_finalized": belief_submitted,
                "belief_submitted_at": belief_submitted_at,
                "registered_duration_seconds": registered_duration_seconds,
                "elapsed_at_freeze_seconds": elapsed_at_freeze_seconds,
                "poll_launch_offset_seconds": poll_launch_offset_seconds,
                "timing_tolerances_seconds": {
                    "freeze_early": early_tolerance,
                    "freeze_late": late_tolerance,
                    "poll_launch": poll_tolerance,
                },
                "standard_60_minute_duration": standard_duration,
                "runtime_identity_drift": runtime_identity_drift,
                "autonomous_only_score_fields_not_interpreted": sorted(
                    AUTONOMOUS_ONLY_SCORE_FIELDS
                ),
                "bundle_fallback": (
                    "All node bundle candidates are frozen. If automatic detection is empty, "
                    "the evaluator must run select-bundle and justify the chosen bundle."
                ),
                "freeze_completed_utc": utc_now(),
            },
        )
        write_json(staging / "capture-manifest.json", _manifest_for(staging))
        write_json(
            private_staging / "capture-manifest.json",
            _manifest_for(private_staging),
        )
        staging.replace(final)
        private_staging.replace(private_final)
    except Exception as error:
        write_json(
            staging / "freeze-error.json",
            {"error": str(error), "error_type": type(error).__name__, "at": utc_now()},
        )
        write_json(
            private_staging / "freeze-error.json",
            {"error": str(error), "error_type": type(error).__name__, "at": utc_now()},
        )
        raise
    return {
        "ok": True,
        "run_id": run_id,
        "minute_60": str(final),
        "snapshot_name": snapshot_name,
        "primary_url": primary_url,
        "site_detected": site is not None,
        "site_running_at_freeze": site_running_at_freeze,
        "capture_errors": capture_errors,
    }


def _event_issues(
    coded: Mapping[str, Any], instrument: Mapping[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    coding_status = coded.get("coding_status")
    if coding_status not in {"complete", "unavailable"}:
        issues.append(
            {"code": "invalid_interaction_coding_status", "path": "coded-events.json"}
        )
    event_codes = set(instrument["event_codes"])
    decisions = set(instrument["decision_objects"])
    layers = set(instrument["failure_layers"])
    scopes = set(instrument["failure_scopes"])
    fixes = set(instrument["candidate_fixes"])
    require_scope_fix = set(instrument["posthoc_scope_and_fix_required_for"])
    seen: set[str] = set()
    events = coded.get("events", [])
    if not isinstance(events, list):
        return [{"code": "coded_events_not_list", "path": "coded-events.json.events"}]
    for index, event in enumerate(events):
        path = f"coded-events.json.events[{index}]"
        if not isinstance(event, dict):
            issues.append({"code": "event_not_object", "path": path})
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            issues.append({"code": "missing_event_id", "path": path})
        elif event_id in seen:
            issues.append(
                {"code": "duplicate_event_id", "path": path, "value": event_id}
            )
        else:
            seen.add(event_id)
        code = event.get("event_code")
        if code not in event_codes:
            issues.append({"code": "invalid_event_code", "path": path, "value": code})
        if (
            code in {"DL-HARD", "DL-SOFT"}
            and event.get("decision_object") not in decisions
        ):
            issues.append({"code": "missing_or_invalid_decision_object", "path": path})
        layer = event.get("failure_layer")
        if layer is not None and layer not in layers:
            issues.append(
                {"code": "invalid_failure_layer", "path": path, "value": layer}
            )
        if code == "DE" and layer not in layers:
            issues.append({"code": "missing_dead_end_failure_layer", "path": path})
        if code in require_scope_fix:
            if event.get("failure_scope") not in scopes:
                issues.append(
                    {"code": "missing_or_invalid_failure_scope", "path": path}
                )
            if event.get("candidate_fix") not in fixes:
                issues.append(
                    {"code": "missing_or_invalid_candidate_fix", "path": path}
                )
            if not str(event.get("evidence_ref") or "").strip():
                issues.append({"code": "missing_event_evidence_ref", "path": path})
        lost = event.get("minutes_lost")
        if code in require_scope_fix and lost is None:
            issues.append({"code": "missing_minutes_lost", "path": path})
        if lost is not None and lost != "not_estimable":
            if (
                not isinstance(lost, (int, float))
                or isinstance(lost, bool)
                or lost <= 0
            ):
                issues.append(
                    {"code": "invalid_minutes_lost", "path": path, "value": lost}
                )
    if not str(coded.get("coded_at") or "").strip():
        issues.append(
            {"code": "posthoc_coding_not_completed", "path": "coded-events.json"}
        )
    if not str(coded.get("coder_id") or "").strip():
        issues.append(
            {"code": "missing_interaction_coder_id", "path": "coded-events.json"}
        )
    turns = coded.get("participant_turns")
    if coding_status == "unavailable":
        if not str(coded.get("unavailable_reason") or "").strip():
            issues.append(
                {
                    "code": "missing_interaction_unavailable_reason",
                    "path": "coded-events.json",
                }
            )
        if events or turns is not None:
            issues.append(
                {
                    "code": "unavailable_interaction_has_counts",
                    "path": "coded-events.json",
                }
            )
        issues.append(
            {"code": "interaction_coding_unavailable", "path": "coded-events.json"}
        )
    elif not isinstance(turns, int) or isinstance(turns, bool) or turns <= 0:
        issues.append(
            {"code": "invalid_participant_turns", "path": "coded-events.json"}
        )
    return issues


def _index_required_rows(
    rows: Any,
    *,
    id_key: str,
    expected_ids: set[str],
    path: str,
    code_prefix: str,
    issues: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index a fixed form section without allowing duplicate or malformed IDs."""

    items = rows if isinstance(rows, list) else []
    if not isinstance(rows, list):
        issues.append({"code": f"{code_prefix}_rows_not_list", "path": path})
    if len(items) != len(expected_ids):
        issues.append(
            {
                "code": f"{code_prefix}_row_count_mismatch",
                "path": path,
                "expected": len(expected_ids),
                "actual": len(items),
            }
        )
    indexed: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(items):
        if not isinstance(row, dict):
            continue
        identifier = row.get(id_key)
        identifier_path = f"{path}[{index}].{id_key}"
        if not isinstance(identifier, str) or identifier not in expected_ids:
            issues.append(
                {
                    "code": f"invalid_{code_prefix}_id",
                    "path": identifier_path,
                    "value": identifier,
                }
            )
            continue
        if identifier in indexed:
            issues.append(
                {
                    "code": f"duplicate_{code_prefix}_id",
                    "path": identifier_path,
                    "value": identifier,
                }
            )
            continue
        indexed[identifier] = row
    return indexed


def _frozen_evidence_issues(
    run_dir: Path, facilitator: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Check immutable capture structure without turning technical failure into exclusion."""

    issues: list[dict[str, Any]] = []
    observations: dict[str, Any] = {
        "minute_60_present": False,
        "manifest_verified": False,
        "private_manifest_verified": False,
        "composer_identity": None,
        "autonomous_access_probe_absent": True,
    }
    frozen = run_dir / "minute-60"
    private_frozen = facilitator / "frozen-minute-60"
    if not frozen.is_dir():
        issues.append({"code": "missing_minute_60_capture", "path": str(frozen)})
        return issues, observations
    observations["minute_60_present"] = True

    required = {
        "workspace.tar.gz",
        "capture-status.json",
        "capture-manifest.json",
        "freeze-receipt.json",
        "run-meta.json",
        "poll-result.json",
        "bundle-candidates.json",
        "role-permissions.json",
        "composer-identity.json",
        "participant-packet/task-card.md",
        "participant-packet/environment-card.md",
        "participant-packet/install-guidance-card.md",
    }
    for relative in sorted(required):
        if not (frozen / relative).is_file():
            issues.append({"code": "missing_frozen_artifact", "path": relative})

    private_required = {
        "belief-inventory.json",
        "session-metadata.json",
        "observer-log.csv",
        "start-receipt.json",
        "registered/instrument-v0.json",
        "registered/protocol.md",
        "capture-manifest.json",
    }
    if not private_frozen.is_dir():
        issues.append(
            {"code": "missing_private_minute_60_capture", "path": str(private_frozen)}
        )
    else:
        for relative in sorted(private_required):
            if not (private_frozen / relative).is_file():
                issues.append(
                    {"code": "missing_private_frozen_artifact", "path": relative}
                )

    manifest = load_json(frozen / "capture-manifest.json", {})
    entries = manifest.get("files", []) if isinstance(manifest, dict) else []
    manifest_ok = isinstance(entries, list)
    if not manifest_ok:
        issues.append(
            {"code": "invalid_capture_manifest", "path": "capture-manifest.json"}
        )
        entries = []
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            manifest_ok = False
            issues.append(
                {
                    "code": "invalid_manifest_entry",
                    "path": f"capture-manifest.json.files[{index}]",
                }
            )
            continue
        relative = entry.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or relative.startswith("/")
            or ".." in Path(relative).parts
        ):
            manifest_ok = False
            issues.append(
                {
                    "code": "unsafe_manifest_path",
                    "path": f"capture-manifest.json.files[{index}]",
                }
            )
            continue
        if relative in seen_paths:
            manifest_ok = False
            issues.append({"code": "duplicate_manifest_path", "path": relative})
            continue
        seen_paths.add(relative)
        artifact = frozen / relative
        if not artifact.is_file():
            manifest_ok = False
            issues.append({"code": "manifest_artifact_missing", "path": relative})
            continue
        if artifact.stat().st_size != entry.get("bytes"):
            manifest_ok = False
            issues.append({"code": "manifest_size_mismatch", "path": relative})
        if sha256_file(artifact) != entry.get("sha256"):
            manifest_ok = False
            issues.append({"code": "manifest_hash_mismatch", "path": relative})
    actual_public_paths = {
        path.relative_to(frozen).as_posix()
        for path in frozen.rglob("*")
        if path.is_file() and path.name != "capture-manifest.json"
    }
    for relative in sorted(actual_public_paths - seen_paths):
        manifest_ok = False
        issues.append({"code": "unlisted_frozen_artifact", "path": relative})
    observations["manifest_verified"] = manifest_ok and bool(entries)

    private_manifest = load_json(private_frozen / "capture-manifest.json", {})
    private_entries = (
        private_manifest.get("files", []) if isinstance(private_manifest, dict) else []
    )
    private_manifest_ok = isinstance(private_entries, list) and bool(private_entries)
    private_seen_paths: set[str] = set()
    if not isinstance(private_entries, list):
        private_entries = []
    for index, entry in enumerate(private_entries):
        relative = entry.get("path") if isinstance(entry, dict) else None
        if (
            not isinstance(relative, str)
            or not relative
            or relative.startswith("/")
            or ".." in Path(relative).parts
        ):
            private_manifest_ok = False
            issues.append(
                {
                    "code": "invalid_private_manifest_entry",
                    "path": f"capture-manifest.json.files[{index}]",
                }
            )
            continue
        artifact = private_frozen / relative
        if relative in private_seen_paths:
            private_manifest_ok = False
            issues.append({"code": "duplicate_private_manifest_path", "path": relative})
            continue
        private_seen_paths.add(relative)
        if (
            not artifact.is_file()
            or artifact.stat().st_size != entry.get("bytes")
            or sha256_file(artifact) != entry.get("sha256")
        ):
            private_manifest_ok = False
            issues.append({"code": "private_manifest_mismatch", "path": relative})
    actual_private_paths = {
        path.relative_to(private_frozen).as_posix()
        for path in private_frozen.rglob("*")
        if path.is_file() and path.name != "capture-manifest.json"
    }
    for relative in sorted(actual_private_paths - private_seen_paths):
        private_manifest_ok = False
        issues.append({"code": "unlisted_private_frozen_artifact", "path": relative})
    observations["private_manifest_verified"] = private_manifest_ok

    frozen_meta = load_json(frozen / "run-meta.json", None)
    live_meta = load_json(run_dir / "run-meta.json", {})
    meta = frozen_meta if isinstance(frozen_meta, dict) else live_meta
    if not isinstance(meta, dict) or meta.get("access_marker") != "":
        issues.append(
            {"code": "autonomous_access_marker_enabled", "path": "run-meta.json"}
        )

    capture = load_json(frozen / "capture-status.json", {})
    if not isinstance(capture, dict):
        issues.append({"code": "invalid_capture_status", "path": "capture-status.json"})
        capture = {}
    observations["registered_duration_seconds"] = capture.get(
        "registered_duration_seconds"
    )
    observations["elapsed_at_freeze_seconds"] = capture.get("elapsed_at_freeze_seconds")
    observations["poll_launch_offset_seconds"] = capture.get(
        "poll_launch_offset_seconds"
    )
    observations["standard_60_minute_duration"] = capture.get(
        "standard_60_minute_duration"
    )
    observations["runtime_identity_drift"] = capture.get("runtime_identity_drift", [])
    if observations["runtime_identity_drift"]:
        issues.append(
            {
                "code": "runtime_identity_drift",
                "path": "capture-status.json",
                "value": observations["runtime_identity_drift"],
            }
        )
    composer_receipt = load_json(frozen / "composer-identity.json", {})
    if isinstance(composer_receipt, dict):
        observations["composer_identity"] = composer_receipt.get("name")
    score_skipped_reason = capture.get("external_score_skipped_reason")
    if (
        capture.get("external_score_returncode") != 0
        and score_skipped_reason != "ddev_not_running_at_freeze"
    ):
        issues.append(
            {
                "code": "external_score_failed",
                "path": "capture-status.json",
                "value": capture.get("external_score_returncode"),
            }
        )
    if (
        capture.get("external_score_returncode") == 0
        and not (frozen / "score.json").is_file()
    ):
        issues.append({"code": "missing_external_score", "path": "score.json"})
    frozen_belief = load_json(private_frozen / "belief-inventory.json", {})
    if (
        not isinstance(frozen_belief, dict)
        or not str(frozen_belief.get("submitted_at") or "").strip()
    ):
        issues.append(
            {
                "code": "belief_not_submitted_before_freeze_finalized",
                "path": "belief-inventory.json",
            }
        )
    else:
        frozen_answers = frozen_belief.get("answers", [])
        if not isinstance(frozen_answers, list) or any(
            not isinstance(answer, dict)
            or answer.get("answer") not in ANSWER_VALUES
            or answer.get("main_reason") is None
            for answer in frozen_answers
        ):
            issues.append(
                {
                    "code": "frozen_belief_answers_incomplete",
                    "path": "belief-inventory.json",
                }
            )
    site_detected = capture.get("site_detected")
    if site_detected is None:
        site_detected = (frozen / "ddev-describe.json").is_file()
    site_running = capture.get("site_running_at_freeze")
    if site_running is None and (frozen / "ddev-describe.json").is_file():
        description = load_json(frozen / "ddev-describe.json", {})
        site_running = (
            str((((description.get("raw") or {}).get("status")) or "")).lower()
            == "running"
        )
    if site_detected is True and site_running is True:
        for relative in (
            "ddev-describe.json",
            "drush-status.json",
            "root.headers",
            "root.html",
            "team.headers",
            "team.html",
        ):
            if not (frozen / relative).is_file():
                issues.append({"code": "missing_live_site_capture", "path": relative})
        snapshot_returncode = capture.get("snapshot_returncode")
        if snapshot_returncode is None:
            snapshot_command = load_json(frozen / "snapshot.command.json", {})
            if isinstance(snapshot_command, dict):
                snapshot_returncode = snapshot_command.get("returncode")
        if snapshot_returncode != 0:
            issues.append(
                {
                    "code": "snapshot_failed",
                    "path": "capture-status.json",
                    "value": snapshot_returncode,
                }
            )
    elif not (frozen / "ddev-capture-errors.json").is_file():
        issues.append(
            {
                "code": "missing_no_site_evidence",
                "path": "ddev-capture-errors.json",
            }
        )

    for source in (
        load_json(frozen / "poll-result.json", {}),
        load_json(frozen / "score.json", {}),
    ):
        if isinstance(source, dict) and "MA" in (source.get("milestones") or {}):
            observations["autonomous_access_probe_absent"] = False
            issues.append(
                {"code": "autonomous_MA_milestone_present", "path": "minute-60"}
            )
    if (run_dir / "access-probe.json").exists() or (
        frozen / "access-probe.json"
    ).exists():
        observations["autonomous_access_probe_absent"] = False
        issues.append(
            {"code": "autonomous_access_probe_present", "path": "access-probe.json"}
        )

    archive = frozen / "workspace.tar.gz"
    if archive.is_file():
        try:
            with tarfile.open(archive, "r:gz") as tar:
                observations["snapshot_present_in_archive"] = any(
                    ".ddev/db_snapshots/" in member.name and member.isfile()
                    for member in tar.getmembers()
                )
        except (tarfile.TarError, json.JSONDecodeError, UnicodeDecodeError) as error:
            issues.append(
                {
                    "code": "invalid_workspace_archive",
                    "path": "workspace.tar.gz",
                    "error": str(error),
                }
            )
    return issues, observations


def _resolve_evidence_ref(ref: Any, run_dir: Path, facilitator: Path) -> Path | None:
    if not isinstance(ref, str) or not ref.strip():
        return None
    file_ref = ref.split("#", 1)[0]
    if file_ref.startswith("minute-60/"):
        relative = file_ref.removeprefix("minute-60/")
        manifest = load_json(run_dir / "minute-60" / "capture-manifest.json", {})
        registered_paths = {
            item.get("path")
            for item in (
                manifest.get("files", []) if isinstance(manifest, dict) else []
            )
            if isinstance(item, dict)
        }
        if relative not in registered_paths:
            return None
        candidate = run_dir / file_ref
    elif file_ref.startswith("evaluator-evidence/"):
        candidate = facilitator / file_ref
    else:
        return None
    candidate = candidate.resolve()
    allowed_root = (
        (run_dir / "minute-60").resolve()
        if file_ref.startswith("minute-60/")
        else (facilitator / "evaluator-evidence").resolve()
    )
    if candidate == allowed_root or not candidate.is_relative_to(allowed_root):
        return None
    return candidate if candidate.is_file() else None


def materialize_team_state(
    *,
    run_id: str,
    facilitator_root: Path,
    bundle_id: str,
    rationale: str,
    source: str = "manual",
    harness_root: Path = DEFAULT_HARNESS_ROOT,
) -> dict[str, Any]:
    """Select one frozen bundle candidate and preserve its exact observed state."""

    validate_run_id(run_id)
    if source not in {"manual", "automatic"}:
        raise StudyError("bundle source must be manual or automatic")
    if not bundle_id.strip() or not rationale.strip():
        raise StudyError("bundle ID and selection rationale are required")
    paths = _harness_paths(harness_root, run_id)
    human = _facilitator_dir(facilitator_root, paths["root"], run_id)
    frozen = paths["run_dir"] / "minute-60"
    candidates_value = load_json(frozen / "bundle-candidates.json", None)
    if isinstance(candidates_value, list):
        candidates = candidates_value
    elif isinstance(candidates_value, dict) and isinstance(
        candidates_value.get("items"), list
    ):
        candidates = candidates_value["items"]
    else:
        raise StudyError("frozen bundle candidates are missing or invalid")
    matches = [
        item
        for item in candidates
        if isinstance(item, dict) and item.get("bundle") == bundle_id
    ]
    if len(matches) != 1:
        raise StudyError(
            f"bundle {bundle_id!r} was not found exactly once in frozen candidates"
        )
    evaluator_path = human / "evaluator.json"
    evaluator = load_json(evaluator_path)
    if not isinstance(evaluator, dict):
        raise StudyError("evaluator form is missing or invalid")
    existing = evaluator.get("team_bundle_id")
    if existing not in {None, bundle_id}:
        raise StudyError(
            f"evaluator already selected a different team bundle: {existing}"
        )
    selected = matches[0]
    receipt = {
        "receipt_type": "frozen_team_state",
        "result": "observed",
        "observed_at": utc_now(),
        "method": "Exact bundle selected from minute-60/bundle-candidates.json",
        "source": source,
        "bundle_id": bundle_id,
        "selection_rationale": rationale,
        "frozen_source_sha256": sha256_file(frozen / "bundle-candidates.json"),
        "fields": selected.get("fields", {}),
        "node_count": selected.get("node_count"),
        "nodes": selected.get("nodes", []),
    }
    receipt_path = human / "evaluator-evidence" / "team-state.json"
    write_json(receipt_path, receipt)
    evaluator["team_bundle_source"] = source
    evaluator["team_bundle_id"] = bundle_id
    evaluator["team_bundle_rationale"] = rationale
    write_json(evaluator_path, evaluator)
    return {
        "ok": True,
        "run_id": run_id,
        "bundle_id": bundle_id,
        "source": source,
        "node_count": receipt["node_count"],
        "evidence_ref": "evaluator-evidence/team-state.json",
    }


def steering_status(
    *,
    run_id: str,
    facilitator_root: Path,
    harness_root: Path = DEFAULT_HARNESS_ROOT,
) -> dict[str, Any]:
    """Expose the live, observable M4 trigger without exposing the rubric."""

    validate_run_id(run_id)
    paths = _harness_paths(harness_root, run_id)
    human = _facilitator_dir(facilitator_root, paths["root"], run_id)
    milestones: dict[str, Any] = {}
    live_log = paths["run_dir"] / "milestones.jsonl"
    if live_log.is_file():
        for line in live_log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("milestone") in {"M1", "M4", "MG"}:
                milestones[event["milestone"]] = event.get("t")
    poll = load_json(paths["run_dir"] / "poll-result.json", {})
    if isinstance(poll, dict):
        for name, value in (poll.get("milestones") or {}).items():
            milestones.setdefault(name, value)
    m4 = milestones.get("M4")
    steering = load_json(human / "steering.json", {})
    return {
        "ok": True,
        "run_id": run_id,
        "m4_seconds": m4,
        "m4_trigger_reached": isinstance(m4, (int, float)),
        "milestones": milestones,
        "participant_statement_trigger_requires_live_observer_judgment": True,
        "steering_record": steering,
    }


def _clock_to_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    parts = value.strip().split(":")
    if len(parts) not in {2, 3}:
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if any(number < 0 for number in numbers) or any(
        number >= 60 for number in numbers[1:]
    ):
        return None
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def _valid_pass_evidence(
    criterion_id: str, kind: str, ref: str, resolved: Path
) -> bool:
    """Reject merely existing files as proof of a criterion-specific pass."""

    if ref.startswith("evaluator-evidence/"):
        if kind in {
            "root_http",
            "composer_identity",
            "drush_bootstrap",
            "anonymous_team_http",
        }:
            return False
        receipt = load_json(resolved, {})
        return (
            isinstance(receipt, dict)
            and receipt.get("result") == "pass"
            and receipt.get("criterion_id") == criterion_id
            and receipt.get("evidence_kind") == kind
            and bool(str(receipt.get("observed_at") or "").strip())
            and bool(str(receipt.get("method") or "").strip())
        )
    exact_ref = ref.split("#", 1)[0]
    if kind == "root_http" and exact_ref == "minute-60/root.headers":
        root_body = resolved.with_name("root.html")
        return (
            bool(re.search(r"^HTTP/\S+\s+200\b", resolved.read_text(errors="replace")))
            and root_body.is_file()
            and root_body.stat().st_size >= 200
        )
    if kind == "anonymous_team_http" and exact_ref == "minute-60/team.headers":
        return bool(
            re.search(r"^HTTP/\S+\s+200\b", resolved.read_text(errors="replace"))
        )
    if kind == "composer_identity" and exact_ref == "minute-60/composer-identity.json":
        identity = load_json(resolved, {})
        return (
            isinstance(identity, dict)
            and identity.get("result") == "observed"
            and identity.get("name") == "drupal/cms"
        )
    if kind == "drush_bootstrap" and exact_ref == "minute-60/drush-status.json":
        status = load_json(resolved, {})
        return (
            isinstance(status, dict)
            and str(status.get("bootstrap", "")).lower() == "successful"
        )
    return False


def validate_session(
    *,
    run_id: str,
    facilitator_root: Path,
    harness_root: Path = DEFAULT_HARNESS_ROOT,
) -> dict[str, Any]:
    validate_run_id(run_id)
    paths = _harness_paths(harness_root, run_id)
    human = _facilitator_dir(facilitator_root, paths["root"], run_id)
    frozen_private = human / "frozen-minute-60"
    frozen_instrument_path = frozen_private / "registered" / "instrument-v0.json"
    instrument = load_instrument(
        frozen_instrument_path
        if frozen_instrument_path.is_file()
        else human / "registered" / "instrument-v0.json"
    )
    issues: list[dict[str, Any]] = []
    evidence_issues, evidence = _frozen_evidence_issues(paths["run_dir"], human)
    issues.extend(evidence_issues)
    required = (
        "session-metadata.json",
        "belief-inventory.json",
        "belief-coding.json",
        "evaluator.json",
        "coded-events.json",
        "observer-log.csv",
        "transfer.json",
        "comprehension.json",
        "steering.json",
    )
    for filename in required:
        if not (human / filename).is_file():
            issues.append({"code": "missing_form", "path": filename})

    session_metadata = load_json(human / "session-metadata.json", {})
    frozen_metadata = load_json(frozen_private / "session-metadata.json", None)
    if not isinstance(session_metadata, dict):
        issues.append(
            {"code": "invalid_session_metadata", "path": "session-metadata.json"}
        )
    else:
        if isinstance(frozen_metadata, dict) and session_metadata != frozen_metadata:
            issues.append(
                {
                    "code": "session_metadata_changed_after_freeze",
                    "path": "session-metadata.json",
                }
            )
        if not session_metadata.get("rehearsal") and not evidence.get(
            "standard_60_minute_duration"
        ):
            issues.append(
                {
                    "code": "nonstandard_participant_timing",
                    "path": "minute-60/capture-status.json",
                    "registered_duration_seconds": evidence.get(
                        "registered_duration_seconds"
                    ),
                    "elapsed_at_freeze_seconds": evidence.get(
                        "elapsed_at_freeze_seconds"
                    ),
                    "poll_launch_offset_seconds": evidence.get(
                        "poll_launch_offset_seconds"
                    ),
                }
            )
        registered_instrument = frozen_private / "registered" / "instrument-v0.json"
        registered_protocol = frozen_private / "registered" / "protocol.md"
        for label, registered, expected_hash in (
            (
                "instrument",
                registered_instrument,
                session_metadata.get("instrument_sha256"),
            ),
            ("protocol", registered_protocol, session_metadata.get("protocol_sha256")),
        ):
            if not registered.is_file() or sha256_file(registered) != expected_hash:
                issues.append(
                    {
                        "code": f"registered_{label}_identity_mismatch",
                        "path": str(registered),
                    }
                )
        for label, identity in session_metadata.get("harness_identity", {}).items():
            if (
                not isinstance(identity, dict)
                or identity.get("registered_path") is None
            ):
                continue
            registered = frozen_private / str(identity["registered_path"])
            if not registered.is_file() or sha256_file(registered) != identity.get(
                "sha256"
            ):
                issues.append(
                    {"code": "registered_harness_identity_mismatch", "path": label}
                )
        for label, identity in session_metadata.get(
            "study_runner_identity", {}
        ).items():
            if (
                not isinstance(identity, dict)
                or identity.get("registered_path") is None
            ):
                continue
            registered = frozen_private / str(identity["registered_path"])
            if not registered.is_file() or sha256_file(registered) != identity.get(
                "sha256"
            ):
                issues.append(
                    {"code": "registered_study_runner_identity_mismatch", "path": label}
                )
        card_root = paths["run_dir"] / "minute-60" / "participant-packet"
        for name, filename in (
            ("task", "task-card.md"),
            ("environment", "environment-card.md"),
            ("install_guidance", "install-guidance-card.md"),
        ):
            card = card_root / filename
            expected_hash = (session_metadata.get("cards", {}).get(name) or {}).get(
                "sha256"
            )
            if (
                not card.is_file()
                or _card_hash(card.read_text(encoding="utf-8")) != expected_hash
            ):
                issues.append(
                    {"code": "participant_card_identity_mismatch", "path": filename}
                )

    coded = load_json(human / "coded-events.json", {})
    issues.extend(_event_issues(coded, instrument))

    expected_claims = {item["id"] for item in instrument["belief_claims"]}
    belief = load_json(human / "belief-inventory.json", {})
    answers = belief.get("answers", []) if isinstance(belief, dict) else []
    answers_by_claim = _index_required_rows(
        answers,
        id_key="claim_id",
        expected_ids=expected_claims,
        path="belief-inventory.json.answers",
        code_prefix="belief_claim",
        issues=issues,
    )
    for index, answer in enumerate(answers if isinstance(answers, list) else []):
        path = f"belief-inventory.json.answers[{index}]"
        if not isinstance(answer, dict):
            issues.append({"code": "belief_answer_not_object", "path": path})
            continue
        if answer.get("answer") not in ANSWER_VALUES:
            issues.append({"code": "missing_or_invalid_belief_answer", "path": path})
        confidence = answer.get("confidence")
        if (
            not isinstance(confidence, int)
            or isinstance(confidence, bool)
            or not 1 <= confidence <= 5
        ):
            issues.append({"code": "missing_or_invalid_confidence", "path": path})
        if answer.get("main_reason") not in set(instrument["belief_bases"]):
            issues.append({"code": "missing_or_invalid_belief_basis", "path": path})
    if set(answers_by_claim) != expected_claims:
        issues.append(
            {"code": "belief_claim_set_mismatch", "path": "belief-inventory.json"}
        )
    frozen_belief = load_json(
        frozen_private / "belief-inventory.json",
        None,
    )
    if isinstance(frozen_belief, dict):
        frozen_by_claim = _index_required_rows(
            frozen_belief.get("answers", []),
            id_key="claim_id",
            expected_ids=expected_claims,
            path="frozen-minute-60/belief-inventory.json.answers",
            code_prefix="frozen_belief_claim",
            issues=issues,
        )
        for index, answer in enumerate(answers if isinstance(answers, list) else []):
            if not isinstance(answer, dict):
                continue
            claim_id = answer.get("claim_id")
            frozen_answer = (
                frozen_by_claim.get(claim_id) if isinstance(claim_id, str) else None
            )
            for field in ("statement", "answer", "confidence", "main_reason", "note"):
                if not isinstance(frozen_answer, dict) or answer.get(
                    field
                ) != frozen_answer.get(field):
                    issues.append(
                        {
                            "code": "participant_belief_changed_after_freeze",
                            "path": f"belief-inventory.json.answers[{index}].{field}",
                        }
                    )
        live_submitted_at = (
            belief.get("submitted_at") if isinstance(belief, dict) else None
        )
        if live_submitted_at != frozen_belief.get("submitted_at"):
            issues.append(
                {
                    "code": "participant_belief_changed_after_freeze",
                    "path": "belief-inventory.json.submitted_at",
                }
            )

    belief_coding = load_json(human / "belief-coding.json", {})
    coding_rows = (
        belief_coding.get("claims", []) if isinstance(belief_coding, dict) else []
    )
    coding_by_claim = _index_required_rows(
        coding_rows,
        id_key="claim_id",
        expected_ids=expected_claims,
        path="belief-coding.json.claims",
        code_prefix="belief_coding_claim",
        issues=issues,
    )
    if set(coding_by_claim) != expected_claims:
        issues.append(
            {"code": "belief_coding_set_mismatch", "path": "belief-coding.json"}
        )

    evaluator = load_json(human / "evaluator.json", {})
    if (
        not isinstance(evaluator, dict)
        or not str(evaluator.get("evaluator_id") or "").strip()
    ):
        issues.append({"code": "missing_evaluator_id", "path": "evaluator.json"})
    if (
        not isinstance(evaluator, dict)
        or not str(evaluator.get("completed_at") or "").strip()
    ):
        issues.append(
            {"code": "missing_evaluator_completed_at", "path": "evaluator.json"}
        )
    criteria = evaluator.get("criteria", []) if isinstance(evaluator, dict) else []
    expected_criteria = {item["id"] for item in instrument["technical_criteria"]}
    criteria_by_id = _index_required_rows(
        criteria,
        id_key="criterion_id",
        expected_ids=expected_criteria,
        path="evaluator.json.criteria",
        code_prefix="criterion",
        issues=issues,
    )
    for index, criterion in enumerate(criteria if isinstance(criteria, list) else []):
        path = f"evaluator.json.criteria[{index}]"
        if not isinstance(criterion, dict):
            issues.append({"code": "criterion_not_object", "path": path})
            continue
        criterion_result = criterion.get("result")
        if criterion_result not in TRUTH_VALUES:
            issues.append({"code": "missing_or_invalid_criterion_result", "path": path})
        elif not criterion.get("evidence_refs"):
            issues.append({"code": "criterion_missing_evidence_ref", "path": path})
        else:
            for ref in criterion["evidence_refs"]:
                if _resolve_evidence_ref(ref, paths["run_dir"], human) is None:
                    issues.append(
                        {
                            "code": "criterion_unresolvable_evidence_ref",
                            "path": path,
                            "value": ref,
                        }
                    )
        expected_kinds = next(
            (
                item["required_pass_evidence"]
                for item in instrument["technical_criteria"]
                if item["id"] == criterion.get("criterion_id")
            ),
            [],
        )
        if criterion_result == "pass":
            evidence_by_kind = criterion.get("evidence_by_kind", {})
            for kind in expected_kinds:
                ref = (
                    evidence_by_kind.get(kind)
                    if isinstance(evidence_by_kind, dict)
                    else None
                )
                resolved = _resolve_evidence_ref(ref, paths["run_dir"], human)
                if resolved is None:
                    issues.append(
                        {
                            "code": "criterion_missing_required_pass_evidence",
                            "path": f"{path}.evidence_by_kind.{kind}",
                        }
                    )
                    continue
                if not _valid_pass_evidence(
                    str(criterion.get("criterion_id")), kind, str(ref), resolved
                ):
                    issues.append(
                        {
                            "code": "invalid_criterion_pass_evidence",
                            "path": str(ref),
                            "evidence_kind": kind,
                        }
                    )
        elif criterion_result in {"fail", "not_tested"}:
            if not str(criterion.get("notes") or "").strip():
                issues.append({"code": "failed_criterion_missing_notes", "path": path})
            valid_result_receipt = False
            for ref in criterion.get("evidence_refs", []):
                if not str(ref).startswith("evaluator-evidence/"):
                    continue
                resolved = _resolve_evidence_ref(ref, paths["run_dir"], human)
                receipt = load_json(resolved, {}) if resolved else {}
                if (
                    isinstance(receipt, dict)
                    and receipt.get("result") == criterion_result
                    and receipt.get("criterion_id") == criterion.get("criterion_id")
                    and bool(str(receipt.get("observed_at") or "").strip())
                    and bool(str(receipt.get("method") or "").strip())
                ):
                    valid_result_receipt = True
            if not valid_result_receipt:
                issues.append(
                    {"code": "missing_valid_criterion_result_receipt", "path": path}
                )
    if set(criteria_by_id) != expected_criteria:
        issues.append({"code": "criterion_set_mismatch", "path": "evaluator.json"})
    team_selection_required = any(
        (criteria_by_id.get(criterion_id) or {}).get("result") == "pass"
        for criterion_id in ("T2", "T3")
    )
    selected_bundle = (
        evaluator.get("team_bundle_id") if isinstance(evaluator, dict) else None
    )
    selected_source = (
        evaluator.get("team_bundle_source") if isinstance(evaluator, dict) else None
    )
    selected_rationale = (
        evaluator.get("team_bundle_rationale") if isinstance(evaluator, dict) else None
    )
    if team_selection_required or selected_bundle is not None:
        team_state = load_json(human / "evaluator-evidence" / "team-state.json", {})
        if (
            selected_source not in {"manual", "automatic"}
            or not str(selected_bundle or "").strip()
            or not str(selected_rationale or "").strip()
            or not isinstance(team_state, dict)
            or team_state.get("receipt_type") != "frozen_team_state"
            or team_state.get("bundle_id") != selected_bundle
        ):
            issues.append(
                {
                    "code": "missing_or_invalid_materialized_team_state",
                    "path": "evaluator.json",
                }
            )
    truth_rows = (
        evaluator.get("belief_truth", []) if isinstance(evaluator, dict) else []
    )
    truth_rows_by_claim = _index_required_rows(
        truth_rows,
        id_key="claim_id",
        expected_ids=expected_claims,
        path="evaluator.json.belief_truth",
        code_prefix="belief_truth_claim",
        issues=issues,
    )
    for index, row in enumerate(truth_rows if isinstance(truth_rows, list) else []):
        path = f"evaluator.json.belief_truth[{index}]"
        if not isinstance(row, dict) or row.get("truth") not in TRUTH_VALUES:
            issues.append({"code": "missing_or_invalid_belief_truth", "path": path})
            continue
        if not row.get("evidence_refs"):
            issues.append({"code": "belief_truth_missing_evidence_ref", "path": path})
        else:
            for ref in row["evidence_refs"]:
                if _resolve_evidence_ref(ref, paths["run_dir"], human) is None:
                    issues.append(
                        {
                            "code": "belief_truth_unresolvable_evidence_ref",
                            "path": path,
                            "value": ref,
                        }
                    )
    truth_by_claim = {
        claim_id: row.get("truth") for claim_id, row in truth_rows_by_claim.items()
    }
    if set(truth_by_claim) != expected_claims:
        issues.append({"code": "belief_truth_set_mismatch", "path": "evaluator.json"})

    scopes = set(instrument["failure_scopes"])
    fixes = set(instrument["candidate_fixes"])
    for index, answer in enumerate(answers if isinstance(answers, list) else []):
        if not isinstance(answer, dict):
            continue
        claim_id = answer.get("claim_id")
        false_confident = (
            isinstance(claim_id, str)
            and answer.get("answer") == "yes"
            and isinstance(answer.get("confidence"), int)
            and answer["confidence"] >= 4
            and truth_by_claim.get(claim_id) == "fail"
        )
        if false_confident:
            coding = coding_by_claim.get(claim_id, {})
            if coding.get("failure_scope") not in scopes:
                issues.append(
                    {
                        "code": "false_confident_missing_failure_scope",
                        "path": f"belief-coding.json:{answer.get('claim_id')}",
                    }
                )
            if coding.get("candidate_fix") not in fixes:
                issues.append(
                    {
                        "code": "false_confident_missing_candidate_fix",
                        "path": f"belief-coding.json:{answer.get('claim_id')}",
                    }
                )
            if not coding.get("evidence_refs"):
                issues.append(
                    {
                        "code": "false_confident_missing_evidence_ref",
                        "path": f"belief-coding.json:{answer.get('claim_id')}",
                    }
                )
            if not str(coding.get("coder_id") or "").strip():
                issues.append(
                    {
                        "code": "false_confident_missing_coder_id",
                        "path": f"belief-coding.json:{answer.get('claim_id')}",
                    }
                )

    transfer = load_json(human / "transfer.json", {})
    precondition = (
        transfer.get("transfer_precondition") if isinstance(transfer, dict) else None
    )
    outcome = transfer.get("transfer_outcome") if isinstance(transfer, dict) else None
    assistance = transfer.get("assistance") if isinstance(transfer, dict) else None
    elapsed_seconds = (
        transfer.get("elapsed_seconds") if isinstance(transfer, dict) else None
    )
    transfer_refs = (
        transfer.get("evidence_refs", []) if isinstance(transfer, dict) else []
    )
    if precondition not in set(instrument["transfer_preconditions"]):
        issues.append(
            {"code": "invalid_transfer_precondition", "path": "transfer.json"}
        )
    else:
        if not isinstance(transfer_refs, list) or not transfer_refs:
            issues.append(
                {"code": "transfer_missing_evidence_ref", "path": "transfer.json"}
            )
        else:
            valid_transfer_receipt = False
            for ref in transfer_refs:
                resolved = _resolve_evidence_ref(ref, paths["run_dir"], human)
                if resolved is None:
                    issues.append(
                        {
                            "code": "transfer_unresolvable_evidence_ref",
                            "path": "transfer.json",
                            "value": ref,
                        }
                    )
                elif str(ref).startswith("evaluator-evidence/"):
                    receipt = load_json(resolved, {})
                    expected_result = (
                        outcome if precondition == "eligible" else precondition
                    )
                    valid_transfer_receipt = (
                        isinstance(receipt, dict)
                        and receipt.get("result") == expected_result
                        and bool(str(receipt.get("observed_at") or "").strip())
                        and bool(str(receipt.get("method") or "").strip())
                    ) or valid_transfer_receipt
            if not valid_transfer_receipt:
                issues.append(
                    {"code": "missing_valid_transfer_receipt", "path": "transfer.json"}
                )
    if precondition == "eligible":
        if outcome not in set(instrument["transfer_outcomes"]):
            issues.append({"code": "invalid_transfer_outcome", "path": "transfer.json"})
        if assistance not in set(instrument["transfer_assistance"]):
            issues.append(
                {"code": "invalid_transfer_assistance", "path": "transfer.json"}
            )
        if (
            not isinstance(elapsed_seconds, (int, float))
            or isinstance(elapsed_seconds, bool)
            or elapsed_seconds <= 0
            or elapsed_seconds > instrument["transfer_duration_seconds"]
        ):
            issues.append(
                {"code": "invalid_transfer_elapsed_seconds", "path": "transfer.json"}
            )
        if outcome == "success" and assistance != "none":
            issues.append(
                {"code": "assisted_transfer_cannot_be_success", "path": "transfer.json"}
            )
        if outcome == "assisted" and assistance == "none":
            issues.append(
                {
                    "code": "assisted_transfer_missing_assistance",
                    "path": "transfer.json",
                }
            )
    elif precondition in {"blocked_by_build", "not_run"}:
        if any(value is not None for value in (outcome, assistance, elapsed_seconds)):
            issues.append(
                {
                    "code": "outcome_present_when_transfer_ineligible",
                    "path": "transfer.json",
                }
            )
        if not str(transfer.get("notes") or "").strip():
            issues.append(
                {"code": "ineligible_transfer_missing_notes", "path": "transfer.json"}
            )

    steering = load_json(human / "steering.json", {})
    exposed = steering.get("steering_exposed") if isinstance(steering, dict) else None
    source = (
        steering.get("steering_trigger_source") if isinstance(steering, dict) else None
    )
    result = steering.get("result") if isinstance(steering, dict) else None
    if not isinstance(exposed, bool):
        issues.append({"code": "invalid_steering_exposed", "path": "steering.json"})
    if source not in set(instrument["steering"]["trigger_sources"]):
        issues.append({"code": "invalid_steering_trigger", "path": "steering.json"})
    if result not in set(instrument["steering"]["results"]):
        issues.append({"code": "invalid_steering_result", "path": "steering.json"})
    if exposed is False and (source != "not_reached" or result != "not_reached"):
        issues.append(
            {"code": "unexposed_steering_has_result", "path": "steering.json"}
        )
    if exposed is True and source == "not_reached":
        issues.append(
            {"code": "exposed_steering_missing_trigger", "path": "steering.json"}
        )
    if exposed is True and result == "not_reached":
        issues.append(
            {"code": "exposed_steering_missing_result", "path": "steering.json"}
        )
    if exposed is True and not str(steering.get("trigger_clock") or "").strip():
        issues.append(
            {"code": "exposed_steering_missing_clock", "path": "steering.json"}
        )
    if exposed is True:
        steering_refs = steering.get("evidence_refs", [])
        if not isinstance(steering_refs, list) or not steering_refs:
            issues.append(
                {"code": "exposed_steering_missing_evidence", "path": "steering.json"}
            )
        else:
            for ref in steering_refs:
                if _resolve_evidence_ref(ref, paths["run_dir"], human) is None:
                    issues.append(
                        {
                            "code": "steering_unresolvable_evidence_ref",
                            "path": "steering.json",
                            "value": ref,
                        }
                    )
        trigger_seconds = _clock_to_seconds(steering.get("trigger_clock"))
        if trigger_seconds is None:
            issues.append(
                {"code": "invalid_steering_trigger_clock", "path": "steering.json"}
            )
        elif trigger_seconds > 2400:
            issues.append(
                {"code": "steering_trigger_after_minute_40", "path": "steering.json"}
            )
        if source == "m4":
            frozen_poll = load_json(
                paths["run_dir"] / "minute-60" / "poll-result.json", {}
            )
            m4 = (
                (frozen_poll.get("milestones") or {}).get("M4")
                if isinstance(frozen_poll, dict)
                else None
            )
            tolerance = float(
                instrument.get("steering", {}).get("exposure_tolerance_seconds", 60)
            )
            if not isinstance(m4, (int, float)):
                issues.append(
                    {"code": "m4_steering_without_m4", "path": "steering.json"}
                )
            elif trigger_seconds is not None and not (
                m4 <= trigger_seconds <= m4 + tolerance
            ):
                issues.append(
                    {"code": "late_or_early_m4_steering", "path": "steering.json"}
                )
        elif source == "participant_statement":
            frozen_poll = load_json(
                paths["run_dir"] / "minute-60" / "poll-result.json", {}
            )
            m4 = (
                (frozen_poll.get("milestones") or {}).get("M4")
                if isinstance(frozen_poll, dict)
                else None
            )
            if (
                isinstance(m4, (int, float))
                and trigger_seconds is not None
                and m4 < trigger_seconds
            ):
                issues.append(
                    {"code": "participant_statement_after_m4", "path": "steering.json"}
                )
    elif exposed is False:
        frozen_poll = load_json(paths["run_dir"] / "minute-60" / "poll-result.json", {})
        m4 = (
            (frozen_poll.get("milestones") or {}).get("M4")
            if isinstance(frozen_poll, dict)
            else None
        )
        if isinstance(m4, (int, float)) and m4 <= 2400:
            issues.append(
                {"code": "missed_m4_steering_trigger", "path": "steering.json"}
            )

    comprehension = load_json(human / "comprehension.json", {})
    if (
        not isinstance(comprehension, dict)
        or not str(comprehension.get("one_change_debrief") or "").strip()
    ):
        issues.append(
            {"code": "missing_one_change_debrief", "path": "comprehension.json"}
        )
    if isinstance(comprehension, dict):
        responses = comprehension.get("responses", [])
        if not isinstance(responses, list) or len(responses) != len(
            instrument["comprehension_questions"]
        ):
            issues.append(
                {
                    "code": "comprehension_response_set_mismatch",
                    "path": "comprehension.json",
                }
            )
        else:
            for index, response in enumerate(responses):
                response_path = f"comprehension.json.responses[{index}]"
                if (
                    not isinstance(response, dict)
                    or not str(response.get("answer") or "").strip()
                ):
                    issues.append(
                        {"code": "missing_comprehension_answer", "path": response_path}
                    )
                score_value = (
                    response.get("score") if isinstance(response, dict) else None
                )
                if (
                    not isinstance(score_value, int)
                    or isinstance(score_value, bool)
                    or score_value not in {0, 1, 2}
                ):
                    issues.append(
                        {"code": "invalid_comprehension_score", "path": response_path}
                    )
        ratings = comprehension.get("ratings", {})
        for rating in instrument["subjective_ratings"]:
            value = ratings.get(rating) if isinstance(ratings, dict) else None
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= 5
            ):
                issues.append(
                    {
                        "code": "invalid_subjective_rating",
                        "path": f"comprehension.json.ratings.{rating}",
                    }
                )
    return {
        "ok": not issues,
        "run_id": run_id,
        "issues": issues,
        "evidence": evidence,
    }


def _rate(count: int, turns: int | None) -> float | None:
    if not turns:
        return None
    return round(count * 10 / turns, 3)


def _validation_lane(issue: Mapping[str, Any]) -> str:
    """Assign validation problems to the measure they can invalidate."""

    code = str(issue.get("code") or "")
    path = str(issue.get("path") or "")
    if code == "missing_form":
        return {
            "coded-events.json": "interaction",
            "belief-inventory.json": "belief",
            "belief-coding.json": "belief",
            "transfer.json": "transfer",
            "steering.json": "steering",
            "comprehension.json": "comprehension",
        }.get(path, "technical")
    if code == "nonstandard_participant_timing":
        return "timing"
    if any(token in code for token in ("transfer", "assistance")) or code.startswith(
        ("outcome_", "assisted_", "ineligible_")
    ):
        return "transfer"
    if "steering" in code or code.startswith(
        ("m4_", "missed_m4", "late_or_early_m4", "participant_statement_after_m4")
    ):
        return "steering"
    if any(token in code for token in ("comprehension", "subjective", "debrief")):
        return "comprehension"
    if "belief" in code or "confidence" in code:
        return "belief"
    interaction_codes = {
        "coded_events_not_list",
        "event_not_object",
        "missing_event_id",
        "duplicate_event_id",
        "invalid_event_code",
        "missing_or_invalid_decision_object",
        "invalid_failure_layer",
        "missing_dead_end_failure_layer",
        "missing_or_invalid_failure_scope",
        "missing_or_invalid_candidate_fix",
        "missing_event_evidence_ref",
        "missing_minutes_lost",
        "invalid_minutes_lost",
        "invalid_participant_turns",
        "posthoc_coding_not_completed",
        "missing_interaction_coder_id",
        "invalid_interaction_coding_status",
        "missing_interaction_unavailable_reason",
        "unavailable_interaction_has_counts",
        "interaction_coding_unavailable",
    }
    if code in interaction_codes:
        return "interaction"
    if code in {
        "external_score_failed",
        "missing_external_score",
        "snapshot_failed",
        "invalid_workspace_archive",
    }:
        return "capture_reproducibility"
    return "technical"


def _partial_interaction(
    coded: Mapping[str, Any], instrument: Mapping[str, Any]
) -> dict[str, Any]:
    events = coded.get("events", [])
    turns = coded.get("participant_turns")
    codes = ("DL-HARD", "DL-SOFT", "VB", "DE", "R-HUMAN", "R-INFRA", "MANUAL")
    counts = {
        code: sum(1 for event in events if event.get("event_code") == code)
        for code in codes
    }
    return {
        "participant_turns": turns,
        **{
            code: {
                "count": count,
                "per_10_participant_turns": _rate(count, turns)
                if code in {"DL-HARD", "DL-SOFT"}
                else None,
            }
            for code, count in counts.items()
        },
        "decision_object_counts": {
            decision: sum(
                1
                for event in events
                if event.get("event_code") in {"DL-HARD", "DL-SOFT"}
                and event.get("decision_object") == decision
            )
            for decision in instrument["decision_objects"]
        },
    }


def _partial_beliefs(
    belief: Mapping[str, Any],
    belief_coding: Mapping[str, Any],
    evaluator: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    truth = {item["claim_id"]: item["truth"] for item in evaluator["belief_truth"]}
    coding = {item["claim_id"]: item for item in belief_coding["claims"]}
    rows: list[dict[str, Any]] = []
    for answer in belief["answers"]:
        actual = truth[answer["claim_id"]]
        category = "aligned_or_low_confidence"
        if answer["answer"] == "yes" and answer["confidence"] >= 4 and actual == "fail":
            category = "false_confident"
        elif answer["answer"] == "no" and actual == "pass":
            category = "false_negative"
        elif answer["answer"] == "unsure":
            category = "uncertain"
        elif (
            answer["answer"] == "yes"
            and answer["confidence"] >= 4
            and actual == "not_tested"
        ):
            category = "unsupported_confidence"
        coded = coding[answer["claim_id"]]
        rows.append(
            {
                "claim_id": answer["claim_id"],
                "participant_answer": answer["answer"],
                "confidence": answer["confidence"],
                "main_reason": answer["main_reason"],
                "evaluator_truth": actual,
                "category": category,
                "failure_scope": coded.get("failure_scope")
                if category == "false_confident"
                else None,
                "candidate_fix": coded.get("candidate_fix")
                if category == "false_confident"
                else None,
                "evidence_refs": coded.get("evidence_refs", []),
            }
        )
    categories = (
        "false_confident",
        "false_negative",
        "uncertain",
        "unsupported_confidence",
        "aligned_or_low_confidence",
    )
    return rows, {
        category: sum(1 for item in rows if item["category"] == category)
        for category in categories
    }


def _markdown_readout(readout: Mapping[str, Any]) -> str:
    if readout.get("readout_status") in {"incomplete", "partial"}:
        status = str(readout["readout_status"])
        lines = [
            f"# {status.title()} session readout: {readout['run_id']}",
            "",
            f"Governed value at registered stop: `{readout.get('verified_governed_value_at_registered_stop')}`.",
            f"Governed value at minute 60: `{readout.get('verified_governed_value_at_60')}`.",
            "Only measures whose own validation lane is complete are reported; affected lanes remain null.",
            "",
            "## Validation issues",
            "",
        ]
        for issue in readout.get("validation_issues", []):
            lines.append(f"- `{issue.get('code')}` — {issue.get('path', '')}")
        return "\n".join(lines) + "\n"
    lines = [
        f"# Session readout: {readout['run_id']}",
        "",
        f"- Governed value at minute 60: `{str(readout['verified_governed_value_at_60']).lower()}`",
        f"- Governed value at registered stop: `{str(readout['verified_governed_value_at_registered_stop']).lower()}`",
        f"- Install guidance: `{readout['install_guidance']}`; discovery pre-solved: `{str(readout['install_discovery_pre_solved']).lower()}`",
        f"- Secondary milestones M1 / M4 / MG: `{readout['milestones']['M1']}` / `{readout['milestones']['M4']}` / `{readout['milestones']['MG']}`",
        f"- Steering exposed: `{str(readout['steering']['steering_exposed']).lower()}`; result: `{readout['steering']['result']}`",
        f"- Transfer: `{readout['transfer']['transfer_precondition']}` / `{readout['transfer']['transfer_outcome']}`",
        f"- Comprehension: `{readout['comprehension']['total']}/8`",
        f"- DL-HARD: {readout['interaction']['DL-HARD']['count']} ({readout['interaction']['DL-HARD']['per_10_participant_turns']} per 10 participant turns)",
        f"- DL-SOFT: {readout['interaction']['DL-SOFT']['count']} ({readout['interaction']['DL-SOFT']['per_10_participant_turns']} per 10 participant turns)",
        "",
        "## Top observed frictions",
        "",
        "| Rank | Event | Friction | Minutes lost | Scope | Candidate fix | Evidence |",
        "| ---: | --- | --- | ---: | --- | --- | --- |",
    ]
    for index, item in enumerate(readout["top_frictions"], start=1):
        lines.append(
            f"| {index} | {item.get('event_id', '')} | {item.get('description', '')} | "
            f"{item.get('minutes_lost', 'not_estimable')} | {item.get('failure_scope', '')} | "
            f"{item.get('candidate_fix', '')} | {item.get('evidence_ref', '')} |"
        )
    if not readout["top_frictions"]:
        lines.append("|  |  | No coded friction events |  |  |  |  |")
    lines.extend(
        [
            "",
            "## Participant debrief",
            "",
            str(readout["one_change_debrief"]),
            "",
            "This response and the candidate fixes are hypothesis-generating, not causal evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def evaluate_session(
    *,
    run_id: str,
    facilitator_root: Path,
    harness_root: Path = DEFAULT_HARNESS_ROOT,
) -> dict[str, Any]:
    """Validate filled forms and produce a non-composite session readout."""

    validation = validate_session(
        run_id=run_id,
        facilitator_root=facilitator_root,
        harness_root=harness_root,
    )
    paths = _harness_paths(harness_root, run_id)
    human = _facilitator_dir(facilitator_root, paths["root"], run_id)
    if not validation["ok"]:
        metadata = load_json(human / "session-metadata.json", {})
        instrument = _session_instrument(human)
        evaluator = load_json(human / "evaluator.json", {})
        coded = load_json(human / "coded-events.json", {})
        belief = load_json(human / "frozen-minute-60" / "belief-inventory.json", {})
        belief_coding = load_json(human / "belief-coding.json", {})
        transfer = load_json(human / "transfer.json", {})
        steering = load_json(human / "steering.json", {})
        comprehension = load_json(human / "comprehension.json", {})
        issues_by_lane: dict[str, list[dict[str, Any]]] = {}
        for issue in validation["issues"]:
            issues_by_lane.setdefault(_validation_lane(issue), []).append(issue)
        criteria: dict[str, Any] = {}
        for item in (
            evaluator.get("criteria", []) if isinstance(evaluator, dict) else []
        ):
            if not isinstance(item, dict):
                continue
            criterion_id = item.get("criterion_id")
            if isinstance(criterion_id, str) and criterion_id not in criteria:
                criteria[criterion_id] = item.get("result")
        criteria_complete = set(criteria) == {
            f"T{number}" for number in range(1, 7)
        } and all(value in TRUTH_VALUES for value in criteria.values())
        technical_complete = not issues_by_lane.get("technical") and criteria_complete
        governed_at_stop = (
            all(criteria.get(f"T{number}") == "pass" for number in range(1, 7))
            if technical_complete
            else None
        )
        standard_60 = (
            validation.get("evidence", {}).get("standard_60_minute_duration") is True
        )
        interaction = (
            _partial_interaction(coded, instrument)
            if not issues_by_lane.get("interaction")
            else None
        )
        beliefs: list[dict[str, Any]] | None = None
        belief_summary: dict[str, int] | None = None
        if not issues_by_lane.get("belief"):
            beliefs, belief_summary = _partial_beliefs(belief, belief_coding, evaluator)
        comprehension_readout = None
        if not issues_by_lane.get("comprehension"):
            scores = [row["score"] for row in comprehension["responses"]]
            comprehension_readout = {
                "item_scores": scores,
                "total": sum(scores),
                "ratings": comprehension["ratings"],
            }
        status = "partial" if technical_complete else "incomplete"
        readout = {
            "ok": False,
            "readout_status": status,
            "study_id": metadata.get("study_id")
            if isinstance(metadata, dict)
            else None,
            "run_id": run_id,
            "participant_id": metadata.get("participant_id")
            if isinstance(metadata, dict)
            else None,
            "rehearsal": bool(metadata.get("rehearsal"))
            if isinstance(metadata, dict)
            else None,
            "retained_in_census": not bool(metadata.get("rehearsal"))
            if isinstance(metadata, dict)
            else True,
            "criteria": criteria,
            "verified_governed_value_at_60": (
                governed_at_stop if technical_complete and standard_60 else None
            ),
            "verified_governed_value_at_registered_stop": governed_at_stop,
            "timing": validation.get("evidence", {}),
            "lane_status": {
                lane: "incomplete" if issues_by_lane.get(lane) else "complete"
                for lane in (
                    "technical",
                    "timing",
                    "interaction",
                    "belief",
                    "transfer",
                    "steering",
                    "comprehension",
                    "capture_reproducibility",
                )
            },
            "interaction": interaction,
            "beliefs": beliefs,
            "belief_summary": belief_summary,
            "transfer": transfer if not issues_by_lane.get("transfer") else None,
            "steering": steering if not issues_by_lane.get("steering") else None,
            "comprehension": comprehension_readout,
            "top_frictions": None,
            "one_change_debrief": (
                comprehension.get("one_change_debrief")
                if comprehension_readout is not None
                else None
            ),
            "validation_issues": validation["issues"],
            "claim_boundary": (
                "Retained measure-specific readout. Null fields are unavailable; "
                "validated technical outcomes remain reportable when nontechnical lanes fail."
            ),
            "generated_at": utc_now(),
        }
        write_json(human / "session-readout.json", readout)
        write_text(human / "session-readout.md", _markdown_readout(readout))
        return readout
    metadata = load_json(human / "session-metadata.json", {})
    coded = load_json(human / "coded-events.json", {})
    evaluator = load_json(human / "evaluator.json", {})
    belief = load_json(
        human / "frozen-minute-60" / "belief-inventory.json",
        {},
    )
    belief_coding = load_json(human / "belief-coding.json", {})
    transfer = load_json(human / "transfer.json", {})
    steering = load_json(human / "steering.json", {})
    comprehension = load_json(human / "comprehension.json", {})
    score = load_json(paths["run_dir"] / "minute-60" / "score.json", {})
    poll_result = load_json(paths["run_dir"] / "minute-60" / "poll-result.json", {})

    criteria = {item["criterion_id"]: item["result"] for item in evaluator["criteria"]}
    truth = {item["claim_id"]: item["truth"] for item in evaluator["belief_truth"]}
    coding_by_claim = {item["claim_id"]: item for item in belief_coding["claims"]}
    belief_categories: list[dict[str, Any]] = []
    for answer in belief["answers"]:
        category = "aligned_or_low_confidence"
        actual = truth[answer["claim_id"]]
        if answer["answer"] == "yes" and answer["confidence"] >= 4 and actual == "fail":
            category = "false_confident"
        elif answer["answer"] == "no" and actual == "pass":
            category = "false_negative"
        elif answer["answer"] == "unsure":
            category = "uncertain"
        elif (
            answer["answer"] == "yes"
            and answer["confidence"] >= 4
            and actual == "not_tested"
        ):
            category = "unsupported_confidence"
        belief_categories.append(
            {
                "claim_id": answer["claim_id"],
                "participant_answer": answer["answer"],
                "confidence": answer["confidence"],
                "main_reason": answer["main_reason"],
                "evaluator_truth": actual,
                "category": category,
                "failure_scope": coding_by_claim[answer["claim_id"]].get(
                    "failure_scope"
                )
                if category == "false_confident"
                else None,
                "candidate_fix": coding_by_claim[answer["claim_id"]].get(
                    "candidate_fix"
                )
                if category == "false_confident"
                else None,
                "evidence_refs": coding_by_claim[answer["claim_id"]].get(
                    "evidence_refs", []
                ),
            }
        )

    turns = coded.get("participant_turns")
    counts = {
        code: sum(1 for event in coded["events"] if event.get("event_code") == code)
        for code in ("DL-HARD", "DL-SOFT", "VB", "DE", "R-HUMAN", "R-INFRA", "MANUAL")
    }
    frictions = [
        event
        for event in coded["events"]
        if event.get("event_code") in {"DL-HARD", "DL-SOFT", "DE", "R-HUMAN"}
    ]
    for belief_item, answer in zip(belief_categories, belief["answers"], strict=True):
        if belief_item["category"] == "false_confident":
            refs = belief_item.get("evidence_refs", [])
            frictions.append(
                {
                    "event_id": f"belief:{belief_item['claim_id']}",
                    "description": f"False-confident belief: {answer.get('statement', belief_item['claim_id'])}",
                    "minutes_lost": "not_estimable",
                    "affected_outcome": belief_item["claim_id"],
                    "failure_scope": belief_item.get("failure_scope"),
                    "candidate_fix": belief_item.get("candidate_fix"),
                    "evidence_ref": refs[0] if refs else None,
                }
            )
    frictions.sort(
        key=lambda event: (
            isinstance(event.get("minutes_lost"), (int, float)),
            event.get("minutes_lost")
            if isinstance(event.get("minutes_lost"), (int, float))
            else -1,
        ),
        reverse=True,
    )
    top = []
    for event in frictions[:3]:
        top.append(
            {
                "event_id": event.get("event_id"),
                "event_ids": [event.get("event_id")],
                "description": event.get("description")
                or event.get("notes")
                or event.get("event_code"),
                "minutes_lost": event.get("minutes_lost") or "not_estimable",
                "affected_outcome": event.get("affected_outcome"),
                "failure_scope": event.get("failure_scope"),
                "candidate_fix": event.get("candidate_fix"),
                "evidence_ref": event.get("evidence_ref"),
            }
        )

    ignored_present = (
        sorted(AUTONOMOUS_ONLY_SCORE_FIELDS.intersection(score))
        if isinstance(score, dict)
        else []
    )
    raw_milestones = (
        poll_result.get("milestones", {}) if isinstance(poll_result, dict) else {}
    )
    comprehension_scores = [
        response["score"] for response in comprehension["responses"]
    ]
    governed_at_stop = all(
        criteria.get(f"T{number}") == "pass" for number in range(1, 7)
    )
    standard_60 = (
        validation.get("evidence", {}).get("standard_60_minute_duration") is True
    )
    readout = {
        "ok": True,
        "readout_status": "complete",
        "study_id": metadata["study_id"],
        "run_id": run_id,
        "participant_id": metadata["participant_id"],
        "rehearsal": metadata["rehearsal"],
        "retained_in_census": not metadata["rehearsal"],
        "install_guidance": metadata["install_guidance"],
        "install_discovery_pre_solved": metadata["install_discovery_pre_solved"],
        "install_guidance_claim_boundary": metadata["install_guidance_claim_boundary"],
        "cards": metadata["cards"],
        "agent_stack": metadata.get("agent_stack", {}),
        "milestones": {name: raw_milestones.get(name) for name in ("M1", "M4", "MG")},
        "criteria": criteria,
        "verified_governed_value_at_60": governed_at_stop if standard_60 else None,
        "verified_governed_value_at_registered_stop": governed_at_stop,
        "timing": {
            key: validation.get("evidence", {}).get(key)
            for key in (
                "registered_duration_seconds",
                "elapsed_at_freeze_seconds",
                "poll_launch_offset_seconds",
                "standard_60_minute_duration",
            )
        },
        "steering": steering,
        "transfer": transfer,
        "interaction": {
            "participant_turns": turns,
            **{
                code: {
                    "count": count,
                    "per_10_participant_turns": _rate(count, turns)
                    if code in {"DL-HARD", "DL-SOFT"}
                    else None,
                }
                for code, count in counts.items()
            },
            "decision_object_counts": {
                decision: sum(
                    1
                    for event in coded["events"]
                    if event.get("event_code") in {"DL-HARD", "DL-SOFT"}
                    and event.get("decision_object") == decision
                )
                for decision in _session_instrument(human)["decision_objects"]
            },
        },
        "beliefs": belief_categories,
        "belief_summary": {
            category: sum(
                1 for item in belief_categories if item["category"] == category
            )
            for category in (
                "false_confident",
                "false_negative",
                "uncertain",
                "unsupported_confidence",
                "aligned_or_low_confidence",
            )
        },
        "comprehension": {
            "item_scores": comprehension_scores,
            "total": sum(comprehension_scores),
            "ratings": comprehension["ratings"],
        },
        "top_frictions": top,
        "one_change_debrief": comprehension["one_change_debrief"],
        "autonomous_score_fields_preserved_but_not_interpreted": ignored_present,
        "claim_boundary": (
            "Formative single-session description. Candidate fixes and debrief answers "
            "are hypotheses, not causal effects or population estimates."
        ),
        "generated_at": utc_now(),
    }
    write_json(human / "session-readout.json", readout)
    write_text(human / "session-readout.md", _markdown_readout(readout))
    return readout


def load_agent_stack(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    value = load_json(path)
    if not isinstance(value, dict):
        raise StudyError("agent stack JSON must contain one object")
    return value
