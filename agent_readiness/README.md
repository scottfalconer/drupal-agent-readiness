# agent_readiness Source Package

This directory contains the runnable Python source, evaluator code, scripts,
tests, prompts, fixtures, and generated public package assets used by the v0
evidence loop.

Start from the repository root for public context:

- [Project README](../README.md)
- [Finding write-up](../docs/finding-site-self-description-v0.md)
- [Claims ledger](../docs/claims-ledger.md)
- [Harness](../method/HARNESS.md)
- [Publishing checklist](../method/PUBLISHING.md)

Run checks from the repository root, not from this subdirectory:

```bash
python3 -B -m unittest discover -s agent_readiness/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile agent_readiness/*.py agent_readiness/evaluators/*.py agent_readiness/scripts/*.py
shasum -a 256 -c CLEAN-MANIFEST.sha256
```

Patch source behavior here first. The `repro/` tree is the retained
release-package copy used for public audit and should only be changed when the
release copy is intentionally kept in sync.
