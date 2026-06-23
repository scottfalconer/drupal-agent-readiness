#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.site_architecture_tools import (
    DEFAULT_MODULE_SOURCE,
    build_install_plan,
    install_site_architecture,
    plan_to_jsonable,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install site_architecture into a disposable run site and emit command artifacts")
    parser.add_argument("--site-root", type=Path, required=True)
    parser.add_argument("--module-source", type=Path, default=DEFAULT_MODULE_SOURCE)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        plan = build_install_plan(
            site_root=args.site_root,
            module_source=args.module_source,
            output_dir=args.output_dir,
        )
        print(json.dumps(plan_to_jsonable(plan), indent=2, sort_keys=True))
        return 0

    result = install_site_architecture(
        site_root=args.site_root,
        module_source=args.module_source,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
