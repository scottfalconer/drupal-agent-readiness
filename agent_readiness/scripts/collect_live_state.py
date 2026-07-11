#!/usr/bin/env python3
"""Collect canonical evaluator-owned Drupal state from a local or DDEV site."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.evaluators.common import collect_live_state


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect the Drupal state consumed by benchmark evaluators"
    )
    parser.add_argument("--site-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    state = collect_live_state(args.site_root)
    payload = json.dumps(
        state,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.output is None:
        sys.stdout.write(payload)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
