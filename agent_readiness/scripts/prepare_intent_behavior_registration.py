#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.intent_behavior import prepare_registration_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize intent-behavior registration artifacts and hashes.")
    parser.add_argument("--design", type=Path, required=True, help="Path to method/intent-behavior-variants-v0.json")
    parser.add_argument("--out-dir", type=Path, required=True, help="Registration artifact directory")
    parser.add_argument("--module-dir", type=Path, help="Intent module directory to hash and copy AGENTS.md from")
    parser.add_argument("--update-design-manifest", action="store_true")
    parser.add_argument("--out", type=Path, help="Optional summary JSON path")
    args = parser.parse_args()

    summary = prepare_registration_artifacts(
        design_path=args.design,
        out_dir=args.out_dir,
        module_dir=args.module_dir,
        update_design_manifest=args.update_design_manifest,
    )
    output = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
