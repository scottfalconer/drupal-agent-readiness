#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.evaluators.common import collect_live_state, load_json
from agent_readiness.run_capture import capture_run


DEFAULT_SUBSTRATE = Path("<workspace>/haven-clean-install")
DEFAULT_RUNS_DIR = Path("agent_readiness/runs")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture an actual agent task run into a scored run package")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", required=True, choices=["inventory.read_only", "act.event_jsonapi", "recover.event_jsonapi"])
    site = parser.add_mutually_exclusive_group(required=True)
    site.add_argument("--site-root", type=Path)
    site.add_argument("--state-json", type=Path)
    parser.add_argument("--baseline-state-json", type=Path)
    parser.add_argument("--answer-json", type=Path, required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--source-path", default=str(DEFAULT_SUBSTRATE))
    parser.add_argument("--run-site-path")
    parser.add_argument("--prompt-version", default="v0.1")
    parser.add_argument("--agent-name", required=True)
    parser.add_argument("--agent-model", required=True)
    parser.add_argument("--agent-harness", required=True)
    parser.add_argument("--system-prompt", default="")
    parser.add_argument("--tooling", action="append", default=[])
    parser.add_argument("--elapsed-seconds", type=float, required=True)
    parser.add_argument("--tool-calls", type=int, required=True)
    parser.add_argument("--human-rescues", type=int, required=True)
    args = parser.parse_args()

    state = load_json(args.state_json) if args.state_json else collect_live_state(args.site_root)
    baseline_state = load_json(args.baseline_state_json) if args.baseline_state_json else None
    run_site_path = args.run_site_path or str(args.site_root or "")
    result = capture_run(
        run_id=args.run_id,
        task_id=args.task_id,
        state=state,
        answer_json=args.answer_json,
        transcript=args.transcript,
        runs_dir=args.runs_dir,
        source_path=args.source_path,
        run_site_path=run_site_path,
        prompt_version=args.prompt_version,
        agent={
            "name": args.agent_name,
            "model": args.agent_model,
            "harness": args.agent_harness,
            "system_prompt": args.system_prompt,
            "tooling": args.tooling,
        },
        metrics={
            "elapsed_seconds": args.elapsed_seconds,
            "tool_calls": args.tool_calls,
            "human_rescues": args.human_rescues,
        },
        baseline_state=baseline_state,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["evaluator"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
