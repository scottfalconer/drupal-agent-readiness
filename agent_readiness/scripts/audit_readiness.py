#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


if os.environ.get("DRUPAL_AGENT_READINESS_FRESH_PYCACHE") != "1":
    environment = dict(os.environ)
    environment["DRUPAL_AGENT_READINESS_FRESH_PYCACHE"] = "1"
    environment["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp(
        prefix="drupal-agent-readiness-audit-pycache-"
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    os.execve(
        sys.executable,
        [sys.executable, "-B", str(Path(__file__).resolve()), *sys.argv[1:]],
        environment,
    )

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.published_experiments import PublishedExperimentError
from agent_readiness.publishing import _json_load
from agent_readiness.readiness import audit_readiness


def bounded_minimum(minimum: int):
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("must be an integer") from exc
        if parsed < minimum:
            raise argparse.ArgumentTypeError(f"must be at least {minimum}")
        return parsed

    return parse


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit State of Agents in Drupal v0 publication readiness")
    parser.add_argument("--base-dir", type=Path, default=Path("agent_readiness"))
    parser.add_argument("--run-result", type=Path, action="append", required=True)
    parser.add_argument(
        "--public-required-passes", type=bounded_minimum(1), default=1
    )
    parser.add_argument(
        "--legacy-example-required-passes", type=bounded_minimum(3), default=3
    )
    parser.add_argument(
        "--require-estimate",
        metavar="EXPERIMENT_ID",
    )
    parser.add_argument(
        "--require-fixed-estimate",
        metavar="EXPERIMENT_ID",
    )
    parser.add_argument(
        "--require-effect-rule",
        metavar="EXPERIMENT_ID",
    )
    parser.add_argument(
        "--require-improvement",
        metavar="EXPERIMENT_ID",
    )
    args = parser.parse_args()

    try:
        run_results = []
        for path in args.run_result:
            run_result = _json_load(path)
            if not isinstance(run_result, dict):
                raise ValueError(f"{path}: JSON root must be an object")
            run_results.append(run_result)
        report = audit_readiness(
            args.base_dir,
            run_results,
            public_required_passes=args.public_required_passes,
            legacy_example_required_passes=args.legacy_example_required_passes,
        )
    except (OSError, UnicodeError, ValueError, PublishedExperimentError) as exc:
        print(json.dumps({
            "error": str(exc),
            "error_code": "readiness_input_invalid",
            "status": "invalid",
        }, indent=2, sort_keys=True))
        return 1
    eligibility = {
        item["experiment_id"]: item for item in report["experiment_eligibility"]
    }
    gate_requests = [
        ("estimate", args.require_estimate, "estimate_reportable"),
        ("fixed_estimate", args.require_fixed_estimate, "fixed_estimate_reportable"),
        ("effect_rule", args.require_effect_rule, "registered_effect_rule_met"),
        ("improvement", args.require_improvement, "improvement_ready"),
    ]
    promotion_gates = []
    for gate, experiment_id, field in gate_requests:
        if experiment_id is None:
            continue
        experiment = eligibility.get(experiment_id)
        promotion_gates.append({
            "gate": gate,
            "experiment_id": experiment_id,
            "status_field": field,
            "satisfied": bool(experiment and experiment[field] is True),
            "known_experiment": experiment is not None,
        })
    report["promotion_gates"] = promotion_gates
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["public_evidence_package_ready"]:
        return 1
    if any(not gate["satisfied"] for gate in promotion_gates):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
