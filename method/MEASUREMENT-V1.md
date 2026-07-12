# Measurement v1

This is the executable measurement-layer contract for deciding what a bounded
experiment may say. Publication and canonical action-registry gates add
separate requirements before the benchmark can report an improvement. This
contract is deliberately stricter than the retained v0 evidence.

The current alias-safety and intent-behavior packages are historical frontier
observations. They remain useful for finding failure modes, but they are not
silently upgraded into v1 estimates. A v1 result starts with a new registered
manifest, a frozen execution census, and new run artifacts.

## What the benchmark measures

A measurement-v1 result measures a bounded Drupal agent task, not a single
universal "agent readiness" score. A result must name:

- the task and lifecycle stages exercised;
- the clean or owner-described messy starting substrate;
- the exact Drupal, agent, model, harness, prompt, tool, permission, evaluator,
  budget, and scoring pins;
- the mechanical task metric and its denominator;
- observable behavior receipts and instrumented cost;
- the population and task boundary to which the result applies.

The lifecycle spine is `choose_onboard`, `connect`, `understand`,
`plan_clarify`, `act`, `verify`, `recover`, and `handoff`. Current coverage and
target task families are defined in `benchmark-coverage-v1.json` and
`task-families-v1.json`. Those registries forbid treating a target design as
current evidence and forbid cross-task readiness aggregation.

`plan_clarify` and `handoff` are specified target contracts, but both remain
`not_covered`: no current evidence is attached to them. The target contract
measures retained, observable artifacts instead of private chain-of-thought.
For planning, a registered authority oracle scores whether the agent correctly
chose `proceed`, `ask`, `refuse`, or `escalate`; the same structured artifact
must surface assumptions, authority gaps, and planned verification, which the
independent evaluator compares with the registered oracle. For handoff, the
artifact must contain a state summary, unresolved risks, and the exact next
action and command, all bound to a registered handoff oracle. A cold second
agent receives only the registered task and that handoff artifact; retained
continuation receipts then score resumability and task-oracle success. Zero
registered decision points or handoff attempts invalidate the run rather than
producing a favorable rate.

## Two lanes, two questions

### Three execution cadences

Execution frequency does not change evidence grade:

1. A cheap per-change smoke or diagnostic run is labeled `diagnostic_only`.
   It can catch harness or product breakage, but it cannot enter the
   claim-bearing published experiment registry, produce an estimate, or support
   promotion.
2. A small fixed regression panel is labeled `directional_only`. It holds a
   useful engineering baseline and can show where to investigate, but its
   output cannot be relabeled as claim-grade evidence or attached to an
   improvement decision.
3. A full preregistered replication uses the v1 manifest, immutable roster,
   complete retained receipts, and the audit gates below. Only this cadence may
   produce a claim-grade estimate, and promotion still requires the separate
   canonical action-registry decision.

Smoke and directional outputs live outside claim-bearing evidence paths. A
later full run must register and execute its own complete census; renaming or
copying an earlier output does not satisfy registration, source custody, or
the roster audit.

### Fixed regression

Use `fixed_regression` to ask a narrow change question:

> With the agent stack and measurement stack held fixed, what happened before
> and after one registered Drupal-side treatment?

The manifest must define paired pre/post arms, the exact allowed Drupal state
delta, a complete attempt roster, order policy, primary metric, sample-size
rationale, confidence method, and minimum favorable effect. Any unregistered
state difference, replacement slot, incomplete pair, or optional continuation
invalidates the planned estimate.

V1 reports this as a comparative estimate. It does not make a causal claim:
the auditor rejects `claim_class: causal` because it cannot independently prove
assignment, reset integrity, or custody of every attempted run.

### Frontier observation

Use `frontier_observation` to ask:

> What did this exact current agent, model, harness, tool, and Drupal stack do?

The result may be a reportable descriptive estimate when all evidence is
complete. It cannot demonstrate that Drupal improved, and it cannot be compared
with an older mutable frontier stack as if only Drupal changed.

