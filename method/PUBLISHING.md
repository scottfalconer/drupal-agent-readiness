# Publishing Checklist

Use this checklist before circulating `State of Agents in Drupal` v0.
Unless a path is explicitly prefixed with `docs/`, `evidence/`, or `method/`,
package paths in this checklist refer to the runnable `agent_readiness/` source
package.

## Required Assets

- Public front door: root `README.md`
- Source-package method and guardrails: `agent_readiness/README.md`
- Task definitions: `tasks.yml`
- Fixed prompts: `prompts/*.md`
- Run-result contract: `schema/run-result.schema.json`
- Evaluators: `evaluators/evaluate_*.py`
- Drupal live-state collector: `evaluators/drupal_state_collector.php`
- At least one run package: `runs/<run-id>/`
- Generated public scorecard: `public/scorecard.csv`
- Source-hashed historical experiment registry:
  `experiments/published-experiments-v1.json`
- Generated normalized experiment metrics: `public/experiments-v1.json` and
  repo-front-door mirror `docs/experiments-v1.json`
- Generated public report: `public/state-of-agents-in-drupal-v0.md`
- Public finding: `public/finding-site-self-description-v0.md`
- Public bench rationale: `public/why-this-bench.md`
- Public claims ledger in the repo front door: `docs/claims-ledger.md`
- Generated non-authoritative source-gate snapshot: `public/readiness.json`;
  the live `scripts/audit_readiness.py` result is the package authority
- Generated package manifest with file hashes: `public/package-manifest.json`

## Current Package Status

The checked-in v0 package includes tooling/evaluator smoke runs:

- `haven-inventory-v0-tooling-smoke`
- `haven-event-v0-tooling-smoke`
- `haven-recovery-v0-tooling-smoke`

Those smoke runs are useful because they exercise:

- the Haven substrate can be cloned and inspected;
- live Drupal state can be collected through Drush;
- `answer.json` can be evaluated mechanically;
- Event creation and recovery evaluators can detect expected live-state changes;
- scorecard and report assets can be rebuilt and audited.

The package also includes retained no-rescue legacy agent runs:

- `inventory-deleaked-blind` — retained evaluator-failure example
- `inventory-deleaked-equipped`
- `inventory-independent-20260620144627`
- `inventory-enhanced-independent-20260620145648`
- `inventory-independent-pass3-20260620150332`
- `event-independent-20260620151052`
- `recovery-independent-20260620151052`

The word `independent` appears in some historical run IDs. It is not an evidence
classification and does not establish independence. These runs are classified
as `legacy_unpinned` unless they satisfy the v1 measurement contract.

`inventory-deleaked-blind` is intentionally retained as a failing run to
exercise a failing evaluator output; it does not by itself establish matched
discriminator validity and is not a passing run.

Those retained legacy runs are early constrained evidence. They do not prove:

- broad Drupal agent-readiness;
- statistical significance;
- month-over-month Drupal improvement;
- pass^k consistency for the write/recovery tasks;
- readiness outside the fixed Drupal CMS/Haven substrate and v0 prompts.

## Pre-Publish Gates

Package integrity, a reportable estimate, a comparable fixed-regression
estimate, a registered measurement effect rule, and a registered improvement
decision are separate gates. Passing an earlier gate never implies a later one.
See `method/MEASUREMENT-V1.md` for the full contract and trust boundary.

### Gate 1: package integrity and public evidence-loop assets

Run:

```bash
python3 -B -m unittest discover -s agent_readiness/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile agent_readiness/*.py agent_readiness/evaluators/*.py agent_readiness/scripts/*.py
python3 -S -B agent_readiness/scripts/audit_benchmark_registries_v1.py --format json
python3 -B agent_readiness/scripts/build_clean_manifest.py --repo-root . --check
python3 -B agent_readiness/scripts/audit_clean_checkout_integrity.py \
  --repo-root . \
  --checksum-manifest CLEAN-MANIFEST.sha256 \
  --require-clean-worktree \
  --entrypoint agent_readiness/intent_behavior_runner.py \
  --entrypoint agent_readiness/measurement_v1.py \
  --entrypoint agent_readiness/published_experiments.py \
  --entrypoint agent_readiness/benchmark_registries_v1.py \
  --generated-summary agent_readiness/experiments/intent-behavior-evaluation-v0-clean/summary.json
RUN_ARGS=()
while IFS= read -r path; do
  RUN_ARGS+=(--run-result "$path")
done < <(find agent_readiness/runs -mindepth 2 -maxdepth 2 -name run-result.json -print | sort)
python3 -B agent_readiness/scripts/audit_publication_package.py \
  --base-dir agent_readiness \
  "${RUN_ARGS[@]}"
```

