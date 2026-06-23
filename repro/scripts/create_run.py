#!/usr/bin/env python3
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_SUBSTRATE = Path("<workspace>/haven-clean-install")
DEFAULT_ROOT = Path("<workspace>/tmp/agent-readiness")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a disposable agent-readiness run site")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--substrate", type=Path, default=DEFAULT_SUBSTRATE)
    parser.add_argument("--copy-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()

    source = args.substrate.resolve()
    if not source.exists():
        raise SystemExit(f"Substrate does not exist: {source}")

    run_dir = (args.copy_root / args.run_id).resolve()
    site_dir = run_dir / "site"
    if run_dir.exists():
        raise SystemExit(f"Run directory already exists: {run_dir}")

    run_dir.mkdir(parents=True)
    shutil.copytree(source, site_dir, symlinks=True)
    metadata = {
        "run_id": args.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source),
        "run_site_path": str(site_dir),
    }
    (run_dir / "run.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
