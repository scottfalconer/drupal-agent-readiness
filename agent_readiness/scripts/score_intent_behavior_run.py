#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.intent_behavior import load_json
from agent_readiness.intent_behavior_runner import score_intent_run_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Score M1/M2 for one captured intent-behavior run directory.")
    parser.add_argument("--design", type=Path, default=Path("method/intent-behavior-variants-v0.json"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    scores = score_intent_run_artifacts(args.run_dir, load_json(args.design))
    output = json.dumps(scores, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
