# Drupal Agent Readiness

A public test bench intended to measure how safely AI agents can operate Drupal
sites and publish what they get wrong. The current release is a narrow
historical observation plus an evidence-loop package, not broad operational
coverage.

## TL;DR — What The Evidence Supports

| Finding | Result | Evidence boundary |
| --- | --- | --- |
| [Basic build capability did not separate the selected first-hour cells](docs/finding-first-hour-v0.md) | All 16 valid selected cells in a four-platform by four-agent-stack matrix cleared five required mechanically checked rungs; 15 of 16 also cleared the optional stretch. Valid single-run extensions on Wagtail, Joomla, and Payload cleared the required bar; the Strapi extension was excluded because its contamination check failed. | Exploratory source index; not registered or claim-grade. The per-run artifacts are not yet in this repository. |
| [A running site did not fully describe its own path claims](docs/finding-site-self-description-v0.md) | Retained judgments differed between a Drush-only condition and a condition whose prompt named a verdict-bearing helper. | Historical frontier observation; unpinned and not claim-grade. |
| [Stored rationale alone did not preserve the target affordances](evidence/experiments/intent-behavior-evaluation-v0-clean/README.md) | The registered arms were equal on the preservation-only outcome. | Registered null; does not judge whether removal, adaptation, deferral, or escalation was appropriate. |

“Capability is becoming table stakes” is a directional interpretation of the
selected first-hour result, not a claim that the platforms are generally
equivalent.

The bench is designed to give an AI agent a real Drupal site and a real job:
figure out the site, decide what is safe to change, make a governed change when
the task calls for it, check the result, and recover from a mistake. Under the
measurement-v1 target contract, a claim-bearing test must ship the task, exact
prompt-as-run, retained answers and execution logs, scoring code, and captured
starting and final state. The current historical packages do not satisfy that
full contract: some retain normalized output without complete prompt, harness,
substrate, budget, model, or trajectory pins. Retained output alone supports
review and re-scoring, not exact historical replication.

It is built for Drupal core and module developers, agent and tool builders, and
anyone deciding whether Drupal is a safe choice for AI-driven work. The reason
it matters: when Drupal is hard for an agent to understand or operate safely,
you almost never get a bug report. The agent quietly works around the problem,
or never picks Drupal at all. The point is to watch Drupal the way an agent
experiences it from the outside and turn rough edges into things someone can
fix.

This is early. The registered scorecard contains one historical frontier
observation plus the harness to produce stronger evidence and one
preservation-only null from the next intent-behavior study. Neither registered
experiment is claim-grade. The adjacent first-hour result above is an
exploratory source index rather than a registered scorecard experiment. For the
first registered test, we asked agents whether a Drupal URL path was free to
use as a new node alias. An agent can incorrectly say "yes" because a disabled
View owns the path but currently returns nothing. Retained judgments differed
between the Drush-only condition and the condition whose prompt named a
verdict-bearing path helper; the bundled treatment did not isolate discovery,
tool availability, facts-only output, advice, or an actual write.

This repo is the public package for `State of Agents in Drupal` v0.

## Where Should I Start?

