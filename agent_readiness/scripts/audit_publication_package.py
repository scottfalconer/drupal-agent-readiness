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

from agent_readiness.publishing import (
    audit_distribution_mirrors,
    audit_publication_package,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Drupal Agent Readiness publish assets")
    parser.add_argument("--base-dir", type=Path, default=Path("agent_readiness"))
    parser.add_argument("--distribution-dir", type=Path, default=Path("docs"))
    parser.add_argument("--run-result", type=Path, action="append", required=True)
    args = parser.parse_args()

    run_results = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in args.run_result
    ]
    errors = audit_publication_package(args.base_dir, run_results)
    errors.extend(
        audit_distribution_mirrors(
            args.base_dir / "public",
            args.distribution_dir,
        )
    )
    if errors:
        for error in errors:
            print(error)
        return 1
    print("publication-package-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
