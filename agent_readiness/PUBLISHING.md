# Publishing Checklist

Use this checklist before circulating `State of Agents in Drupal` v0.
Unless a path is explicitly prefixed with `docs/`, `evidence/`, `method/`, or
`prototype/`, package paths in this checklist refer to the runnable
`agent_readiness/` source package.

## Required Assets

- Method and guardrails: `README.md`
- Task definitions: `tasks.yml`
- Fixed prompts: `prompts/*.md`
- Run-result contract: `schema/run-result.schema.json`
- Evaluators: `evaluators/evaluate_*.py`
- Drupal live-state collector: `evaluators/drupal_state_collector.php`
- At least one run package: `runs/<run-id>/`
- Generated public scorecard: `public/scorecard.csv`
- Generated public report: `public/state-of-agents-in-drupal-v0.md`
- Public finding: `public/finding-site-self-description-v0.md`
- Public bench rationale: `public/why-this-bench.md`
- Public claims ledger in the repo front door: `../docs/claims-ledger.md`
- Generated readiness snapshot: `public/readiness.json`
- Generated package manifest with file hashes: `public/package-manifest.json`

## Current Package Status

The checked-in v0 package includes tooling/evaluator smoke runs:

- `haven-inventory-v0-tooling-smoke`
- `haven-event-v0-tooling-smoke`
- `haven-recovery-v0-tooling-smoke`

Those smoke runs are useful because they prove:

- the Haven substrate can be cloned and inspected;
- live Drupal state can be collected through Drush;
- `answer.json` can be evaluated mechanically;
- Event creation and recovery evaluators can detect expected live-state changes;
- scorecard and report assets can be rebuilt and audited.

The package also includes independent/constrained agent runs:

- `inventory-independent-20260620144627`
- `inventory-enhanced-independent-20260620145648`
- `inventory-independent-pass3-20260620150332`
- `event-independent-20260620151052`
- `recovery-independent-20260620151052`

Those independent runs are early constrained evidence. They do not prove:

- broad Drupal agent-readiness;
- statistical significance;
- month-over-month Drupal improvement;
- pass^k consistency for the write/recovery tasks;
- readiness outside the fixed Drupal CMS/Haven substrate and v0 prompts.

## Pre-Publish Gate

Run:

```bash
python3 -B -m unittest discover -s agent_readiness/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile agent_readiness/*.py agent_readiness/evaluators/*.py agent_readiness/scripts/*.py
python3 agent_readiness/scripts/audit_publication_package.py \
  --base-dir agent_readiness \
  --run-result agent_readiness/runs/haven-inventory-v0-tooling-smoke/run-result.json \
  --run-result agent_readiness/runs/haven-event-v0-tooling-smoke/run-result.json \
  --run-result agent_readiness/runs/haven-recovery-v0-tooling-smoke/run-result.json
```

The package is ready for private circulation only when all commands pass and the
report clearly labels smoke runs as smoke runs.

For a public independent-agent baseline, also run:

```bash
python3 agent_readiness/scripts/audit_readiness.py \
  --base-dir agent_readiness \
  --run-result agent_readiness/runs/<independent-inventory-run>/run-result.json
```

That command returns JSON. `private_circulation_ready` is enough for internal
review of the smoke package. `public_v0_package_ready` is required before
publishing the v0 package as public evidence.

For any constrained v0 mechanical-pass claim, require `numeric_claim_ready: true`:

```bash
python3 agent_readiness/scripts/audit_readiness.py \
  --base-dir agent_readiness \
  --run-result agent_readiness/runs/<independent-inventory-run-1>/run-result.json \
  --run-result agent_readiness/runs/<independent-inventory-run-2>/run-result.json \
  --run-result agent_readiness/runs/<independent-inventory-run-3>/run-result.json
```

Do not interpret that flag as permission to claim broad Drupal agent-readiness
or a statistically meaningful benchmark result. It only says the constrained v0
mechanical-pass evidence loop has enough repeated inventory runs for the
package's narrow claim scope.

## Public Claim And Prompt-Leak Scan

Before public circulation, verify:

- The public package includes `public/why-this-bench.md`,
  `public/finding-site-self-description-v0.md`,
  `public/state-of-agents-in-drupal-v0.md`, `HARNESS.md`, `PUBLISHING.md`,
  scorecard, readiness JSON, and manifest.
- Fully blind prompts do not include ground-truth hints or candidate notes.
- Any task file that includes hints is labeled as a told/control variant.
- Public docs contain no deprecated claims such as "replicates across vendors",
  "would alias content", "public baseline ready", or "benchmark verdict".

## First Independent Baseline

For the first scored baseline, use `prompts/inventory.read_only.md` against a
fresh disposable copy of Haven:

```bash
python3 agent_readiness/scripts/prepare_inventory_run.py \
  --run-id <independent-inventory-run>
```

Give the agent the generated `agent-prompt.md`. The agent must produce its own
`answer.json` and transcript in that run directory. Then package and evaluate
the run:

```bash
python3 agent_readiness/scripts/capture_run.py \
  --run-id <independent-inventory-run> \
  --task-id inventory.read_only \
  --site-root <workspace>/tmp/agent-readiness/<run-id>/site \
  --answer-json /path/to/answer.json \
  --transcript /path/to/transcript.md \
  --agent-name "<agent name>" \
  --agent-model "<model>" \
  --agent-harness "<harness>" \
  --elapsed-seconds <seconds> \
  --tool-calls <count> \
  --human-rescues <count>
```

Only add that run to the public scorecard after the evaluator output, transcript,
run-result JSON, publication audit, and baseline gate all pass.

## Enhanced Inventory Variant

For the second inventory run, prepare a fresh clone and install the live
inspection commands first:

```bash
python3 agent_readiness/scripts/prepare_inventory_run.py \
  --run-id <enhanced-inventory-run> \
  --variant enhanced
```

Give the agent the same fixed inventory prompt plus the generated
`site-architecture-brief.md` and `site-architecture-surfaces.json` paths from
that run directory. Capture it with `scripts/capture_run.py` and include it in
the baseline gate only if it is an independent no-rescue mechanical pass.
