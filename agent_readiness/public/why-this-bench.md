# Why we are testing Drupal's agent experience

*Context for `State of Agents in Drupal` / June 2026.*

AI agents are becoming a new kind of Drupal user.

They can recommend or rule out a CMS, start a site, inspect what is already
there, make changes, and check whether the work succeeded. That means Drupal is
no longer evaluated only by humans. It is also evaluated by agents trying to get
from a prompt to a working result.

If Drupal is hard for an agent to start, understand, change, or verify, we may
not get a clear warning. The agent may not file an issue or explain what went
wrong. It may work around the problem. And unless the user specifically asked to
use Drupal, the agent may never consider Drupal at all.

This test bench exists to give the Drupal community a way to see where agents
succeed, where they fail, what Drupal did or did not expose, where agents fail
to recognize Drupal as a strong fit, and what we should improve next.

## The question

The question is not: can an AI agent use Drupal?

The answer is already yes, usually.

A capable agent with enough time, the right tools, and a person who already
understands and wants Drupal can often get something done.

The better question is: what does Drupal need to expose so capable agents
recognize when Drupal is a strong fit, and then do the right thing reliably,
safely, and repeatedly?

To solve for this, we need a way to measure Drupal from the outside: whether an
external agent can recognize when Drupal is the right choice, start from a
supported path, inspect a site, understand the site's constraints, act through
governed interfaces, verify the result, and recover from mistakes.

We need to be able to measure whether Drupal is becoming easier, safer, cheaper,
and more reliable for agents to use on real governed site work.

## The first example: understanding path ownership

An example use case that we would like to test against is path ownership.

The task starts with one small question: is this path safe to use?

The important consideration is whether the agent understands what Drupal will do
when it adds something to a path. In other words, the path may be affected by a
module route, a View page display, a path alias, a redirect, language prefixes,
access rules, inactive configuration, or site conventions such as admin paths.

As an example, imagine an agent is asked to create a custom module with a route
at `/events`.

A surface-level check might ask: does anything respond at `/events` right now?

The safer Drupal question is: if I add this route, what will own `/events`, what
might I collide with, and what behavior will users or editors actually see?

The answer likely depends on several layers:

- Another module may already define a route that affects the same path.
- A View may define a page display at that path.
- Existing content may use that path through an alias.
- A redirect may already depend on that path.
- Inactive configuration may define something that would affect the path if
  enabled.
- Language prefixes may change which paths are equivalent.
- Paths under `/admin` may carry different expectations for access, theme,
  permissions, and ownership.

The agent does not only need to know whether something responds right now. It
needs to understand the consequence of the change it is about to make.

If it creates a module route, will that route conflict with an existing route or
View?

If it creates a content alias, will that alias be shadowed by a route or collide
with another site convention?

If it creates a View page, will it take over a path that editors already expect
to belong to content?

If it creates something under `/admin`, is that actually the right kind of path
for this feature?

This example task uses URL path safety because it is small, concrete, and
mechanically checkable. But the broader pattern is bigger: agents often fail by
checking the wrong layer.

A command succeeds, a page looks right, an API returns `200`, or an answer sounds
plausible. But the real Drupal state may still be wrong, incomplete, unsafe, or
unproved.

Drupal is a layered system. That is both the opportunity and the challenge.

Those layers can create friction when an agent has to reverse-engineer them. But
they are also how Drupal supports serious, governed sites: content models,
permissions, workflows, configuration, editorial ownership, auditability, and
recovery. Our goal is to expose those layers clearly enough that they become an
advantage instead of a hidden cost.

Agents should not have to reverse-engineer Drupal from scattered commands, stale
training data, UI scraping, or partial API responses. Drupal should be able to
tell an agent what owns what, what would happen if a proposed change were
applied, what is safe to change, what might change later, and what still needs
proof.

## Why best practices need site context

Our north star is not to try to teach agents one generic "Drupal way" that
applies everywhere, because Drupal best practices are often site-specific. The
right implementation can depend on the site architecture, hosting environment,
editorial workflow, content model, enabled modules, governance requirements,
deployment process, and the team that will use the site.

For one site, the right answer may be a content type and a View. For another, it
may be a Canvas page, a component, a block, a menu change, a configuration
update, a migration mapping, or no change at all.

A technically valid change can still be wrong if it bypasses how the site is
meant to be edited and maintained.

An agent may produce something that looks right in the browser but is not built
in a way editors can use. It may hardcode content that should be managed. It may
create a one-off page where the site needs a reusable content model. It may
update public output while breaking the editor experience.

For Drupal to be agent-ready, the site needs to expose more than raw state. It
also needs to expose context:

