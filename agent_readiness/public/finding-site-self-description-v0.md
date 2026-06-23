# Finding: Drupal can warn agents about hidden path conflicts

*State of Agents in Drupal v0 — proof of direction, not a readiness verdict. June 2026.*

## Plain-English summary

We tested whether an external AI agent can safely decide if a URL path is free
to use in Drupal.

Some Drupal paths look unused but are still claimed by disabled configuration.
For example, a disabled View may reserve `/events` even though nothing currently
responds there. An agent using only ordinary Drush inspection can wrongly
conclude the path is safe.

In this v0 test, agents using Drush-only inspection missed some of those hidden
claims. Agents given a site self-description command,
`site-architecture:path-owner`, caught all of them in the headline run.

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
| Drupal-reported state caught hidden path claims that Drush-only inspection missed. | The prototype resolver is production-ready. |
| Public, repeatable tasks can make agent failure modes concrete. | The result is statistically powered or a claim across model providers. |

## The concrete Drupal trap

The task is small: *given a URL path, is it safe to create a new node with that
path as its alias?*

Some cases are easy: an active route, an existing alias, or an entity's canonical
page. The hard case is a **hidden path claim** (a latent claim): a path reserved
by disabled configuration. For example, a disabled View may declare `/events`.
Nothing responds at `/events` right now, so a surface-level check says the path
is free. But if that View is enabled later, Drupal reclaims the path and collides
with the content the agent created.

This v0 task tests path safety for one operation: creating a new node alias. It
does not cover the full Drupal path-ownership problem. A future path task should
test other operations, such as adding a module route, creating a View page
display, adding a redirect, or creating paths under `/admin`. The larger
question is not whether a string is free-looking. It is what Drupal will do with
that path for the operation the agent is about to perform.

## The test

We ran the same task on the same Drupal starting site in two conditions:

- **Drush-only inspection** — the agent inspects with ordinary Drush commands.
- **Site self-description** — the agent also has `site-architecture:path-owner`,
  which reports what claims or owns a path, including hidden disabled-View claims.

The agent was not told that disabled Views might matter. Ground truth is computed
by an independent Drupal evaluator that does not use the tested tool, so it
judges both conditions fairly.

Full method and reproduction steps: `../method/HARNESS.md`. Detailed results:
`../evidence/experiments/alias-safety-SYNTHESIS.md`.

## The result

We ran the headline task on stock Drupal CMS / Haven. The agent was not told
that disabled Views might matter. Each run asked the agent to judge two hidden
path claims, so 10 runs produced 20 latent-claim judgments per arm.

| Model | Drush-only: hidden claims flagged | With site self-description: hidden claims flagged |
| --- | --- | --- |
| claude-haiku-4-5 | **16/20 (80%)** | **20/20 (100%)** |
| claude-opus-4-8 | **14/20 (70%)** | **20/20 (100%)** |

Put differently: Drush-only agents incorrectly judged hidden claimed paths as
safe in roughly **20-30% of latent-claim judgments**. With site
self-description, we observed **0 such misses** in the headline run. In a real
write flow, those are the cases where the agent would be allowed to create
content on a path already claimed by disabled configuration.

The important point is not that one model was weak. The stronger model also
missed the hidden claim, because its reasoning — "nothing routes here now, so the
path is free" — is exactly the failure mode. Drush-only inspection answers the
current routing question. Site self-description answers the safer
operation-specific Drupal question: what will happen if the agent creates the
proposed alias here?

We saw the same direction across additional Drupal starting sites (core and
Convivial) and in initial non-Claude evidence. OpenAI Codex (gpt-5.5), on
stock Haven at n=3, missed **6 of 6** hidden claims with Drush-only inspection
and flagged **6 of 6** with site self-description. That is encouraging breadth
evidence, not yet a claim across model providers.

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

`../method/HARNESS.md` — prepare a test fixture from any Drupal site, run any agent
against the documented contract (Claude, Codex, and Gemini runners shown), and
score with the provided independent Drupal evaluator.
