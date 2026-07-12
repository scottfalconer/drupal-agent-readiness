# Human-agent first-hour study kit

This directory contains the versioned instrument and blank forms for the
real-participant Drupal CMS pilot defined in
[`../human-agent-first-hour-experience-v0.md`](../human-agent-first-hour-experience-v0.md).
Start with `participant-screener-v0.md`; a chat-only agent is not eligible for
this shell-and-workspace task.

The canonical controlled vocabularies live in `instrument-v0.json`. During a
session, use `observer-log-v0.csv` only for neutral timestamps and descriptions.
Apply decision-leakage, dead-end, scope, and candidate-fix codes afterward from
the recording or transcript.

Before participant 1, complete a facilitator-as-participant rehearsal through
prepare, start, freeze, T1–T6 evaluation, and transfer classification. Mark it
excluded from the participant census. A shortened rehearsal stop is a
registered-stop check, not a minute-60 outcome.

The implementation rehearsal and fixes are recorded in
[`rehearsal-2026-07-12.md`](rehearsal-2026-07-12.md).

## Required isolation

The CLI has two storage planes:

- `HARNESS_ROOT` contains the participant workspace and the participant-safe
  `minute-60/` technical capture.
- `FACILITATOR_ROOT/<run-id>/` contains identity, hidden forms, Taylor's held-out
  asset, evaluator evidence, coding, and readouts.

`FACILITATOR_ROOT` must be outside the harness and must be unreadable by the
participant's agent. Merely choosing a sibling path is not sufficient when the
agent can read the whole filesystem. Run an unrestricted participant agent
under a separate OS account or on a separate device, or use an agent whose
enforced workspace boundary excludes the private root. Do not place hidden
forms or Taylor anywhere under the harness or participant workspace.
The runner creates a missing private root as mode `0700`. If the root already
exists, it must already be a `0700` directory; the runner refuses it and never
changes an existing directory's permissions.

## Operator quick start

Prepare an asset directory containing exactly `alex.jpg`, `jordan.jpg`,
`sam.jpg`, and `taylor.jpg`. Use a unique run ID whose final segment is
hexadecimal; `human-dcms-01` is valid, while `human-dcms-p01` is not.

Create an agent-stack JSON object with every required field:

```json
{
  "product": "Codex desktop",
  "version": "record the exact version",
  "model_or_selector": "record the displayed model or selector",
  "mode": "record the agent mode",
  "approval_policy": "record the approval policy",
  "enabled_tools": ["shell", "workspace filesystem"],
  "workspace_boundary": "assigned workspace only",
  "workspace_shell": true
}
```

`enabled_tools` must be a nonempty string list and `workspace_shell` must be
`true`. Record the actual stack; the example values are not defaults.

From the repository root, set the paths once. The required global
`--facilitator-root` option, and optional `--harness-root`, must appear before
the subcommand in every invocation:

```bash
RUN_ID=human-dcms-01
PARTICIPANT_ID=P01
ASSET_DIR=/absolute/path/to/four-study-images
AGENT_STACK_JSON=/absolute/private/path/agent-stack-p01.json
FACILITATOR_ROOT=/absolute/private/path/human-first-hour
HARNESS_ROOT=/Users/scott/dev/first-hour-experience
RUNNER=agent_readiness/scripts/human_first_hour.py
```

### 1. Prepare

```bash
python3 -B "$RUNNER" \
  --facilitator-root "$FACILITATOR_ROOT" \
  --harness-root "$HARNESS_ROOT" \
  prepare \
  --run-id "$RUN_ID" \
  --participant-id "$PARTICIPANT_ID" \
  --install-guidance full_recipe_v0 \
  --asset-dir "$ASSET_DIR" \
  --agent-stack-json "$AGENT_STACK_JSON" \
  --facilitator-isolation-confirmed
```

Use `--rehearsal` only for the excluded rehearsal. The isolation-confirmation
flag attests that the participant agent cannot read the private root; it is not
a mechanism that creates that boundary.

