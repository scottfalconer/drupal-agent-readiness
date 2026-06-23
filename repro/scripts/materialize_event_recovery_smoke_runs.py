#!/usr/bin/env python3
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.evaluators.common import collect_live_state
from agent_readiness.run_artifacts import (
    TOOLING_SMOKE_AGENT,
    materialize_event_run_from_state,
    materialize_recovery_run_from_state,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUBSTRATE = Path("<workspace>/haven-clean-install")
DEFAULT_RUNS_DIR = Path("agent_readiness/runs")
DEFAULT_COPY_ROOT = Path("<workspace>/tmp/agent-readiness")


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize Event write/recovery smoke runs")
    parser.add_argument("--run-prefix", default="haven-event-v0-tooling-smoke")
    parser.add_argument("--substrate", type=Path, default=DEFAULT_SUBSTRATE)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--copy-root", type=Path, default=DEFAULT_COPY_ROOT)
    args = parser.parse_args()

    event_run_id = args.run_prefix
    recovery_run_id = args.run_prefix.replace("event", "recovery", 1)
    event_run_dir = args.runs_dir / event_run_id
    recovery_run_dir = args.runs_dir / recovery_run_id
    for run_dir in [event_run_dir, recovery_run_dir]:
        if run_dir.exists():
            raise SystemExit(f"Run directory already exists: {run_dir}")

    site_dir = args.copy_root / args.run_prefix / "site"
    if site_dir.exists():
        raise SystemExit(f"Run site already exists: {site_dir}")
    site_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(args.substrate, site_dir, symlinks=True)

    baseline_state = collect_live_state(site_dir)
    baseline = {
        "bundles": baseline_state["content_model"]["bundles"],
        "views": baseline_state.get("views", []),
        "aliases": baseline_state.get("aliases", []),
        "role_permissions": baseline_state.get("permissions", {}).get("role_permissions", {}),
        "event_add_route_available": baseline_state.get("routes", {}).get("event_add_route_available", False),
    }

    start = time.monotonic()
    _run_drush_script(site_dir, ROOT / "evaluators" / "apply_event_jsonapi.php")
    event_state = collect_live_state(site_dir)
    event_state["baseline"] = baseline
    event_elapsed = round(time.monotonic() - start, 3)
    event_result = materialize_event_run_from_state(
        run_id=event_run_id,
        state=event_state,
        run_dir=event_run_dir,
        source_path=str(args.substrate),
        run_site_path=str(site_dir),
        transcript_lines=[
            f"# Transcript: {event_run_id}",
            "",
            "This smoke run applied the Event JSON:API task through Drupal APIs on a disposable Haven clone.",
            "",
            "Commands represented:",
            "",
            f"- Copied substrate `{args.substrate}` to `{site_dir}`.",
            "- Ran `vendor/drush/drush/drush.php php:script agent_readiness/evaluators/apply_event_jsonapi.php`.",
            "- Collected live Drupal state and evaluated the Event task mechanically.",
            "",
            "This is a tooling/evaluator smoke run, not a blinded independent-agent run.",
        ],
        metrics={
            "elapsed_seconds": event_elapsed,
            "tool_calls": 4,
            "human_rescues": 0,
        },
        agent=TOOLING_SMOKE_AGENT,
    )

    start = time.monotonic()
    _run_drush_script(site_dir, ROOT / "evaluators" / "recover_event_jsonapi.php")
    recovery_state = collect_live_state(site_dir)
    recovery_state["baseline"] = baseline
    recovery_elapsed = round(time.monotonic() - start, 3)
    recovery_result = materialize_recovery_run_from_state(
        run_id=recovery_run_id,
        state=recovery_state,
        run_dir=recovery_run_dir,
        source_path=str(args.substrate),
        run_site_path=str(site_dir),
        transcript_lines=[
            f"# Transcript: {recovery_run_id}",
            "",
            "This smoke run recovered the Event JSON:API task through Drupal APIs on the same disposable Haven clone.",
            "",
            "Commands represented:",
            "",
            "- Ran `vendor/drush/drush/drush.php php:script agent_readiness/evaluators/recover_event_jsonapi.php`.",
            "- Collected live Drupal state and evaluated the recovery task mechanically.",
            "",
            "This is a tooling/evaluator smoke run, not a blinded independent-agent run.",
        ],
        metrics={
            "elapsed_seconds": recovery_elapsed,
            "tool_calls": 3,
            "human_rescues": 0,
        },
        agent=TOOLING_SMOKE_AGENT,
    )

    print(event_run_dir / "run-result.json")
    print(recovery_run_dir / "run-result.json")
    return 0 if event_result["evaluator"]["passed"] and recovery_result["evaluator"]["passed"] else 1


def _run_drush_script(site_dir: Path, script: Path) -> None:
    command = [
        "php",
        "-d",
        "memory_limit=1024M",
        str(site_dir / "vendor" / "drush" / "drush" / "drush.php"),
        "php:script",
        str(script),
    ]
    subprocess.run(command, cwd=site_dir, text=True, capture_output=True, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
