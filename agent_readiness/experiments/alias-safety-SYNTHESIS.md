# Historical alias-safety synthesis (superseded claim boundary)

This is a retained qualitative synthesis of the exploratory alias-safety work.
It is not a claim-grade experiment report and it does not supersede the
generated metrics or claims ledger.

Use these sources for the current review boundary:

- `../../docs/experiments-v1.json` for generated counts, denominators, evidence
  classes, and source hashes;
- `../../docs/claims-ledger.md` for the supported public wording;
- `../../REVIEW-READINESS.md` for publication limitations.

## Bounded historical observation

In one constrained Drupal path-safety judgment task, retained agent answers
changed when the equipped arm exposed a named, verdict-bearing
`site-architecture:path-owner` helper instead of Drush-only inspection.

The failure pattern is useful: a path can be unrouted now while disabled
configuration still declares it. Some retained Drush-only answers treated
"currently unrouted" as "safe"; equipped answers could cite the disabled
declaration. This identifies a Drupal agent-experience problem worth testing.

It does **not** establish that:

- the helper independently caused the change;
- discoverability, facts-only output, normative advice, or the verdict was the
  active ingredient;
- an agent attempted or completed a write;
- the observed judgments predict real write collisions;
- the result generalizes across models, sites, providers, or Drupal tasks; or
- the helper should be deployed based on this evidence.

## Why the stronger original interpretation was retired

The historical package is re-scoreable, but it does not retain every pin needed
for exact replication: the original workflow harness, starting-site identity,
resolved provider model snapshot, budget, and prompt-as-run provenance are not
all independently captured. The public registry therefore classifies the work
as `exploratory_legacy_unpinned`, with incomplete artifacts and pins.

The task also produced multiple path judgments from one transcript. Those
judgments are correlated; the run, not each path, is the defensible analysis
unit. Exact generated results remain available in `docs/experiments-v1.json`,
but this hand-authored narrative intentionally does not copy headline ratios or
turn judgment counts into significance, provider, deployment, or real-write
claims.

## What remains useful

- The retained answers provide concrete examples of a wrong-layer lookup:
  checking current routing state while operation-relevant configuration exists
  elsewhere.
- The task is a useful curriculum and diagnostic case for Drupal tool authors.
- The evidence motivates a fresh, source-audited measurement-v1 experiment; it
  is not itself that experiment.

## Required next experiment

A claim-bearing follow-up should use a disposable, resettable Drupal fixture
and a preregistered fixed-regression roster. It should separate:

1. ordinary discovery;
2. discoverable structured facts without a verdict;
3. policy or safety advice;
4. the combined verdict-bearing helper; and
5. a governed attempted write with a post-write collision probe.

The run census, agent and measurement stack, prompt delivery, starting and
final state, evaluator execution, costs, exclusions, and guardrails must all be
retained under measurement v1. Only a complete fixed-regression result may test
a registered effect rule, and only a compatible decided action-registry record
may support an improvement claim.