Give the participant only the reported workspace and the three files in the
reported `participant_packet` (`work/.ddev/study-packet/`). The build images are
in `work/.ddev/study-assets/`. Taylor and all hidden forms remain in the
reported private facilitator session. `prepare` also removes the autonomous
prompt from the run, disables the old access marker, and registers exact copies
and hashes of the study runner, CLI, external harness config/runner/adapter,
instrument, and protocol. Do not change any of them before freeze; validation
rejects prepare-to-freeze runtime identity drift.

### 2. Start and observe

At the moment the cards and workspace are handed over, run this in a dedicated
facilitator terminal. It blocks for the registered 3,600 seconds:

```bash
python3 -B "$RUNNER" \
  --facilitator-root "$FACILITATOR_ROOT" \
  --harness-root "$HARNESS_ROOT" \
  start --run-id "$RUN_ID"
```

Do not pass `--seconds` for a retained participant session. A standard
minute-60 observation requires a registered duration of 3,600 seconds, capture
to begin between 3,599 and 3,610 seconds after the canonical start, and the
poller to launch no more than 2 seconds after that start. Stop participant and
agent mutations at exactly 3,600 seconds; the capture tolerance is not extra
build time.

In another facilitator terminal, check the observable M4 steering trigger
during the hour:

```bash
python3 -B "$RUNNER" \
  --facilitator-root "$FACILITATOR_ROOT" \
  --harness-root "$HARNESS_ROOT" \
  steering-status --run-id "$RUN_ID"
```

This command reports live milestone state without exposing the rubric. It does
not decide whether a participant-statement trigger occurred and does not edit
`steering.json`; the live observer must record that trigger and the probe result
in the private form.

For a compressed technical rehearsal only, `start --seconds N` may register a
shorter stop. Mark the run with `prepare --rehearsal`. Its readout may describe
verified governed value at that registered stop, but
`verified_governed_value_at_60` remains null and must not be reported as a
first-hour result.

### 3. Stop, respond, and freeze

At exactly 3,600 seconds, stop all participant, agent, and site changes. In a
participant-facing terminal controlled by the facilitator, close or hide the
agent and run the plain-language questionnaire:

```bash
python3 -B "$RUNNER" \
  --facilitator-root "$FACILITATOR_ROOT" \
  --harness-root "$HARNESS_ROOT" \
  respond --run-id "$RUN_ID"
```

The participant answers the terminal prompts without seeing or editing JSON.
The command records the submission timestamp and refuses to overwrite a prior
submission. Do not let the participant ask the agent or inspect evaluator truth
while responding.

In parallel, immediately run freeze from another facilitator terminal:

```bash
python3 -B "$RUNNER" \
  --facilitator-root "$FACILITATOR_ROOT" \
  --harness-root "$HARNESS_ROOT" \
  freeze --run-id "$RUN_ID" \
  --transcript /absolute/private/path/to/redacted-agent-transcript.txt
```

Omit `--transcript` when none is available and record that limitation. `freeze`
attempts DDEV, HTTP, Drush, Composer-identity, snapshot, candidate-bundle, and
role-permission capture; archives the workspace; copies the participant packet;
and atomically publishes the participant-safe technical evidence to
`HARNESS_ROOT/evidence/runs/<run-id>/minute-60/`. A build that never configured
DDEV is still frozen with explicit error evidence rather than dropped. If DDEV
is configured but stopped, the runner does not invoke commands that could start
or repair it after the clock.

Participant belief state, session metadata, the observer log, clock and poll
receipts, registered protocol/harness identities, and Taylor are frozen under
`FACILITATOR_ROOT/<run-id>/frozen-minute-60/`, not the public `minute-60/`
directory. Post-session evaluator, coding, transfer, comprehension, and steering
forms also stay under `FACILITATOR_ROOT/<run-id>/`.

### 4. Materialize and evaluate the frozen team state

Inspect `minute-60/bundle-candidates.json`. If one bundle is defensibly the
team-member model, materialize its exact frozen fields and records:

```bash
python3 -B "$RUNNER" \
  --facilitator-root "$FACILITATOR_ROOT" \
  --harness-root "$HARNESS_ROOT" \
  select-bundle \
  --run-id "$RUN_ID" \
  --bundle-id team_member \
  --source manual \
  --rationale "This frozen bundle contains the registered name, role, and image fields."
```

