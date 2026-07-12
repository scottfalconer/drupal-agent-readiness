from __future__ import annotations

import argparse
from pathlib import Path

from agent_readiness.external_eval_results import (
    DEFAULT_EVIDENCE_DIR,
    DEFAULT_JSON_OUTPUT,
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_RUN_SCHEMA_PATH,
    DEFAULT_SOURCE_VALIDATION_SCHEMA_PATH,
    ExternalEvalResultError,
    check_outputs,
    write_outputs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and publish bounded trusted-local external eval evidence."
    )
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--run-schema", type=Path, default=DEFAULT_RUN_SCHEMA_PATH)
    parser.add_argument(
        "--source-validation-schema",
        type=Path,
        default=DEFAULT_SOURCE_VALIDATION_SCHEMA_PATH,
    )
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when checked-in generated outputs are missing or stale",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check:
            failures = check_outputs(
                args.json_output,
                args.markdown_output,
                evidence_dir=args.evidence_dir,
                run_schema_path=args.run_schema,
                source_validation_schema_path=args.source_validation_schema,
            )
            if failures:
                for failure in failures:
                    print(f"FAIL: {failure}")
                return 1
            print("OK: external eval evidence and generated results match")
            return 0

        write_outputs(
            args.json_output,
            args.markdown_output,
            evidence_dir=args.evidence_dir,
            run_schema_path=args.run_schema,
            source_validation_schema_path=args.source_validation_schema,
        )
        print(f"wrote {args.json_output}")
        print(f"wrote {args.markdown_output}")
        return 0
    except ExternalEvalResultError as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
