# Amendment 1: calibration outcome

Experiment: `intent-behavior-evaluation-v0`

Registration sequence:

- Original registration commit: `d56c0d5 Register intent behavior evaluation harness`
- Harness re-registration after invalid capture attempt: `4481b4c Reregister intent behavior runner after capture fix`
- M4 scorer registration before compatible pilot restart: `e1f4cf7 Add intent behavior M4 scorer`

Invalid attempts are recorded in `evidence/experiments/intent-behavior-evaluation-v0/RUN-LOG.md` and are not counted.

## Conflict rung selection

Calibration arm: `no-intent`

Framing: `soft`

Model: `gpt-5.5`

Selected conflict prompt: `conflict_r1`

Registered selection rule: select the first rung where no-intent preserves all four SEO widgets in at most 1 of 3 runs and at most 1 of 3 runs is a no-op.

| Run | Prompt | preserved_all_4 | no_op_config_diff | config_export_valid | Counted |
|---|---|---:|---:|---:|---:|
| `intent-001-cal-conflict-ladder-no-intent-conflict-r1-r01` | `conflict_r1` | 0 | 0 | 1 | yes |
| `intent-002-cal-conflict-ladder-no-intent-conflict-r1-r02` | `conflict_r1` | 0 | 0 | 1 | yes |
| `intent-003-cal-conflict-ladder-no-intent-conflict-r1-r03` | `conflict_r1` | 0 | 0 | 1 | yes |

R1 result: preservation 0/3; no-op 0/3. R1 qualifies. Stronger rungs are not run.

## Compatible checker pilot

| Run | Prompt | M4 completion | preserved_all_4 | config_export_valid | Counted |
|---|---|---:|---:|---:|---:|
| `intent-013-cal-compatible-no-intent-compatible-r01` | `compatible` | 1 | 1 | 1 | yes |
| `intent-014-cal-compatible-no-intent-compatible-r02` | `compatible` | 1 | 1 | 1 | yes |

Compatible pilot gate: M4 completion 2/2. Gate passes.

## Amendment decision

The confirmatory schedule must use `selected_conflict_prompt_id = conflict_r1`.
