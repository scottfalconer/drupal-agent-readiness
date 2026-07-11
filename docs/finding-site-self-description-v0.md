# Historical observation: judgments differed between two path-inspection conditions

*State of Agents in Drupal v0 — frontier observation, not claim-grade evidence
or a readiness verdict. June 2026.*

## Plain-English summary

A Drupal path can look empty while disabled configuration has already claimed
it. For example, a disabled View may reserve `/events` even though nothing
currently responds there. If an agent only asks whether a URL routes right now,
it can wrongly conclude the path is safe to use as a new node alias.

In this historical v0 test, agents using Drush-only inspection judged some
hidden disabled-View path claims safe. In the condition whose prompt named the
verdict-bearing `site-architecture:path-owner` fixture command, equipped answers
cited disabled declarations and retained judgments differed.

This does not prove Drupal is broadly agent-ready, that self-description alone
caused the result, or that an actual write became safer. It is an exploratory
frontier observation about one helper in one judgment task. Its registered
evidence class is `exploratory_legacy_unpinned` and `claim_grade` is `false`.

## Why this matters

We do not want agents to reverse-engineer Drupal. We want Drupal to tell agents
what is true.

The broader Drupal agent-readiness bet is that external agents need Drupal to be
legible, callable, and verifiable: the site can report its state, the agent can
act through governed interfaces, and the result can be checked. This is one
historical observation motivating that bet. The broader release context is in
[`why-this-bench.md`](why-this-bench.md).

| What the retained observation shows | What it does not prove |
| --- | --- |
| Retained judgments differed between the Drush-only condition and the condition whose prompt named a helper with path-state and verdict guidance. | Tool discovery, the helper as an isolated cause, facts-only self-description, an end-to-end write, or Drupal-side longitudinal improvement. |
| Equipped answers cited disabled declarations that some Drush-only answers did not. | The resolver fixture is production-ready or a Drupal core/contrib feature. |
| Public, rerunnable tasks can make agent failure modes concrete. | Exact replication of the historical effect, statistical power, or behavior across model providers. |

## The concrete Drupal trap

The task is small: *given a URL path, is it safe to create a new node with that
path as its alias?*

Some cases are easy: an active route, an existing alias, or an entity's canonical
page. The hard case is a **hidden path claim** (a latent claim): a path declared
by disabled configuration. For example, a disabled View may declare `/events`.
Nothing responds at `/events` right now, so a surface-level check says the path
is free. But if that View is enabled later, Drupal can reclaim the path and
collide with content the agent is trying to place there.

This v0 task tests path safety for one operation: creating a new node alias. It
does not cover the full Drupal path-ownership problem. A future path task should
test other operations, such as adding a module route, creating a View page
display, adding a redirect, or creating paths under `/admin`. The larger
question is not whether a string is free-looking. It is what Drupal will do with
that path for the operation the agent is about to perform.

## The test

We ran the same task on the same Drupal starting site in two bundled conditions:

- **Drush-only inspection** — the agent inspects with ordinary Drush commands.
- **Named decision helper** — the agent also has the bundled
  `site-architecture:path-owner` fixture command, which reports what claims or
  owns a path, including hidden disabled-View declarations, and gives normative
  guidance about risky claims.

The conditions differ in module/tool availability and prompt instructions: the
equipped prompt names the exact helper command and describes its role. Ground
truth is computed by a separate Drupal evaluator that does not use the tested
tool, but this design does not isolate which part of the bundled condition is
associated with the answer difference.

Full method and task-rerun steps: `method/HARNESS.md` in the repo root.
The experiment package retains a superseded qualitative
`alias-safety-SYNTHESIS.md`; use `experiments-v1.json` for generated
metrics, evidence classes, and source hashes.

Artifact note: the headline A/B package retains normalized `answer.json`,
`evaluator.json`, `meta.json`, ground truth, candidates, and raw workflow output.
It does not retain full per-command transcripts for every A/B run. The
inventory/event/recovery scorecard runs do retain transcripts.

## The result

We ran the historical task on stock Drupal CMS with the Haven testbed profile.
The prompt did not tell the agent that disabled Views might matter. Drush-only
inspection sometimes judged hidden claims safe; equipped answers cited the
hidden layer, and retained judgments differed between conditions. Exact counts, denominators, source paths,
source hashes, and the registered claim boundary are generated in
[`docs/experiments-v1.json`](experiments-v1.json), experiment
`alias-safety-haven-n10-fullyblind-v0`.

This was a judgment task. It did not ask the agent to discover an unnamed tool
or carry the decision through an actual Drupal write, so it cannot establish
either outcome.

The two stock Haven hidden paths in the headline run are under `/admin`. That
matters: a Drush-only agent can mark an admin path unsafe for the right
operational outcome but the wrong Drupal-specific reason. The supporting
`reason named disabled View` metric separates the actionable verdict from
evidence that the agent identified the latent disabled-View declaration. A
controlled non-admin fixture is included as breadth evidence, but the non-admin
case needs a pinned repeated experiment before replacing the headline case.

The important point is not that one model was weak. The stronger model also
judged hidden claims safe in some runs, because the failure mode is to answer a
current-routing question instead of the safer operation-specific Drupal
question: what will happen if the agent creates the proposed alias here?

The registry also includes initial Codex breadth evidence from stock Haven. It
is a historical frontier observation, not provider-general evidence or a stable
non-Claude baseline. Its exact metrics are in the same generated artifact.

## What it means next

This finding points to three practical next steps:

- Drupal should describe its own state.
- Agents should act through governed interfaces.
- Risky changes should be verified before they become damage.

For internal roadmap tracking, this maps to site self-description (Outcome 3B),
governed action (Outcome 4), and verification and recovery (Outcome 5).

The practical hypothesis is simple: Drupal already has structured state. If it
exposes facts clearly through discoverable, non-verdicting interfaces, agents may
make better judgments without guessing from routes, files, or stale assumptions.
That narrower mechanism and an end-to-end write still need to be tested.

The alias-safety finding is the first example of the broader wrong-layer failure
pattern. The agent checked whether anything currently responded at a path, but
the safer Drupal question was operation-specific: what will Drupal do with this
path if the agent creates the proposed alias?

## Honest scope

- This is **one historical task**, a directional observation — not a Drupal agent-readiness
  verdict, and not a benchmark.
- Exact historical counts are in `docs/experiments-v1.json`; the registry marks
  the experiment `frontier_observation`, `exploratory_legacy_unpinned`, and
  `claim_grade: false`.
- One latent path in the breadth set was injected to remove an "admin path is
  reserved" confound; the headline stock Haven case is not injected.
- The tool here is a working `site_architecture` resolver fixture, not a
  contributed module. The roadmap path is to land this as site self-description
  through the normal Drupal process (work items #10, #11).

## Rerun the task

`method/HARNESS.md` in the repo root — prepare a test fixture from any Drupal
site, use the documented Claude provenance, Codex diagnostic example, and
vendor-neutral contract, and score with the provided separate Drupal
evaluator. This can rerun the task; it cannot exactly reproduce the historical
effect because the original harness, model, prompt-as-run, budget, and substrate
were not all fully pinned.
