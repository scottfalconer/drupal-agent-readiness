# Drupal Agent Readiness

A public test bench that measures how safely AI agents can operate Drupal sites
and publishes what they get wrong.

This project gives an AI agent a real Drupal site and a real job: figure out
the site, decide what is safe to change, make a governed change when the task
calls for it, check the result, and recover from a mistake. Each test ships with
the task, exact prompts, retained answers and transcripts/logs where available,
scoring code, and captured site state so someone else can rerun or challenge the
result.

It is built for Drupal core and module developers, agent and tool builders, and
anyone deciding whether Drupal is a safe choice for AI-driven work. The reason
it matters: when Drupal is hard for an agent to understand or operate safely,
you almost never get a bug report. The agent quietly works around the problem,
or never picks Drupal at all. The point is to watch Drupal the way an agent
experiences it from the outside and turn rough edges into things someone can
fix.

This is early: one finding so far, plus the harness to produce more. For the
first test, we asked agents whether a Drupal URL path was free to use as a new
node alias. An agent can incorrectly say "yes" because a disabled View owns the
path but currently returns nothing. Giving the agent access to Drupal's own
record of path ownership changed that behavior.

This repo is the public package for `State of Agents in Drupal` v0.

## Where Should I Start?

- Skimmers: read the v0 finding below, then
  [`docs/finding-site-self-description-v0.md`](docs/finding-site-self-description-v0.md).
- Drupal roadmap reviewers: read
  [`docs/why-this-bench.md`](docs/why-this-bench.md), then the next hardening
  steps in [`docs/state-of-agents-in-drupal-v0.md`](docs/state-of-agents-in-drupal-v0.md).
- Reproducers: start with [`method/HARNESS.md`](method/HARNESS.md) and
  [`method/PUBLISHING.md`](method/PUBLISHING.md).
- Skeptics: inspect the prompts, evaluator code, retained answers/transcripts
  where present, ground truth, retained failures, package manifest, and
  `CLEAN-MANIFEST.sha256`.
- Claim reviewers: read [`docs/claims-ledger.md`](docs/claims-ledger.md) and
  [`REVIEW-READINESS.md`](REVIEW-READINESS.md).
- Contributors: propose a task, a starting site, a rubric, an evaluator, or an
  adversarial case.

Quick local checks:

```bash
python3 -B -m unittest discover -s agent_readiness/tests -v
shasum -a 256 -c CLEAN-MANIFEST.sha256
```

Full maintainer checklist:

```text
method/PUBLISHING.md
```

## The v0 Finding

Can an agent safely decide whether a Drupal URL path is free to use as a new
node alias?

In Drupal, a path can look unused while still being claimed by site state. For
example, a disabled View can declare a path that currently returns nothing, then
reclaim that path when someone re-enables the View. An agent that only asks
"does anything respond at this URL right now?" can make the wrong decision.

This package tests that failure mode. In a constrained path-safety task on stock
Drupal CMS (the Haven testbed profile), agents inspected path-only candidates
and had to decide whether each path was safe for a new node alias. The table
reports hidden-claim judgments, not a model leaderboard or a broad Drupal
readiness score.

| Agent setup | Runs (hidden judgments) | Correctly flagged unsafe | Reason named disabled View |
| --- | ---: | ---: | ---: |
| Claude Haiku, Drush-only inspection | 10 runs (20 judgments) | 16/20 | 0/20 |
| Claude Haiku, with the `site-architecture:path-owner` tool | 10 runs (20 judgments) | 20/20 | 20/20 |
| Claude Opus, Drush-only inspection | 10 runs (20 judgments) | 14/20 | 14/20 |
| Claude Opus, with the `site-architecture:path-owner` tool | 10 runs (20 judgments) | 20/20 | 20/20 |
| OpenAI Codex[^codex], Drush-only inspection | 3 runs (6 judgments) | 0/6 | 0/6 |
| OpenAI Codex[^codex], with the `site-architecture:path-owner` tool | 3 runs (6 judgments) | 6/6 | 6/6 |

[^codex]: In this repo, "OpenAI Codex" names the Codex agent/model id used in
    the retained run artifacts (`gpt-5.5-codex`), not the legacy OpenAI Codex API
    models that were retired in 2023.

The Claude rows are the headline n=10 run; the Codex rows are initial breadth
evidence at n=3 and should not be read as provider-general.

The stock Haven hidden paths are under `/admin`, so the verdict and the reason
are separated. A verdict can be correct because an agent treats `/admin` paths
as conventionally unsafe; the reasoned column shows whether the agent actually
identified the disabled-View declaration.

