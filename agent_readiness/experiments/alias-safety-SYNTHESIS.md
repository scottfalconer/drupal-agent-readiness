# Synthesis: does live site self-description help agents? (alias-safety, all experiments)

The candidate thesis: a running Drupal site answering "what is true" through live
commands (`site-architecture:path-owner`) **materially helps** an agent over raw
Drupal inspection. We tested it on the hardest case the tool is built for — **latent
claims**: paths declared by a *disabled* view, unrouted now but a collision if the view
is enabled. We swept **model** (`claude-haiku-4-5`, `claude-opus-4-8`), **prompt framing**
(told the criterion → soft-blind → fully-blind), and **substrate** (Haven, core-std,
Convivial — all stock — plus a Haven clone with a controlled non-admin latent injected).

All numbers are latent-claim accuracy. The headline stock Haven run is n=10 per
arm; cross-substrate and initial non-Claude breadth runs are n=3 per cell.
**verdict** = flagged the path unsafe (the actionable answer). **reasoned** = a
supporting free-text heuristic for whether the reason recognized the *disabled*
nature, vs. getting the verdict right by an "admin path is reserved" shortcut or
by treating the disabled view as active.

## Headline

**Live self-description caught every tested latent claim; raw drush did not when the
agent was unprompted.** With `path-owner`, the equipped arm flagged **every** latent claim
across **every** substrate, model, and run in this experiment — **100/100 verdict, 100/100 reasoned**. Raw drush,
fully-blind, missed a real fraction. The firmest number is **stock Haven at n=10** (20
latent observations per arm/model):

| stock Haven, fully-blind, n=10 | raw verdict | equip verdict | raw reasoned | equip reasoned |
|---|---|---|---|---|
| **claude-haiku-4-5** | **16/20 (80%)** | 20/20 (100%) | 0/20 (0%) | 20/20 (100%) |
| **claude-opus-4-8** | **14/20 (70%)** | 20/20 (100%) | 14/20 (70%) | 20/20 (100%) |

The two stock Haven latent paths in this headline run are under `/admin`, so the
verdict and reasoned metrics need to be read together. The verdict is the
actionable safety decision; the reasoned metric shows whether the agent found the
disabled-View layer instead of only applying an admin-path convention.

So unprompted, raw drush incorrectly judged latent claimed paths safe in ~20% (Haiku) /
~30% (Opus) of latent-claim judgments; with site self-description, we observed 0 such
misses. In a real write flow, those misses are the cases where the agent would be allowed
to create content on a path already claimed by disabled configuration. Note Opus-raw is
*worse* than Haiku-raw here — its careful "this path is unrouted right now, so it's free"
reasoning is exactly the trap (the disabled view makes it unrouted *now* but a collision
later). The gap shows up across substrates (core, Convivial, plus an injected non-admin
latent) at the smaller n=3 below; those per-cell numbers are noisy (the n=10 Haven figure
is the one to cite).

### Cross-substrate breadth (n=3 per cell — supporting, noisy)

| | raw verdict | equip verdict | raw reasoned | equip reasoned |
|---|---|---|---|---|
| claude-haiku-4-5 (4 substrates) | 19/30 (63%) | 30/30 | 0/30 (0%) | 30/30 |
| claude-opus-4-8 (4 substrates) | 25/30 (83%) | 30/30 | 23/30 (77%) | 30/30 |
| stock only (haven+core+convivial), haiku | 16/21 (76%) | 21/21 | 0/21 | 21/21 |
| stock only, opus | 17/21 (81%) | 21/21 | 17/21 | 21/21 |

The gap is **not** an artifact of the injected non-admin path — it holds on three stock
substrates and firms up to 20–30% at n=10.

### Initial non-Claude breadth (not provider-general)

A non-Claude agent, **OpenAI Codex (gpt-5.5)**, fully-blind on stock Haven (n=3):

| | raw verdict | equip verdict |
|---|---|---|
| gpt-5.5-codex | **0/6 (0%)** | 6/6 (100%) |

Codex-raw is *worse* than the Claude models — it ran one router/alias check and concluded
"no route, safe" for every latent claim. This is initial non-Claude evidence, not yet a
claim across model providers. (See `experiments/alias-safety-codex-fullyblind-v0/` for
per-run artifacts.)

## Per-substrate (fully-blind)

| Substrate | Model | raw verdict | equip verdict | raw reasoned | equip reasoned |
|---|---|---|---|---|---|
| Haven (stock) | haiku | 4/6 (67%) | 6/6 | 0/6 (0%) | 6/6 |
| Haven (stock) | opus | 4/6 (67%) | 6/6 | 4/6 (67%) | 6/6 |
| core-std (stock) | haiku | 6/9 (67%) | 9/9 | 0/9 (0%) | 9/9 |
| core-std (stock) | opus | 9/9 (100%) | 9/9 | 9/9 (100%) | 9/9 |
| Convivial (stock) | haiku | 6/6 (100%) | 6/6 | 0/6 (0%) | 6/6 |
| Convivial (stock) | opus | 4/6 (67%) | 6/6 | 4/6 (67%) | 6/6 |
| non-admin (injected) | haiku | 3/9 (33%) | 9/9 | 0/9 (0%) | 9/9 |
| non-admin (injected) | opus | 8/9 (89%) | 9/9 | 6/9 (67%) | 9/9 |