The command writes
`FACILITATOR_ROOT/<run-id>/evaluator-evidence/team-state.json` and records the
selection in `evaluator.json`. It never invents a candidate. If none is
defensible, do not call it; mark T2/T3 `fail` or `not_tested` with evidence and
notes.

Complete the private forms. Every T1–T6 result needs at least one resolvable
`evidence_refs` entry. References may point only to `minute-60/...` or
`evaluator-evidence/...`. A passing criterion must also map every registered
`required_pass_evidence` kind in `evidence_by_kind` to criterion-specific proof.
An evaluator-created JSON proof receipt must contain at least:

```json
{
  "criterion_id": "T5",
  "evidence_kind": "editor_create",
  "result": "pass",
  "observed_at": "2026-07-12T12:00:00+00:00",
  "method": "Exact command, URL, account, and observed result"
}
```

Each evaluator pass receipt is bound to one criterion and one evidence kind;
do not reuse a generic receipt. The native `root_http`, `composer_identity`,
`drush_bootstrap`, and `anonymous_team_http` kinds must use their exact frozen
capture files. The root check requires both a 200 header and a substantial
captured body. For T1, use the exact
captured `root.headers`, `composer-identity.json`, and `drush-status.json`
receipts. `team-state.json` is the frozen selected source; create explicit pass
receipts for the T2/T3 assertions derived from it. A `fail` or `not_tested`
criterion needs explanatory notes and a private evaluator receipt whose
`criterion_id` and `result` match the row and includes `observed_at` and
`method`. Record nonempty `evaluator_id` and `completed_at` values. Record a
nonempty interaction `coder_id`; any false-confident belief also needs its
posthoc coder ID.

If recording/transcript evidence is unavailable, do not enter zero events.
Set `coded-events.json` to `coding_status: "unavailable"`, provide an
`unavailable_reason`, retain a coder ID and `coded_at` timestamp, and leave
`participant_turns` null with an empty event list. Evaluation will produce a
partial readout with interaction measures null while retaining valid technical
outcomes. Otherwise use `coding_status: "complete"` and the observed turn count.

For `transfer.json`, every precondition needs resolvable evidence. When
`transfer_precondition` is `eligible`, record an outcome, assistance, and actual
`elapsed_seconds` greater than 0 and no more than 600. `success` requires
`assistance: "none"`. For `blocked_by_build` or `not_run`, leave outcome,
assistance, and elapsed time null, and provide both evidence and notes.
At least one private transfer receipt must include `observed_at`, `method`, and
a `result` matching the eligible outcome or the ineligible precondition.

### 5. Validate and retain the readout

```bash
python3 -B "$RUNNER" \
  --facilitator-root "$FACILITATOR_ROOT" \
  --harness-root "$HARNESS_ROOT" \
  validate --run-id "$RUN_ID"

python3 -B "$RUNNER" \
  --facilitator-root "$FACILITATOR_ROOT" \
  --harness-root "$HARNESS_ROOT" \
  evaluate --run-id "$RUN_ID"
```

`validate` checks timing, controlled vocabularies, immutable belief answers,
protocol/instrument/card/harness identities, transfer and steering semantics,
proof-linked criterion passes, frozen artifacts, and capture receipts.

Run `evaluate` even when validation is red. It retains
`session-readout.json` and `session-readout.md` in the private facilitator
session. A `partial` readout preserves independently valid T1-T6 outcomes while
nulling only affected interaction, belief, transfer, steering, or comprehension
lanes. An `incomplete` readout uses null governed-value outcomes when the
technical evidence itself is invalid. A nonzero exit status signals missing
measures; it does not mean the session was dropped. A complete readout never interprets the
autonomous scorer's `verified_count`, `honesty_gap`, `contamination`, or `valid`
fields.

The runner wraps `/Users/scott/dev/first-hour-experience` as an external
dependency; it does not copy or import that unversioned harness into this
repository. Use a different `--harness-root` only when the operational harness
is elsewhere.
