# Human-Agent First-Hour Experience — Real-Participant Pilot v0

Status: runnable formative pilot. This protocol is designed to be used with real
participants now, without building a simulated novice or changing the existing
first-hour harness.

## Decision

Run a one-arm, real-participant study on Drupal CMS. The experimental unit is an
agent-fluent, Drupal-naive human working with a coding agent they already know.

This is not an A/B test, a cross-platform comparison, or a Measurement v1 agent
run. It is an observational pilot intended to answer:

> During their first hour with Drupal CMS, where does a capable coding agent
> absorb Drupal's complexity, where does it forward that complexity to a novice,
> and what verified, understood, maintainable result does the person have after
> 60 minutes?

The pilot reports a vector of outcomes, not one universal readiness score. It
also asks which recurring failures suggest a bounded Drupal-side, agent-side,
or study-infrastructure intervention. Those intervention labels are roadmap
hypotheses grounded in observed episodes; they are not causal treatment effects.

## Why this is different from the autonomous first-hour study

The existing v0/v1/v2 first-hour study asks what happens when the owner steps
away and an agent works autonomously. It measures platform setup, visible value,
governed value, native-affordance use, and agent claims against verified state.

This pilot keeps the useful team-site task and the M1/M4/MG instrumentation, but
changes the unit of observation. It measures things an autonomous run cannot:

- questions the agent forwards to a person who cannot answer them;
- what the participant believes is working versus what is actually working;
- whether the participant can operate the result without the agent;
- whether the hour produces understanding and ownership or only dependency;
- dead ends, corrections, and human or facilitator rescues.

Do not calculate an "interaction tax" by subtracting autonomous-run timing from
this pilot unless the task, agent stack, environment, milestone definitions, and
stopping policy are identical. They are not assumed to be identical here.

## What is adopted and deferred

Adopted from the supplied critique:

- the human-agent dyad as the construct;
- avoidable decision leakage;
- participant belief versus independent truth;
- exit comprehension and ownership;
- dead ends and time to verified value;
- an outcome-language task and a small steering probe;
- a post-session insight-to-intervention coding layer.

Deferred:

- an LLM simulating the novice, because real participants are available;
- Drupal CMS versus Drupal core or WordPress, because the novel variable is the
  human interaction and a small participant pool should not be split yet;
- a readiness-treatment A/B until this protocol and scoring survive real use;
- any predicted headline or platform-ordering claim.

## Evidence and claim class

This is a convenience-sample, formative human-participant pilot. It may report:

> In these sessions, with these participants, agent stacks, workstation, and
> team-directory task, X of N dyads reached independently verified governed
> value by minute 60. The observed decision-leakage, belief-truth, transfer, and
> dead-end patterns were ... The bounded intervention hypotheses most directly
> supported by those episodes were ...

It may not claim:

- that Drupal is or is not broadly agent-ready;
- that Drupal improved relative to an earlier version or treatment;
- that Drupal CMS is better or worse than another platform;
- that participant differences were caused by Drupal;
- statistical significance, population prevalence, or a stable ordering;
- production readiness from a passing first-hour task.

The closest current target contract is `governed_editorial_change` in
[`task-families-v1.json`](task-families-v1.json), but that target remains
unexecuted and treats human intervention differently. This pilot borrows its
public-output, least-privilege, reproducibility, blast-radius, and handoff ideas;
it is not registered as an execution of that task family.

## Participants

### Include

A participant should:

- have used a coding agent at least weekly during the previous month, or have
  completed at least five multi-step repository tasks with one;
- be comfortable opening a fresh agent conversation, sharing files or errors,
  reviewing proposed work, and asking the agent to verify its result;
- use a familiar agent that can execute shell commands and read and write files
  in the assigned workspace; a chat-only agent is structurally ineligible;
- use an agent whose enforced filesystem boundary excludes the facilitator's
  private study directory. If the familiar agent can read the whole filesystem,
  run it under a separate OS account or on a separate device; a sibling path
  alone is not isolation;
- never have built or administered a Drupal site;
- have no advance exposure to this task, rubric, or existing first-hour results.

Prior experience editing content in Drupal is not automatically disqualifying,
but record it. Record experience with other CMSs and web frameworks as context.

### Pilot census

Before participant 1, run one zero-participant rehearsal with the facilitator as
participant through `prepare` → `start` → minute-60 freeze → T1-T6 evaluation →
transfer classification. Exclude it from the census. Verify that capture can run
while the participant completes the belief form, snapshot/archive restore works,
the empty-bundle fallback works, transfer-blocking semantics work, and the exact
template's root `composer.json` identifies `drupal/cms`.

Mark the preparation with `--rehearsal`. A compressed rehearsal may register a
shorter `start --seconds N`, but its stop is only a registered-stop technical
check. It must leave `verified_governed_value_at_60` null and must not be
described as a first-hour participant outcome.

Run every available eligible participant under the same protocol. Use
`full_recipe_v0` for the rehearsal and first two instrument shakeouts. Then
choose and freeze one install-guidance condition for the retained pilot. If the
task, setup card, moderator behavior, or scoring changes after shakeout, version
the protocol and do not silently pool the earlier sessions with later ones.

Before the first session, record the recruitment window, intended participants
or maximum N, and the rule for ending recruitment. End by that rule, not because
the emerging result looks positive, negative, or repetitive.

Do not exclude a completed session after seeing its outcome. Retain protocol
deviations, missing evidence, timeouts, and failures in the census.

## Environment

Use one fresh Drupal CMS workspace per participant on the same class of capable
development workstation:

- Docker, DDEV, PHP, Composer, Node, and a browser available;
- shared base container images may be pre-pulled;
- no Drupal project or site already present in the participant workspace;
- web access allowed;
- a fresh browser profile and a fresh agent conversation;
- no previous task transcript or Drupal-specific project memory supplied;
- the same three team-member records and local image assets;
- no real customer data, production credentials, or personal secrets.

