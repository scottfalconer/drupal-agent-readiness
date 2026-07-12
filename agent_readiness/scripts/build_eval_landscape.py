from __future__ import annotations

import argparse
from pathlib import Path

from agent_readiness.eval_references import (
    DEFAULT_JSON_OUTPUT,
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_SCHEMA_PATH,
    DEFAULT_SOURCE_DIR,
    EvalReferenceError,
    check_outputs,
    write_outputs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate inert external-eval pointers and generate discovery views."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
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
                source_dir=args.source_dir,
                schema_path=args.schema,
            )
            if failures:
                for failure in failures:
                    print(f"FAIL: {failure}")
                return 1
            print("OK: external eval reference sources and generated landscape match")
            return 0

        write_outputs(
            args.json_output,
            args.markdown_output,
            source_dir=args.source_dir,
            schema_path=args.schema,
        )
        print(f"wrote {args.json_output}")
        print(f"wrote {args.markdown_output}")
        return 0
    except EvalReferenceError as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
