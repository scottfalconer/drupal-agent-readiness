# State of Agents in Drupal v0: a repeatable evidence loop for constrained Drupal agent tasks

Short version: this is a qualitative v0 snapshot and first finding, not a statistical benchmark. It records a small, repeatable evidence loop for Drupal CMS with the Haven testbed profile so the team can inspect what agents can verify today and what the running site still needs to expose.

This is not a cross-CMS comparison, not a model leaderboard, and not a migration-to-launch claim.

**This is an instrument and a first finding, not a readiness verdict.** The loop below is a Drupal agent-evaluation harness; the scorecard shows the loop runs and discriminates, not that Drupal is agent-ready.

## What we found

We tested a simple question: can an external AI agent safely decide if a Drupal URL path is free to use as a new node alias?

Some Drupal paths look unused but are still claimed by disabled configuration. An agent using ordinary Drush-only inspection can ask whether anything currently routes there and still answer the wrong Drupal question: what Drupal will do with this path for the proposed operation, and whether the change could collide with active or inactive site state.

In the headline run on stock Drupal CMS with the Haven testbed profile, each run asked the agent to judge two hidden path claims. Ten runs produced 20 hidden disabled-View path judgments per arm.

| Model | Runs (hidden judgments) | Drush-only correctly flagged unsafe | Drush-only reason named disabled View | With self-description correctly flagged unsafe | With self-description reason |
| --- | ---: | ---: | ---: | ---: | ---: |
| claude-haiku-4-5 | 10 runs (20 judgments) | 16/20 (80%) | 0/20 (0%) | 20/20 (100%) | 20/20 (100%) |
| claude-opus-4-8 | 10 runs (20 judgments) | 14/20 (70%) | 14/20 (70%) | 20/20 (100%) | 20/20 (100%) |

Put differently: Drush-only agents incorrectly judged hidden path claims as safe in roughly 20-30% of hidden disabled-View path judgments. With site self-description through `site-architecture:path-owner`, we observed 0 hidden-claim safe judgments in the headline run.

The stock Haven hidden paths are under `/admin`, so the verdict and the reason are separated. A verdict can be correct because an agent treats `/admin` paths as conventionally unsafe; the reasoned column shows whether the agent actually identified the disabled-View declaration.

Initial non-Claude evidence shows the same pattern: OpenAI Codex (`gpt-5.5-codex`, the Codex agent/model id in the retained artifacts, not the legacy Codex API models) judged 6/6 hidden claims safe with Drush-only inspection and flagged 6/6 with site self-description. That is encouraging breadth evidence, not yet a claim across model providers.

Full write-up: `finding-site-self-description-v0.md` (source package path: `public/finding-site-self-description-v0.md`). Why this bench exists: `why-this-bench.md` (source package path: `public/why-this-bench.md`). Full method and reproduction steps: `method/HARNESS.md` in the repo root.

## What the method proves

The package is an evidence loop: fixed public tasks, prompts, retained answers, scorecard run transcripts, live-state capture, mechanical evaluators, scorecard rows, readiness flags, and package hashes.

**This release makes three claims:**

1. **Finding:** site self-description changed behavior and reduced measured hidden-claim safe judgments in this constrained task.
2. **Method:** constrained Drupal agent tasks can be measured with public tasks, retained answers, scorecard transcripts, state capture, and mechanical evaluators.
3. **Roadmap signal:** site self-description is a concrete Drupal roadmap item because it changes agent behavior.

The package may include tooling/evaluator smoke runs. Treat those as proof that the evidence loop works, not as blinded independent-agent results.

## What we are not claiming yet

- Drupal is broadly agent-ready.
- This result is statistically powered.
- This is a cross-CMS comparison or model leaderboard.
- The public tasks are held out or uncontaminated.
- The prototype resolver is production-ready.
- That the initial Codex result proves behavior across model providers.

## Method

- Hold the Drupal starting site fixed: Drupal CMS with the Haven testbed profile.
- Keep prompts and evaluators versioned.
- Require `answer.json`, transcript or command log, live-state collection, evaluator output, and run-result JSON for each scored run.
- Treat low v0 numbers as baseline evidence, not a failed initiative.

## Scorecard

- Constrained task runs in this scorecard: 10
- Constrained evaluator passes: 9/10
- Failing runs retained: 1
- Discrimination: demonstrated — the evaluator fails an incorrect answer on identical ground truth.
- Inventory prompt: v0.2 (de-leaked) — answers must be discovered from the live site, not transcribed from the prompt. Some earlier passes used v0.1 (leaked) prompts; see prompt_version per run.

These are constrained v0 tasks. They prove the evidence loop and evaluator contract, not broad Drupal agent-readiness.

| This scorecard proves | This scorecard does not prove |
| --- | --- |
| The harness can collect runs, retained answers, transcripts/logs, state, and evaluator output. | Drupal is broadly agent-ready. |
| The evaluator can pass correct answers and fail incorrect answers. | Agents can complete realistic Drupal projects. |
| Public, repeatable Drupal agent tasks are feasible. | The task set is statistically powered. |
| A retained failure can identify concrete missing context. | The current pass rate generalizes beyond these constrained tasks. |

### Tooling/evaluator smoke runs

These runs prove the package, evaluator, and reporting loop work.

