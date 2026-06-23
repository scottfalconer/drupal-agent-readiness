#!/usr/bin/env python3
import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.evaluators.common import collect_live_state
from agent_readiness.run_artifacts import TOOLING_SMOKE_AGENT, materialize_inventory_run_from_state


DEFAULT_SUBSTRATE = Path("<workspace>/haven-clean-install")
DEFAULT_RUNS_DIR = Path("agent_readiness/runs")
DEFAULT_COPY_ROOT = Path("<workspace>/tmp/agent-readiness")


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize an inventory.read_only run artifact package")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--substrate", type=Path, default=DEFAULT_SUBSTRATE)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--copy-root", type=Path, default=DEFAULT_COPY_ROOT)
    parser.add_argument("--elapsed-seconds", type=float, default=0.0)
    parser.add_argument("--tool-calls", type=int, default=0)
    parser.add_argument("--human-rescues", type=int, default=0)
    args = parser.parse_args()

    start = time.monotonic()
    run_dir = args.runs_dir / args.run_id
    if run_dir.exists():
        raise SystemExit(f"Run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    site_dir = args.copy_root / args.run_id / "site"
    if site_dir.exists():
        raise SystemExit(f"Run site already exists: {site_dir}")
    site_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(args.substrate, site_dir, symlinks=True)
    state = collect_live_state(site_dir)
    elapsed = args.elapsed_seconds if args.elapsed_seconds else round(time.monotonic() - start, 3)
    transcript = [
        f"# Transcript: {args.run_id}",
        "",
        "This run was materialized by `agent_readiness/scripts/materialize_inventory_run.py`.",
        "It records the tool-assisted inventory path used to validate the v0 evaluator and publish assets.",
        "",
        "Commands represented:",
        "",
        f"- Copied substrate `{args.substrate}` to `{site_dir}`.",
        "- Collected live Drupal state via `vendor/bin/drush status --format=json`.",
        "- Collected site facts via `vendor/bin/drush php:script agent_readiness/evaluators/drupal_state_collector.php`.",
        "- Built `answer.json` from live state and evaluated it mechanically.",
        "",
        "This is a tooling/evaluator smoke run, not a blinded independent-agent run.",
    ]
    run_result = materialize_inventory_run_from_state(
        run_id=args.run_id,
        state=state,
        run_dir=run_dir,
        source_path=str(args.substrate),
        run_site_path=str(site_dir),
        transcript_lines=transcript,
        metrics={
            "elapsed_seconds": elapsed,
            "tool_calls": args.tool_calls,
            "human_rescues": args.human_rescues,
        },
        agent=TOOLING_SMOKE_AGENT,
    )
    print(run_dir / "run-result.json")
    return 0 if run_result["evaluator"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
