#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.intent_behavior import build_intent_behavior_schedule, load_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an intent-behavior calibration or core run schedule.")
    parser.add_argument("--design", type=Path, required=True, help="Path to method/intent-behavior-variants-v0.json")
    parser.add_argument("--phase", choices=["calibration", "core"], required=True)
    parser.add_argument("--selected-rung", dest="selected_conflict_prompt_id", choices=[
        "conflict_r1",
        "conflict_r2",
        "conflict_r3",
        "conflict_r4",
    ])
    parser.add_argument("--seed", type=int)
    parser.add_argument("--include-extensions", action="store_true")
    parser.add_argument("--include-cross-provider", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    plan = build_intent_behavior_schedule(
        load_json(args.design),
        phase=args.phase,
        selected_conflict_prompt_id=args.selected_conflict_prompt_id,
        seed=args.seed,
        include_extensions=args.include_extensions,
        include_cross_provider=args.include_cross_provider,
    )
    output = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 1 if plan["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
