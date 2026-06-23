#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.baseline_gate import audit_inventory_baseline


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit independent inventory baseline readiness")
    parser.add_argument("--run-result", type=Path, action="append", required=True)
    parser.add_argument("--required-passes", type=int, default=1)
    args = parser.parse_args()

    run_results = [json.loads(path.read_text(encoding="utf-8")) for path in args.run_result]
    errors = audit_inventory_baseline(run_results, required_passes=args.required_passes)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("baseline-gate-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