| Run | Task | Success | Human rescues | Elapsed seconds | Tool calls | Verification | Blast radius |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| haven-event-v0-tooling-smoke | act.event_jsonapi | true | 0 | 16.154 | 4 | mechanical-pass | clean |
| haven-inventory-v0-tooling-smoke | inventory.read_only | true | 0 | 18.887 | 4 | mechanical-pass | clean |
| haven-recovery-v0-tooling-smoke | recover.event_jsonapi | true | 0 | 12.426 | 3 | mechanical-pass | clean |

### Independent/constrained agent runs

These runs provide early evidence about agent performance on constrained Drupal tasks.

| Run | Task | Success | Human rescues | Elapsed seconds | Tool calls | Verification | Blast radius |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| event-independent-20260620151052 | act.event_jsonapi | true | 0 | 518.0 | 50 | mechanical-pass | clean |
| inventory-deleaked-blind | inventory.read_only | false | 0 | 196.0 | 32 | mechanical-fail | clean |
| inventory-deleaked-equipped | inventory.read_only | true | 0 | 203.0 | 25 | mechanical-pass | clean |
| inventory-enhanced-independent-20260620145648 | inventory.read_only | true | 0 | 336.0 | 36 | mechanical-pass | clean |
| inventory-independent-20260620144627 | inventory.read_only | true | 0 | 536.0 | 48 | mechanical-pass | clean |
| inventory-independent-pass3-20260620150332 | inventory.read_only | true | 0 | 372.0 | 33 | mechanical-pass | clean |
| recovery-independent-20260620151052 | recover.event_jsonapi | true | 0 | 506.0 | 48 | mechanical-pass | clean |

## Readiness

- Private circulation: ready
- Public v0 package: ready
- Constrained v0 mechanical-pass claims: ready

Provenance — what these flags do NOT certify:

- Metrics for the inventory/event/recovery runs are operator-supplied, not instrumented (the v0.2 de-leaked inventory run and the alias-safety runs are instrumented).
- 'Independent' is asserted via free-text agent metadata, not bound to the answer.
- The flags certify the evidence-loop method plus N genuine evaluator passes on a fixed Drupal starting site — not a blinded or statistically-powered benchmark.

## Current interpretation

The candidate solution is simple:

- Static `AGENTS.md` should explain how to inspect safely.
- The running Drupal site should answer current site facts through live commands, config reads, path ownership, generated briefs, and machine-readable inventories.

The alias-safety finding is the first example of a wrong-layer failure pattern: the agent checks the current routing layer and can judge paths safe despite operation-specific Drupal state. It is not the full scope of path ownership or agent readiness.

The controlled tests support that second point narrowly. Live self-description helps lightly prompted agents avoid hidden path conflicts. When an agent is already told exactly what hidden state to check, the extra tool adds little correctness value.

## Experiments

`assess.alias_safety` compares `site-architecture:path-owner` with Drush-only inspection.

What varied:

- Models: claude-haiku-4-5 and claude-opus-4-8.
- Drupal starting sites: Haven, core-std, Convivial, plus one controlled non-admin hidden path claim.
- Prompt framing: told, soft-blind, and fully blind.

What the experiment found:

- When the agent is told the safety criterion, both arms are near 100%; the tool gives little correctness edge.
- When the agent is not told the hidden risk, Drush-only inspection can judge disabled-View hidden path claims safe.
- On stock Haven at n=10 runs per arm, with two hidden-claim judgments per run, Drush-only inspection flagged 80% (haiku) and 70% (opus) of hidden claims.
- With `path-owner`, both models flagged 100% of those hidden claims.
- Initial OpenAI Codex evidence shows the same direction: Drush-only judged 6/6 hidden claims safe and site self-description flagged 6/6. That is non-Claude breadth evidence at n=3, not a provider-general claim.

So the tool's narrow correctness value is reducing observed hidden-claim safe judgments for lightly prompted agents. Evidence, not proof. See the retained `alias-safety-SYNTHESIS.md` in the experiment evidence package.

## Publication Notes

- Publish the method, prompts, evaluator contract, and sample runs together.
- Keep v0 claims Drupal-first until repeated runs and more tasks exist.
- Do not present v0 as statistically significant; use it to make failure modes concrete and rerunnable.

## Next hardening steps

This v0 package proves the evidence loop and now demonstrates discrimination. It does not yet prove broad Drupal agent-readiness.

Completed in v0.2:

- De-leaked the inventory prompt (v0.2): expected values are no longer printed in the prompt, so passing requires live discovery.
- Retained a failing run to validate failure classification and demonstrate that the evaluator separates correct from incorrect answers on identical ground truth.
- Hardened the inventory evaluator: list fields are graded as sets (hallucinated surfaces fail) and Canvas page count must match exactly.
- Built and ran the assess.alias_safety A/B (`site-architecture:path-owner` vs Drush-only inspection) across two models, three stock Drupal starting sites plus a controlled non-admin hidden path claim, and three prompt framings; finding: the tool reduced observed hidden-claim safe judgments for lightly-prompted agents (stock Haven n=10: 80% haiku / 70% opus hidden-claim flags vs 100% with site self-description).

Remaining:

1. Repeat the non-Claude alias-safety run at n=10 and add another non-Claude stack before making a claim across model providers.
2. Repeat a fully blind non-admin hidden-path condition at n=10 before making that the headline rather than a breadth check.
3. Repeated runs for act.event_jsonapi and recover.event_jsonapi, not only inventory.read_only.
4. Token cost alongside elapsed time in the public scorecard.
5. Raise n on the remaining Drupal starting sites (core, Convivial) for the condition where the agent is not told the hidden risk; stock Haven is done at n=10.
6. A larger task set before any aggregate readiness claim.
