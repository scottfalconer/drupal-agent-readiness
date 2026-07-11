#!/usr/bin/env python3
"""Audit whether tracked checksums describe a runnable, complete checkout."""

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


PACKAGE_NAME = "agent_readiness"


def audit_clean_checkout_integrity(
    *,
    repo_root: Path,
    entrypoints: list[Path],
    checksum_manifest: Path | None = None,
    generated_summaries: list[Path] | None = None,
    tracked_paths: set[str] | None = None,
    ignored_paths: set[str] | None = None,
    require_clean_worktree: bool = False,
) -> dict[str, Any]:
    """Combine checksum, Python import-closure, and generated-artifact checks."""
    repo_root = repo_root.resolve()
    tracked = tracked_paths if tracked_paths is not None else _git_tracked_paths(repo_root)
    checksum = audit_checksum_manifest(repo_root, checksum_manifest)
    if checksum_manifest is not None:
        manifest_relative = _display_path(
            repo_root,
            _absolute_path(repo_root, checksum_manifest),
        )
        listed = set(checksum.get("listed_paths", []))
        expected = {_normalize_relative(path) for path in tracked} - {manifest_relative}
        missing = sorted(expected - listed)
        unexpected = sorted(listed - expected)
        checksum["unlisted_tracked_paths"] = missing
        checksum["listed_untracked_paths"] = unexpected
        checksum["errors"] = [
            *checksum.get("errors", []),
            *(f"checksum_manifest.unlisted_tracked:{path}" for path in missing),
            *(f"checksum_manifest.listed_untracked:{path}" for path in unexpected),
        ]
        checksum["status"] = "valid" if not checksum["errors"] else "invalid"
    manifest_paths = set(checksum.get("listed_paths", [])) if checksum_manifest else None
    imports = audit_python_import_closure(
        repo_root=repo_root,
        entrypoints=entrypoints,
        tracked_paths=tracked,
        checksum_paths=manifest_paths,
    )
    generated = audit_required_generated_artifacts(
        repo_root=repo_root,
        summaries=generated_summaries or [],
        tracked_paths=tracked,
        ignored_paths=ignored_paths,
        checksum_paths=manifest_paths,
    )
    release_hygiene = (
        audit_git_release_hygiene(repo_root)
        if require_clean_worktree
        else {"status": "skipped", "errors": []}
    )
    errors = [
        *checksum.get("errors", []),
        *imports.get("errors", []),
        *generated.get("errors", []),
        *release_hygiene.get("errors", []),
    ]
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "checks": {
            "checksum": checksum,
            "python_import_closure": imports,
            "generated_artifacts": generated,
            "release_hygiene": release_hygiene,
        },
    }


def audit_git_release_hygiene(repo_root: Path) -> dict[str, Any]:
    """Require immutable-HEAD parity plus a clean index/worktree/submodules."""
    repo_root = repo_root.resolve()
    errors: list[str] = []

    head = _run_git(repo_root, ["rev-parse", "--verify", "HEAD^{commit}"])
    if head.returncode != 0:
        return {
            "status": "invalid",
            "errors": ["release_git.head_missing"],
        }

    head_entries = _git_tree_entries(repo_root)
    index_entries = _git_index_entries(repo_root)
    if head_entries is None:
        errors.append("release_git.head_tree_unreadable")
    if index_entries is None:
        errors.append("release_git.index_unreadable")
    if head_entries is not None and index_entries is not None:
        if head_entries != index_entries:
            errors.append("release_git.index_differs_from_head")

    status = _run_git(
        repo_root,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ],
    )
    if status.returncode != 0:
        errors.append("release_git.status_failed")
    elif status.stdout:
        for entry in status.stdout.split(b"\0"):
            if entry:
                errors.append(
                    "release_worktree.dirty:"
                    + entry.decode("utf-8", errors="backslashreplace")
                )

    submodules = _run_git(repo_root, ["submodule", "status", "--recursive"])
    if submodules.returncode != 0:
        errors.append("release_submodule.status_failed")
    else:
        for line in submodules.stdout.decode(
            "utf-8", errors="backslashreplace"
        ).splitlines():
            if line and not line.startswith(" "):
                errors.append(f"release_submodule.not_clean:{line}")

    for path in sorted(repo_root.rglob("*")):
        try:
            relative = path.relative_to(repo_root)
        except ValueError:
            continue
        if ".git" in relative.parts:
            continue
        if path.is_symlink():
            errors.append(f"release_symlink.present:{relative.as_posix()}")
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            errors.append(f"release_executable_cache.present:{relative.as_posix()}")

    return {
        "status": "valid" if not errors else "invalid",
        "errors": sorted(set(errors)),
        "head": head.stdout.decode("ascii", errors="replace").strip(),
    }


