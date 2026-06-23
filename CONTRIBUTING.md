# Contributing

This repository is a public v0 evidence package for Drupal agent-readiness work.
The most useful contributions are concrete, reproducible, and narrow.

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
- The prototype module is production-ready.
- Public tasks are held out or uncontaminated.

Use [docs/claims-ledger.md](docs/claims-ledger.md) as the claim boundary.

`docs/` is the repo front door for public readers. `agent_readiness/public/` is
the source-package copy used by the packaging checks. Mirrored files may differ
only where relative evidence paths need to point from their own directory.

## Run Submissions

A run submission should include:

- `answer.json`
- transcript or command log
- agent name, model/version, harness, and system prompt where available
- allowed tools
- elapsed time, tool-call count, human-rescue count, and token counts where
  available
- starting-site provenance or hash
- evaluator output

If the run used AI-generated code, prompts, or analysis, disclose that in the
submission. Review and understand any AI-generated output before submitting it.

## Local Checks

Run these from the repository root before opening a pull request:

```bash
python3 -B -m unittest discover -s agent_readiness/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile agent_readiness/*.py agent_readiness/evaluators/*.py agent_readiness/scripts/*.py
python3 agent_readiness/scripts/audit_publication_package.py --base-dir agent_readiness $(find agent_readiness/runs -maxdepth 2 -name run-result.json | sort | sed 's/^/--run-result /')
python3 agent_readiness/scripts/audit_readiness.py --base-dir agent_readiness $(find agent_readiness/runs -maxdepth 2 -name run-result.json | sort | sed 's/^/--run-result /')
shasum -a 256 -c CLEAN-MANIFEST.sha256
```

If a change updates public package wording or artifacts, regenerate or update the
relevant public files and refresh `CLEAN-MANIFEST.sha256`.

Refresh the clean manifest from tracked plus new nonignored files:

```bash
{ git ls-files; git ls-files --others --exclude-standard; } \
  | grep -v '^CLEAN-MANIFEST\.sha256$' \
  | LC_ALL=C sort -u \
  | xargs shasum -a 256 > CLEAN-MANIFEST.sha256
```
