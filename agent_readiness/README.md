# Active Source Package

This directory contains the current Python implementation of Drupal Agent
Readiness. It includes evaluators, scripts, tests, prompts, fixtures, and public
package assets.

Use the [project README](../README.md) for the purpose, evidence limits, and
initial setup. Use Python 3.12 for the commands below.

## Check The Source

Run commands from the repository root.

1. Run the unit tests.

   ```bash
   python3 -B -m unittest discover -s agent_readiness/tests -v
   ```

2. Check the benchmark registries.

   ```bash
   python3 -S -B agent_readiness/scripts/audit_benchmark_registries_v1.py --format json
   ```

3. Check the generated evaluation documents.

   ```bash
   python3 -S -B -m agent_readiness.scripts.build_eval_landscape --check
   python3 -S -B -m agent_readiness.scripts.build_external_eval_results --check
   ```

The [contributor guide](../CONTRIBUTING.md) explains the change process. The
[publishing checklist](../method/PUBLISHING.md) defines the complete release
checks. File changes require updated generated assets and checksums before the
clean-checkout audit can pass.

## Make Changes

Make current behavior changes in this directory. The
[`repro/` directory](../repro/README.md) preserves historical v0 source. Current
checks must not import that historical source.

The [`site_architecture` fixture](fixtures/site_architecture_module/) supplies
Drupal test tools for disposable sites. It is not a supported public module.

| Work | Reference |
| --- | --- |
| Review a claim | [Claims ledger](../docs/claims-ledger.md) |
| Inspect the historical finding | [Path-safety finding](../docs/finding-site-self-description-v0.md) |
| Prepare an alias-safety experiment | [Harness guide](../method/HARNESS.md) |
| Register an experiment | [Measurement v1 guide](../method/MEASUREMENT-V1.md) |
| Review task coverage | [Coverage registry](../method/benchmark-coverage-v1.json) |
| Review target tasks | [Task-family registry](../method/task-families-v1.json) |
| Record a proposed improvement | [Improvement registry](../method/improvement-registry-v1.json) |
| Prepare a human-agent study | [First-hour study kit](../method/human-agent-first-hour/README.md) |