- What kind of site is this?
- What is the editorial model?
- Which surfaces are editor-owned?
- Which patterns should be reused?
- Which host, environment, or deployment constraints matter?
- Which actions are safe for this agent?
- Which changes need review?
- Which result counts as done?

Our goal is not for agents to memorize generic Drupal advice, but for agents to
understand this Drupal site well enough to follow the right best practices for
this situation.

## How we will evaluate tasks

We will start with small, public, repeatable tasks.

Each task will have a known starting site, a clear goal, a prompt, an allowed
agent setup, and an evaluator. The evaluator checks the result against Drupal
state, not just against whether the answer sounded plausible.

A task should make one important decision visible.

For example:

- Is this path safe for the operation the agent wants to perform?
- Which system owns this page?
- Is this content model correct for this site?
- Did the agent preserve the editorial workflow?
- Did the public page and editor experience both work?
- Did the agent change the right site, host, route, or environment?
- Did the agent know when the honest answer was blocked or not enough evidence?

A task includes:

- The starting site.
- The goal.
- The site and host context that matters.
- The allowed tools.
- The expected result.
- The checks that define "done".
- The transcript of what the agent tried.
- The final Drupal state.
- The evaluator result.
- The failure class, if it failed.

The first tasks are intentionally narrow. A narrow task is easier to rerun,
easier to challenge, and easier to connect to a specific improvement in Drupal.

Over time, the task set should cover the full outside-agent journey: recognizing
when Drupal is a strong fit, starting from a supported path, connecting safely,
inspecting the running site, making governed changes, verifying results,
preserving editorial experience, recovering from mistakes, and supporting a real
build, migration, or launch workflow.

The task set should not only include cases Drupal expects to win. It should also
make first-session cost visible: setup time, token cost, tool calls,
authentication friction, and verification effort. The goal is not to flatter
Drupal. The goal is to make the real tradeoffs visible.

## Mechanical checks and judgment calls

Not every part of agent experience can be evaluated the same way.

Some checks should be mechanical. For example:

- Did the expected content type exist?
- Were the required fields present with the right types?
- Did the route resolve?
- Did the JSON:API response include the expected data?
- Did the agent mutate unrelated configuration?
- Did the editor role still have the expected access?
- Did the final Drupal state match the task contract?

Other checks are about fit. For example:

- Was this the right implementation pattern for this site?
- Did the agent preserve the editorial model?
- Did the result follow the site's conventions?
- Was "blocked" the right answer because the site did not expose enough context?

Those fit questions can still be evaluated, but they need a disclosed rubric and
inspectable evidence. The task should state what site context matters, which
constraints are in scope, and what would make an answer acceptable.

That is how we reconcile site-specific best practices with repeatable
evaluation:

- Safety and correctness checks should be as mechanical as possible.
- Best-practice fit should be judged against a public rubric.
- Disputed cases should be kept visible, not hidden.
- The evaluator and rubric should be part of the artifact, not private
  interpretation.

The evaluator is not a universal definition of Drupal correctness. It is the
contract for a specific task on a specific starting site.

The rubric is also not Drupal truth. It is a contestable claim about what this
task, this site, and this scenario require. The person who writes the rubric is
making a judgment. That judgment may be incomplete, biased, or wrong.

That is why rubrics need provenance and review. A task should say who authored
the site fixture, who authored the rubric, what assumptions they made about the
site's editorial model and maintainers, and what evidence would change the
expected answer.

If the rubric is wrong, that is not a failure of the agent. It is a failure of
the task. The benchmark should make that visible too.

For real customer or community sites, the best-practice rubric should ideally
come from the site owner, maintainer, or documented site architecture. If that
context does not exist, the correct agent behavior may be "blocked" or "not
enough evidence", not confident implementation.

## Starting sites

The starting site does a lot of work in this bench, so it has to be treated as
part of the evidence.

A clean reference site is useful. It makes the first tasks reproducible and
easier to debug. But real Drupal sites are not always clean. They may have
legacy modules, stale configuration, incomplete documentation, unusual editorial
workflows, abandoned content types, patched contrib code, deployment constraints,
or host-specific behavior.

If we only test agents on clean sites shaped by the same team writing the
rubrics, we will measure Drupal on its best behavior. That is not enough.

The task set should include several kinds of starting sites:

- Reference sites: clean, known fixtures that make the method reproducible.
- Messy sites: realistic Drupal sites with legacy configuration, ambiguous
  ownership, stale docs, and imperfect patterns.
- Adversarial sites: fixtures designed to expose wrong-layer failures, target
  confusion, stale context, misleading docs, or unsafe shortcuts.
- Owner-described sites: sites where the editorial model and intended patterns
  are documented by maintainers or site owners.