- Skimmers: start with the [TL;DR](#tldr--what-the-evidence-supports), then read
  the v0 finding below and
  [`docs/finding-site-self-description-v0.md`](docs/finding-site-self-description-v0.md).
- Drupal roadmap reviewers: read
  [`docs/why-this-bench.md`](docs/why-this-bench.md), then the next hardening
  steps in [`docs/state-of-agents-in-drupal-v0.md`](docs/state-of-agents-in-drupal-v0.md).
- Reproducers: start with [`method/HARNESS.md`](method/HARNESS.md) and
  [`method/PUBLISHING.md`](method/PUBLISHING.md).
- Measurement reviewers: inspect the v1 experiment/run schemas, the
  [`method/MEASUREMENT-V1.md`](method/MEASUREMENT-V1.md) execution and claim
  guide, the
  [`method/benchmark-coverage-v1.json`](method/benchmark-coverage-v1.json)
  coverage map, the
  [`method/task-families-v1.json`](method/task-families-v1.json) clean/messy
  task contracts, and the
  [`method/improvement-registry-v1.json`](method/improvement-registry-v1.json)
  evidence-to-change loop.
- Eval ecosystem reviewers: start with
  [Where This Fits In The Ecosystem](#where-this-fits-in-the-ecosystem), then
  use the generated
  [`docs/eval-landscape.md`](docs/eval-landscape.md) to discover external task,
  evaluator, workflow, and substrate candidates, and inspect the separately
  retained [`docs/external-eval-results.md`](docs/external-eval-results.md).
- Skeptics: inspect the prompts, evaluator code, retained answers/transcripts
  where present, ground truth, retained failures, package manifest, and
  `CLEAN-MANIFEST.sha256`.
- Claim reviewers: read [`docs/claims-ledger.md`](docs/claims-ledger.md) and
  [`REVIEW-READINESS.md`](REVIEW-READINESS.md).
- Contributors: propose a task, a starting site, a rubric, an evaluator, an
  adversarial case, or an inert external-eval reference.

The benchmark and audit tooling requires Python 3.12, matching CI. The older
Python bundled with some macOS releases is not a supported runtime.

Quick local checks:

```bash
python3 -B -m unittest discover -s agent_readiness/tests -v
python3 -S -B agent_readiness/scripts/audit_benchmark_registries_v1.py --format json
python3 -S -B -m agent_readiness.scripts.build_eval_landscape --check
python3 -S -B -m agent_readiness.scripts.build_external_eval_results --check
python3 -B agent_readiness/scripts/build_clean_manifest.py --repo-root . --check
python3 -B agent_readiness/scripts/audit_clean_checkout_integrity.py \
  --repo-root . --checksum-manifest CLEAN-MANIFEST.sha256 \
  --require-clean-worktree \
  --entrypoint agent_readiness/measurement_v1.py \
  --entrypoint agent_readiness/published_experiments.py \
  --entrypoint agent_readiness/benchmark_registries_v1.py
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
and had to decide whether each path was safe for a new node alias. Exact counts,
denominators, evidence classes, source paths, and source hashes are generated in
[`docs/experiments-v1.json`](docs/experiments-v1.json). They report
hidden-claim judgments, not a model leaderboard or a broad Drupal readiness
score.

The historical Claude cells are the headline observation; the Codex cells are
initial breadth evidence and should not be read as provider-general. The unit of
analysis is the run, not the individual hidden-path judgment: multiple judgments
from the same transcript are correlated.

The stock Haven hidden paths are under `/admin`, so the verdict and the reason
are separated. A verdict can be correct because an agent treats `/admin` paths
as conventionally unsafe; the reasoned column shows whether the agent actually
identified the disabled-View declaration.

Bounded historical observation, with the v0 provenance caveat:

> In one constrained Drupal path-safety task, retained judgments differed
> between the Drush-only condition and the condition whose prompt named the
> verdict-bearing `site-architecture:path-owner` helper. This historical
> observation does not isolate tool discovery, installation, prompt guidance,
> facts-only output, an end-to-end write, or Drupal-side progress.

That is reviewable and re-scoreable from retained artifacts, but it is still an
exploratory v0 finding rather than a pinned replication package: the original
Claude workflow harness, starting-site hash, resolved model snapshot, budget,
and prompt-as-run provenance are not all independently captured. The registry
therefore labels it `frontier_observation`, `exploratory_legacy_unpinned`, and
`claim_grade: false`.

## What This Is

This is a public, inspectable evidence package for `State of Agents in Drupal`.
It includes fixed prompts, retained answers, evaluator outputs, scorecard run
transcripts, live-state captures, a package manifest, and a bundled Drupal
fixture used to reproduce the self-description condition.

The goal is not to rank AI models. The goal is to make Drupal's agent-facing
gaps visible, inspectable, testable, and fixable.

## What This Is Not

- Not a broad verdict that Drupal is agent-ready.
- Not a statistically powered benchmark.
- Not a general cross-CMS ranking.
- Not a private held-out model exam.
- Not a production-ready Drupal.org contrib module.

## Where This Fits In The Ecosystem

Several Drupal community projects now build or evaluate agent capability. They
are mostly complementary layers rather than competing versions of one project.
This bench occupies the consequence-and-improvement layer: give a
general-purpose external agent a real Drupal site and a bounded job, retain
what actually happened to site state, explain the Drupal-facing cause of a
failure, and test whether a Drupal-side change improves the outcome with the
agent stack held fixed.

Source names, links, and descriptions below are checked against the registry.
The relationship column is maintainer-curated orientation, not a second
artifact index; the generated landscape remains the maintained inventory.

| Project | What it is | Relationship to this bench |
| --- | --- | --- |
| [AI Best Practices for Drupal](https://www.drupal.org/project/ai_best_practices) | Drupal-specific guidance and behavioral evaluation cases for external coding agents. | Task and treatment candidates (skill versus no-skill); one case is retained as a bounded local diagnostic in [`docs/external-eval-results.md`](docs/external-eval-results.md) |
| [AI Eval](https://www.drupal.org/project/ai_eval) | A Drupal evaluation framework with versioned dataset, rubric, judge, deterministic-grader, and result-contract implementations. | Grader and interchange infrastructure this bench can adopt; adopting a framework is not readiness evidence |
| [AI Agents Test and DrupalForge testing template](https://www.drupal.org/project/ai_agents_test) | Drupal-native agent tool-behavior test suites plus a hosted Drupal CMS template that runs them on a site. | Prior art and substrate candidates; Drupal-native agents are a separate agent class from the external coding agents measured here |
| [AI Ongoing Evaluations](https://www.drupal.org/project/ai_evaluations) | A Drupal-native framework for capturing human feedback, comparing AI outputs, and importing or exporting evaluation records. | Human-label dataset and comparison-workflow prior art; a separate evaluation design is required before those records become a validated grader or readiness evidence |
| [AI Bench](https://www.drupal.org/project/ai_bench) | A proposed public program for Drupal-specific model and agent benchmark tasks and community-submitted runs. | Monitored for concrete task and evaluator artifacts; model and hardware leaderboards stay out of scope here |
| [AI Maintenance Skills](https://www.drupal.org/project/ai_maintenance_skills) | Drupal.org issue-triage and maintenance workflows for coding agents within a constrained DDEV design. | Workflow and substrate prior art; a candidate for a separately defined local task that measures net maintainer burden after its inputs, evaluator, decision target, and stop condition are fixed |

Generic runners and result formats (for example Inspect AI and
every-eval-ever-style envelopes) are consumed where useful rather than
rebuilt, and where a shared community evaluation umbrella emerges this bench
participates as a consumer and producer, not as a second standard.

The maintained index of these and future references is the generated
[`docs/eval-landscape.md`](docs/eval-landscape.md), built from inert pointers
under [`method/eval-references/`](method/eval-references/README.md).
Maintainer-run external diagnostics are retained separately in
[`docs/external-eval-results.md`](docs/external-eval-results.md). Listing a
project is discovery, not endorsement; no external listing or result changes
lifecycle coverage or enters the scorecard.

## Current Status

| Area | Status |
| --- | --- |
| v0 finding | Historical frontier observation, re-scoreable for review but `claim_grade: false` |
| Claim scope | Evidence-package readiness plus named estimate, fixed-estimate, registered-effect, and action-registry improvement gates; no aggregate score |
| Current headline task | Alias safety / hidden path claims |
| Reproducibility | Retained evidence is re-scoreable; exact original-run replication has documented prompt, harness, substrate, and model-pin caveats |
| Site self-description fixture | Bundled only for reproduction, not as a public module artifact |

## What Is Measured Today

| Surface | Current evidence | Supported use |
| --- | --- | --- |
| Alias-safety judgments | Historical, exploratory, and incompletely pinned; judgments differ between two bundled conditions. | Diagnose a wrong-layer path lookup and design a fresh factorial rerun. |
| Intent preservation | Summary-only preservation null. | Inspect the retained summary, not infer general intent value or conflict handling. |
| Inventory/Event/recovery examples | Legacy, re-scoreable evaluator examples. | Exercise package mechanics; not longitudinal or independent performance evidence. |
| Frontier canary | Adversarially tested harness implementation; no canary run is shipped in the public package. The task is no-tool, schema-constrained interpretation of an inline trusted-host snapshot under pinned macOS no-child-process containment. | Validate runner, containment, evidence custody, and scoring mechanics; not direct Drupal discovery or operation, hosted-model attestation, or VM-grade isolation. |
| Measurement-v1 fixed regression | None reportable. | Target contract only. |
| Canonical improvement decision | None; the sole record is `pending_registration`. | Track proposed work without claiming adoption or improvement. |

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
- `evidence/experiments/`: source-hashed alias-safety and intent-behavior
  experiment packages, with exact published metrics normalized in
  `docs/experiments-v1.json`.
- `evidence/runs/`: Inventory, Event, and recovery run packages used by the
  scorecard.
- `repro/`: frozen historical v0 workflow/evaluator snapshot retained to audit
  the original evidence; it is not the current implementation.
- `agent_readiness/`: runnable Python/source-package layout used by the
  commands in `method/PUBLISHING.md`. It also contains the internal
  `site_architecture` Drupal fixture used to reproduce the equipped arm.

- **`agent_readiness/`**: the active runnable source package. Make source
  behavior changes here.
- **`repro/`**: a frozen historical snapshot used to inspect how the original
  v0 evidence was produced. It intentionally does not track current source
  changes; run current checks from `agent_readiness/`.
- **`agent_readiness/fixtures/site_architecture_module/`**: the internal Drupal
  fixture copied into disposable sites for reproduction. Treat it as test-bench
  evidence infrastructure, not a public module surface.

## How Claims Should Be Interpreted

Public tasks are curriculum. They teach agents and humans the Drupal patterns we
want to make easier: inspect live site state, act through governed surfaces,
verify mechanically, and record blast radius.

Preregistered, source-audited fresh variants can be measurement. A stronger
Drupal-side progress claim should pin the model, harness, prompt-as-run, allowed
tools, task version, starting-site hash, evaluator version, rubric version,
budget, and scoring rules. If those pins are missing, use exploratory or
anecdotal language even when the retained answers re-score cleanly.

The machine-enforced contract is
`agent_readiness/schema/benchmark-experiment-v1.schema.json` plus
`agent_readiness/schema/benchmark-run-v1.schema.json`, audited by
`agent_readiness/scripts/audit_measurement_v1.py` and explained in
`method/MEASUREMENT-V1.md`. Fixed-agent regression and
frontier observation are separate lanes. The eight-stage lifecycle coverage
registry includes explicit planning/clarification and cold-handoff target
contracts. Both remain `not_covered`; their structured decision,
verification-plan, handoff, and second-agent continuation metrics are target
design, not current evidence. The registry marks current evidence separately
from target designs, and the improvement registry
requires an owner, upstream issue, expected delta, immutable design snapshot,
complete frozen reruns, append-only transitions, and a decision. A statistical
`registered_effect_rule_met` result is not `improvement_ready` until that
canonical action record also verifies.

This release supports a narrow historical observation and a reusable evidence loop. It
does not prove aggregate Drupal agent readiness.

## Next Work

- Establish a source-audited measurement-v1 fixed-regression lane before
  reporting an effect, then complete the canonical action-registry decision
  before claiming that a Drupal change improved agent outcomes.
- Keep frontier-observation reruns separate when measuring current agent/tool
  capability or provider breadth.
- Repeat `act.event_jsonapi` and `recover.event_jsonapi`, not only
  `inventory.read_only`.
- Capture harness-derived token cost for claim-bearing runs; keep legacy blanks
  visibly distinct from instrumented values.
- Expand repeated fully blind coverage across Drupal starting sites.
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

## Licensing

Original Drupal Agent Readiness work is MIT-licensed. Retained third-party
evaluation artifacts keep their upstream terms; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and `REUSE.toml` for the
path-level assignments and bundled license texts.
