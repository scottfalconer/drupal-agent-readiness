# Finding: Basic Build Capability Did Not Separate The Selected First-Hour Cells (v0)

- Status: `exploratory_summary_only`
- Registered measurement-v1 experiment: no
- Claim-grade: false
- Frozen selected-run index:
  [`first-hour-selected-runs-v0.json`](first-hour-selected-runs-v0.json)

## TL;DR

In a selected four-platform by four-agent-stack matrix, all 16 valid selected cells
cleared five required mechanically checked rungs. **15 of 16** also
cleared the optional stretch. Valid single-run extensions on Wagtail, Joomla,
and Payload cleared the same required bar. The Strapi extension is excluded
because its sole selected run failed the contamination check.

Within this selected set, basic construction capability did not distinguish
the cells. “Capability is becoming table stakes” is a useful directional
interpretation of that bounded result. It is not evidence that the platforms
are generally equivalent, equally safe, equally maintainable, or equally fast.

## What Was Checked

Each task started in a fresh work directory and asked an autonomous agent to
build a small structured team site. Platform-specific instructions supplied
the required install and serving contract. An external scorer inspected the
running HTTP output plus platform configuration or database state; the agent's
own completion report was not accepted as proof.

The five required mechanically checked rungs were:

1. a reachable site;
2. a real team-member content model;
3. three team members;
4. a public `/team` page; and
5. a scoped editor role.

The optional stretch was scored separately. The selected-run index preserves
the exact rung keys used by the source scorer.

## Selected Primary Matrix

The numerator below is the number of selected cells that cleared the bar. It is
not a count of every run attempted in the source workspace.

The source work treated these cells as its completed four-by-four matrix. Each
cell below uses the named valid matrix run; infrastructure failures and runs
affected by known probe defects were excluded or rerun rather than counted as
platform outcomes. This index freezes that denominator but does not enumerate
every attempt.

| Platform | Selected agent stacks | Required five-rung bar | Optional stretch |
| --- | ---: | ---: | ---: |
| From-scratch framework | 4 | 4/4 | 3/4 |
| WordPress | 4 | 4/4 | 4/4 |
| Drupal core | 4 | 4/4 | 4/4 |
| Drupal CMS | 4 | 4/4 | 4/4 |
| **Selected matrix total** | **16** | **16/16** | **15/16** |

The four agent-stack labels identify two Codex configurations and two Claude
configurations. They are not pinned model-snapshot claims. Exact selected run
IDs and score-file hashes are in the
[`selected-run index`](first-hour-selected-runs-v0.json).

## Single-Run Extensions

| Platform | Selected run | Required five-rung bar | Optional stretch | Included? |
| --- | --- | ---: | ---: | --- |
| Wagtail | `wag-g55-1` | 5/5 | yes | Yes; exploratory `n=1` extension |
| Joomla | `joo-g55-1` | 5/5 | yes | Yes; exploratory `n=1` extension |
| Payload | `pay-g55-1` | 5/5 | no | Yes; exploratory `n=1` extension |
| Strapi | `str-g55-1` | 5/5 observed | no | **No; invalid because strong contamination was detected** |

This is why the safe summary names the three valid extensions rather than
saying that every platform attempted passed.

## What The Drupal Cells Support

All eight selected Drupal cells cleared the mechanically checked content-model
and scoped-editor rungs. That supports the narrower observation that the agents
used Drupal's structured content and permission system instead of satisfying
the task with only a static lookalike.

It does not support saying that each run used every possible native surface.
In particular, this summary does not claim that every selected Drupal run used
Views, exported configuration, moderation, or the same implementation path.

## Evidence Boundary

The source workspace retains prompts, runner output, HTTP captures, answers,
and scoring files. Those per-run artifacts are not included in this repository.
The public index freezes the selected denominator and records SHA-256 hashes of
the source `score.json` files, but a hash without the corresponding artifact is
a provenance pointer, not independent reproducibility.

This summary is therefore not a registered measurement-v1 experiment and is
not claim-grade. It supports review of the construct, selected denominator, and
bounded interpretation while a privacy-reviewed, allowlisted run package is
prepared. Raw run directories must not be copied wholesale because they also
contain local runner credentials, caches, and state unrelated to the evidence.

The result does not establish:

- a statistically powered cross-platform comparison;
- a platform or model leaderboard;
- equal setup cost, speed, security, maintainability, or handoff quality;
- general success outside this task and selected run set; or
- improvement caused by a change to Drupal.

Timing and downstream handoff are intentionally outside this public finding.
They require their own frozen denominators and evidence packages.
