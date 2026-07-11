#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.intent_behavior import load_json
from agent_readiness.intent_behavior_runner import run_intent_batch


def _csv_set(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a resumable intent-behavior schedule.")
    parser.add_argument("--design", type=Path, default=Path("method/intent-behavior-variants-v0.json"))
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, default=Path("method/intent-behavior"))
    parser.add_argument("--baseline-main", type=Path, required=True)
    parser.add_argument("--baseline-stale", type=Path)
    parser.add_argument("--baseline-a11y", type=Path)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--codex-home-template", type=Path)
    parser.add_argument("--isolate-home", action="store_true")
    parser.add_argument("--allow-memory-contamination", action="store_true")
    parser.add_argument("--service-tier", default="fast")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--base-port", type=int, default=8910)
    parser.add_argument("--copy-strategy", choices=["copy", "apfs-clone"], default="apfs-clone")
    parser.add_argument("--run-ids", help="Comma-separated run ids to include")
    parser.add_argument("--cell-ids", help="Comma-separated cell ids to include")
    parser.add_argument("--arm-ids", help="Comma-separated arm ids to include")
    parser.add_argument("--prompt-ids", help="Comma-separated prompt ids to include")
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--include-successful", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = run_intent_batch(
        design=load_json(args.design),
        schedule=load_json(args.schedule),
        artifact_root=args.artifact_root,
        baseline_main=args.baseline_main,
        baseline_stale=args.baseline_stale,
        baseline_a11y=args.baseline_a11y,
        out_root=args.out_root,
        codex_bin=args.codex_bin,
        codex_home=args.codex_home,
        codex_home_template=args.codex_home_template,
        isolate_home=args.isolate_home,
        fail_on_memory_contamination=not args.allow_memory_contamination,
        service_tier=args.service_tier,
        timeout_seconds=args.timeout_seconds,
        base_port=args.base_port,
        copy_strategy=args.copy_strategy,
        run_ids=_csv_set(args.run_ids),
        cell_ids=_csv_set(args.cell_ids),
        arm_ids=_csv_set(args.arm_ids),
        prompt_ids=_csv_set(args.prompt_ids),
        limit=args.max_runs,
        only_missing=not args.include_successful,
        keep_going=args.keep_going,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2))
    if args.dry_run:
        return 0
    return 0 if summary["failed_run_count"] == 0 and summary["infrastructure_failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
