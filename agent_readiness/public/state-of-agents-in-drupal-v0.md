# State of Agents in Drupal v0: a runnable evidence loop for constrained Drupal agent tasks

Short version: this is a qualitative v0 snapshot and historical observation, not a statistical benchmark. It records a small, rerunnable evidence loop for Drupal CMS with the Haven testbed profile so the team can inspect what agents can verify today and what the running site still needs to expose.

This is not a cross-CMS comparison, not a model leaderboard, and not a migration-to-launch claim.

**This is an instrument and a historical observation, not a readiness verdict.** The loop below is a Drupal agent-evaluation harness; the scorecard reports retained evaluator outcomes, not evidence that Drupal is agent-ready or that the instrument is a validated discriminator.

## What we found

### Alias safety: named decision helper

This historical frontier observation compares a Drush-only condition with a bundled condition whose prompt names a verdict-bearing path helper. It does not isolate tool discovery, installation, prompt guidance, facts-only output, or an end-to-end write, and its original pins are incomplete.

The run is the analysis unit. Hidden-path judgments are nested within a run and are shown only as supporting detail.

| Model | Arm | Runs with all hidden judgments correct | Nested hidden judgments correct | Nested reasons naming hidden layer |
| --- | --- | ---: | ---: | ---: |
| claude-haiku-4-5 | raw_drush | 8/10 | 16/20 | 0/20 |
| claude-haiku-4-5 | site_architecture | 10/10 | 20/20 | 20/20 |
| claude-opus-4-8 | raw_drush | 7/10 | 14/20 | 14/20 |
| claude-opus-4-8 | site_architecture | 10/10 | 20/20 | 20/20 |
| gpt-5.5-codex | raw_drush | 0/3 | 0/6 | 0/6 |
| gpt-5.5-codex | site_architecture | 3/3 | 6/6 | 6/6 |

Claim boundary: Retained judgments differed between the Drush-only condition and the condition whose prompt named a verdict-bearing path helper; equipped answers cited disabled declarations. Tool discovery, the helper as an isolated cause, facts-only output, actual writes, provider generality, and longitudinal Drupal improvement are not established.
Evidence class: `exploratory_legacy_unpinned`; claim-grade: `false`.

### Intent behavior: preservation-only null

The retained summary reports whether the four SEO editor widgets survived. That is not a complete measure of appropriate authority/conflict handling, so this result is published as a preservation-only null rather than evidence that intent did or did not help generally.

| Arm | Runs | Preserved all four | Target considered before write | Task completion |
| --- | ---: | ---: | ---: | ---: |
| conflict-intent | 10 | 0/10 | 10/10 | 0/10 |
| no-intent | 10 | 0/10 | 10/10 | 0/10 |
| placebo-intent | 10 | 0/10 | 10/10 | 0/10 |

Claim boundary: The three arms were equal on SEO-widget preservation in this task. The summary does not establish appropriate conflict handling, general durable-intent value, or a Drupal-side longitudinal change.
Evidence class: `exploratory_summary_only`; claim-grade: `false`.


## What the package demonstrates

The package is an evidence loop: fixed public tasks, prompts, retained answers, scorecard run transcripts, live-state capture, mechanical evaluators, scorecard rows, readiness flags, and package hashes.

**This release makes one method claim:**

Constrained Drupal agent tasks can be packaged with public tasks, retained evidence, state capture, mechanical evaluators, and explicit claim boundaries. Each experiment above carries its own narrower evidence class; package validity does not promote an experiment to claim-grade.

The package may include tooling/evaluator smoke runs. Treat those as evidence that the mechanics execute, not as blinded independent-agent results.

## What we are not claiming yet

- Drupal is broadly agent-ready.
- This result is statistically powered.
- This is a cross-CMS comparison or model leaderboard.
- The public tasks are held out or uncontaminated.
- The bundled resolver fixture is production-ready.
- That the initial Codex result proves behavior across model providers.

## Method

Context and claim policy: `public/why-this-bench.md`. Reproduction details: the repository-root `method/HARNESS.md`.

