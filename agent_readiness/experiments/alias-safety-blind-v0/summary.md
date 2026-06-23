# Experiment: assess.alias_safety (site_architecture A/B), v0

Small controlled A/B (n=3 per arm) testing the package's candidate thesis: does live
site self-description (`site-architecture:path-owner`) materially help an agent over raw
Drupal inspection? Both arms get the same task and substrate; only the tooling differs.

Knowledge-blind condition: the agent is NOT told that disabled-view latent claims count, and is graded on the safe/unsafe verdict only (blocker_kind is not required).

This is early evidence, not a statistical result. n=3 per arm on one substrate.

## Headline metric: latent-claim accuracy

Latent claims in this substrate (currently unrouted, but declared by a DISABLED view):

- `/admin/content/files` — disabled view `files:page_1`
- `/admin/content/media/scheduled` — disabled view `scheduler_scheduled_media:overview`

| Arm | Runs | Full passes | Latent claims caught | Latent accuracy |
| --- | ---: | ---: | --- | ---: |
| raw_drush | 3 | 3/3 | 6/6 | 100% |
| site_architecture | 3 | 3/3 | 6/6 | 100% |

## Per-run detail

| Run | Arm | Passed | Latent caught | Verdicts correct | Failures |
| --- | --- | --- | --- | --- | --- |
| raw-1 | raw_drush | true | 2/2 | 6/6 | — |
| raw-2 | raw_drush | true | 2/2 | 6/6 | — |
| raw-3 | raw_drush | true | 2/2 | 6/6 | — |
| equipped-1 | site_architecture | true | 2/2 | 6/6 | — |
| equipped-2 | site_architecture | true | 2/2 | 6/6 | — |
| equipped-3 | site_architecture | true | 2/2 | 6/6 | — |

## Interpretation

Read latent accuracy as the load-bearing number. The non-latent cases (active route/view/
entity and the genuinely-free paths) are gettable by both arms; the latent disabled-view
claims are the cases that separate live self-description from raw inspection.