#### Frontier canary boundary

`run_frontier_canary.py` is a custody and snapshot-interpretation canary, not a
direct Drupal-operation benchmark. The trusted host collects one governed
Drupal snapshot and embeds it in the canonical prompt envelope. The task
forbids every tool call. A pinned macOS Seatbelt profile denies child-process
creation, so the agent cannot start a shell or escape process-group cleanup.
The agent-facing permissions profile denies the observed project, DDEV/Docker
control plane, credentials, Git metadata, and agent-tool network access.
Codex itself necessarily reads the referenced credential and uses provider
transport; those are trusted runner operations, not agent tools. Identical
trusted-host captures before and after each slot are required.

For the current macOS Codex runner, bundled system skills are preregistered by
starting the exact canonical `codex exec` shape with no auth under a pinned
`/usr/bin/sandbox-exec` profile. A loopback control proves that profile denies
network egress, and exact in-sandbox markers prove the socket denial rather
than merely accepting a failed subprocess. The profile also denies child-process
creation plus ambient user auth, config, plugins,
rules, memories, apps, and skills. The bootstrap must fail without a provider
exchange or response; its prompt, schema, argv, fixed environment, raw streams,
initial/final home manifests, and every bundled skill byte are retained in the
private canary evidence. Only the registered local DNS-denial event shape is
accepted; usage, quota, capacity, auth, HTTP, or other provider semantics fail
closed. The execution home is then seeded with exactly that tree and checked
before and after the turn. Home identity and mode, the exact auth symlink target,
profile and sentinel file types, every skill file and directory mode, and every
skill byte are bound. Unexpected provider-layer evidence, home entries, paths,
symlinks, plugins, unsafe modes, or drift fail the run.

This boundary depends on the pinned Codex and macOS sandbox binaries and the
recorded Darwin build; it is not portable proof for another operating system.
Seatbelt denies direct child-process creation for the pinned Codex process, but
it is not a container, VM, remote attestation, or proof against pre-existing
local brokers, Mach/XPC services, the host kernel, or a malicious pinned binary.
The host, pinned Codex binary, and recorded enforcement receipt remain trusted.
The bootstrap's `provider_exchange_observed=false` is a retained observation
under that boundary, not a provider attestation. The canary also does not attest
hosted model weights. A successful canary can support a descriptive result for
this exact inline-snapshot task only. No successful canary is currently shipped
in the public package.

## Register before execution

1. Create a manifest conforming to
   `agent_readiness/schema/benchmark-experiment-v1.schema.json`.
2. Freeze every execution slot in `execution_plan.attempt_roster`. The stopping
   rule must require the whole roster; replacements and outcome-based stopping
   are not permitted.
3. Store every referenced prompt, policy, fixture, ground-truth, evaluator, and
   pin artifact under one contained artifact root. Record its SHA-256 digest.
4. Serialize the manifest as canonical JSON and commit those exact bytes at the
   `registration.manifest_path` named by the manifest.
5. Record the full Git commit object ID. The registration commit must remain an
   ancestor of the commit used for audit, and its committer time must precede
   all supplied run start times.
6. Only then execute the registered roster.

Git proves content identity and repository ancestry. It does **not** provide an
independent timestamp or prove that omitted runs never existed: committer and
run times can be backdated, and a local object has no third-party custody. For
high-stakes publication, preserve a public commit or signed CI/transparency
receipt and an append-only attempt log outside the operator's control. Report
those receipts alongside the audit; do not describe the local Git check alone
as independently witnessed preregistration.

## Retain one complete run record per slot

Each run must conform to
`agent_readiness/schema/benchmark-run-v1.schema.json` and bind back to the
canonical manifest hash and one roster slot. Required retained artifacts are:

- the exact composed prompt and render inputs plus a prompt-delivery receipt;
- a unique agent/provider execution receipt bound to the roster slot;
- a model-identity receipt bound to that execution and retained as canonical
  evidence;
