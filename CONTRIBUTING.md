# Contributing

This repository contains exploratory historical evidence plus a v1 measurement
contract for Drupal agent work. The most useful contributions are concrete,
reproducible, and narrow.

## Useful Contributions

- New task proposals with a starting site, prompt, expected result, evaluator
  contract, and claim boundary.
- Messy, adversarial, or owner-described Drupal starting sites with provenance.
- Evaluator bugs with a passing and failing fixture.
- Reruns with another agent stack, including prompts, answers, transcripts,
  model/version, harness, allowed tools, and evaluator output.
- Documentation fixes that make claims narrower or easier to audit.

## Claim Discipline

Do not expand v0 results into broad claims. In particular, do not claim:

- Drupal is broadly agent-ready.
- The v0 result is statistically powered.
- The result is a model leaderboard.
- The bundled `site_architecture` reproduction fixture is production-ready.
- Public tasks are held out or uncontaminated.

Use [docs/claims-ledger.md](docs/claims-ledger.md) as the claim boundary.

`docs/` is the repo front door for public readers. `agent_readiness/public/` is
the source-package copy used by the packaging checks. Mirrored files may differ
only where relative evidence paths need to point from their own directory.

## Run Submissions

Use Python 3.12 for all benchmark, audit, and test commands. This is the runtime
used in CI; older system Python installations are not supported.

A historical or diagnostic run submission should include:

- `answer.json`
- transcript or command log
- exact agent, model selector, harness, and system prompt
- allowed tools
- elapsed time, tool-call count, human-rescue count, and token counts, with
  explicit provenance or `unknown` rather than an inferred value
- content-addressed starting and final Drupal state
- evaluator output

Missing pins keep a submission exploratory. They must never be filled with
free-text guesses or promoted by editing a readiness boolean.

A v1 fixed-regression submission must additionally satisfy
[`method/MEASUREMENT-V1.md`](method/MEASUREMENT-V1.md): a committed canonical
manifest, exact run census, paired roster, retained prompt, execution, model,
and evaluator receipts, state and artifact closure, preregistered analysis and
guardrails, and the applicable backend-identity boundary. Hosted model names or
invented provider request IDs do not establish an immutable backend. The
canonical action registry—not the measurement effect rule alone—controls any
final improvement decision.

If the run used AI-generated code, prompts, or analysis, disclose that in the
submission. Review and understand any AI-generated output before submitting it.

## Local Checks

Run these from the repository root before opening a pull request:

```bash
python3 -B -m unittest discover -s agent_readiness/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile agent_readiness/*.py agent_readiness/evaluators/*.py agent_readiness/scripts/*.py
python3 -S -B agent_readiness/scripts/audit_benchmark_registries_v1.py --format json
python3 agent_readiness/scripts/audit_publication_package.py --base-dir agent_readiness $(find agent_readiness/runs -maxdepth 2 -name run-result.json | sort | sed 's/^/--run-result /')
python3 agent_readiness/scripts/audit_readiness.py --base-dir agent_readiness $(find agent_readiness/runs -maxdepth 2 -name run-result.json | sort | sed 's/^/--run-result /')
python3 -B agent_readiness/scripts/audit_clean_checkout_integrity.py \
  --repo-root . --checksum-manifest CLEAN-MANIFEST.sha256 \
  --require-clean-worktree \
  --entrypoint agent_readiness/intent_behavior_runner.py \
  --entrypoint agent_readiness/scripts/build_publish_assets.py \
  --entrypoint agent_readiness/scripts/audit_publication_package.py \
  --entrypoint agent_readiness/scripts/audit_readiness.py \
  --entrypoint agent_readiness/scripts/audit_measurement_v1.py \
  --entrypoint agent_readiness/scripts/audit_benchmark_registries_v1.py \
  --entrypoint agent_readiness/scripts/run_frontier_canary.py
python3 -B agent_readiness/scripts/build_clean_manifest.py --repo-root . --check
shasum -a 256 -c CLEAN-MANIFEST.sha256
```

If a change updates public package wording or artifacts, regenerate or update the
relevant public files and refresh `CLEAN-MANIFEST.sha256`.

Regenerate the clean manifest only from an immutable, already-committed release
candidate. The builder reads `HEAD`; it deliberately does not bless ambient
modified or untracked files:

```bash
python3 -B agent_readiness/scripts/build_clean_manifest.py --repo-root .
```