def audit_checksum_manifest(
    repo_root: Path,
    checksum_manifest: Path | None,
) -> dict[str, Any]:
    """Verify every file enumerated by a SHA-256 manifest."""
    if checksum_manifest is None:
        return {"status": "skipped", "errors": [], "listed_paths": []}
    manifest_path = _absolute_path(repo_root, checksum_manifest)
    if not manifest_path.exists():
        return {
            "status": "invalid",
            "errors": [f"checksum_manifest.missing:{_display_path(repo_root, manifest_path)}"],
            "listed_paths": [],
        }

    errors: list[str] = []
    listed_paths: list[str] = []
    for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or re.fullmatch(r"[0-9a-f]{64}", parts[0]) is None:
            errors.append(f"checksum_manifest.line_invalid:{line_number}")
            continue
        expected_hash, raw_path = parts
        relative_path = _normalize_relative(raw_path.lstrip("*"))
        if not _safe_repo_relative(relative_path):
            errors.append(f"checksum_manifest.path_unsafe:{line_number}")
            continue
        if relative_path in listed_paths:
            errors.append(f"checksum_manifest.path_duplicate:{relative_path}")
            continue
        listed_paths.append(relative_path)
        path = repo_root / relative_path
        if not path.is_file():
            errors.append(f"checksum.file_missing:{relative_path}")
            continue
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            errors.append(f"checksum.hash_mismatch:{relative_path}")
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "listed_paths": sorted(set(listed_paths)),
    }


def audit_python_import_closure(
    *,
    repo_root: Path,
    entrypoints: list[Path],
    tracked_paths: set[str] | None = None,
    checksum_paths: set[str] | None = None,
) -> dict[str, Any]:
    """Require every local Python import reachable from entrypoints to be present and tracked."""
    repo_root = repo_root.resolve()
    tracked = tracked_paths if tracked_paths is not None else _git_tracked_paths(repo_root)
    tracked = {_normalize_relative(path) for path in tracked}
    checksummed = (
        {_normalize_relative(path) for path in checksum_paths}
        if checksum_paths is not None
        else None
    )
    queue = [_relative_path(repo_root, path) for path in entrypoints]
    package_init = f"{PACKAGE_NAME}/__init__.py"
    if (repo_root / package_init).exists():
        queue.append(package_init)
    visited: set[str] = set()
    errors: list[str] = []

    while queue:
        relative_path = _normalize_relative(queue.pop(0))
        if relative_path in visited:
            continue
        visited.add(relative_path)
        path = repo_root / relative_path
        if not path.is_file():
            errors.append(f"python_entrypoint.missing:{relative_path}")
            continue
        if relative_path not in tracked:
            errors.append(f"python_import.untracked:{relative_path}")
        if checksummed is not None and relative_path not in checksummed:
            errors.append(f"python_import.not_in_checksum_manifest:{relative_path}")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            errors.append(f"python_import.unparseable:{relative_path}:{type(exc).__name__}")
            continue
        for module_name in _local_imports(tree, relative_path):
            dependency = _resolve_local_module(repo_root, module_name)
            if dependency is None:
                errors.append(f"python_import.missing:{relative_path}:{module_name}")
                continue
            dependency_relative = _relative_path(repo_root, dependency)
            if dependency_relative not in visited:
                queue.append(dependency_relative)

    return {
        "status": "valid" if not errors else "invalid",
        "errors": sorted(set(errors)),
        "visited_paths": sorted(visited),
    }