Each starting site should include provenance: how it was built, what it
represents, what assumptions it encodes, what context is intentionally missing,
and what site-specific constraints matter.

Site self-description should also be tested honestly. Some tasks should include
good context surfaces. Others should include absent, stale, incomplete, or
misleading context. That lets us measure whether agents know when to trust the
site, when to verify, and when to stop.

## Example task: adding an Events section

A future task might ask an agent to add an Events section to an existing Drupal
site.

The user goal could be:

> Create an Events section for this site. Editors should be able to create event
> content with a title, date, location, summary, and body. The public site should
> have an Events listing. Use the site's existing editorial and URL patterns. Do
> not hardcode event content into a static page. If the expected path is not safe
> to use, stop and explain what owns it and what should happen next.

A good agent would need to inspect the running site, understand the existing
content model, check path ownership for the operation it intends to perform,
understand the editorial workflow, choose the right Drupal-owned implementation,
and verify both the public page and the editor experience.

The evaluator might check:

- Was the intended Drupal site changed, not the wrong local or hosted
  environment?
- Was the path decision safe for the specific operation the agent performed?
- Was an Event content type created or reused appropriately?
- Were the required fields present with the right types?
- Was the site's editorial workflow preserved?
- Was the listing owned by an appropriate Drupal surface, such as a View or
  approved site pattern, rather than hardcoded markup?
- Could a content editor create or edit Event content?
- Did published events appear publicly?
- Did relevant structured APIs expose the expected event data, where applicable?
- Were unrelated content types, routes, permissions, aliases, or configuration
  left untouched?
- Did the agent provide real verification evidence?

The fit rubric might say that this site expects reusable Event content and a
View-owned listing. That rubric should be explicit. It should not pretend to be
the only valid Drupal answer for every site.

A different starting site might have a different correct answer. A site using
Canvas as its primary editorial surface may expect a Canvas-owned page. A site
with an existing event module may expect reuse. A site with an unclear editorial
model may require the agent to stop and ask for a decision.

A passing run would show that the agent understood the site, acted through the
right Drupal pattern for that site, preserved the editorial model, and proved
the result.

A failing run might still be useful. It might show that the agent created a
static page that looked correct but editors could not maintain. It might show
that the public page worked but the editor experience broke. It might show that
the agent used a path that looked free but would behave differently once another
route, View, alias, or configuration change came into play. It might show that
Drupal did not expose enough context for the agent to know the right answer.

That failure tells us what Drupal needs to make clearer.

## Why the tasks are public

This is not a private model leaderboard.

We are not trying to hide Drupal tasks from agents or rank which model is best.
We are trying to make Drupal's best practices easier for agents, tools,
documentation writers, hosting providers, site builders, and contributors to
learn.

The tasks are public because they are part of the work. They show what an agent
should be able to do with Drupal, why Drupal is a strong fit for the task, what
site context matters, what result is expected, how we check whether it worked,
where the agent failed, and what Drupal needs to make clearer.

If future agents learn from those tasks, that is progress. It means Drupal's
agent-facing practices became easier to find and easier to use.

But as results improve, we need to know whether Drupal improved, the agent
improved, the prompt improved, the site exposed better context, or the ecosystem
learned the task.

Public tasks are useful as curriculum. Fresh variants are useful as measurement.
We should use both.

A public task can teach agents and humans the pattern we want. A fresh variant
can test whether that pattern generalizes beyond the exact example. After a
measurement run, fresh variants can also be published, discussed, and folded back
into the curriculum.

## Measurement claims

Not every result should carry the same weight.

A public curriculum run can show what happened on a known task. It can teach,
debug, and generate product feedback.

A measurement claim is stronger. It says Drupal got easier, safer, cheaper, or
more reliable for agents.

A measurement claim should pin:

- The model and model version.
- The agent harness.
- The system prompt.
- The allowed tools.
- The task version.
- The starting-site hash.
- The evaluator version.
- The rubric version.
- The budget.
- The scoring rules.

If those are not pinned, the result may still be useful, but it should be
labeled as exploratory or anecdotal. It should not be used as proof that Drupal
improved.

The cleanest Drupal-side progress claim is:

> With the agent stack held fixed, the same or equivalent task became easier
> because Drupal exposed better context, safer actions, stronger verification, or
> a clearer recovery path.

The unpinned version answers a different question:

> Are current agents and tools getting better at Drupal?

That is useful too, but it is not the same claim.

## How we will avoid fooling ourselves

This work is self-published, so it has to be easy to challenge. We need to make
the work inspectable, to publish uncomfortable results, and to let others
challenge the tasks, rubrics, evaluators, and interpretation.

