# alias-safety experiments

Controlled A/B studies of the candidate thesis: does live site self-description
(`site-architecture:path-owner`) materially help an agent decide whether a URL
path is safe to claim with a new node alias, vs. raw Drupal inspection?

**Start with [`alias-safety-SYNTHESIS.md`](alias-safety-SYNTHESIS.md)** — the
cross-experiment conclusion and cited example answers.

## Method

- Task `assess.alias_safety`: classify candidate paths as safe/unsafe to alias.
  The discriminating cases are **disabled-view latent claims** — paths declared by
  a disabled view, unrouted now but a collision if the view is ever enabled.
- Two arms: `raw_drush` (module absent) vs `site_architecture` (`path-owner`
  available), each on its own disposable clone.
- Variables swept: **model** (`claude-haiku-4-5`, `claude-opus-4-8`), **prompt
  framing** (`told` the criterion → `soft-blind`, hints "after routine config
  changes" → `fully-blind`, only "is it already claimed?"), and **substrate**.
- Ground truth is collected by a core-only PHP collector
  (`evaluators/alias_safety_collector.php`) that does NOT use the site_architecture
  module, so it is a valid independent referee for both arms.
- Metrics: **verdict** (flagged the latent path unsafe — the actionable answer);
  **reasoned** (supporting, free-text heuristic — did the reason recognize the
  *disabled* nature, vs. an "admin path is reserved" heuristic).

## Experiment dirs

Each model-sweep dir holds `model-ab-results.json`, `model-ab-FINDING.md`,
`raw-workflow-output.json`, `ground-truth.json`, retained scorer
`candidates.json`, and `runs/<cell>/<arm>-n/{answer,evaluator,meta}.json`
(per-run, with exact model IDs). The retained experiment `candidates.json` files
are post-run metadata for auditability; the fully blind agent-facing candidate
file is path-only and lives under `prompts/`.

- `alias-safety-v0/`, `alias-safety-blind-v0/` — first studies, Opus-only
  (told+blind / knowledge-blind), scored by `scripts/score_alias_safety_ab.py`.
- `alias-safety-haven-told-softblind-v0/` — Haiku+Opus, Haven, told + soft-blind.
- `alias-safety-nonadmin-softblind-v0/`, `alias-safety-nonadmin-fullyblind-v0/` —
  Haven clone with a **controlled non-admin latent claim injected** (the disabled
  `files` view retargeted to `/research-library`). Labelled as injected, not stock.
- `alias-safety-core-fullyblind-v0/`, `alias-safety-haven-fullyblind-v0/`,
  `alias-safety-convivial-fullyblind-v0/` — **stock** substrates, fully-blind.

## Reproducing / provenance

The workflow scripts (`scripts/_model_ab_workflow.js`,
`scripts/_substrate_ab_workflow.js`) are **retained run-specific scratch**, not a
parameterized library: the substrate config (clone paths + candidate paths) was
hardcoded and hand-edited per run. The exact post-run scorer metadata for each
recorded experiment is captured in that experiment's `candidates.json` +
`ground-truth.json`; those files are not the fully blind prompt input. Results
are processed into the package by `scripts/process_model_ab.py` (tested by
`tests/test_process_model_ab.py`). Disposable site clones under
`tmp/agent-readiness/` are not retained.
