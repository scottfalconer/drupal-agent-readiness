# Claims Ledger

This ledger pins what the v0 package claims, what unit is counted, and where the
evidence lives. It is meant to prevent headline numbers from drifting into
broader claims than the artifacts support.

## Headline Finding

| Claim | Unit counted | Denominator | Run class | Prompt / substrate | Evidence | Does not prove |
| --- | --- | --- | --- | --- | --- | --- |
| Site self-description changed agent behavior in one Drupal path-safety task. | Hidden disabled-View path judgment. | Stock Haven: 10 runs per arm, 2 hidden judgments per run, 20 hidden judgments per arm; run-level n is 10 per arm because both hidden judgments come from the same transcript. | Fully blind A/B, Drush-only vs bundled `site-architecture:path-owner` fixture. | Prompt-as-run retained in `../scripts/_n10_workflow.js`; reusable prompt template in `../prompts/assess.alias_safety.fully_blind.md`; stock Drupal CMS (Haven testbed profile). | `../experiments/alias-safety-haven-n10-fullyblind-v0/model-ab-results.json`; `../experiments/alias-safety-haven-n10-fullyblind-v0/model-ab-FINDING.md`. | Broad Drupal agent readiness, statistical power, production module readiness, model-provider generality, or exact third-party replication of the original Claude workflow conditions. |
| Drush-only inspection flagged fewer hidden disabled-View path declarations unsafe in the headline task. | Hidden disabled-View path judgment flagged unsafe. | Haiku: 16/20 flagged and 4/20 judged safe; Opus: 14/20 flagged and 6/20 judged safe. | Same as above. | Same as above. | Same as above. | That every safe judgment would become production damage, or that the agent always misunderstood the reason. |
| The bundled site-description command made the hidden declarations visible in the headline task. | Hidden disabled-View path judgment flagged unsafe. | Haiku: 20/20 flagged; Opus: 20/20 flagged. | Same as above, equipped arm. | Same as above. | Same as above. | That the resolver is complete for every Drupal path-ownership operation. |
| The reasoned metric shows whether the agent identified the disabled-View layer, not only whether it avoided the alias. | Free-text reason heuristic for hidden disabled-View judgments. | Haiku Drush-only: 0/20 reasoned; Opus Drush-only: 14/20 reasoned; equipped arms: 20/20. | Supporting metric, not the primary actionable verdict. | Same as above. | Same as above. | Agent cognition. It is a heuristic over answer text. |
| Initial Codex evidence points in the same direction. | Hidden disabled-View path judgment. | Codex: n=3 runs per arm, 6 hidden judgments per arm. | Fully blind A/B on stock Haven. | `../prompts/assess.alias_safety.fully_blind.md`; stock Drupal CMS (Haven testbed profile). | `../experiments/alias-safety-codex-fullyblind-v0/model-ab-results.json`. | Provider-general behavior or a stable non-Claude baseline. |

## Known Confounds And Caveats

- The two stock Haven hidden paths in the headline n=10 run are under `/admin`.
  A Drush-only agent can reject those paths because `/admin` is conventionally
  unsafe without identifying the disabled View. That is why the public result
  reports both verdict and reasoned metrics.
- The controlled non-admin hidden-path fixture exists as breadth evidence, but
  it should be repeated at n=10 before replacing the stock Haven headline.
- The equipped arm uses a bundled site-description fixture command that exposes
  the same path-ownership predicate the evaluator grades through an independent
  collector and emits normative advice about risky path claims. The 20/20
  equipped result shows that surfaced Drupal state and verdict guidance changed
  the agent's judgment in this task; it is not independent proof of model
  capability or resolver completeness.
- The headline alias-safety evidence is re-scoreable from retained artifacts,
  but the original Claude workflow is not a fully pinned replication package:
  the non-public harness, resolved model snapshots, budget, starting-site hash,
  and exact prompt-as-run provenance are not all independently captured outside
  the retained scratch workflow.
- The public tasks are curriculum as well as evidence. Future progress claims
  need fresh variants or pinned repeat conditions.
- The evaluator contract is task-specific. If the evaluator or rubric is wrong,
  that is a task failure, not an agent failure, and the claim computed from that
  rubric must be re-evaluated.

## Visible Nulls And In-Progress Experiments

| Result | Unit counted | Denominator | Run class | Prompt / substrate | Evidence | Does not prove |
| --- | --- | --- | --- | --- | --- | --- |
| Clean intent-behavior rerun did not preserve the target SEO editor affordances in any headline arm. | `M1` preserved-all-4 score per run. | 30 completed headline runs: 10 `conflict-intent`, 10 `placebo-intent`, 10 `no-intent`; all three arms scored 0/10 on `M1`. | Clean Codex rerun with isolated `CODEX_HOME`, isolated `HOME`, `CODEX_DISABLE_MEMORY=1`, and memory-contamination scan. | Clean rerun schedule `run-schedule-core-conflict_r1.json`; conflict prompt `conflict_r1`; Drupal CMS intent-behavior baseline. | `../experiments/intent-behavior-evaluation-v0-clean/summary.json`; `../experiments/intent-behavior-evaluation-v0-clean/RUN-LOG.md`. | That durable intent cannot help generally, that the registered broader 62-run schedule is complete, or that a positive intent-behavior claim is supported. |

## Evidence Loop Claims

| Claim | Unit counted | Denominator | Evidence | Does not prove |
| --- | --- | --- | --- | --- |
| The v0 harness can collect answers, transcripts, state, evaluator output, and scorecard rows. | Scored inventory/event/recovery run package. | 10 constrained scorecard runs. | `scorecard.csv`; `../runs/*`. | Realistic project completion or aggregate Drupal readiness. |
| The evaluator can discriminate at least one incorrect answer. | Retained failed run against identical ground truth. | 1 retained failed inventory run. | `../runs/inventory-deleaked-blind/*`. | Statistical validity across the full task set. |
| The package is re-scoreable enough for public review. | Checked-in artifacts plus local verification commands. | Current checked-in v0 package. | Unit tests, compile check, publication audit, readiness audit, and `CLEAN-MANIFEST.sha256`. | That every future run is independent, instrumented, fresh, or exactly rerunnable from the original agent harness. |
