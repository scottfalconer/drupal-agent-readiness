# Finding: alias-safety A/B across models

Models: gpt-5.5-codex.

Latent-claim accuracy. **n** is runs per arm. **verdict** = flagged the latent path unsafe (the
actionable answer). **reasoned** (supporting metric, free-text heuristic) = the reason
explicitly recognized the path is declared by a *disabled* view.

Discriminating cases = disabled-view latent claims: `/admin/content/files`, `/admin/content/media/scheduled`.

| Model | Condition | raw n | equip n | raw verdict | equip verdict | raw reasoned | equip reasoned | raw cmds | equip cmds |
| --- | --- | ---: | ---: | --- | --- | --- | --- | ---: | ---: |
| gpt-5.5-codex | blind | 3 | 3 | 0/6 (0%) | 6/6 (100%) | 0/6 (0%) | 6/6 (100%) | 1.3 | 6.0 |

Per-run artifacts (answer.json, evaluator.json, meta.json), raw workflow output, ground
truth, and candidates are under this directory. Read the cross-substrate synthesis
(`../alias-safety-SYNTHESIS.md`) for the conclusion and cited example answers.