- answer context where applicable;
- transcript and tool log;
- starting and final Drupal state attestations reconciled to retained collector
  sources and code/site manifests;
- evaluator output plus a trusted evaluator-execution receipt;
- instrumented cost trace;
- observable behavior trace;
- the pre-outcome validity decision.

Required semantic JSON artifacts must use canonical bytes and equal the fields
in the run record. Empty evidence files, duplicate artifact identities used as
different evidence kinds, path traversal, hash mismatches, self-reported cost,
unregistered behavior phases, and incoherent metric denominators fail the
audit.

Behavior evidence is based on observable tool, harness, or independent-observer
receipts. Private chain-of-thought or a model's narration of what it did is not
a required measurement surface.

### Model backend identity

A model name, dated selector, thread ID, or unique provider request ID does not
prove immutable backend weights. Measurement v1 therefore has three explicit
registration modes:

- `held_selector` records the requested selector. A frontier result remains a
  descriptive snapshot; a fixed panel is `directional_only`.
- `provider_attested_snapshot` records provider evidence, but v1 deliberately
  fails it closed for claim-grade use until the auditor can authenticate raw
  provider evidence through a trusted issuer key or provider API. An operator-
  authored, hash-consistent attestation is not authenticity proof.
- `local_model_artifact` may qualify only when the exact local artifact bytes,
  a canonical runner contract, the digest-bearing launch argument, the attempt
  receipt, and the execution receipt all reconcile. This eligibility is inside
  a declared trusted-pinned-harness boundary; it is not hardware remote
  attestation against a malicious runner.

The audit exposes the assurance reason and limitations. Neither provider
request uniqueness nor direct invocation of the effect-rule helper can bypass
this gate.

## Audit levels

Run the auditor with the manifest, every roster run, the artifact root, and the
external registration anchor:

```bash
python3 agent_readiness/scripts/audit_measurement_v1.py \
  --manifest evidence/experiments/<experiment>/experiment.json \
  --run evidence/experiments/<experiment>/runs/<run-1>.json \
  --run evidence/experiments/<experiment>/runs/<run-2>.json \
  --artifact-root evidence/experiments/<experiment> \
  --registration-repo . \
  --registration-commit <full-commit-object-id> \
  --registration-manifest-path evidence/experiments/<experiment>/experiment.json \
  --require estimate
```

`--require` selects the minimum successful gate:

| Gate | Meaning |
| --- | --- |
| `contract` | Documents satisfy the schema and cross-document contract. No artifact or registration claim follows. |
| `evidence` | Exact registration bytes, hashes, semantic artifacts, and the complete supplied roster census verify. |
| `estimate` | Evidence is complete, there are no exclusions, the registered denominator is complete, and the registered estimate can be reported. A null estimate passes this gate. |
| `effect-rule` | A fixed-regression estimate's favorable one-sided confidence lower bound meets the positive registered minimum and every absolute guardrail passes. This is `registered_effect_rule_met`, not a final improvement decision. |

These levels are not synonyms. In particular, a valid package does not imply a
reportable estimate, a reportable estimate does not imply that the registered
effect rule passed, and an effect-rule result does not imply that the canonical
action registry adopted the change.

## Adversarial cases that fail closed

The v1 tests include counterexamples for:

- mutable or short registration refs and changed post-commit manifests;
- unreachable registration commits and registration times after execution;
- missing, duplicate, relabeled, replacement, excluded, or one-sided attempt
  slots;
- mixed frontier and fixed lanes;
- mutable model/tool labels and fixed-pair pin drift;
- unregistered Drupal treatment differences and component identity collisions;
- missing, empty, aliased, noncanonical, semantically inconsistent, traversing,
  or hash-mismatched artifacts;
- self-reported costs, budget overruns, and numerator/denominator mismatches;
- behavior source/artifact mismatches, missing lifecycle phases, overlapping
  events, and summaries that do not derive from retained events;