Safe public claim:

> In one constrained Drupal path-safety task, exposing live site
> self-description changed agent behavior: Drush-only inspection judged some
> hidden disabled-View path claims safe, while `site-architecture:path-owner`
> made those claims visible, reducing false "safe" judgments to zero in the
> headline run.

## What This Is

This is a public, inspectable evidence package for `State of Agents in Drupal`.
It includes fixed prompts, retained answers, evaluator outputs, scorecard run
transcripts, live-state captures, a package manifest, and a prototype Drupal
module.

The goal is not to rank AI models. The goal is to make Drupal's agent-facing
gaps visible, reproducible, and fixable.

## What This Is Not

- Not a broad verdict that Drupal is agent-ready.
- Not a statistically powered benchmark.
- Not a cross-CMS comparison.
- Not a private held-out model exam.
- Not a production-ready Drupal.org contrib module.

## Current Status

| Area | Status |
| --- | --- |
| v0 finding | Ready for review/public preview |
| Claim scope | `constrained_v0_mechanical_evidence_loop` |
| Current headline task | Alias safety / hidden path claims |
| Reproducibility | Harness, prompts, evaluators, retained answers/evaluator outputs, raw workflow outputs, and manifest included |
| Prototype module | Included for reproduction, not production/contrib readiness |

## Current Tasks

| Task | What it tests | Current role |
| --- | --- | --- |
| `inventory.read_only` | Can the agent discover live site state without mutation? | Constrained read-only task |
| `act.event_jsonapi` | Can the agent create a minimal Event bundle, fields, sample content, and verify JSON:API without unrelated changes? | Minimal write/evaluator task; not the fuller editorial Events-section task |
| `recover.event_jsonapi` | Can the agent remove or restore Event work without leaving content, routes, JSON:API resources, aliases, or unrelated blast radius? | Constrained recovery task |
| `assess.alias_safety` | Can the agent classify paths as safe or unsafe from a path-only candidate list? | Headline v0 finding |
| `act.events_section_editorial` | Future fuller Events-section task with editorial workflow, listing ownership, content-editor access, public output, JSON:API, and operation-specific path safety. | Future task |

## What Is Included

- `docs/`: public-facing release docs and generated scorecard assets.
- `method/`: harness, prompts, task definitions, publishing checklist, and
  schema.
- `evidence/experiments/`: alias-safety experiment packages, including n=10
  Haven and Codex runs.
- `evidence/runs/`: Inventory, Event, and recovery run packages used by the
  scorecard.
- `repro/`: evaluator, script, and test copy retained for package review.
- `agent_readiness/`: runnable Python/source-package layout used by the
  commands in `method/PUBLISHING.md`.
- `prototype/site_architecture_module/`: the Drupal prototype module used by
  the finding.

- **`agent_readiness/`**: the active runnable source package. Make source
  behavior changes here.
- **`repro/`**: a retained review copy of the same evaluator/script code so the
  public evidence package can be audited without relying on generated docs
  alone. Do not edit it for source behavior; update it only when intentionally
  mirroring release-package material.

## How Claims Should Be Interpreted

Public tasks are curriculum. They teach agents and humans the Drupal patterns we
want to make easier: inspect live site state, act through governed surfaces,
verify mechanically, and record blast radius.

Fresh variants are measurement. A stronger Drupal-side progress claim should pin
the model, harness, prompt, allowed tools, task version, starting-site hash,
evaluator version, rubric version, budget, and scoring rules.

This release supports a narrow first finding and a reusable evidence loop. It
does not prove aggregate Drupal agent readiness.

## Next Work

- Repeat the non-Claude alias-safety run at n=10 and add another non-Claude
  stack before making any provider-general claim.
- Repeat `act.event_jsonapi` and `recover.event_jsonapi`, not only
  `inventory.read_only`.
- Add token cost to the scorecard where available.
- Raise n on remaining fully blind Drupal starting sites.
- Add messy, adversarial, and owner-described starting sites.
- Add richer editorial-experience tasks.
- Grow the task set before any aggregate Drupal readiness claim.

## Contributing Or Challenging

Good challenges are welcome. The most useful ones are concrete:

- a task Drupal should be able to win;
- a task Drupal should be expected to struggle with;
- a messy or adversarial starting site;
- a better rubric for a site-specific best-practice question;
- an evaluator bug;
- a rerun with another agent stack;
- evidence that a claim is too broad for the artifacts.

The evaluator is not universal Drupal truth. It is the contract for a specific
task on a specific starting site. If the rubric is wrong, that is a task failure,
not an agent failure.