The package is ready for review as an evidence-loop package only when all
commands pass and the report clearly labels smoke and legacy runs. This gate
does not make any experiment claim-grade.

Also run the readiness audit with the retained run results being published:

```bash
RUN_ARGS=()
while IFS= read -r path; do
  RUN_ARGS+=(--run-result "$path")
done < <(find agent_readiness/runs -mindepth 2 -maxdepth 2 -name run-result.json -print | sort)
python3 -B agent_readiness/scripts/audit_readiness.py \
  --base-dir agent_readiness \
  "${RUN_ARGS[@]}"
```

That live command returns JSON. `public_evidence_package_ready: true` reports that
the checked package-integrity and evidence-loop conditions passed at audit time.
It does not certify truthful provenance capture, construct validity, or broad
Drupal readiness. The compatibility field `public_v0_package_ready` has the
same bounded meaning. The checked-in `public/readiness.json` deliberately sets
package-dependent readiness fields to `null`; it is a source-gate snapshot and
cannot attest to later deletion, substitution, or untracked release dirt.

### Gate 2: reportable experiment estimate

First validate the experiment manifest and every planned run against the v1
contract. A reportable estimate requires the complete registered denominator,
exact Git registration bytes, and byte- and semantics-verified artifacts. A
valid contract alone is not a result:

```bash
python3 agent_readiness/scripts/audit_measurement_v1.py \
  --manifest <experiment-manifest.json> \
  --run <run-1.json> \
  --run <run-2.json> \
  --artifact-root <experiment-artifact-root> \
  --registration-repo . \
  --registration-commit <full-registration-commit-id> \
  --registration-manifest-path <repo-relative-manifest-path> \
  --require estimate
```

After the validated experiment is registered in the published data plane, run:

```bash
RUN_ARGS=()
while IFS= read -r path; do
  RUN_ARGS+=(--run-result "$path")
done < <(find agent_readiness/runs -mindepth 2 -maxdepth 2 -name run-result.json -print | sort)
python3 agent_readiness/scripts/audit_readiness.py \
  --base-dir agent_readiness \
  "${RUN_ARGS[@]}" \
  --require-estimate <experiment-id>
```

`estimate_ready: true` means at least one *named* source-audited measurement-v1
experiment has a reportable estimate. The per-experiment eligibility list is
canonical; the CLI gate requires the experiment ID so one result cannot promote
another. A null estimate passes this gate. Current historical alias-safety and
intent-behavior observations remain ineligible, and repeated legacy passes
cannot promote them.

### Gate 3: comparable fixed-regression estimate

To compare a Drupal-side treatment before and after, the experiment must be in
the `fixed_regression` lane with a paired pre/post contract and a held-fixed
agent and measurement stack:

```bash
RUN_ARGS=()
while IFS= read -r path; do
  RUN_ARGS+=(--run-result "$path")
done < <(find agent_readiness/runs -mindepth 2 -maxdepth 2 -name run-result.json -print | sort)
python3 agent_readiness/scripts/audit_readiness.py \
  --base-dir agent_readiness \
  "${RUN_ARGS[@]}" \
  --require-fixed-estimate <experiment-id>
```

`fixed_estimate_ready: true` permits reporting that bounded paired estimate. It
does not mean the registered improvement threshold passed. A
`frontier_observation` answers what an exact current agent/tool stack did and
cannot satisfy this gate.

### Gate 4: registered measurement effect rule

The measurement-level favorable-effect rule is a separate gate:

```bash
python3 agent_readiness/scripts/audit_measurement_v1.py \
  --manifest <experiment-manifest.json> \
  --run <every-registered-run.json> \
  --artifact-root <experiment-artifact-root> \
  --registration-repo . \
  --registration-commit <full-registration-commit-id> \
  --registration-manifest-path <repo-relative-manifest-path> \
  --require effect-rule
```

After registering that audited source in the published experiment registry,
require the same named result through the package readiness plane:

```bash
RUN_ARGS=()
while IFS= read -r path; do
  RUN_ARGS+=(--run-result "$path")
done < <(find agent_readiness/runs -mindepth 2 -maxdepth 2 -name run-result.json -print | sort)
python3 agent_readiness/scripts/audit_readiness.py \
  --base-dir agent_readiness \
  "${RUN_ARGS[@]}" \
  --require-effect-rule <experiment-id>
```