- Hold the Drupal starting site fixed: Drupal CMS with the Haven testbed profile.
- Keep prompts and evaluators versioned.
- Require `answer.json`, transcript or command log, live-state collection, evaluator output, and run-result JSON for each scored run.
- Treat low v0 numbers as baseline evidence, not a failed initiative.

## Scorecard

- Constrained task runs in this scorecard: 10
- Constrained evaluator passes: 9/10
- Failing runs retained: 1
- Failing evidence: retained — at least one evaluator result is a failure; this alone does not establish matched discriminator validity.
- Inventory prompt: v0.2 (de-leaked) — answers must be discovered from the live site, not transcribed from the prompt. Some earlier passes used v0.1 (leaked) prompts; see prompt_version per run.

These constrained v0 tasks exercise the evidence loop and evaluator contract; they do not establish broad Drupal agent-readiness.

| This scorecard demonstrates | This scorecard does not establish |
| --- | --- |
| The harness can collect runs, retained answers, transcripts/logs, state, and evaluator output. | Drupal is broadly agent-ready. |
| The current evaluator code can recompute the retained pass/fail outputs from retained state and answers. | Agents can complete realistic Drupal projects, or that the evaluator has matched discriminator validity. |
| Public, rerunnable Drupal agent tasks are feasible. | The task set is statistically powered. |
| A retained failure can identify concrete missing context. | The current pass rate generalizes beyond these constrained tasks. |

### Tooling/evaluator smoke runs

These runs exercise the package, evaluator, and reporting loop.

| Run | Class | Task | Model | Substrate | Prompt | Success | Human rescues | Elapsed seconds | Tool calls | Metric source | Verification | Blast radius |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |
| haven-event-v0-tooling-smoke | tooling_smoke | act.event_jsonapi | none | haven-clean-install | v0.1 | true | 0 | 16.154 | 4 | operator_supplied_or_unknown | mechanical-pass | clean |
| haven-inventory-v0-tooling-smoke | tooling_smoke | inventory.read_only | none | haven-clean-install | v0.1 | true | 0 | 18.887 | 4 | operator_supplied_or_unknown | mechanical-pass | clean |
| haven-recovery-v0-tooling-smoke | tooling_smoke | recover.event_jsonapi | none | haven-clean-install | v0.1 | true | 0 | 12.426 | 3 | operator_supplied_or_unknown | mechanical-pass | clean |

### Non-smoke constrained agent runs

These runs provide early evidence about agent performance on constrained Drupal tasks. The label does not certify independence, pinning, or longitudinal comparability; use each row's provenance columns and run artifacts.

| Run | Class | Task | Model | Substrate | Prompt | Success | Human rescues | Elapsed seconds | Tool calls | Metric source | Verification | Blast radius |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |
| event-independent-20260620151052 | legacy_unpinned | act.event_jsonapi | gpt-5 | haven-clean-install | v0.1 | true | 0 | 518.0 | 50 | operator_supplied_or_unknown | mechanical-pass | clean |
| inventory-deleaked-blind | legacy_unpinned | inventory.read_only | claude-opus-4-8 | haven-clean-install | v0.2 | false | 0 | 196.0 | 32 | operator_supplied_or_unknown | mechanical-fail | clean |
| inventory-deleaked-equipped | legacy_unpinned | inventory.read_only | claude-opus-4-8 | haven-clean-install | v0.2 | true | 0 | 203.0 | 25 | operator_supplied_or_unknown | mechanical-pass | clean |
| inventory-enhanced-independent-20260620145648 | legacy_unpinned | inventory.read_only | gpt-5 | haven-clean-install | v0.1 | true | 0 | 336.0 | 36 | operator_supplied_or_unknown | mechanical-pass | clean |
| inventory-independent-20260620144627 | legacy_unpinned | inventory.read_only | gpt-5 | haven-clean-install | v0.1 | true | 0 | 536.0 | 48 | operator_supplied_or_unknown | mechanical-pass | clean |
| inventory-independent-pass3-20260620150332 | legacy_unpinned | inventory.read_only | gpt-5 | haven-clean-install | v0.1 | true | 0 | 372.0 | 33 | operator_supplied_or_unknown | mechanical-pass | clean |
| recovery-independent-20260620151052 | legacy_unpinned | recover.event_jsonapi | gpt-5 | haven-clean-install | v0.1 | true | 0 | 506.0 | 48 | operator_supplied_or_unknown | mechanical-pass | clean |