Let participants use an agent surface they already understand. Before prepare,
record all mandatory agent-stack fields in JSON: `product`, `version`,
`model_or_selector`, `mode`, `approval_policy`, a nonempty `enabled_tools` list,
`workspace_boundary`, and `workspace_shell: true`. The participant agent must
have a workspace shell, but its readable boundary must exclude the private
facilitator root. If participants use different stacks, describe the sessions
as ecological observations; do not compare their times as if Drupal were the
only difference.

Participants may use the browser and agent normally. Direct participant-written
code or shell changes are allowed but must be logged as manual implementation.
The facilitator must not provide Drupal implementation advice.

## Materials

Prepare four neutral image files. Put only the first three in
`[WORKSPACE]/.ddev/study-assets/` before the clock; DDEV's special
`composer create-project` path permits `.ddev` while a normal nonempty project
root would fail. Keep Taylor's image outside the participant workspace until the
transfer test:

| File | Person | Role |
| --- | --- | --- |
| `alex.jpg` | Alex Rivera | Executive Director |
| `jordan.jpg` | Jordan Lee | Program Manager |
| `sam.jpg` | Sam Patel | Communications Lead |
| `taylor.jpg` | Taylor Morgan | Volunteer Coordinator |

The first three are part of the build task. Taylor and `taylor.jpg` are reserved
for the post-hour transfer test and must not be shown beforehand.

Also prepare a private `FACILITATOR_ROOT` outside the external harness and
participant workspace. It must be inaccessible to the participant agent. Put
Taylor, participant identity, hidden forms, evaluator materials, and study
receipts only under `FACILITATOR_ROOT/<run-id>/`. Also prepare:

- the participant task card below;
- a timer visible only to the facilitator;
- the observer event log;
- the minute-60 belief inventory;
- the evaluator checklist;
- the minute-60 comprehension questions and ratings;
- recording consent and a written access/retention rule for any raw recording.

The only study material placed in the participant workspace is the three build
images and the three participant cards under `.ddev/study-packet/`. The
`--facilitator-isolation-confirmed` prepare flag records that the boundary was
checked; it does not create the boundary.

## Participant task and setup cards

Give the participant only this task card and the workspace location. Do not show
the evaluator checks, comprehension questions, or transfer task before minute 60.

> You have 60 minutes. Use Drupal CMS and your coding agent to create a small
> team area for this site.
>
> The site should work in a browser. Add these people using the supplied photos:
> Alex Rivera, Executive Director; Jordan Lee, Program Manager; and Sam Patel,
> Communications Lead. Visitors should be able to see the team at `/team`.
>
> Create a staff editor account that can add and update team members through the
> browser, but cannot manage users, site-wide settings, or the site's structure.
>
> Leave the site running. Before time ends, ask your agent to show you what
> works, verify it, and explain what another owner would need to know.
>
> Work with your agent as you normally would. If it asks something you genuinely
> do not know, do not pretend to know Drupal; respond as you would in real life.
> You may ask the agent to explain, recommend, show evidence, or make a reasonable
> choice. The facilitator can help only with study logistics, not Drupal.
>
> The three supplied photos are in `[BUILD_ASSETS]`.

Every participant receives this always-on environment card:

> Work directly in `[WORKSPACE]`. Use DDEV project name `[DDEV_PROJECT]`
> exactly. When the site is available, use the `raw.primary_url` reported by
> `ddev describe -j`; do not assume HTTPS or a default router port. Do not run
> `ddev poweroff`, because it would stop unrelated projects.

Separately choose exactly one versioned install-guidance card:

`full_recipe_v0`:

> Configure DDEV with project type `drupal11` and docroot `web`. Create the
> Drupal CMS project with `ddev composer create-project drupal/cms:^2`. Use
> `ddev drush ...` for Drush and install non-interactively with `ddev drush
> site:install -y`; do not use the browser installer.

`constraints_only_v0`:

> Use your familiar agent to identify and execute a supported way to install
> the Drupal CMS distribution while honoring the fixed DDEV constraints. Bare
> Drupal core does not satisfy the task.

Record `install_guidance`, each card's version and SHA-256, and
`install_discovery_pre_solved`. A full-recipe session deliberately pre-solves
install-path discovery: its M1 measures execution under supplied guidance and
machine time, not novice Drupal setup discovery. Do not pool setup-friction
findings across card versions. A run that intentionally uses another server,
DDEV name, or bare Drupal core is retained as a protocol deviation; its harness
milestones may be unreliable.

## Optional steering probe

This is a secondary measure and is not required for minute-60 governed success.

Before minute 40, trigger on the earliest observable event:

- the poller records `M4`; or
- the participant states that `/team` works and shows it in the browser.

During the hour, the facilitator can run the runner's `steering-status`
subcommand in a separate private terminal to see whether the harness has
recorded M4. It reports live milestone state without revealing the rubric or
mutating `steering.json`. A participant-statement trigger still requires live
observer judgment and a neutral timestamp.

Then say:

> One change: please also feature the three team members on the homepage, while
> keeping the full `/team` page.

Record `steering_exposed`, `steering_trigger_source` (`m4`,
`participant_statement`, or `not_reached`), trigger time, the agent's response,
any new questions, whether `/team` regresses, and result (`pass`, `partial`,
`fail`, or `not_reached`). Always report governed success with steering exposure
because the probe consumes dyad time and may affect T5/T6. If neither trigger is
reached before minute 40, do not expose the probe or score it as a failure.

## Moderator timeline

### Before the clock

1. Confirm eligibility and assign a pseudonymous participant ID.
2. Explain what will be retained and obtain explicit recording/transcript
   consent. Do not record without a defined access and retention rule.