def audit_required_generated_artifacts(
    *,
    repo_root: Path,
    summaries: list[Path],
    tracked_paths: set[str] | None = None,
    ignored_paths: set[str] | None = None,
    checksum_paths: set[str] | None = None,
) -> dict[str, Any]:
    """Require source artifacts named by generated summaries to ship in the checkout."""
    repo_root = repo_root.resolve()
    tracked = tracked_paths if tracked_paths is not None else _git_tracked_paths(repo_root)
    tracked = {_normalize_relative(path) for path in tracked}
    ignored = (
        {_normalize_relative(path) for path in ignored_paths}
        if ignored_paths is not None
        else None
    )
    checksummed = (
        {_normalize_relative(path) for path in checksum_paths}
        if checksum_paths is not None
        else None
    )
    errors: list[str] = []
    references: list[dict[str, str]] = []

    for summary_arg in summaries:
        summary_path = _absolute_path(repo_root, summary_arg)
        summary_relative = _display_path(repo_root, summary_path)
        if not summary_path.is_file():
            errors.append(f"generated.summary_missing:{summary_relative}")
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"generated.summary_invalid:{summary_relative}:{type(exc).__name__}")
            continue
        for reference in _required_artifact_references(summary):
            artifact_path = Path(reference)
            if not artifact_path.is_absolute():
                artifact_path = summary_path.parent / artifact_path
            artifact_path = artifact_path.resolve()
            artifact_relative = _display_path(repo_root, artifact_path)
            references.append({"summary": summary_relative, "artifact": artifact_relative})
            if not artifact_path.is_file():
                errors.append(
                    f"generated.required_missing:{summary_relative}:{artifact_relative}"
                )
                continue
            is_ignored = (
                artifact_relative in ignored
                if ignored is not None
                else _git_path_is_ignored(repo_root, artifact_relative)
            )
            if is_ignored:
                errors.append(
                    f"generated.required_ignored:{summary_relative}:{artifact_relative}"
                )
            elif artifact_relative not in tracked:
                errors.append(
                    f"generated.required_untracked:{summary_relative}:{artifact_relative}"
                )
            if checksummed is not None and artifact_relative not in checksummed:
                errors.append(
                    f"generated.required_not_in_checksum_manifest:{summary_relative}:{artifact_relative}"
                )

    return {
        "status": "valid" if not errors else "invalid",
        "errors": sorted(set(errors)),
        "references": references,
    }


def _local_imports(tree: ast.AST, source_path: str) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name for alias in node.names
                if alias.name == PACKAGE_NAME or alias.name.startswith(f"{PACKAGE_NAME}.")
            )
        elif isinstance(node, ast.ImportFrom):
            module_name = _absolute_import_from(node, source_path)
            if module_name == PACKAGE_NAME or module_name.startswith(f"{PACKAGE_NAME}."):
                imports.add(module_name)
                # ``from agent_readiness import helper`` asks Python to resolve
                # ``agent_readiness.helper`` when it is a submodule.  Queue the
                # alias as well so a package-level import cannot hide an
                # untracked or missing local dependency from the closure audit.
                if module_name == PACKAGE_NAME:
                    imports.update(
                        f"{PACKAGE_NAME}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
    return imports


def _absolute_import_from(node: ast.ImportFrom, source_path: str) -> str:
    if node.level == 0:
        return str(node.module or "")
    module_parts = Path(source_path).with_suffix("").parts
    if module_parts[-1] == "__init__":
        package_parts = list(module_parts[:-1])
    else:
        package_parts = list(module_parts[:-1])
    keep = max(0, len(package_parts) - (node.level - 1))
    parts = package_parts[:keep]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _resolve_local_module(repo_root: Path, module_name: str) -> Path | None:
    module_path = repo_root.joinpath(*module_name.split("."))
    candidates = [module_path.with_suffix(".py"), module_path / "__init__.py"]
    return next((path for path in candidates if path.is_file()), None)


def _required_artifact_references(value: Any) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"source_artifact", "required_artifact"} and isinstance(child, str):
                references.append(child)
            elif key == "required_artifacts" and isinstance(child, list):
                references.extend(item for item in child if isinstance(item, str))
            else:
                references.extend(_required_artifact_references(child))
    elif isinstance(value, list):
        for child in value:
            references.extend(_required_artifact_references(child))
    return references


