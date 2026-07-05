# Intent Behavior Evaluation v0 Clean Rerun

This directory records the clean rerun status for `intent-behavior-evaluation-v0`.

The headline result is a null:

| Arm | Runs | M1 preserved all 4 | M2 considered target before write | M4 completion |
| --- | ---: | ---: | ---: | ---: |
| `conflict-intent` | 10 | 0/10 | 10/10 | 0/10 |
| `placebo-intent` | 10 | 0/10 | 10/10 | 0/10 |
| `no-intent` | 10 | 0/10 | 10/10 | 0/10 |

All 30 selected headline runs completed without infrastructure failures. The
runs used isolated `CODEX_HOME`, isolated `HOME`, `CODEX_DISABLE_MEMORY=1`, and
memory-contamination scanning.

This does not support a positive durable-intent claim. It also does not prove
durable intent cannot help generally; it is one task shape and does not complete
the broader registered schedule.

Artifacts:

- `summary.json`: compact public summary of the headline rerun.
- `RUN-LOG.md`: rerun setup, calibration, and validation notes.
- `runs/intent-batch-summary.json`: full local batch summary when retained in
  the workspace package.