3. Record the agent stack and workstation metadata.
4. Confirm the workspace is fresh and the local assets are present.
5. Open a new agent conversation and browser profile.
6. Give the task card. Do not explain Drupal concepts or the scoring rubric.

### Minute 0

Record one canonical UTC start timestamp and start the 60-minute participant
clock when the task card and workspace are handed over. Launch the poller at the
same moment and record its signed offset from the canonical start in seconds.
For a standard session, the runner registers exactly 3,600 seconds and the
poller must launch no more than 2 seconds after the canonical start. Do not use
the CLI's `--seconds` override for a retained participant session. If the launch
offset exceeds 2 seconds, retain the session but do not report its stop as a
standard minute-60 observation.

### During the hour

- Observe silently; do not require think-aloud narration.
- Record only neutral timestamps, actors, short descriptions, results or
  durations, and source locators during the live session. Apply DL, dead-end,
  scope, and intervention codes from the recording or transcript afterward.
- If asked a Drupal question, say: "Please handle that with your agent; I can
  only help with the study setup."
- Fix only verified study-infrastructure faults. Record each fix as an
  infrastructure rescue and stop the clock only if the pre-registered policy
  says that class of fault is outside the participant experience.
- Give identical time notices at minute 45 and minute 55. At minute 55 say:
  "Five minutes remain. Please finish, verify, and get a handoff from your agent."

### Minute 60

1. Stop implementation exactly 3,600 seconds after the canonical start. Do not
   extend participant time while waiting for the poller, which can finish up to
   one polling interval later. Do not allow further agent or site changes yet.
2. In a participant-facing terminal controlled by the facilitator, run the
   runner's plain-language `respond` command. The participant completes its
   prompts without the agent or facilitator and before seeing evaluator truth;
   do not ask them to view or edit raw JSON.
3. In parallel, the facilitator immediately preserves the minute-60 site, HTTP,
   milestone, and transcript state. Create the named database snapshot before
   the workspace archive and before any transfer or evaluator mutation.
4. Hide all evaluator and adapter output from the participant. Never show it
   before the belief form is submitted.
5. After form submission, ask and score the comprehension questions and ratings.
6. Finish the non-mutating captures and existing adapter before transfer changes
   content. Record any evidence that was missing; do not silently recreate it.

Begin `freeze` as close as operationally possible to the exact stop. The
instrument accepts a capture-start timestamp from 3,599 through 3,610 seconds
after canonical start (a -1/+10-second capture tolerance), provided the
registered duration is 3,600 seconds and poll launch offset is 0-2 seconds.
This tolerance accommodates process launch; it never grants extra build time.
Outside that window, retain the session and registered-stop evidence, but leave
the standard minute-60 outcome null.

### After the minute-60 snapshot

1. Hide or close the coding agent.
2. Run the unaided editor transfer test, capped at 10 minutes.
3. Run the remaining independent positive and negative editor checks without
   showing the participant the results.
4. If scheduling allows, the participant may resume for up to 20 minutes to see
   whether a blocked session recovers. Report eventual completion separately;
   never backfill the minute-60 result.

## Primary technical outcome

`verified_governed_value_at_60` is true only when all six checks pass against the
minute-60 state:

| ID | Required outcome | Independent proof |
| --- | --- | --- |
| T1 | A real Drupal CMS site is running. | Site root returns `200` with substantial Drupal content, and Composer/project state identifies the Drupal CMS distribution rather than bare core. |
| T2 | A reusable team-member model has name, role, and photo. | Inspect Drupal bundles and field definitions; a static page does not pass. |
| T3 | The three supplied people exist as separate records with their assigned data. | Query live content; match all three names and roles; confirm each record has a non-empty image/media reference. |
| T4 | `/team` is a public team listing. | Anonymous request returns `200`, differs from the homepage, contains all three names and roles, and publicly renders each assigned image. |
| T5 | A real non-admin editor can create and edit team members. | Using the minute-60 account and permissions, create and then edit an evaluator-owned record without administrator fallback. |
| T6 | The editor is denied on the three registered unrelated-administration probes. | The same account lacks the corresponding permissions and is denied direct access to user creation, site information configuration, and the detected team bundle's field administration. |

A passing `200`, a role name, a hidden menu item, an agent claim, or success with
administrator credentials does not establish T5 or T6.

T5 and T6 may be behaviorally probed after the clock, but they must use the
account and permissions present in the preserved minute-60 state. The probe
verifies a minute-60 capability; it does not give the participant extra build
time. Keep the separate transfer result distinct so participant difficulty does
not get misreported as a missing Drupal capability, or vice versa.

Report these separately from the primary outcome:

- `handoff_evidence_at_60`: the participant received working URLs, editor login
  instructions, known limitations, and exact start/verification commands;
- `config_evidence_at_60`: relevant configuration was exported or otherwise
  captured in a form another workspace could attempt to reproduce;
- `unrelated_blast_radius`: existing or host state changed outside the task;
- `steering_exposed`, trigger source/time, and `steering_probe_result`: pass,
  fail, partial, or not reached.

Do not call the site reproducible unless a clean reconstruction is actually
tested. Configuration export is evidence toward reproducibility, not proof.

## Existing milestone reuse

The existing `/Users/scott/dev/first-hour-experience` harness can timestamp:

- `M1`: first real site response;
- `M4`: first substantial, distinct public `/team` response;
- `MG`: its content-model-plus-scoped-role governed-value proxy.

Treat M1/M4/MG as secondary timing measures. In particular, M4 does not prove
the supplied names are present, and MG does not prove that an editor account can
log in and perform the workflow. T1-T6 remain authoritative.

### Operational runner

Use the versioned runner and exact commands in
[`human-agent-first-hour/README.md`](human-agent-first-hour/README.md). It wraps
the existing harness for private `prepare`, minute-0 `start`, participant
`respond`, live `steering-status`, atomic `freeze`, `select-bundle`, form
`validate`, and `evaluate`. The required global `--facilitator-root` option must
appear before the subcommand on every invocation. `prepare` also requires the
complete agent-stack JSON and an explicit isolation confirmation.

