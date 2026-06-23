#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.readiness import audit_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit State of Agents in Drupal v0 publication readiness")
    parser.add_argument("--base-dir", type=Path, default=Path("agent_readiness"))
    parser.add_argument("--run-result", type=Path, action="append", required=True)
    parser.add_argument("--public-required-passes", type=int, default=1)
    parser.add_argument("--numeric-required-passes", type=int, default=3)
    args = parser.parse_args()

    run_results = [json.loads(path.read_text(encoding="utf-8")) for path in args.run_result]
    report = audit_readiness(
        args.base_dir,
        run_results,
        public_required_passes=args.public_required_passes,
        numeric_required_passes=args.numeric_required_passes,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["public_v0_package_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
