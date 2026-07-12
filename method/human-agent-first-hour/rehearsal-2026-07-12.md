# Zero-participant rehearsal — 2026-07-12

Status: current implementation rehearsal passed; excluded from the participant
census. This was not a human-outcome observation and its zero-second poll is not
a first-hour timing result. The earlier `human-rehearsal-01` remains immutable
historical debugging evidence; `human-rehearsal-02` is the acceptance run for
instrument v0.4.0.

## Live capture acceptance run: `human-rehearsal-02`

- Public technical evidence:
  `/Users/scott/dev/first-hour-experience/evidence/runs/human-rehearsal-02/minute-60/`
- Private facilitator evidence and readout:
  `/Users/scott/.codex/private-study/human-first-hour/human-rehearsal-02/`
- Condition: `full_recipe_v0`; install discovery deliberately pre-solved.
- Drupal CMS Composer identity: `drupal/cms` (`2.1.3` source archive), with
  Drupal `11.4.2` bootstrapped after restore.
- Registered duration: zero seconds for the excluded technical rehearsal.
  Capture began 27.278 seconds after start, so
  `standard_60_minute_duration=false` and
  `verified_governed_value_at_60=null` as required.
- Poll-launch offset: 0.000391 seconds.

The run exercised the current CLI end to end: mandatory agent-stack metadata,
explicit isolation confirmation, participant-safe cards, plain-language
`respond`, live DDEV/HTTP/Drush/Composer capture, snapshot-before-archive,
generic bundle capture, proof-linked T1-T6 evaluation, transfer
classification, validation, and readout generation. The 192,204,744-byte
workspace archive contains the newly created database snapshot.

The public manifest verifies 42 files. It contains the technical capture and
participant packet, but no `human/` directory, Taylor asset, hidden rubric,
evaluator forms, or transcript. The private frozen manifest verifies 12 files,
including the submitted belief inventory, Taylor, clock receipt, exact
instrument/protocol, and registered harness files.

Validation returned `ok: true` with zero issues. The excluded readout returned
`readout_status: complete`, T1 `pass`, T2-T5 `fail`, T6 `not_tested`, transfer
`blocked_by_build`, and `verified_governed_value_at_registered_stop: false`.
These are expected instrumentation-rehearsal outcomes, not evidence about a
human-agent dyad. After capture, `human-rehearsal-02-minute60` restored
successfully; Drush then reported bootstrap `Successful`, database `Connected`,
and Drupal `11.4.2`. The retained private receipt is
`evaluator-evidence/snapshot-restore.json`. Only the rehearsal DDEV project was
stopped afterward.

### Post-run validation hardening

The acceptance run froze instrument v0.4.0 and its exact then-current protocol
hash. The final independent audit then tightened the runner and current protocol
without mutating that frozen packet: proof receipts are criterion/evidence-kind
bound, root proof includes body size, missing interaction evidence yields a
measure-specific partial readout, earliest steering is enforced, existing-root
permissions are never rewritten, nested Composer identity is captured, and
manifests are closed sets. The same immutable run revalidates with zero issues
under the hardened validator. Fourteen focused tests cover these paths,
including accepted and late full-hour timing boundaries. The current protocol
SHA-256 is
`68dee3fe072ca5bfe2361c0e0845f4f64ea8a8a1b5bc75354c946a40f88c2260`;
each real shakeout registers its own exact current copies and hashes.

## Historical debugging run: `human-rehearsal-01`

## Run identity

- Run: `human-rehearsal-01`
- Participant ID: `rehearsal-00`
- Condition: `full_recipe_v0`
- External evidence:
  `/Users/scott/dev/first-hour-experience/evidence/runs/human-rehearsal-01/`
- DDEV project: `fh-human-rehearsal-01`
- Drupal CMS Composer identity/version: `drupal/cms` `2.1.3`
- Primary URL during capture: `http://fh-human-rehearsal-01.ddev.site:8800`

## What was exercised

1. `prepare` registered the external run, called the existing harness, blanked
   `access_marker`, rendered versioned participant cards and JSON forms, placed
   Alex/Jordan/Sam under `.ddev/study-assets`, and kept Taylor outside the
   participant workspace.
2. The exact `full_recipe_v0` path configured DDEV, ran
   `ddev composer create-project 'drupal/cms:^2'`, and ran noninteractive Drush
   installation. DDEV's scaffold succeeded with the study assets present.
3. `start --seconds 0` produced canonical start/end receipts and an empty poll
   result. Zero seconds was intentional for runner rehearsal; it is not M1/M4/MG
   evidence.
4. While `freeze` was running, the facilitator completed the local belief form.
   The submitted form is present in the frozen packet.
5. `freeze` captured root `200`, `/team` `404`, successful Drush bootstrap,
   DDEV description, role permissions, all bundle candidates, a database
   snapshot, and a 188,284,570-byte full-workspace archive. The external scorer
   exited `0`.
6. Automatic team-bundle detection returned `null`. Generic capture still
   returned the sole `page` candidate and did not call field APIs with an empty
   bundle. The evaluator therefore classified T2/T3 as failed, not as a capture
   crash.
7. Because the instrumentation rehearsal intentionally stopped after site
   installation, no team editor capability existed. Transfer was classified
   `blocked_by_build`, not `navigation_failure`.
8. The snapshot `human-rehearsal-01-minute60` was restored with
   `ddev snapshot restore human-rehearsal-01-minute60`; the restored site then
   reported Drush bootstrap `Successful` and database status `Connected`.
   After verification, only this rehearsal project was stopped; its files,
   snapshot, archive, and run evidence remain intact.

## Rehearsal findings and fixes

The live freeze exposed one packet bug: the initial implementation copied only
top-level files from `human/`, so the nested task/environment/guidance cards were
not in the immutable packet. The frozen rehearsal was not altered after the
fact; current validation correctly reports those three missing artifacts.

The rehearsal operator also noticed that the first generated full-recipe card
named Composer and Drush but omitted the DDEV configuration command. The live
operator supplied that command while exercising the intended recipe. The
versioned card now includes the exact project name, `drupal11` project type, and
`web` docroot; a test asserts the rendered command.

The runner now copies the participant packet recursively. A disposable
fake-harness end-to-end test verifies the corrected atomic packet and all
manifest hashes. The rehearsal review also identified and fixed two other
failure-path issues before participant 1:

- a session that never configures DDEV is still archived and finalized with
  explicit capture errors rather than being lost;
- `validate` now checks frozen hashes, required receipts, the disabled access
  probe, external score status, and snapshot/live-capture artifacts.

## Acceptance decision

The current operator workflow passed the live acceptance rehearsal and is ready
for instrument shakeouts with `full_recipe_v0`. Both rehearsals are retained:
run 01 as immutable debugging evidence and run 02 as the green v0.4.0 acceptance
run. The corrected code path is also covered by disposable fake-harness tests.
The first two real sessions remain shakeouts and must not be silently pooled if
the instrument changes again.