The runner maintains a participant-visible plane under the external harness
and a private control plane under `FACILITATOR_ROOT/<run-id>/`. Public
`minute-60/` contains participant-safe technical captures, the workspace
archive, and the participant packet. Participant identity, belief answers,
Taylor, start/poll receipts, registered protocol and harness copies, evaluator
evidence, coding, and readouts remain under the private root. The exact study
runner and CLI are registered too; prepare-to-freeze source or external-harness
drift invalidates the runtime-identity lane. It also preserves
a failed build that never configures DDEV, records missing capture evidence,
and verifies frozen hashes. If a configured project is stopped at minute 60, it
records that state and skips commands that could start or repair it after the
clock.

After freeze, `select-bundle` materializes one exact candidate from the frozen
bundle list as private `evaluator-evidence/team-state.json` and records the
bundle ID, source, and rationale. It fails rather than inventing a candidate.
Every evaluator pass must link each registered proof kind to a resolvable
minute-60 artifact or a private evaluator receipt bound to that criterion and
evidence kind, containing `result: pass`, an observation timestamp, and the
method used. Native HTTP, Composer, and Drush proof kinds use the exact frozen
captures; the root HTTP proof also requires a substantial body. File existence
alone is not a pass.

Run `evaluate` even if `validate` reports missing evidence or coding. The runner
retains a measure-specific private readout. If technical evidence is valid, a
`partial` readout preserves T1-T6 and nulls only affected interaction, belief,
transfer, steering, or comprehension lanes. If technical evidence is invalid,
an `incomplete` readout nulls governed-value outcomes. A nonzero CLI result
represents missing measures, not an exclusion.

The following no-code procedure is retained only as a diagnostic fallback. It
does not provide the runner's atomic capture or validation guarantees; using it
is a protocol deviation.

### Nonconforming manual diagnostic fallback

The runner is required for a standard retained participant session. The legacy
procedure below may help diagnose the external harness, but it does not enforce
the private facilitator boundary, immutable response capture, proof-linked
evaluation, or the registered timing window. Never substitute it on the day of
a participant session and then label the result a standard minute-60 outcome.

No harness code change is required, but the out-of-scope access marker must be
disabled in each human run before polling. Otherwise the old rung-9 probe runs
after M1 and can distort the 15-second milestone cadence.

For each participant:

1. Add a unique entry to
   `/Users/scott/dev/first-hour-experience/state/schedule.json`:

   ```json
   {
     "run_id": "human-dcms-01",
     "platform": "drupal-cms",
     "runner": "human-agent",
     "model": "recorded-in-session-metadata"
   }
   ```

2. Prepare a fresh workspace. Never reuse or overwrite an earlier run ID:

   ```bash
   cd /Users/scott/dev/first-hour-experience
   python3 scripts/firsthour.py prep --run-id human-dcms-01
   ```

3. Disable the autonomous access-coverage marker, then read the exact work path
   and DDEV project name for the environment card:

   ```bash
   cd /Users/scott/dev/first-hour-experience
   RUN_META=evidence/runs/human-dcms-01/run-meta.json
   jq '.access_marker = ""' "$RUN_META" > "$RUN_META.tmp"
   mv "$RUN_META.tmp" "$RUN_META"
   jq '{work, ddev_project}' "$RUN_META"
   ```

4. Copy only `alex.jpg`, `jordan.jpg`, and `sam.jpg` into
   `work/.ddev/study-assets/`. A normal project-root asset directory makes
   Composer's target nonempty and is not valid. Keep `taylor.jpg` outside the
   harness in an agent-inaccessible private facilitator directory. Do not give
   the participant the generated autonomous `prompt.md`; give them only the
   participant task, environment, and guidance cards.

5. At canonical minute 0, record the UTC start and poller offset in the observer
   log, then run the poller in a separate terminal:

   ```bash
   cd /Users/scott/dev/first-hour-experience
   python3 scripts/firsthour.py poll --run-id human-dcms-01 --seconds 3600
   ```

