## Summary

## Claim Boundary

Does this change alter any public claim, denominator, prompt, evaluator, or
artifact path? If yes, explain and update `docs/claims-ledger.md`.

## Validation

- [ ] `python3 -B -m unittest discover -s agent_readiness/tests -v`
- [ ] `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile agent_readiness/*.py agent_readiness/evaluators/*.py agent_readiness/scripts/*.py`
- [ ] `python3 agent_readiness/scripts/audit_publication_package.py --base-dir agent_readiness $(find agent_readiness/runs -maxdepth 2 -name run-result.json | sort | sed 's/^/--run-result /')`
- [ ] `python3 agent_readiness/scripts/audit_readiness.py --base-dir agent_readiness $(find agent_readiness/runs -maxdepth 2 -name run-result.json | sort | sed 's/^/--run-result /')`
- [ ] `shasum -a 256 -c CLEAN-MANIFEST.sha256`

## Run Artifacts

If this adds or changes a run, include the prompt, answer, transcript/log,
model/version, harness, allowed tools, evaluator output, and starting-site
provenance.