## How prompt framing moves it (Haven)

| Framing | Model | raw verdict | equip verdict | raw reasoned | equip reasoned |
|---|---|---|---|---|---|
| told | haiku / opus | 100% | 100% | 100% | 100% |
| soft-blind | haiku | 100% | 100% | 33% | 100% |
| soft-blind | opus | 100% | 100% | 100% | 100% |
| fully-blind | haiku | 67% | 100% | 0% | 100% |
| fully-blind | opus | 67% | 100% | 67% | 100% |

- **Told the criterion → the tool is useless** (everything 100%).
- **Soft-blind ("…or after routine config changes") → raw verdict holds** (the hint pushes
  raw agents to check disabled views); only reasoning degrades.
- **Fully-blind ("is it already claimed?") → raw verdict drops**; the tool's edge appears.

## Cited answers (fully-blind)

The verdict number is concrete behavior, not a metric artifact:

- **Dangerous miss — Haiku raw, stock Haven, `/admin/content/files`:**
  *"safe: true — Files view is disabled; route not active."* (Reasoned the disabled state
  means *safe* — the exact failure.)
- **Dangerous miss — Opus raw, Convivial, `/admin/content/media/scheduled`:**
  *"safe: true — the /scheduled child is unrouted… scheduler module uses
  /admin/content/scheduled, not this path… nothing currently claims the exact path."*
  (Careful, thorough — and still wrong, because it only looked at what routes *now*.)
- **Right answer, shallow reason — Haiku raw, Haven, `/admin/content/files`:**
  *"safe: false — Admin path… part of admin system."* (Correct verdict via an "admin is
  reserved" heuristic, not by finding the disabled view. This is why raw verdict on
  admin-namespaced latents is higher than reasoned: the heuristic rescues it. It would not
  rescue a non-admin latent — see the injected substrate, where Haiku raw verdict is 33%.)
- **Tool catch — Haiku equipped, Haven, `/admin/content/files`:**
  *"safe: false — Disabled view files:page_1 declares this path. If that view is ever
  enabled, it will collide with any content created here."*

## Conclusion

The thesis is **supported, narrowly and concretely**: live self-description (`path-owner`)
**reduced a measured alias-safety failure — a lightly-prompted agent incorrectly judging
a latent claimed path safe.** The benefit is largest for the weaker model and for
unprompted tasks, and it consistently produces correct *reasoning* (raw agents that get the
verdict right often do so by heuristic, not understanding). It adds nothing once the agent
is told the criterion, and capable models recover much (not all) of the gap on their own.

So the deployment guidance is concrete: **if the target is cheaper models acting with light
prompting, the tool earns its place; if the target is frontier models or carefully-prompted
workflows, this task does not justify it.**

## Caveats

- Cross-substrate and initial non-Claude breadth cells are n=3; those per-cell
  numbers are noisy. The headline stock Haven run is n=10 per arm.
- `reasoned` is a free-text substring heuristic (requires "disabl"/"latent"); it is a
  supporting metric — read the cited answers above, not the percentage alone.
- The non-admin latent claim was injected (disabled `files` view retargeted to
  `/research-library`); stock Drupal disabled views are admin-namespaced. The stock
  substrates carry the headline; the injection only isolates the admin-heuristic confound.
- Empire (`empire_devstability` in this workspace) is a valid but **minimal** install (4
  modules; `node` and `views` not enabled). It bootstraps fine. With no views and no node it
  has none of this task's collision phenomena — no view page paths, no disabled-view latent
  claims — so the alias-safety task has nothing to discriminate there (every candidate path
  is free; both arms trivially agree). It is a legitimate data point, not an untestable site.
  Note: the collector originally *threw* on it (it assumed the `view` entity type exists);
  that was a tooling bug, now fixed to degrade to an empty result. A collector that crashes
  on a valid minimal site is itself a readiness gap, and the same `hasDefinition` guard should
  be audited across the other collectors (e.g. `drupal_state_collector.php`).

## Next

1. ~~Raise n on the fully-blind cells~~ — done for stock Haven (n=10): haiku 80% vs 100%,
   opus 70% vs 100%. Raise n on core/Convivial too if a cross-substrate number is needed.
2. A second off-the-shelf (non-Claude) tool consumer to confirm the effect generalizes beyond
   the Claude family.
3. If publishing: lead with "live self-description reduced observed latent-path misses for
   lightly-prompted agents (and even careful ones can over-trust 'unrouted now = free')",
   citing the n=10 Haven figures (haiku 80% vs 100%, opus 70% vs 100% verdict) — not "site
   architecture helps agents" generally.