6. At exactly canonical minute 60, stop the participant. Before any transfer or
   evaluator mutation, create a database snapshot and full workspace archive
   from the actual Drupal project directory. Then wait for the poller to exit,
   run the existing adapter, and copy the minute-60 evidence into a frozen
   directory:

   ```bash
   RUN_DIR=/Users/scott/dev/first-hour-experience/evidence/runs/human-dcms-01
   SITE="$RUN_DIR/work"
   mkdir -p "$RUN_DIR/minute-60"
   cd "$SITE"
   BASE_URL=$(ddev describe -j | jq -r '.raw.primary_url')
   ddev describe -j > "$RUN_DIR/minute-60/ddev-describe.json"
   ddev drush status --format=json > "$RUN_DIR/minute-60/drush-status.json"
   curl -ksS -D "$RUN_DIR/minute-60/root.headers" \
     -o "$RUN_DIR/minute-60/root.html" "$BASE_URL/"
   curl -ksS -D "$RUN_DIR/minute-60/team.headers" \
     -o "$RUN_DIR/minute-60/team.html" "$BASE_URL/team"
   ddev snapshot --name=human-dcms-01-minute60
   tar -czf "$RUN_DIR/minute-60/workspace.tar.gz" -C "$SITE" .
   cd /Users/scott/dev/first-hour-experience
   python3 scripts/firsthour.py score --run-id human-dcms-01
   for FILE in score.json run-meta.json milestones.jsonl poll-result.json captured-http.json; do
     test ! -f "$RUN_DIR/$FILE" || cp "$RUN_DIR/$FILE" "$RUN_DIR/minute-60/"
   done
   cd "$SITE"
   ddev drush php:eval '
   $efm = \Drupal::service("entity_field.manager");
   $info = \Drupal::service("entity_type.bundle.info")->getBundleInfo("node");
   $out = [];
   foreach ($info as $bundle => $definition) {
     $fields = [];
     foreach ($efm->getFieldDefinitions("node", $bundle) as $name => $field) {
       $fields[$name] = $field->getType();
     }
     $ids = \Drupal::entityQuery("node")->accessCheck(FALSE)
       ->condition("type", $bundle)->execute();
     $nodes = [];
     foreach (\Drupal\node\Entity\Node::loadMultiple($ids) as $node) {
       $nodes[] = ["id" => $node->id(), "label" => $node->label()];
     }
     $out[] = ["bundle" => $bundle, "label" => $definition["label"] ?? $bundle,
       "fields" => $fields, "node_count" => count($ids), "nodes" => $nodes];
   }
   print json_encode($out);
   ' > "$RUN_DIR/minute-60/bundle-candidates.json"
   ddev drush php:eval '
   $out = [];
   foreach (\Drupal\user\Entity\Role::loadMultiple() as $id => $role) {
     $out[$id] = array_values($role->getPermissions());
   }
   print json_encode($out);
   ' > "$RUN_DIR/minute-60/role-permissions.json"
   ```

   If the agent nested the project, use the directory containing `.ddev` rather
   than the generated `work` directory shown in the example. Do not copy
   identity, belief answers, observer logs, Taylor, or other facilitator-only
   material into public `minute-60`. Preserve it in the agent-inaccessible
   private location before allowing later agent work. If required evidence is
   absent, record it as missing rather than erasing the diagnostic run.

   Always capture every node-type candidate. Never call
   `getFieldDefinitions()` with an empty bundle. If the adapter returns no team
   bundle, the evaluator may select a defensible candidate from the frozen list
   only in the private control plane, with source, bundle ID, and rationale. If
   no candidate is defensible, mark T2/T3 failed or `not tested`; the capture
   must not crash.

7. Preserve but do not interpret the autonomous scorer's `verified_count`,
   `honesty_gap`, `contamination`, or `valid` fields. For this pilot, score
   T1-T6, participant belief, and transfer explicitly. Current rung 8 and rung 9
   are outside this pilot.

If schedule preparation or polling would delay a session, repair or reschedule
before participant start. A manual timer may support a rehearsal or diagnostic,
but it does not satisfy the runner's standard timing receipts. Do not invent
missing milestone or minute-60 precision afterward.

## Interaction measures

### Avoidable decision leakage

Count one `DL-HARD` event only when all are true:

1. the agent asks the participant to choose or confirm an implementation detail;
2. the choice depends on Drupal vocabulary or technical state the participant
   cannot reasonably observe;
3. the agent gives no plain-language consequences and no supported recommendation;
4. the participant says they do not know, guesses, asks the agent to choose, or
   follows an unexplained default.

Examples that count:

- asking "View or custom controller?" without explaining the user/editor impact;
- asking which bundle, display mode, recipe, or permission string to use without
  translating the choice or recommending a safe default.

Do not count:

- product or owner choices such as wording, visual priority, or which people to
  feature;
- requests for credentials or missing authority;
- warnings or confirmation before a destructive or security-sensitive action;
- a concise clarification where different outcomes genuinely matter and the
  agent explains the tradeoff.

Count `DL-SOFT` when an implementation choice is surfaced with a confident
recommendation or default but without plain-language consequences, and the
participant accepts or delegates it without transcript evidence that they could
evaluate the choice. This is an observational signal, not proof that the
participant understood nothing.

Every hard or soft leakage event must use one `decision_object` from the
versioned instrument: `bundle_choice`, `view_vs_block`, `permission_strings`,
`recipe_vs_manual`, `text_format`, `media_handling`, `theme`, or `other`.
Additional instrument values must be versioned before use.

Report `DL-HARD` and `DL-SOFT` separately, both raw and per 10
participant-to-agent turns. Preserve the triggering question, recommendation,
and participant response in redacted form.

### Verification burden

Count a separate `VB` event when the agent asks the participant to confirm a
technical success the agent could have checked itself, without showing a relevant
check or explaining how the participant can observe it. This is not decision
leakage unless the agent also forwards an unanswerable implementation choice.

### Dead ends

A `DE` episode begins when an unsuccessful approach, incorrect assumption, or
contradictory state causes at least two recovery turns or approximately three
minutes without progress. It ends when the dyad adopts a materially different
approach or reaches the next observable milestone.

Record count, duration, responsible layer, and whether the agent recovered
without help. Classify the layer as setup, Drupal discovery, content modeling,
rendering/routing, permissions, verification, agent/tool, or study infrastructure.

### Rescues and manual implementation

- `R-HUMAN`: the facilitator supplies a Drupal command, diagnosis, architecture
  choice, or implementation answer. This is a substantive rescue.
- `R-INFRA`: the facilitator repairs a study-owned machine, port, account, or
  capture failure. Keep this separate from Drupal outcomes.
- `MANUAL`: the participant directly implements or repairs technical state
  instead of directing the agent.

Retain the run after a rescue. Report what was achieved before and after it.

### Insight-to-intervention coding

Every `DL-HARD`, `DL-SOFT`, `DE`, `R-HUMAN`, and derived false-confident belief
gets one `failure_scope` and one `candidate_fix` from
[`human-agent-first-hour/instrument-v0.json`](human-agent-first-hour/instrument-v0.json).

`failure_scope` is `drupal_specific`, `agent_generic`, `mixed`,
`study_infrastructure`, or `unclear`:

- `drupal_specific` depends on Drupal mechanics and has a plausible Drupal-side
  repair;
- `agent_generic` would likely occur in an equivalent non-Drupal local build;
- `mixed` means both materially contributed.

