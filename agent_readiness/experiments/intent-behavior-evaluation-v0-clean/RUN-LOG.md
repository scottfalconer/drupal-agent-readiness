# Intent behavior evaluation clean rerun log

Experiment: `intent-behavior-evaluation-v0`

Clean rerun artifact root: `evidence/experiments/intent-behavior-evaluation-v0-clean/`

## 2026-07-02 rerun changes

This rerun is a new clean attempt, not a continuation of the excluded headline
attempt under `evidence/experiments/intent-behavior-evaluation-v0/runs/`.

Changes before scored clean execution:

- Broadened root/module `AGENTS.md` guidance from "working on Drupal
  configuration" to site-building changes that may affect Drupal configuration,
  fields, content types, forms, displays, menus, blocks, views, permissions,
  workflows, SEO, analytics, or other site behavior.
- Seeded the treatment target objects with the CSV `seo_editor_fields` value.
- Applied that value to the five target objects the task mutates/watches:
  `core.entity_form_display.node.page.default` plus the four
  `field.field.node.page.field_seo_*` instances.
- Isolated each Codex run with a fresh per-run `CODEX_HOME`, isolated `HOME`,
  and `CODEX_DISABLE_MEMORY=1`.
- Added memory-contamination scanning over raw Codex events, stderr, and
  rendered transcripts.
- Replaced the old string-position M2 metric with event-ordered command-log
  scoring.
- Tightened M2 write detection so read-only discovery commands such as
  `drush list | rg 'config:set'` are not counted as mutating writes.

## 2026-07-02 pre-headline validation

Commands recorded in the source rerun log:

```bash
python3 -m unittest agent_readiness.tests.test_intent_behavior -v
python3 agent_readiness/scripts/prepare_intent_behavior_registration.py --design method/intent-behavior-variants-v0.json --out-dir method/intent-behavior --module-dir /Users/scott/dev/drupal-contrib/intent --update-design-manifest --out method/intent-behavior/prepare-summary.json
python3 agent_readiness/scripts/audit_intent_behavior_registration.py --design method/intent-behavior-variants-v0.json --artifact-root method/intent-behavior --module-dir /Users/scott/dev/drupal-contrib/intent
python3 agent_readiness/scripts/audit_intent_behavior_memory_contamination.py --runs-root evidence/experiments/intent-behavior-evaluation-v0-clean/runs --glob 'intent-0??-cal-*'
```

Recorded results:

- Focused unit suite: 16 tests passed.
- Registration audit: `valid`, no errors, no warnings.
- Clean calibration/pilot memory audit: 5 runs, 0 contaminated.

## 2026-07-05 registration drift disclosure

The 2026-07-02 pre-headline registration audit above was valid against the
then-current registration artifacts. As of 2026-07-05, running
`python3 agent_readiness/scripts/audit_intent_behavior_registration.py --design method/intent-behavior-variants-v0.json`
against this tree reports `status: invalid` with `module_dir.hash_mismatch` and
`code_hash.hash_mismatch` for `agent_readiness/intent_behavior_runner.py`.

The visible runner drift includes per-run Codex/HOME isolation,
memory-contamination scanning and failure handling, prompt filtering,
event-ordered M2 scoring, and tighter read-only command handling. The visible
artifact drift includes broadened intent-agent guidance and refreshed baseline
artifacts. Treat the clean rerun as a new clean registration attempt under the
design's own rule, not as a continuation of the previously registered
confirmatory schedule.

## Clean headline result

The clean headline cell completed 30/30 runs with no infrastructure failures.
All three headline arms scored `M1=0/10`; each arm considered the target before
writing in `10/10` runs. See `summary.json`.
