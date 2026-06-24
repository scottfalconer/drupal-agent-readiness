# Finding: a Drupal self-description prototype can warn agents about hidden path conflicts

*State of Agents in Drupal v0 — proof of direction, not a readiness verdict. June 2026.*

## Plain-English summary

A Drupal path can look empty while disabled configuration has already claimed
it. For example, a disabled View may reserve `/events` even though nothing
currently responds there. If an agent only asks whether a URL routes right now,
it can wrongly conclude the path is safe to use as a new node alias.

In this v0 test, agents using Drush-only inspection judged some hidden
disabled-View path claims safe. Agents given the prototype site
self-description command, `site-architecture:path-owner`, found those claims and
flagged them unsafe in the headline run.

This does not prove Drupal is broadly agent-ready. It proves one narrower point:
when Drupal exposes its structured state clearly, agents make safer decisions.

## Why this matters

We do not want agents to reverse-engineer Drupal. We want Drupal to tell agents
what is true.

The broader Drupal agent-readiness bet is that external agents need Drupal to be
legible, callable, and verifiable: the site can report its state, the agent can
act through governed interfaces, and the result can be checked. This is one
measured result behind that bet. The broader release context is in
[`why-this-bench.md`](why-this-bench.md).

| What this proves | What this does not prove |
| --- | --- |
| Site self-description changed agent behavior in one constrained path-safety task. | Drupal is broadly agent-ready. |
| Prototype Drupal-reported state made hidden path claims visible that Drush-only inspection sometimes judged safe. | The prototype resolver is production-ready or a Drupal core/contrib feature. |
| Public, repeatable tasks can make agent failure modes concrete. | The result is statistically powered or a claim across model providers. |

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

We ran the same task on the same Drupal starting site in two conditions:

- **Drush-only inspection** — the agent inspects with ordinary Drush commands.
- **Site self-description** — the agent also has the prototype
  `site-architecture:path-owner` command, which reports what claims or owns a
  path, including hidden disabled-View declarations.

The agent was not told that disabled Views might matter. Ground truth is computed
by an independent Drupal evaluator that does not use the tested tool, so it
judges both conditions fairly.

Full method and reproduction steps: `method/HARNESS.md` in the repo root.
Detailed results: the retained `alias-safety-SYNTHESIS.md` in the experiment
evidence package.

Artifact note: the headline A/B package retains normalized `answer.json`,
`evaluator.json`, `meta.json`, ground truth, candidates, and raw workflow output.
It does not retain full per-command transcripts for every A/B run. The
inventory/event/recovery scorecard runs do retain transcripts.

## The result

We ran the headline task on stock Drupal CMS with the Haven testbed profile. The
agent was not told that disabled Views might matter. Each run asked the agent to
judge two hidden path claims, so 10 runs produced 20 hidden disabled-View path
judgments per arm.

| Model | Runs (hidden judgments) | Drush-only correctly flagged unsafe | Drush-only reason named disabled View | With self-description correctly flagged unsafe | With self-description reason |
| --- | ---: | ---: | ---: | ---: | ---: |
| claude-haiku-4-5 | 10 runs (20 judgments) | **16/20 (80%)** | **0/20 (0%)** | **20/20 (100%)** | **20/20 (100%)** |
| claude-opus-4-8 | 10 runs (20 judgments) | **14/20 (70%)** | **14/20 (70%)** | **20/20 (100%)** | **20/20 (100%)** |

Put differently: Drush-only agents incorrectly judged hidden path claims as
safe in roughly **20-30% of hidden disabled-View path judgments**. With site
self-description, we observed **0 hidden-claim safe judgments** in the headline
run. In a real write flow, those are the cases where the agent could proceed
toward creating content on a path already claimed by disabled configuration.

The two stock Haven hidden paths in the headline run are under `/admin`. That
matters: a Drush-only agent can mark an admin path unsafe for the right
operational outcome but the wrong Drupal-specific reason. The supporting
`reason named disabled View` metric separates the actionable verdict from
evidence that the agent identified the latent disabled-View declaration. A
controlled non-admin fixture is included as breadth evidence, but the non-admin
case should be repeated at n=10 before making it the headline.

The important point is not that one model was weak. The stronger model also
judged hidden claims safe in some runs, because the failure mode is to answer a
current-routing question instead of the safer operation-specific Drupal
question: what will happen if the agent creates the proposed alias here?

We saw the same direction across additional Drupal starting sites (core and
Convivial) and in initial non-Claude evidence. OpenAI Codex[^codex], on stock
Haven at n=3, judged **6 of 6** hidden claims safe with Drush-only inspection
and flagged **6 of 6** with site self-description. That is encouraging breadth
evidence, not yet a claim across model providers.

[^codex]: In this repo, "OpenAI Codex" names the Codex agent/model id used in
    the retained run artifacts (`gpt-5.5-codex`), not the legacy OpenAI Codex API
    models that were retired in 2023.

## What it means next

This finding points to three practical next steps:

- Drupal should describe its own state.
- Agents should act through governed interfaces.
- Risky changes should be verified before they become damage.

For internal roadmap tracking, this maps to site self-description (Outcome 3B),
governed action (Outcome 4), and verification and recovery (Outcome 5).

The practical point is simple: Drupal already has structured state. If Drupal
exposes that state clearly, agents can make safer decisions without guessing
from routes, files, or stale assumptions.

The alias-safety finding is the first example of the broader wrong-layer failure
pattern. The agent checked whether anything currently responded at a path, but
the safer Drupal question was operation-specific: what will Drupal do with this
path if the agent creates the proposed alias?

## Honest scope

- This is **one task**, a proof of direction — not a Drupal agent-readiness
  verdict, and not a benchmark.
- Numbers are n=10 runs per arm on one Drupal starting site (the headline) and n=3
  elsewhere (breadth, noisy). Treat the aggregate direction as the signal, not
  any single small-n condition.
- One latent path in the breadth set was injected to remove an "admin path is
  reserved" confound; the headline (stock Haven) and the other stock Drupal
  starting sites are not injected.
- The tool here is a working `site_architecture` resolver, not yet a contributed
  module. The roadmap path is to land this as site self-description through the
  normal Drupal process (work items #10, #11).

## Reproduce it

`method/HARNESS.md` in the repo root — prepare a test fixture from any Drupal
site, run any agent against the documented contract (Claude, Codex, and Gemini
runners shown), and score with the provided independent Drupal evaluator.