- post-outcome validity decisions and post-hoc exclusion codes;
- free-text estimands, undersized comparative designs, causal claims, and
  thresholds that define zero effect as a favorable result;
- reportable null estimates being mislabeled as a favorable effect.

The registry tests separately attack target-as-evidence promotion, unsafe
evidence paths, aggregate readiness language, incoherent metrics, wrong issue
ownership, non-executable clean/messy or fault matrices, narrative
chain-of-thought measures, volatile byte comparisons, and workflow decisions
without hashed run and metric evidence.

## From a result to an improvement

Every published actionable finding must map to exactly one record in
`improvement-registry-v1.json`. That record binds:

1. the failure and retained evidence;
2. a bounded diagnosis;
3. accountable Drupal and measurement owners plus canonical upstream work;
4. a proposed change;
5. a typed expected delta and guardrails;
6. a frozen role-specific binding plan with primary, placebo, and diagnostic
   contrasts;
7. a decision supported by lifecycle-custodied manifests and runs, recomputed
   metrics, mechanical completion checks, binding decisions, and a complete
   synthesis.

The workflow is fail-closed. The preregistered manifest pins an immutable action
design snapshot. Before that snapshot may move from `pending_registration` to
`frozen`, registration must also bind a separate hashed
`calibration_design_decision` artifact. That artifact must choose the intended
claim (`strong_effect_gate` or a separately revised pooled design), record the
detectable threshold, and approve the final sample and inference rules. The
registry's `artifact_required_before_freeze: true` flag is enforced by requiring
that exact artifact in the frozen registration and every later lifecycle
evidence prefix; prose or a sample-size rationale alone cannot satisfy the gate.

For the current unpooled 20-pair-per-binding design, the one-sided paired
Hoeffding margin rounds to `0.547`. An observed favorable effect must therefore
reach `0.747` for its lower confidence bound to reach the registered `0.2`
minimum. That is a strong-effect gate, not a design calibrated to detect a true
`0.2` effect. A smaller-effect claim requires a revised, separately registered
pooled design and its own approved sample and inference rule. Until one of those
choices is recorded in the hashed calibration decision, the canonical record
must remain pending and cannot support adoption.

The current proposed matrix contains 16 in-action bindings: two
placebo contrasts, one structured-facts primary contrast, and one policy-advice
diagnostic contrast, crossed with two substrates and two held-fixed model
cells. Prompt naming remains a separate non-Drupal diagnostic. Later
append-only transitions may bind execution, analysis, and decision artifacts
without rewriting that frozen snapshot. Pending work cannot contain an
adoption decision, and a decision cannot be promoted without the exact
registered manifest and run census, role-specific gates, mechanical completion,
guardrails, binding decisions, and complete synthesis. Publication readiness
therefore separates:

1. `estimate_reportable` — the bounded estimate can be reported;
2. `registered_effect_rule_met` — its registered uncertainty and guardrail rule
   passed;
3. `improvement_ready` — the named experiment is a verified
   `primary_efficacy` binding in a compatible decided-and-adopted canonical
   action record, its published sources match the lifecycle-custodied bytes,
   and the complete 16-binding synthesis adopts the explicit treatment scope.
   Placebo and diagnostic bindings never satisfy this per-experiment gate.

The current public improvement registry remains `pending_registration`, so the
third gate is intentionally false even if a standalone measurement fixture
meets its effect rule.

## Remaining validity boundary

The auditor establishes document integrity and internal consistency. It cannot
by itself prove that an operator truthfully captured the raw trace, that an
unverified hosted provider executed a claimed immutable backend, that a
malicious local runner honored its launch argument, that an external system
retained every attempt, or that the registered tasks represent all Drupal work.
Those are explicit trust and external-validity limits, not reasons to broaden
the claim.

Use provider or harness receipts, external registration and attempt custody,
multiple owner-described substrates, and independent replications when the
claim warrants them. Keep every result scoped to its task, metric, substrate,
agent stack, and lane.
