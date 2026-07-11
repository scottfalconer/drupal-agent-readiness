#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.intent_behavior import audit_intent_behavior_registration
from agent_readiness.scripts.audit_clean_checkout_integrity import (
    audit_python_import_closure,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify intent-behavior registration hashes still match.")
    parser.add_argument("--design", type=Path, required=True, help="Path to method/intent-behavior-variants-v0.json")
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--module-dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    summary = audit_intent_behavior_registration(
        design_path=args.design,
        artifact_root=args.artifact_root,
        module_dir=args.module_dir,
    )
    repo_root = Path(__file__).resolve().parents[2]
    import_closure = audit_python_import_closure(
        repo_root=repo_root,
        entrypoints=[repo_root / "agent_readiness" / "intent_behavior_runner.py"],
    )
    summary["import_closure"] = import_closure
    if import_closure["errors"]:
        summary["errors"] = sorted(set([
            *summary.get("errors", []),
            *import_closure["errors"],
        ]))
        summary["status"] = "invalid"
    output = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if summary.get("status") == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
