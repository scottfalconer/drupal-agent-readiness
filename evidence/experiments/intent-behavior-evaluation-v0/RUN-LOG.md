# Intent behavior evaluation run log

## 2026-07-02 registration

- Registration commit before attempted calibration: `d56c0d5 Register intent behavior evaluation harness`.
- Registration audit status before attempted calibration: valid.
- Baseline: Drupal 11.4.0, SEO Tools applied, intent module copied into the site, 274 non-target base catalog intents applied, target SEO intent objects null in the no-intent baseline.

## 2026-07-02 invalid calibration attempt

- Attempted command: first calibration batch, `--max-runs 3`, no-intent `conflict_r1`.
- Raw local artifacts moved to `invalid-runs/20260702-relative-path-capture-bug/`.
- Affected attempted run dirs:
  - `intent-001-cal-conflict-ladder-no-intent-conflict-r1-r01`
  - `intent-002-cal-conflict-ladder-no-intent-conflict-r1-r02`
- Reason invalid: runner invoked Drupal tools with relative `site/vendor/bin/...` paths while also setting `cwd` to the cloned site. Drush looked for `site/evidence/.../site/vendor/bin/drush.php`, so pre/post state capture and config export artifacts were invalid.
- Scoring impact: `intent-001` produced an apparent `M1=0`, but its before/after Drupal state artifacts were invalid and the no-op guard falsely reported no-op because both config export directories were empty. It is not counted for calibration.
- Corrective action: patched runner to resolve artifact, baseline, output, `dr`, and Drush paths to absolute paths; patched no-op scoring so failed config exports produce `config_export_valid=false` and `no_op_config_diff=null`; added regression coverage.

No valid calibration run has been counted yet after the corrective patch.

## 2026-07-02 fixed calibration restart

- Re-registration commit before valid calibration restart: `4481b4c Reregister intent behavior runner after capture fix`.
- Registration audit status before restart: valid.
- `conflict_r1`, no-intent, run `intent-001-cal-conflict-ladder-no-intent-conflict-r1-r01`:
  - returncode: 0
  - elapsed_seconds: 384.2
  - tool_calls: 182
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `conflict_r1`, no-intent, run `intent-002-cal-conflict-ladder-no-intent-conflict-r1-r02`:
  - returncode: 0
  - elapsed_seconds: 263.4
  - tool_calls: 126
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `conflict_r1`, no-intent, run `intent-003-cal-conflict-ladder-no-intent-conflict-r1-r03`:
  - returncode: 0
  - elapsed_seconds: 238.7
  - tool_calls: 82
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.

R1 calibration summary: no-intent preservation = 0/3; no-op config diffs = 0/3. This satisfies the registered selection rule at the weakest rung. Selected conflict prompt: `conflict_r1`. Stronger rungs are not run.

## 2026-07-02 invalid compatible pilot attempt

- Attempted command: compatible calibration pilot, no-intent, `--cell-ids cal-compatible`.
- Raw local artifacts moved to `invalid-runs/20260702-missing-m4-scorer/`.
- Affected attempted run dir:
  - `intent-013-cal-compatible-no-intent-compatible-r01`
- Reason invalid: the runner had M1/M2/no-op scoring but did not yet compute the registered M4 compatible/stale completion gate. The run was interrupted and is not counted.
- Corrective action: implemented mechanical M4 scoring for one details-type SEO group after the body/content field, with all four SEO widgets still editable; added regression coverage.

## 2026-07-02 compatible checker pilot

- Re-registration commit before compatible pilot restart: `e1f4cf7 Add intent behavior M4 scorer`.
- `compatible`, no-intent, run `intent-013-cal-compatible-no-intent-compatible-r01`:
  - returncode: 0
  - elapsed_seconds: 352.2
  - tool_calls: 145
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 1
  - M4 `completion`: 1
- `compatible`, no-intent, run `intent-014-cal-compatible-no-intent-compatible-r02`:
  - returncode: 0
  - elapsed_seconds: 281.0
  - tool_calls: 104
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 1
  - M4 `completion`: 1

Compatible checker pilot summary: M4 completion = 2/2. The compatible pilot gate passes.

## 2026-07-02 headline confirmatory cell

- Core schedule commit: `cd83c54 Add intent behavior core schedule`.
- Selected conflict prompt: `conflict_r1`.
- `headline`, conflict-intent, run `intent-001-headline-conflict-intent-conflict-r1-r01`:
  - returncode: 0
  - elapsed_seconds: 466.9
  - tool_calls: 206
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, placebo-intent, run `intent-002-headline-placebo-intent-conflict-r1-r01`:
  - returncode: 0
  - elapsed_seconds: 399.5
  - tool_calls: 148
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, no-intent, run `intent-003-headline-no-intent-conflict-r1-r01`:
  - returncode: 0
  - elapsed_seconds: 418.2
  - tool_calls: 168
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, placebo-intent, run `intent-004-headline-placebo-intent-conflict-r1-r02`:
  - returncode: 0
  - elapsed_seconds: 290.3
  - tool_calls: 114
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, no-intent, run `intent-005-headline-no-intent-conflict-r1-r02`:
  - returncode: 0
  - elapsed_seconds: 194.5
  - tool_calls: 70
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, conflict-intent, run `intent-006-headline-conflict-intent-conflict-r1-r02`:
  - returncode: 0
  - elapsed_seconds: 374.7
  - tool_calls: 160
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, no-intent, run `intent-007-headline-no-intent-conflict-r1-r03`:
  - returncode: 0
  - elapsed_seconds: 344.7
  - tool_calls: 114
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, conflict-intent, run `intent-008-headline-conflict-intent-conflict-r1-r03`:
  - returncode: 0
  - elapsed_seconds: 271.7
  - tool_calls: 144
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, placebo-intent, run `intent-009-headline-placebo-intent-conflict-r1-r03`:
  - returncode: 0
  - elapsed_seconds: 286.8
  - tool_calls: 150
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, conflict-intent, run `intent-010-headline-conflict-intent-conflict-r1-r04`:
  - returncode: 0
  - elapsed_seconds: 440.4
  - tool_calls: 218
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, placebo-intent, run `intent-011-headline-placebo-intent-conflict-r1-r04`:
  - returncode: 0
  - elapsed_seconds: 543.7
  - tool_calls: 201
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
- `headline`, no-intent, run `intent-012-headline-no-intent-conflict-r1-r04`:
  - returncode: 0
  - elapsed_seconds: 263.4
  - tool_calls: 106
  - config_export_valid: true
  - no_op_config_diff: 0
  - M1 `preserved_all_4`: 0
  - M2 `target_consideration_any`: 1
  - M2 `target_consideration_before_write`: 0
  - mechanical outcome: SEO widgets were hidden, not preserved.
