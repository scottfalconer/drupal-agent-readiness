import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "agent_readiness" / "scripts" / "build_clean_manifest.py"


class CleanManifestTest(unittest.TestCase):

    def test_manifest_is_complete_deterministic_and_fails_after_tracked_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            tracked = root / "tracked.txt"
            ignored = root / "untracked.txt"
            tracked.write_text("first\n", encoding="utf-8")
            ignored.write_text("not in the index\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"],
                cwd=root,
                check=True,
            )

            built = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(root),
                    "--output",
                    "CLEAN-MANIFEST.sha256",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, built.returncode, built.stderr)
            manifest = root / "CLEAN-MANIFEST.sha256"
            first = manifest.read_text(encoding="utf-8")
            self.assertIn("  tracked.txt\n", first)
            self.assertNotIn("untracked.txt", first)

            subprocess.run(["git", "add", "CLEAN-MANIFEST.sha256"], cwd=root, check=True)
            checked = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(root),
                    "--output",
                    "CLEAN-MANIFEST.sha256",
                    "--check",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, checked.returncode, checked.stderr)

            tracked.write_text("changed\n", encoding="utf-8")
            drift = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(root),
                    "--output",
                    "CLEAN-MANIFEST.sha256",
                    "--check",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(1, drift.returncode)
            self.assertIn("clean-manifest-drift", drift.stderr)

    def test_ambient_alternate_index_cannot_omit_a_head_file(self) -> None:
        from agent_readiness.scripts.audit_clean_checkout_integrity import (
            audit_git_release_hygiene,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "keep.txt").write_text("keep\n", encoding="utf-8")
            (root / "overclaim.md").write_text(
                "must stay visible\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "add", "keep.txt", "overclaim.md"], cwd=root, check=True
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-qm",
                    "base",
                ],
                cwd=root,
                check=True,
            )
            alternate = Path(tmp) / "alternate-index"
            env = {**os.environ, "GIT_INDEX_FILE": str(alternate)}
            subprocess.run(["git", "read-tree", "--empty"], cwd=root, env=env, check=True)
            subprocess.run(["git", "add", "keep.txt"], cwd=root, env=env, check=True)

            built = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(root),
                    "--output",
                    "CLEAN-MANIFEST.sha256",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, built.returncode, built.stderr)
            manifest = (root / "CLEAN-MANIFEST.sha256").read_text(encoding="utf-8")
            self.assertIn("  keep.txt\n", manifest)
            self.assertIn("  overclaim.md\n", manifest)
            (root / "CLEAN-MANIFEST.sha256").unlink()
            with patch.dict(os.environ, {"GIT_INDEX_FILE": str(alternate)}):
                hygiene = audit_git_release_hygiene(root)
            self.assertEqual("valid", hygiene["status"], hygiene["errors"])

    def test_local_replace_object_cannot_omit_a_head_file(self) -> None:
        from agent_readiness.scripts.audit_clean_checkout_integrity import (
            audit_git_release_hygiene,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "keep.txt").write_text("keep\n", encoding="utf-8")
            (root / "overclaim.md").write_text(
                "must stay visible\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "add", "keep.txt", "overclaim.md"], cwd=root, check=True
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-qm",
                    "base",
                ],
                cwd=root,
                check=True,
            )
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()

            subprocess.run(
                ["git", "switch", "-qc", "replacement"], cwd=root, check=True
            )
            subprocess.run(["git", "rm", "-q", "overclaim.md"], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-qm",
                    "replacement",
                ],
                cwd=root,
                check=True,
            )
            replacement = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "switch", "-q", "--detach", base], cwd=root, check=True
            )
            subprocess.run(["git", "replace", base, replacement], cwd=root, check=True)

            built = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(root),
                    "--output",
                    "CLEAN-MANIFEST.sha256",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, built.returncode, built.stderr)
            manifest = (root / "CLEAN-MANIFEST.sha256").read_text(encoding="utf-8")
            self.assertIn("  keep.txt\n", manifest)
            self.assertIn("  overclaim.md\n", manifest)
            (root / "CLEAN-MANIFEST.sha256").unlink()

            subprocess.run(["git", "read-tree", replacement], cwd=root, check=True)
            (root / "overclaim.md").unlink()
            hygiene = audit_git_release_hygiene(root)
            self.assertEqual("invalid", hygiene["status"])
            self.assertIn("release_git.index_differs_from_head", hygiene["errors"])

    def test_frontier_canary_entrypoint_closure_reaches_local_dependencies(self) -> None:
        from agent_readiness.scripts.audit_clean_checkout_integrity import (
            audit_python_import_closure,
        )

        local_sources = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "agent_readiness").rglob("*.py")
            if path.is_file()
        }
        report = audit_python_import_closure(
            repo_root=REPO_ROOT,
            entrypoints=[Path("agent_readiness/scripts/run_frontier_canary.py")],
            tracked_paths=local_sources,
            checksum_paths=local_sources,
        )

        self.assertEqual("valid", report["status"], report["errors"])
        self.assertIn("agent_readiness/frontier_canary.py", report["visited_paths"])
        self.assertIn("agent_readiness/codex_runner_utils.py", report["visited_paths"])

    def test_release_hygiene_rejects_untracked_modified_and_bytecode_dirt(self) -> None:
        from agent_readiness.scripts.audit_clean_checkout_integrity import (
            audit_git_release_hygiene,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            tracked = root / "tracked.txt"
            tracked.write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"],
                cwd=root,
                check=True,
            )
            self.assertEqual("valid", audit_git_release_hygiene(root)["status"])

            untracked = root / "untracked.txt"
            untracked.write_text("dirt\n", encoding="utf-8")
            dirty = audit_git_release_hygiene(root)
            self.assertTrue(any("release_worktree.dirty:?? untracked.txt" in error for error in dirty["errors"]))
            untracked.unlink()

            tracked.write_text("changed\n", encoding="utf-8")
            modified = audit_git_release_hygiene(root)
            self.assertTrue(any("release_worktree.dirty:" in error for error in modified["errors"]))
            tracked.write_text("clean\n", encoding="utf-8")

            cache = root / "ignored" / "__pycache__" / "payload.pyc"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"malicious")
            cached = audit_git_release_hygiene(root)
            self.assertIn(
                "release_executable_cache.present:ignored/__pycache__/payload.pyc",
                cached["errors"],
            )

            link = root / "untracked-link"
            link.symlink_to(tracked)
            linked = audit_git_release_hygiene(root)
            self.assertIn("release_symlink.present:untracked-link", linked["errors"])

    def test_release_hygiene_rejects_dirty_submodule(self) -> None:
        from agent_readiness.scripts.audit_clean_checkout_integrity import (
            audit_git_release_hygiene,
        )

        with tempfile.TemporaryDirectory() as tmp:
            container = Path(tmp)
            child = container / "child"
            root = container / "repo"
            child.mkdir()
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=child, check=True)
            (child / "child.txt").write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "child.txt"], cwd=child, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "child"],
                cwd=child,
                check=True,
            )
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "protocol.file.allow=always",
                    "submodule",
                    "add",
                    "-q",
                    str(child),
                    "modules/child",
                ],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qam", "submodule"],
                cwd=root,
                check=True,
            )
            self.assertEqual("valid", audit_git_release_hygiene(root)["status"])

            (root / "modules/child/untracked.txt").write_text("dirt\n", encoding="utf-8")
            dirty = audit_git_release_hygiene(root)

        self.assertEqual("invalid", dirty["status"])
        self.assertTrue(
            any("release_worktree.dirty:" in error for error in dirty["errors"]),
            dirty["errors"],
        )


if __name__ == "__main__":
    unittest.main()
