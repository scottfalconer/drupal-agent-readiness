#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.intent_behavior_runner import scan_memory_contamination


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit intent-behavior run artifacts for memory contamination.")
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--glob", default="intent-*-headline-*")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    runs = sorted(path for path in args.runs_root.glob(args.glob) if path.is_dir())
    results = []
    contaminated = 0
    for run_dir in runs:
        result = scan_memory_contamination(run_dir)
        result = {
            "run_id": run_dir.name,
            **result,
        }
        if result["contaminated"]:
            contaminated += 1
        results.append(result)

    summary = {
        "runs_root": str(args.runs_root),
        "run_count": len(runs),
        "contaminated_run_count": contaminated,
        "clean_run_count": len(runs) - contaminated,
        "runs": results,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"runs={len(runs)} contaminated={contaminated} clean={len(runs) - contaminated}")
        for result in results:
            if result["contaminated"]:
                first = result["findings"][0]
                print(f"{result['run_id']}: contaminated {first['path']}:{first['line']} {first['patterns']}")
    return 1 if contaminated else 0


if __name__ == "__main__":
    raise SystemExit(main())