def _git_tracked_paths(repo_root: Path) -> set[str]:
    entries = _git_tree_entries(repo_root)
    if entries is None:
        return set()
    return {
        _normalize_relative(path)
        for mode, object_type, _object_id, path in entries
        if object_type == "blob"
    }


def _git_path_is_ignored(repo_root: Path, relative_path: str) -> bool:
    completed = _run_git(
        repo_root,
        ["check-ignore", "--quiet", "--", relative_path],
    )
    return completed.returncode == 0


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
        return subprocess.CompletedProcess(args, 127, b"", b"git not found")
    return subprocess.run(
        [str(Path(executable).resolve()), "--no-replace-objects", *args],
        cwd=repo_root,
        env=env,
        capture_output=True,
        check=False,
    )


def _git_tree_entries(
    repo_root: Path,
) -> set[tuple[str, str, str, str]] | None:
    completed = _run_git(
        repo_root,
        ["ls-tree", "-r", "-z", "--full-tree", "HEAD"],
    )
    if completed.returncode != 0:
        return None
    return _parse_git_entries(completed.stdout)


def _git_index_entries(
    repo_root: Path,
) -> set[tuple[str, str, str, str]] | None:
    completed = _run_git(repo_root, ["ls-files", "--stage", "-z"])
    if completed.returncode != 0:
        return None
    entries: set[tuple[str, str, str, str]] = set()
    for item in completed.stdout.split(b"\0"):
        if not item:
            continue
        try:
            metadata, raw_path = item.split(b"\t", 1)
            mode, object_id, stage = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8", errors="strict")
        except (UnicodeError, ValueError):
            return None
        if stage != b"0":
            return None
        object_type = "commit" if mode == b"160000" else "blob"
        entries.add(
            (
                mode.decode("ascii"),
                object_type,
                object_id.decode("ascii"),
                path,
            )
        )
    return entries


def _parse_git_entries(
    output: bytes,
) -> set[tuple[str, str, str, str]] | None:
    entries: set[tuple[str, str, str, str]] = set()
    for item in output.split(b"\0"):
        if not item:
            continue
        try:
            metadata, raw_path = item.split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8", errors="strict")
        except (UnicodeError, ValueError):
            return None
        entries.add(
            (
                mode.decode("ascii"),
                object_type.decode("ascii"),
                object_id.decode("ascii"),
                path,
            )
        )
    return entries


def _relative_path(repo_root: Path, path: Path | str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        return candidate.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return candidate.resolve().as_posix()


def _absolute_path(repo_root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def _display_path(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _normalize_relative(path: str) -> str:
    return Path(path.strip()).as_posix().removeprefix("./")


def _safe_repo_relative(path: str) -> bool:
    candidate = Path(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts


def _paths(values: Iterable[str]) -> list[Path]:
    return [Path(value) for value in values]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify checksum completeness, local Python imports, and generated evidence."
    )
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--entrypoint", action="append", default=[])
    parser.add_argument("--checksum-manifest", type=Path)
    parser.add_argument("--generated-summary", action="append", default=[])
    parser.add_argument(
        "--require-clean-worktree",
        action="store_true",
        help="require HEAD/index parity and no tracked, untracked, submodule, or bytecode dirt",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    entrypoints = _paths(args.entrypoint) or [Path("agent_readiness/intent_behavior_runner.py")]
    summary = audit_clean_checkout_integrity(
        repo_root=args.repo_root,
        entrypoints=entrypoints,
        checksum_manifest=args.checksum_manifest,
        generated_summaries=_paths(args.generated_summary),
        require_clean_worktree=args.require_clean_worktree,
    )
    output = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if summary.get("status") == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
