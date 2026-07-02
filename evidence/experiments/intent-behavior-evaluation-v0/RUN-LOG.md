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
