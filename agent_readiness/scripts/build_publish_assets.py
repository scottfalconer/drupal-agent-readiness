#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.publishing import write_package_manifest, write_report, write_scorecard_csv
from agent_readiness.readiness import write_readiness_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Build publishable scorecard/report assets from run-result JSON")
    parser.add_argument("--run-result", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("agent_readiness/public"))
    args = parser.parse_args()

    run_results = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in args.run_result
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_scorecard_csv(run_results, args.output_dir / "scorecard.csv")
    write_report(run_results, args.output_dir / "state-of-agents-in-drupal-v0.md")
    (args.output_dir / "readiness.json").write_text("{}\n", encoding="utf-8")
    write_package_manifest(args.output_dir.parent, run_results, args.output_dir / "package-manifest.json")
    write_readiness_json(args.output_dir.parent, run_results, args.output_dir / "readiness.json")
    write_package_manifest(args.output_dir.parent, run_results, args.output_dir / "package-manifest.json")
    print(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
