#!/usr/bin/env python3
"""Audit v1 benchmark evidence and derive claim eligibility from evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.measurement_v1 import (
    CanonicalJSONError,
    GitRegistrationAnchor,
    audit_measurement_v1,
    load_canonical_json_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a preregistered benchmark manifest and runs. By default, "
            "success requires a reportable estimate; satisfying the registered "
            "effect rule is a separate, stricter measurement requirement."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        required=True,
        help="Root against which all manifest and run artifact URIs resolve.",
    )
    requirement_group = parser.add_mutually_exclusive_group()
    requirement_group.add_argument(
        "--require",
        choices=("contract", "evidence", "estimate", "effect-rule"),
        default="estimate",
        help=(
            "Exit-success gate: document contract, complete evidence, reportable "
            "estimate (default), or the registered effect rule."
        ),
    )
    requirement_group.add_argument(
        "--contract-only",
        action="store_true",
        help="Deprecated alias for --require contract.",
    )
    parser.add_argument("--registration-repo", type=Path)
    parser.add_argument("--registration-commit")
    parser.add_argument("--registration-manifest-path")
    args = parser.parse_args()
    anchor_values = (
        args.registration_repo,
        args.registration_commit,
        args.registration_manifest_path,
    )
    if any(value is not None for value in anchor_values) and not all(
        value is not None for value in anchor_values
    ):
        parser.error(
            "--registration-repo, --registration-commit, and "
            "--registration-manifest-path must be supplied together"
        )
    anchor = (
        GitRegistrationAnchor(
            repo_path=args.registration_repo,
            commit=args.registration_commit,
            manifest_path=args.registration_manifest_path,
        )
        if all(value is not None for value in anchor_values)
        else None
    )

    required_level = "contract" if args.contract_only else args.require
    status_field = {
        "contract": "contract_valid",
        "evidence": "evidence_complete",
        "estimate": "estimate_reportable",
        "effect-rule": "registered_effect_rule_met",
    }[required_level]
    try:
        manifest = load_canonical_json_file(args.manifest)
        runs = [load_canonical_json_file(path) for path in args.run]
    except (OSError, UnicodeError, CanonicalJSONError) as exc:
        code = (
            "measurement_input_unreadable"
            if "invalid JSON" in str(exc) or "valid UTF-8" in str(exc)
            else "measurement_input_noncanonical"
        )
        print(json.dumps({
            "schema_version": "drupal_agent_readiness.measurement_audit_cli_error.v1",
            "cli_requirement": {
                "level": required_level,
                "status_field": status_field,
                "satisfied": False,
            },
            "errors": [{
                "severity": "error",
                "code": code,
                "path": "$.inputs",
                "message": str(exc),
            }],
        }, indent=2, sort_keys=True))
        return 1
    report = audit_measurement_v1(
        manifest,
        runs,
        artifact_root=args.artifact_root,
        registration_anchor=anchor,
    )
    report["cli_requirement"] = {
        "level": required_level,
        "status_field": status_field,
        "satisfied": bool(report[status_field]),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    success = report[status_field]
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