`registered_effect_rule_met: true` means the fixed-regression estimate's
favorable one-sided confidence lower bound meets the positive frozen minimum
and every absolute guardrail passes. It remains a measurement result, not a
workflow decision that Drupal improved.

### Gate 5: canonical action-registry improvement decision

An improvement statement requires the stricter cross-bound action decision:

```bash
RUN_ARGS=()
while IFS= read -r path; do
  RUN_ARGS+=(--run-result "$path")
done < <(find agent_readiness/runs -mindepth 2 -maxdepth 2 -name run-result.json -print | sort)
python3 agent_readiness/scripts/audit_readiness.py \
  --base-dir agent_readiness \
  "${RUN_ARGS[@]}" \
  --require-improvement <experiment-id>
```

`improvement_ready: true` is available only to a named `primary_efficacy`
experiment whose exact lifecycle-custodied manifest and run sources match the
canonical action record. The accepted action design has 16 in-action bindings:
two placebo contrasts, the structured-facts primary contrast, and the
policy-advice diagnostic contrast, each crossed with two substrates and two
held-fixed model cells. Every role-specific gate, mechanical completion check,
guardrail, binding decision, and the complete synthesis must verify, and the
synthesis must adopt the explicitly named treatment scope. Prompt naming stays
in a separate non-Drupal diagnostic lane. Placebo and diagnostic experiments
can satisfy their synthesis roles but never become `improvement_ready`.

The current registry remains `pending_registration`, so this gate is
intentionally false. Even a future passing decision is a bounded comparative
result, not a causal claim: measurement v1 rejects causal claim classes because
it cannot independently prove assignment, reset integrity, or complete external
attempt custody.

## Public Claim And Prompt-Leak Scan

Before public circulation, verify:

- The public package includes `public/why-this-bench.md`,
  `public/finding-site-self-description-v0.md`,
  `public/state-of-agents-in-drupal-v0.md`, `HARNESS.md`, `PUBLISHING.md`,
  scorecard, readiness JSON, and manifest.
- Fully blind prompts do not include ground-truth hints or candidate notes.
- Any task file that includes hints is labeled as a told/control variant.
- Every circulated Markdown front door (root and package READMEs/checklists,
  public/docs mirrors, method guides, and the repro notice) contains no
  affirmative broad-readiness or benchmark-verdict claim and no deprecated
  claims such as "replicates across vendors",
  "would alias content", "public baseline ready", "benchmark verdict", or
  "runs and discriminates".

The lexical scan is a fail-closed heuristic tripwire for common broad-readiness
paraphrases; it is not a complete semantic review and a passing scan does not
prove that every public statement is supported. The claims ledger and human
review remain required. Keep positive result statements bounded to the
registered experiment or claim ID and its stated scope, evidence, and
limitations; add a regression case whenever review finds a new unsafe
paraphrase class.

## Legacy Scorecard Capture Example

The older capture path remains useful for exercising the harness and retaining
no-rescue examples. It does not create a claim-grade or fixed-regression run. Use
`prompts/inventory.read_only.md` against a fresh disposable copy of Haven:

```bash
python3 agent_readiness/scripts/prepare_inventory_run.py \
  --run-id <legacy-inventory-run>
```

Give the agent the generated `agent-prompt.md`. The agent must produce its own
`answer.json` and transcript in that run directory. Then package and evaluate
the run:

```bash
python3 agent_readiness/scripts/capture_run.py \
  --run-id <legacy-inventory-run> \
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
run-result JSON, and package audit pass. Label it `legacy_unpinned`; a no-rescue
mechanical pass does not satisfy the claim-grade or longitudinal gate.

## Legacy Enhanced Inventory Variant

For the second inventory run, prepare a fresh clone and install the live
inspection commands first:

```bash
python3 agent_readiness/scripts/prepare_inventory_run.py \
  --run-id <enhanced-inventory-run> \
  --variant enhanced
```

Give the agent the same versioned inventory prompt plus the generated
`site-architecture-brief.md` and `site-architecture-surfaces.json` paths from
that run directory. Capture it with `scripts/capture_run.py` and retain it as a
legacy no-rescue example only if its artifacts and evaluator result are valid.
Do not describe it as independent or use it to satisfy a v1 measurement gate.
