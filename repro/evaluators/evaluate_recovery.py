#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.evaluators.common import build_parser, load_inputs, print_result
from agent_readiness.evaluators.recovery import evaluate


def main() -> int:
    parser = build_parser("Evaluate the recover.event_jsonapi task")
    state, answer = load_inputs(parser.parse_args())
    result = evaluate(state, answer)
    print_result(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
