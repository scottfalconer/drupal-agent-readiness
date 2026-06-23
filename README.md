# State of Agents in Drupal v0 evidence package

This repository contains the clean v0 evidence package for the first `State of
Agents in Drupal` finding.

It is intentionally scoped to a first finding, not a broad readiness verdict:

> Drupal can warn agents about hidden path conflicts.

## Recommended reading order

1. `REVIEW-READINESS.md`
   - Reviewer alignment sheet.
   - Safe claims, non-claims, and how the package maps to the Outside AI loop.
2. `docs/finding-site-self-description-v0.md`
   - One concrete agent mistake Drupal can prevent.
   - Plain-English summary plus the headline result table.
3. `docs/why-this-bench.md`
   - Why we are testing Drupal's agent experience.
   - Why site context, public tasks, rubrics, starting sites, and claim
     boundaries matter.
   - Why public curriculum tasks and fresh measurement variants are both useful.
4. `docs/state-of-agents-in-drupal-v0.md`
   - The broader v0 evidence-loop report and scorecard.
5. `docs/scorecard.csv`
   - Machine-readable scorecard rows.
6. `docs/readiness.json`
   - Current readiness flags and caveats.

## What is included

- `docs/`
  - Public-facing release docs and generated scorecard assets.
- `REVIEW-READINESS.md`
  - Reviewer-only alignment note with safe claims and non-claims.
- `method/`
  - Harness, prompts, task definitions, publishing checklist, and schema.
- `evidence/experiments/`
  - Alias-safety experiment packages, including n=10 Haven and Codex runs.
- `evidence/runs/`
  - Inventory, Event, and recovery run packages used by the scorecard.
- `repro/`
  - Evaluators, scripts, tests, and Python modules needed to reproduce or audit
    the package.
- `agent_readiness/`
  - Runnable source-package layout assembled from the sanitized release assets.
  - Use this for the commands in `method/PUBLISHING.md`.
- `prototype/site_architecture_module/`
  - The working Drupal module used by the finding.
  - This is included for review and reproduction, not as a Drupal.org-ready
    contrib package.

## Intended claim

Safe public claim:

> In a constrained Drupal path-safety task, exposing live site self-description
> changed agent behavior: Drush-only inspection missed hidden disabled-View path
> claims, while `site-architecture:path-owner` made those claims visible and
> prevented the unsafe alias decision.

Do not claim yet:

- Drupal is broadly agent-ready.
- This is a statistically powered benchmark.
- The public tasks are held out or uncontaminated.
- The prototype module is ready for Drupal.org contribution.

## Two-minute version

The public story should start with the concrete mistake:

> Can an agent safely decide whether a Drupal URL path is free to use?

In this v0 task, some paths looked unused but were claimed by disabled Views.
Drush-only agents missed a meaningful fraction of those hidden claims. Agents
given a live Drupal self-description command saw the claims and avoided the
unsafe alias decision.

That is the release. The rest of the package explains why the task exists, how
to reproduce it, what the scorecard records, and what the result does not prove.

## Contamination policy

This bench is intentionally public. That is a feature, not a flaw.

For this release, the goal is curriculum and readiness: make the failure mode
visible, make the safe inspection pattern learnable, and give contributors a
repeatable way to improve Drupal's agent-facing surfaces.

For headline progress claims, use new task variants, repeated runs, and clear
provenance so the community can distinguish "agents learned the public task" from
"Drupal became easier and safer for agents to operate."

## Final public-release decisions

Before publishing outside a review circle, decide:

- license for the package;
- AI-assisted authorship/disclosure wording;
- whether to publish the clean folder as-is, or publish only `docs/` plus a
  linked evidence archive;
- whether to commit this package on a public branch before announcement.

## Reader ladder

- Skimmers: read the plain-English summary and result table in the finding.
- Roadmap reviewers: read the finding, then the roadmap section and next
  hardening steps in the state doc.
- Skeptics: inspect the harness, evaluator, manifest, transcripts, SHA hashes,
  and retained failing run.
