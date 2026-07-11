#!/usr/bin/env python3
"""Build or verify the checksum manifest for every tracked repository file."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys


def render_clean_manifest(repo_root: Path, output_path: Path) -> str:
    repo_root = repo_root.resolve()
    if output_path.is_symlink():
        raise ValueError("checksum manifest path must not be a symlink")
    output_path = output_path.resolve()
    try:
        output_relative = output_path.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise ValueError("checksum manifest must be inside the repository") from exc

    completed = _run_git(repo_root, ["ls-tree", "-r", "-z", "--full-tree", "HEAD"])
    if completed.returncode != 0:
        raise RuntimeError("git ls-tree HEAD failed; commit the release candidate first")

    lines: list[str] = []
    head_paths: list[bytes] = []
    for entry in completed.stdout.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            _mode, object_type, _object_id = metadata.split(b" ", 2)
        except ValueError as exc:
            raise RuntimeError("git ls-tree HEAD returned malformed output") from exc
        if object_type == b"blob":
            head_paths.append(raw_path)
    for raw_path in sorted(head_paths):
        relative = raw_path.decode("utf-8", errors="strict")
        if relative == output_relative:
            continue
        path = (repo_root / relative).resolve()
        try:
            path.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(f"tracked path escapes repository: {relative}") from exc
        unresolved = repo_root / relative
        if unresolved.is_symlink():
            raise ValueError(f"tracked symlink is not allowed in a release: {relative}")
        if not path.is_file():
            raise FileNotFoundError(f"tracked file is missing: {relative}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}")
    return "\n".join(lines) + "\n"


def _sanitized_git_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    env = _sanitized_git_environment()
    system_git = Path("/usr/bin/git")
    executable = (
        str(system_git)
        if system_git.is_file()
        else shutil.which("git", path=env.get("PATH"))
    )
    if executable is None:
        raise RuntimeError("trusted git executable not found")
    return subprocess.run(
        [str(Path(executable).resolve()), "--no-replace-objects", *args],
        cwd=repo_root,
        env=env,
        capture_output=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify CLEAN-MANIFEST.sha256 from immutable HEAD blobs."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("CLEAN-MANIFEST.sha256"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    try:
        expected = render_clean_manifest(repo_root, output)
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        print(f"clean-manifest-error: {exc}", file=sys.stderr)
        return 1

    if args.check:
        try:
            actual = output.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"clean-manifest-error: {exc}", file=sys.stderr)
            return 1
        if actual != expected:
            print("clean-manifest-drift", file=sys.stderr)
            return 1
        print("clean-manifest-ok")
        return 0

    output.write_text(expected, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
