# Claims Ledger

This ledger pins what the v0 package claims, what unit is counted, and where the
evidence lives. It is meant to prevent headline numbers from drifting into
broader claims than the artifacts support.

## Headline Finding

| Claim | Unit counted | Denominator | Run class | Prompt / substrate | Evidence | Does not prove |
| --- | --- | --- | --- | --- | --- | --- |
| Prototype site self-description changed agent behavior in one Drupal path-safety task. | Hidden disabled-View path judgment. | Stock Haven: 10 runs per arm, 2 hidden judgments per run, 20 hidden judgments per arm. | Fully blind A/B, Drush-only vs prototype `site-architecture:path-owner`. | `../prompts/assess.alias_safety.fully_blind.md`; stock Drupal CMS/Haven. | `../experiments/alias-safety-haven-n10-fullyblind-v0/model-ab-results.json`; `../experiments/alias-safety-haven-n10-fullyblind-v0/model-ab-FINDING.md`. | Broad Drupal agent readiness, statistical power, production module readiness, or model-provider generality. |
| Drush-only inspection flagged fewer hidden disabled-View path declarations unsafe in the headline task. | Hidden disabled-View path judgment flagged unsafe. | Haiku: 16/20 flagged and 4/20 missed; Opus: 14/20 flagged and 6/20 missed. | Same as above. | Same as above. | Same as above. | That every miss would become production damage, or that the agent always misunderstood the reason. |
| The prototype command made the hidden declarations visible in the headline task. | Hidden disabled-View path judgment flagged unsafe. | Haiku: 20/20 flagged; Opus: 20/20 flagged. | Same as above, equipped arm. | Same as above. | Same as above. | That the resolver is complete for every Drupal path-ownership operation. |
| The reasoned metric shows whether the agent identified the disabled-View layer, not only whether it avoided the alias. | Free-text reason heuristic for hidden disabled-View judgments. | Haiku Drush-only: 0/20 reasoned; Opus Drush-only: 14/20 reasoned; equipped arms: 20/20. | Supporting metric, not the primary actionable verdict. | Same as above. | Same as above. | Agent cognition. It is a heuristic over answer text. |
| Initial Codex evidence points in the same direction. | Hidden disabled-View path judgment. | Codex: n=3 runs per arm, 6 hidden judgments per arm. | Fully blind A/B on stock Haven. | `../prompts/assess.alias_safety.fully_blind.md`; stock Drupal CMS/Haven. | `../experiments/alias-safety-codex-fullyblind-v0/model-ab-results.json`. | Provider-general behavior or a stable non-Claude baseline. |

## Known Confounds And Caveats

- The two stock Haven hidden paths in the headline n=10 run are under `/admin`.
  A Drush-only agent can reject those paths because `/admin` is conventionally
  unsafe without identifying the disabled View. That is why the public result
  reports both verdict and reasoned metrics.
- The controlled non-admin hidden-path fixture exists as breadth evidence, but
  it should be repeated at n=10 before replacing the stock Haven headline.
- The public tasks are curriculum as well as evidence. Future progress claims
  need fresh variants or pinned repeat conditions.
- The evaluator contract is task-specific. If the evaluator or rubric is wrong,
  that is a task failure, not an agent failure.

## Evidence Loop Claims

| Claim | Unit counted | Denominator | Evidence | Does not prove |
| --- | --- | --- | --- | --- |
| The v0 harness can collect answers, transcripts, state, evaluator output, and scorecard rows. | Scored inventory/event/recovery run package. | 10 constrained scorecard runs. | `scorecard.csv`; `../runs/*`. | Realistic project completion or aggregate Drupal readiness. |
| The evaluator can discriminate at least one incorrect answer. | Retained failed run against identical ground truth. | 1 retained failed inventory run. | `../runs/inventory-deleaked-blind/*`. | Statistical validity across the full task set. |
| The package is reproducible enough for public review. | Checked-in artifacts plus local verification commands. | Current checked-in v0 package. | Unit tests, compile check, publication audit, readiness audit, and `CLEAN-MANIFEST.sha256`. | That every future run is independent, instrumented, or fresh. |