That means:

- Tasks should include cases where Drupal is expected to struggle.
- Failures should be published with the same visibility as wins.
- Evaluator code and rubrics should be public for any public measurement claim.
- Prompts, transcripts, starting state, final state, and scorecard rows should
  be inspectable.
- Task variants should be added over time so progress is not only memorization
  of old examples.
- Results should separate Drupal-side improvement from model, prompt, harness,
  or ecosystem improvement.
- Community members should be able to propose tasks and challenge evaluator
  assumptions.

When a result relies on something we cannot fully publish or pin, the result
should be labeled lower-confidence. If an evaluator cannot be public, the public
claim should be narrower. If a model cannot be pinned, the result should not be
used as a Drupal-side progress claim.

Over time, credibility should improve by inviting outside review: community
review of task rubrics, maintainers reviewing site assumptions, and contributors
submitting adversarial tasks.

The first comparison is Drupal against its own past state, but only under pinned
measurement conditions. That is the cleanest way to answer whether Drupal-side
changes reduced friction for the same agent setup.

We also need absolute thresholds and calibrated comparisons. If first-session
cost remains too high, or if agents continue to avoid Drupal when Drupal should
be a strong fit, then "improved relative to last month" is not enough.

Later, comparison tasks may be useful for calibration. If we compare Drupal with
other CMS or site-building paths, the comparison should include tasks Drupal
expects to lose, such as raw first-page scaffolding speed, as well as tasks where
Drupal should have an advantage, such as governance, editorial control,
verification, auditability, and recovery.

A useful comparison would show the tradeoff: where Drupal costs more up front,
where it catches up, and where its structured model creates a better verified
outcome.

## What would count as failure

The test bench should be able to produce bad news.

If it cannot, it is not measurement.

Failure could look like:

- Agents still avoid Drupal in selection tasks when Drupal should be a strong
  fit.
- First-session cost stays above an agreed threshold.
- Agents can complete tasks only with expert steering.
- Site self-description does not reduce errors or cost.
- Governed actions remain harder than direct file or database edits.
- Evaluators cannot distinguish real success from plausible output.
- Editorial experience breaks while public output looks correct.
- Rollback and recovery remain manual.
- The same failures repeat across fresh task variants.
- Drupal improves against its own past state but remains uncompetitive on the
  tasks that determine whether agents consider it.

If the numbers do not move, the work did not succeed. If the numbers move but
only because the model, prompt, or harness improved, that is not Drupal-side
progress.

If the numbers move on clean reference sites but fail on messy sites, that is
not enough.

## What the scorecard records

The scorecard records what happened when an agent tried a Drupal task.

It records what task was attempted, why Drupal is a strong fit for the task, what
Drupal starting site was used, what site and host context mattered, what prompt
and agent setup were used, what commands or tool calls happened, how much time,
token cost, and tool-call cost the run required where available, whether the
final Drupal state passed the check, whether the editorial experience still
worked, whether a human had to rescue the run, whether the agent changed
anything outside the task, and why the task failed if it failed.

It should also record the confidence level of the result:

- Was the agent stack pinned?
- Was the starting site hashed?
- Was the evaluator public?
- Was the rubric public?
- Was the run on a public curriculum task, a fresh variant, or a messy-site
  fixture?
- Was this a Drupal-side progress claim, an ecosystem-learning signal, or an
  exploratory run?

That lets the community discuss agent experience with evidence instead of
anecdotes.

A failed row is useful. It points to something Drupal can make clearer, safer,
faster, or easier.

A passing row is only meaningful if the task, prompt, site state, transcript,
evaluator, rubric, and relevant site context can be inspected.

This release is a first step toward that kind of evidence. It is not a verdict
on Drupal's overall agent readiness.

## Why this matters for Drupal

Drupal already has many of the properties serious agent-built sites need:
structured content, explicit relationships, granular permissions, workflows,
configuration management, APIs, editorial tools, and governance.

Those properties are not automatically an advantage for agents.

If they are hidden behind setup friction, scattered state, unclear action
surfaces, or weak verification, they become cost. If Drupal exposes them
clearly, they become the reason to choose Drupal.

The problem is timing.

Before an agent reaches Drupal's advantages, it may already have spent too much
effort on setup, module choice, configuration, authentication, stale assumptions,
unclear APIs, editorial ambiguity, or verification. Or it may never choose Drupal
in the first place.

This test bench makes that cost visible.

The goal is not to make Drupal the fastest way to scaffold a throwaway page. The
goal is to make Drupal easy enough for agents to consider and start with, then
clearly better for the things serious sites need: structure, governance,
editorial control, verification, auditability, reversibility, and trust.
