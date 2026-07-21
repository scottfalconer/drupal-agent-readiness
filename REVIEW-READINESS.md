# Review readiness

This note is for reviewers deciding whether the v0 package is ready to circulate.
It is not a new public claim.

## Bottom line

When the checked package and readiness audits pass, the supported review posture
is **historical frontier observation and method package**, not claim-grade
evidence:

> Retained judgments differed between a Drush-only condition and a condition
> whose prompt named a verdict-bearing Drupal path helper in one constrained
> task.

The registered alias-safety and intent-behavior experiments both have
`claim_grade: false`. Exact registered metrics and evidence classes are generated
in `docs/experiments-v1.json`.

It is not ready to be framed as a broad Drupal agent-readiness verdict, a
statistical benchmark, a general cross-CMS ranking, or a model-provider
leaderboard. The repository separately links an exploratory first-hour source
index; that summary is not a registered scorecard experiment and does not change
this package posture.

## Alignment with the Outside AI / Dries framing

The Outside AI frame asks whether external agents can choose Drupal, start
productively, connect safely, understand a running site, act through governed
interfaces, verify results, recover from mistakes, and show measurable progress.

This v0 package covers only the middle of that loop:

| Outside AI measurement area | v0 coverage | Review posture |
| --- | --- | --- |
| Selection rate | Not covered. | Do not claim agents choose Drupal more often. Add as a future harness scenario. |
| Cold-start cost | Not covered. | Do not claim install/onboarding is solved. Prepared-site work remains separate. |
| Orientation and footgun rate | Historical frontier observation for one path-safety judgment task. | Report the observed change in retained judgments; do not call it an effect or generalize to discovery, facts-only output, actual writes, or Drupal-side progress. |
| Connection and scope enforcement | Not covered by the finding. | Do not claim scoped identity, deny behavior, audit, or revoke coverage yet. |
| Governed action | Lightly covered by the Event task and evaluator. | Treat as evidence-loop coverage, not a production action model. |
| Mechanical verification | Covered by package-owned evaluators and retained live-state captures. | Claim that answers can be recomputed against retained Drupal state; do not imply an independent witness or truthful-capture guarantee. |
| Recovery | Lightly covered by the Event rollback task. | Claim a constrained recovery check, not broad reversibility. |
| Fixed-model vs frontier-model separation | Frontier observations are registered; no reportable measurement-v1 fixed-regression estimate exists yet. | Require a pinned fixed-regression estimate, a passing registered effect rule, and a compatible decided canonical action-registry record before claiming a Drupal change improved agent outcomes. Keep current-agent/provider breadth in the frontier lane. |

The hardened frontier canary is a harness-validation lane, not new Drupal-task
coverage. It asks two executions to interpret the same inline trusted-host JSON
snapshot without tools, under pinned macOS child-process denial and an explicit
trusted-host boundary. No canary run is shipped in the public package, and even
a passing run would not demonstrate direct Drupal discovery, operation,
treatment effect, hosted-model identity, VM-grade isolation, or improvement.

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
4. `method/benchmark-coverage-v1.json`, `method/task-families-v1.json`, and
   `method/improvement-registry-v1.json`
   - Separate current from target coverage, define clean/messy end-to-end task
     contracts, and connect failures to an accountable change and frozen rerun.
5. `agent_readiness/schema/benchmark-experiment-v1.schema.json` and
   `agent_readiness/schema/benchmark-run-v1.schema.json`
   - Define the pinned fixed-regression and frontier-observation evidence
     contracts consumed by `audit_measurement_v1.py`.
6. `method/MEASUREMENT-V1.md`
   - Defines the register-run-audit workflow, the evidence/estimate/improvement
     gates, adversarial cases, and the remaining trust boundary.
7. `method/HARNESS.md`
   - Shows how to rerun the alias-safety finding with another agent.
8. `evidence/experiments/alias-safety-SYNTHESIS.md`
   - Superseded historical qualitative synthesis. Use generated
     `docs/experiments-v1.json` for exact metrics and evidence classes.
9. `CLEAN-MANIFEST.sha256`
   - Tracked-file hash manifest for review-package integrity. It is generated
     from repository files only and excludes `.git`, caches, and the manifest
     itself.

## Safe claims

- In one constrained Drupal path-safety judgment task, Drush-only agents missed
  hidden disabled-configuration path claims in retained historical runs.
- In the condition whose prompt named `site-architecture:path-owner`, equipped
  answers cited disabled declarations; retained judgments differed from the
  Drush-only condition.
- The package contains and exercises a runnable, re-scoreable evidence loop: versioned
  tasks and prompt templates, retained artifacts, live-state capture, mechanical
  evaluators, scorecard rows, and retained failures. It does not reproduce the
  original historical effect from fully pinned inputs.
- Public tasks are intentional here: the bench is a curriculum and readiness
  workbench, not a hidden model exam.

## Claims to avoid

- Drupal is broadly agent-ready.
- The result is statistically powered.
- The result proves behavior across model providers.
- The bundled `site_architecture` reproduction fixture is production-ready or
  Drupal.org-ready.
- Drupal has solved scoped agent identity, action governance, audit, revoke, or
  full reversibility.
- Public task contamination invalidates the work. For this package,
  contamination is useful learning; only headline progress claims need fresh
  variants and repeated runs.

## Package note

`CLEAN-MANIFEST.sha256` is the manifest for this clean review folder's tracked
files.
`docs/package-manifest.json` is the generated source-package manifest retained
for reproducibility of the original `agent_readiness/` layout.