## Readiness

`public/readiness.json` is a generated, non-authoritative source-gate snapshot. It does not audit the live package tree. Run `scripts/audit_readiness.py` against the files and complete run census being circulated for the authoritative package result. This report render exposes only the run and experiment source gates it can derive directly:

- At least one no-rescue legacy inventory example: yes
- Three-example legacy evidence-loop check: yes (not a numeric-claim gate)
- Reportable measurement-v1 estimate: none
- Reportable fixed-regression estimate: none
- Registered measurement effect rule met: none
- Canonical action-registry improvement decision ready: none

Provenance — what the legacy example gates do NOT certify:

- Outcome judgments for the v0.2 inventory and alias-safety examples can be mechanically re-scored from retained answers and ground truth. Tool invocation, token/cost, and complete trajectory evidence are not independently instrumented or retained; legacy timing and tool counts may be operator-supplied or self-reported.
- Non-smoke status is inferred from legacy free-text metadata; it does not establish independence or complete pins.
- Passing examples certify the evidence-loop mechanics only; they do not establish a treatment effect, statistical power, or longitudinal improvement.

## Current interpretation

The candidate solution is simple:

- Static `AGENTS.md` should explain how to inspect safely.
- The running Drupal site should answer current site facts through live commands, config reads, path ownership, generated briefs, and machine-readable inventories.

The historical alias-safety observation is one example of a wrong-layer failure pattern: an agent can check the current routing layer while operation-relevant Drupal state exists elsewhere. It is not the full scope of path ownership or agent readiness.

The historical comparison bundled module/tool availability with prompt guidance naming a verdict-bearing helper. Retained judgments differed between that condition and Drush-only inspection, but the experiment does not isolate discoverability, installation, facts-only output, advice, or an actual write. `method/improvement-registry-v1.json` therefore requires those layers to be factored in the next frozen rerun.

## Publication Notes

- Publish the method, prompts, evaluator contract, and sample runs together.
- Keep v0 claims Drupal-first until repeated runs and more tasks exist.
- Do not present v0 as statistically significant; use it to make failure modes concrete and rerunnable.

## Next hardening steps

This v0 package exercises the evidence loop and recomputes retained passing and failing evaluator examples. It does not establish matched discriminator validity or broad Drupal agent-readiness.

Completed in v0.2:

- De-leaked the inventory prompt (v0.2): expected values are no longer printed in the prompt, so passing requires live discovery.
- Retained a failing run so the package exercises and recomputes both passing and failing evaluator outputs.
- Hardened the inventory evaluator: list fields are graded as sets (hallucinated surfaces fail) and Canvas page count must match exactly.
- Registered the historical alias-safety and intent studies with source hashes, explicit evidence classes, and narrow claim boundaries; the generated experiment tables above are the only numeric source for this report.

Remaining:

1. Run paired pre/post fixed-agent experiments with identical model, harness, prompt, tools, substrate, attempt policy, and evaluator pins before attributing a change to Drupal.
2. Factor decision helpers into discovery, facts-only, advice, and actual-write conditions so the benchmark can locate which layer changes behavior.
3. Measure intent conflict handling and authority resolution, not preservation alone.
4. Exercise the Drupal lifecycle on clean and messy sites, including onboarding, selection, planning, acting, verification, recovery, and handoff.
5. Capture harness-derived timing, token, cost, tool-call, rescue, invalid-attempt, and trajectory events for every claim-grade run.
6. Keep fixed-agent regression and frontier-observation lanes separate; do not publish an aggregate readiness score until coverage and construct-validity evidence justify it.
