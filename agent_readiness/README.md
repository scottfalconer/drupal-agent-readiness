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
- [Measurement v1 guide](../method/MEASUREMENT-V1.md)
- [Lifecycle coverage](../method/benchmark-coverage-v1.json)
- [Clean/messy task families](../method/task-families-v1.json)
- [Improvement registry](../method/improvement-registry-v1.json)

Run checks from the repository root, not from this subdirectory:

```bash
python3 -B -m unittest discover -s agent_readiness/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile agent_readiness/*.py agent_readiness/evaluators/*.py agent_readiness/scripts/*.py
python3 -S -B agent_readiness/scripts/audit_benchmark_registries_v1.py --format json
python3 agent_readiness/scripts/audit_measurement_v1.py --help
python3 -B agent_readiness/scripts/build_clean_manifest.py --repo-root . --check
python3 -B agent_readiness/scripts/audit_clean_checkout_integrity.py \
  --repo-root . --checksum-manifest CLEAN-MANIFEST.sha256 \
  --require-clean-worktree \
  --entrypoint agent_readiness/measurement_v1.py \
  --entrypoint agent_readiness/published_experiments.py \
  --entrypoint agent_readiness/benchmark_registries_v1.py
shasum -a 256 -c CLEAN-MANIFEST.sha256
```

Patch source behavior here first. The `repro/` tree is a frozen historical v0
snapshot used to audit the original evidence; it is not a mirror of the current
implementation and should not be imported by current checks.