Do not translate an `agent_generic` finding into a Drupal backlog item.
`candidate_fix` is a bounded hypothesis—platform default/recipe, agent site
self-description, introspection, verification, onboarding, harness/infra, a
generic agent/tool change, or unclear—not evidence the treatment will work.

## Live observation and post-session coding

During the session use
[`observer-log-v0.csv`](human-agent-first-hour/observer-log-v0.csv) for neutral
observation only:

| Clock | Actor | Neutral description | Result/duration | Source locator |
| --- | --- | --- | --- | --- |
| `00:00` | facilitator | Task card handed over | — | recording `00:00` |

After the session, code the recording or transcript in
[`coded-events-v0.csv`](human-agent-first-hour/coded-events-v0.csv). `CQ` means
an appropriate clarification and is not leakage. `CLAIM` records a material
claim; `VERIFY` records the observable check and result. Public interaction
findings require a second coder blinded to participant identity and agent stack,
with disagreements resolved event by event.

## Minute-60 belief inventory

Before the participant sees evaluator results, run the CLI's `respond`
subcommand in a participant-facing terminal. It presents the registered
plain-language claims one at a time, records the submission timestamp, and
refuses to overwrite a prior submission. The participant must not inspect or
edit raw JSON. The markdown
[`participant-belief-inventory-v0.md`](human-agent-first-hour/participant-belief-inventory-v0.md)
is a reference copy, not the live entry surface. They answer every claim `yes`,
`no`, or `unsure`, confidence 1–5, and the main reason:

`agent_said_so`, `agent_showed_check`, `saw_in_browser`, `tested_myself`,
`inferred_other`, or `not_enough_evidence`.

Keep evaluator truth on a separate hidden worksheet. The nine registered claims
cover browser availability, public completeness, separate structured records,
the editor's positive workflow, three distinct negative boundaries, automatic
listing, and handoff continuity. Do not combine denial claims; doing so would
hide which safety boundary the participant misunderstands.

The mutable participant response and its frozen copy both remain in the private
facilitator tree. Validation rejects any change to the statement, answer,
confidence, reason, note, or submission timestamp after freeze.

Derive:

- `false_confident`: participant says yes with confidence 4-5, evaluator fails;
- `false_negative`: participant says no, evaluator passes;
- `uncertain`: participant says unsure;
- `unsupported_confidence`: participant says yes with confidence 4-5, but the
  claim was not tested.

Do not collapse these into one honesty score. They describe different trust and
comprehension failures. Treat each false-confident belief as a coded event with
evidence references, `failure_scope`, and `candidate_fix`.

## Unaided editor transfer test

After the minute-60 state and belief inventory are frozen, determine the
transfer precondition:

- `eligible`: a usable minute-60 editor account, credentials, and required
  editing capability exist;
- `blocked_by_build`: the account/credentials are unusable or the required
  capability does not exist at minute 60;
- `not_run`: the transfer was not attempted for a recorded non-outcome reason.

`blocked_by_build` is a build outcome, not a navigation failure. If eligible,
hide the coding agent, give the participant the minute-60 editor credentials,
and ask:

> Add Taylor Morgan, Volunteer Coordinator, using `taylor.jpg`. Make Taylor
> appear on `/team`. You have 10 minutes. Use only the browser and the staff
> editor account.

Classify the outcome as `success`, `login_failure`, `navigation_failure`,
`workflow_failure`, `listing_failure`, `timeout`, or `assisted`. Record
assistance separately as `none`, `facilitator_hint`, `admin_fallback`, `agent`,
or `cli`. Every transfer precondition requires one or more resolvable evidence
references under `minute-60/...` or `evaluator-evidence/...`. For an eligible
attempt, record actual `elapsed_seconds` greater than 0 and no more than 600,
plus:

- whether the participant can log in;
- time to find the correct editing surface;
- whether the record can be created without administrator access;
- whether `taylor.jpg` is attached and Taylor's image and details appear
  automatically on `/team`;
- any facilitator hint or administrator fallback.

`transfer_outcome=success` requires successful editor login, browser-only creation with
the assigned role and photo, and Taylor's details and image appearing on
`/team`, all within 10 minutes without a hint, administrator fallback, agent
use, or code/CLI changes.

Use `navigation_failure` only if a valid account and capability exist, login
succeeds, and the participant cannot locate the editing surface. Reclassify the
initial observation after the evaluator establishes whether the capability
actually existed.

For `blocked_by_build` or `not_run`, leave transfer outcome, assistance, and
elapsed seconds null, and record both explanatory notes and evidence for the
precondition. For `eligible`, all outcome, assistance, elapsed, and evidence
fields are required. `success` is invalid with any assistance other than
`none`.

The evaluator then uses the same editor account to confirm that user management,
site-wide configuration, and site-structure administration are denied. Merely
hiding navigation is not enough; direct access must be denied.

## Minute-60 comprehension

Ask these questions after the belief inventory but before the transfer test,
correction, or teaching. Do not require Drupal terms; score whether the
participant understands the operational reality.

1. What are the main pieces that make the team area work?
2. How would the next owner add or change a team member?
3. What controls what the staff editor may and may not do?
4. What would you tell the next owner is working, uncertain, or still risky?

Score each 0-2:

- `0`: incorrect, cannot answer, or relies on a false model;
- `1`: partially correct but misses a material dependency or boundary;
- `2`: operationally correct and specific enough for the next action.

Report the four item scores and total out of 8. Also ask for 1-5 ratings of:

- clarity about what the agent changed;
- sense of control;
- trust that the result works;
- frustration;
- confidence continuing with Drupal tomorrow.

## Independent evaluator checklist

The evaluator must inspect the minute-60 state rather than the agent's narrative:

1. Capture anonymous site root and `/team` responses.
2. Match all three supplied names and roles on `/team`.
3. Inspect the actual Drupal bundle and fields.
4. Query the three separate content records.
5. Confirm the editor account exists and is not an administrator.
6. Test successful creation and editing of an evaluator-owned team record using
   that account, without administrator fallback.
