#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.evaluators.alias_safety import (
    DEFAULT_CANDIDATES,
    collect_alias_safety_state,
    evaluate,
)
from agent_readiness.evaluators.common import load_json, print_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the assess.alias_safety task")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--state-json", type=Path, help="Pre-collected ground-truth state JSON")
    source.add_argument("--site-root", type=Path, help="Drupal clone to collect ground truth from")
    parser.add_argument("--answer-json", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--php-ini-scan-dir")
    args = parser.parse_args()

    if args.state_json:
        state = load_json(args.state_json)
    else:
        state = collect_alias_safety_state(args.site_root, args.candidates, args.php_ini_scan_dir)
    answer = load_json(args.answer_json)
    result = evaluate(state, answer)
    print_result(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
