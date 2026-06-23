# Review readiness

This note is for reviewers deciding whether the v0 package is ready to circulate.
It is not a new public claim.

## Bottom line

The package is ready for review as a **first finding and method package**:

> Drupal can warn agents about hidden path conflicts.

It is not ready to be framed as a broad Drupal agent-readiness verdict, a
statistical benchmark, a cross-CMS comparison, or a model-provider leaderboard.

## Alignment with the Outside AI / Dries framing

The Outside AI frame asks whether external agents can choose Drupal, start
productively, connect safely, understand a running site, act through governed
interfaces, verify results, recover from mistakes, and show measurable progress.

This v0 package covers only the middle of that loop:

| Outside AI measurement area | v0 coverage | Review posture |
| --- | --- | --- |
| Selection rate | Not covered. | Do not claim agents choose Drupal more often. Add as a future harness scenario. |
| Cold-start cost | Not covered. | Do not claim install/onboarding is solved. Prepared-site work remains separate. |
| Orientation and footgun rate | Covered strongly for one path-safety failure mode. | This is the headline: live site self-description changes agent behavior. |
| Connection and scope enforcement | Not covered by the finding. | Do not claim scoped identity, deny behavior, audit, or revoke coverage yet. |
| Governed action | Lightly covered by the Event task and evaluator. | Treat as evidence-loop coverage, not a production action model. |
| Independent verification | Covered by mechanical evaluators and live-state collectors. | Claim the method: answers can be checked against Drupal state. |
| Recovery | Lightly covered by the Event rollback task. | Claim a constrained recovery check, not broad reversibility. |
| Fixed-model vs frontier-model separation | Partially covered through run metadata and explicit caveats. | Keep model/provider claims narrow until more repeated non-Claude runs exist. |

## What reviewers should read

1. `docs/finding-site-self-description-v0.md`
   - Start here. It is the public-facing story and the least inside-baseball entry
     point.
2. `docs/why-this-bench.md`
   - Explains why Drupal's agent experience needs measurement, why site context
     matters, how public curriculum tasks differ from measurement variants, and
     where public claims still need pinned runs.
3. `docs/state-of-agents-in-drupal-v0.md`
   - Gives the scorecard, method claims, caveats, and next hardening steps.
4. `method/HARNESS.md`
   - Shows how to rerun the alias-safety finding with another agent.
5. `evidence/experiments/alias-safety-SYNTHESIS.md`
   - Technical synthesis and retained evidence behind the finding.
6. `CLEAN-MANIFEST.sha256`
   - Clean-folder hash manifest for review-package integrity.

## Safe claims

- In one constrained Drupal path-safety task, Drush-only agents missed hidden
  disabled-configuration path claims.
- Exposing Drupal-reported site self-description through
  `site-architecture:path-owner` made those hidden claims visible in the headline
  run.
- The package demonstrates a repeatable evidence loop: fixed prompts, run
  artifacts, live-state capture, mechanical evaluators, scorecard rows, and
  retained failures.
- Public tasks are intentional here: the bench is a curriculum and readiness
  workbench, not a hidden model exam.

## Claims to avoid

- Drupal is broadly agent-ready.
- The result is statistically powered.
- The result proves behavior across model providers.
- The prototype `site_architecture` module is production-ready or
  Drupal.org-ready.
- Drupal has solved scoped agent identity, action governance, audit, revoke, or
  full reversibility.
- Public task contamination invalidates the work. For this package,
  contamination is useful learning; only headline progress claims need fresh
  variants and repeated runs.

## Package note

`CLEAN-MANIFEST.sha256` is the manifest for this clean review folder.
`docs/package-manifest.json` is the generated source-package manifest retained
for reproducibility of the original `agent_readiness/` layout.