7. Confirm the permissions `administer users`, `administer site configuration`,
   and `administer node fields` are absent (`administer content types` is useful
   supplementary evidence), then directly test denial of
   `/admin/people/create`, `/admin/config/system/site-information`, and
   `/admin/structure/types/manage/<team_bundle>/fields`.
8. Inspect relevant exported configuration and the agent's handoff.
9. Record unrelated workspace, host, route, content, or configuration changes.
10. Mark unavailable evidence `not tested`; never infer a pass from a role name,
    screenshot, hidden link, final answer, or HTTP status alone.

In private `evaluator.json`, every T1-T6 row requires at least one resolvable
`evidence_refs` entry. A passing row must also map every registered
`required_pass_evidence` key in `evidence_by_kind` to criterion-specific proof.
References may point only to frozen `minute-60/...` files or private
`evaluator-evidence/...` files. An evaluator-created JSON receipt used to prove
a pass must contain `result: "pass"`, a nonempty `observed_at` timestamp, and a
nonempty `method` describing the exact check and result, plus the matching
`criterion_id` and `evidence_kind`. Existing files,
screenshots, or arbitrary notes do not pass merely because they resolve. Failed
or `not tested` rows require explanatory notes and a private receipt with the
matching `criterion_id`, result, timestamp, and method. Require a nonempty
evaluator ID and completion timestamp. Require a nonempty interaction coder ID;
false-confident belief coding also records its coder ID.

For a pilot, one trained evaluator may score the run. Before any public claim,
blind a second evaluator to participant identity and agent stack and resolve
disagreements criterion by criterion. Apply the same blinded second-coder rule
to interaction coding used in public findings.

### Executable T1-T6 worksheet

Use the frozen minute-60 artifacts for T1-T4 and the account/permissions that
existed at minute 60 for the post-clock T5-T6 behavior probes. For each item,
record `pass`, `fail`, or `not tested`, the exact command or URL, timestamp, and
evidence path.

Set the run paths:

```bash
RUN_DIR=/Users/scott/dev/first-hour-experience/evidence/runs/human-dcms-01
MIN60="$RUN_DIR/minute-60"
```

T1 passes only when all three checks agree:

```bash
head -n 1 "$MIN60/root.headers"
tar -xOf "$MIN60/workspace.tar.gz" ./composer.json | jq -e '.name == "drupal/cms"'
jq . "$MIN60/drush-status.json"
```

- The captured root response must be `200` with substantial Drupal output.
- Root `composer.json` must identify `drupal/cms`; bare Drupal core fails this
  criterion even if the site works.
- The preserved Drush status must show a bootstrapped Drupal site.

T2 and T3 start with all frozen bundle candidates:

```bash
jq . "$MIN60/bundle-candidates.json"
```

If one candidate is defensibly the team model, run the CLI's `select-bundle`
subcommand with its exact bundle ID, source, and rationale. It writes private
`evaluator-evidence/team-state.json`, preserving the selected frozen fields and
records and updating the evaluator selection fields. If no candidate is
defensible, do not materialize one; T2/T3 must be `fail` or `not tested` with
notes and evidence. The team-state receipt records the selected source; create
separate `result: "pass"` receipts for the actual T2 field and T3 record
assertions and link those in `evidence_by_kind`.

- T2 requires a real bundle with name/title semantics, a role/position field,
  and an image or media field.
- T3 requires separate live records for Alex, Jordan, and Sam with the assigned
  roles and a non-empty image/media reference on each record.

T4 uses the frozen anonymous response:

```bash
head -n 1 "$MIN60/team.headers"
rg -n -i 'Alex Rivera|Jordan Lee|Sam Patel|Executive Director|Program Manager|Communications Lead' \
  "$MIN60/team.html"
```

T4 passes only if the response is `200`, is not a copy of the homepage, contains
all six expected name/role strings, and visual or DOM evidence binds each
assigned image to the corresponding person. Generic theme images do not count.

For T5, log in with the minute-60 staff editor account—never an administrator:

1. Create an `Evaluator Probe` team member with role `Initial Role` and a local
   test image; save successfully.
2. Reopen that same record, change the role to `Updated Role`, and save again.
3. Confirm the updated record renders through the public team listing.
4. Retain the authenticated create/edit URLs and before/after evidence.

For T6, retain `role-permissions.json`, identify the editor's assigned role, and
confirm `administer users`, `administer site configuration`, and `administer
node fields` are absent; retain `administer content types` as supplementary
diagnostic evidence. Then, while logged in as the same editor, directly request:

```text
/admin/people/create
/admin/config/system/site-information
/admin/structure/types/manage/<team_bundle>/fields
```

Each registered probe must return an access-denied result and must not allow the
privileged operation. Direct behavioral denial is authoritative; the permission
inventory supports diagnosis. T6 supports only "denied on these registered
probes," not an exhaustive claim about every Drupal administrative route.

## Retained artifacts and participant safety

Private derived-artifact home:

`FACILITATOR_ROOT/<run-id>/`

The external harness may retain only the participant workspace and
participant-safe technical capture under
`HARNESS_ROOT/evidence/runs/<run-id>/minute-60/`. Do not encode the participant
ID in that public tree. Private identity, belief, observer, transfer, evaluator,
coding, held-out asset, and readout files stay under the facilitator root,
including its `frozen-minute-60/` copy.

Retain, when consent and policy allow:

- frozen protocol version or SHA-256;
- pseudonymous participant screener and CMS/agent experience;
- exact task card and environment metadata;
- agent product/model/mode/tools/version;
- observer log;
- agent transcript;
- M1/M4/MG milestones and minute-60 score;
- minute-60 participant belief inventory;
- evaluator checklist and supporting commands/screenshots;
- transfer-test result;
- exit answers and item scores;
- protocol deviations, rescues, and exclusion status.

