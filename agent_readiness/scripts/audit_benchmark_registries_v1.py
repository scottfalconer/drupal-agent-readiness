#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_readiness.benchmark_registries_v1 import (  # noqa: E402
    RegistryValidationError,
    validate_default_registries,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the v1 benchmark coverage, task, and improvement registries."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root containing method/ and evidence/.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Emit human-readable text or a machine-readable JSON report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = validate_default_registries(args.repo_root)
    except (RegistryValidationError, OSError, ValueError) as exc:
        report = {"valid": False, "error": str(exc)}
        if args.format == "json":
            print(json.dumps(report, sort_keys=True))
        else:
            print(f"benchmark registry audit: FAIL: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(report, sort_keys=True))
    else:
        print(
            "benchmark registry audit: OK "
            f"({report['lifecycle_stages']} stages, "
            f"{report['evidence_records']} pinned evidence records, "
            f"{report['task_families']} target task families, "
            f"{report['improvement_records']} improvement record)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
