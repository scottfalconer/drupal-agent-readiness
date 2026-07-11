#!/usr/bin/env python3
import argparse
import shutil
from pathlib import Path


ALLOWLIST_FILES = [
    "auth.json",
    "config.json",
    "config.toml",
    "installation_id",
    "models_cache.json",
    "version.json",
]


DENYLIST_NAMES = {
    "AGENTS.md",
    "instructions.md",
    "memories",
    "memories_extensions",
    "sessions",
    "archived_sessions",
    "attachments",
    "history.json",
    "history.jsonl",
    "session_index.jsonl",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a memory-free Codex home template for experiment runs.")
    parser.add_argument("--source", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    out = args.out.expanduser().resolve()
    if out.exists():
        if not args.force:
            raise SystemExit(f"Refusing to overwrite existing output without --force: {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    copied: list[str] = []
    skipped_existing: list[str] = []
    for name in ALLOWLIST_FILES:
        src = source / name
        if not src.exists():
            skipped_existing.append(name)
            continue
        shutil.copy2(src, out / name)
        copied.append(name)

    for name in DENYLIST_NAMES:
        path = out / name
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    for pattern in ["memories*.sqlite*", "state*.sqlite*", "logs*.sqlite*", "goals*.sqlite*"]:
        for path in out.glob(pattern):
            path.unlink()

    print("prepared_clean_codex_home")
    print(f"source={source}")
    print(f"out={out}")
    print(f"copied={','.join(copied)}")
    if skipped_existing:
        print(f"missing={','.join(skipped_existing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