Raw screen/audio recordings, credentials, tokens, participant names, and private
agent history must not be committed to this repository. Store raw recordings in
the approved private location, with access and retention communicated before
consent. Pause or redact capture around credentials. Publish only redacted,
task-relevant excerpts and derived measures.

## Validity and exclusions

- Screen Drupal experience before the session; do not infer naivety afterward.
- A pre-clock study-machine failure is repaired or rescheduled. A post-start
  failure remains in the record and is classified by layer.
- Missing recording or transcript does not become an outcome-based exclusion.
  Set interaction coding to `unavailable`, record the reason/coder/timestamp,
  leave event/turn measures null, and retain independently valid technical
  outcomes in a partial readout.
- Participant abandonment, agent refusal, timeout, and incomplete site are
  outcomes, not exclusions.
- Record deviations such as prior task exposure, use of an administrator account,
  manual implementation, facilitator rescue, or unavailable verifier evidence.
- Keep protocol and scoring changes versioned. Never reinterpret a metric after
  looking at which participant or stack appears to win.
- The observer and exit interview create reactivity. Report that limitation.
- Different familiar-agent stacks improve ecological realism but weaken
  comparison. Report exact stacks and individual cases.
- A red validation does not exclude or erase a session. Run `evaluate` to write
  a retained readout with lane-specific validation issues. Preserve validated
  technical outcomes in a `partial` readout; use null governed outcomes only
  when the technical lane is incomplete. Do not convert null to fail or success.

## Analysis and report shape

Do not publish a composite score. Report one row per retained participant:

| Participant | Agent stack | Guidance / pre-solved | Steering exposed / result | M1 | M4 | MG proxy | T1-T6 at 60 | Governed success | Transfer | DL-HARD /10 | DL-SOFT /10 | VB | Dead ends | Human rescues | False-confident | Comprehension /8 |
| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
|  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |

For each session also complete the top-three table in
[`session-synthesis-v0.md`](human-agent-first-hour/session-synthesis-v0.md):

| Rank | Event IDs | Friction | Observable minutes until progress resumed | Affected milestone/outcome | Scope | Candidate fix | Evidence |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| 1 |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |

Use `not_estimable`, never zero, when duration cannot be supported. Ask every
participant, “What one change would have most improved this hour?” Preserve the
answer as a hypothesis-generating debrief response, not a causal finding.

For a small pilot:

- report the full census, counts, medians, ranges, and individual failure stories;
- separate instrument shakeout from unchanged-protocol sessions;
- publish nulls and incomplete sessions;
- report `verified_governed_value_at_60` only for a standard 3,600-second run
  whose capture began in the -1/+10-second window and whose poller launched
  within 2 seconds. Otherwise report the registered-stop result separately and
  leave the minute-60 value null;
- distinguish appropriate clarification from avoidable decision leakage;
- report technical success, belief accuracy, and comprehension separately;
- do not use significance tests or platform-level language.

The decision after this pilot is whether the instrument produces repeatable,
actionable failure modes. If it does, freeze it and choose one next comparison:

1. current Drupal CMS versus one defined agent-readiness treatment; or
2. Drupal CMS versus Drupal core on the same real-participant protocol.

Do not run both comparisons at once with a small participant pool.

The pilot's durable output is also a calibration corpus. Preserve redacted
examples and final codes for hard/soft leakage, decision objects, dead-end
classes, claims and beliefs, failure scope, and candidate fixes. Use recurring
patterns to specify a simulated novice and regression fixtures for defined
treatments such as recipes/defaults, site self-description, introspection, and
novice-visible verification. Run at least three simulated trials per condition
only as a cheap treatment-regression harness. Simulation does not estimate human
prevalence or replace confirmation with real participants.

## Same-day operator checklist

Before the first session:

- [ ] Freeze this protocol version and intended pilot census.
- [ ] Complete and exclude the zero-participant rehearsal, including snapshot
      restore, empty-bundle fallback, transfer classification, and T1 identity.
- [ ] Select and hash the versioned install-guidance card; do not pool setup
      findings across versions.
- [ ] Define consent, raw-recording access, and retention.
- [ ] Prepare participant IDs and four neutral image assets.
- [ ] Create an agent-inaccessible facilitator root outside the harness; use a
      separate OS account or device if the participant agent is unrestricted.
- [ ] Prepare a unique fresh workspace and run ID per participant.
- [ ] Record every mandatory agent-stack JSON field and confirm workspace shell.
- [ ] Confirm the poller or manual timestamp sheet is ready.
- [ ] Confirm the participant sees only the workspace, three build images, and
      three participant cards; all hidden state and Taylor remain private.

For every session:

- [ ] Start the exact 3,600-second clock and poller together; confirm poll launch
      offset is no more than 2 seconds.
- [ ] Log neutral timestamps and descriptions; code interaction events later.
- [ ] Use `steering-status` during the hour; apply the probe only on an
      observable trigger and record exposure privately.
- [ ] Stop all changes exactly at 3,600 seconds and start freeze within the
      -1/+10-second capture window.
- [ ] Run the plain-language `respond` command while freeze runs; keep truth hidden.
- [ ] Materialize a defensible frozen bundle with `select-bundle`, or record that
      none exists without inventing one.
- [ ] Score T1-T6 with resolvable criterion-specific proof references.
- [ ] Classify the transfer precondition before the agent-free transfer and exit interview.
- [ ] Record transfer evidence and, when eligible, actual elapsed seconds <=600.
- [ ] Code scope/fix and top-three friction after the session.
- [ ] Run `evaluate` even when validation is red; retain the incomplete null readout.
- [ ] Redact credentials and personal data before retaining artifacts.
- [ ] Record deviations and missing evidence without dropping the run.
