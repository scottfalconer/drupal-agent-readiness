# Finding: alias-safety A/B across models (claude-haiku-4-5 vs claude-opus-4-8)

Latent-claim accuracy. **n** is runs per arm. **verdict** = flagged the latent path unsafe (the
actionable answer). **reasoned** (supporting metric, free-text heuristic) = the reason
explicitly recognized the path is declared by a *disabled* view.

Discriminating cases = disabled-view latent claims: `/admin/content/files`, `/admin/content/media/scheduled`.

| Model | Condition | raw n | equip n | raw verdict | equip verdict | raw reasoned | equip reasoned | raw cmds | equip cmds |
| --- | --- | ---: | ---: | --- | --- | --- | --- | ---: | ---: |
| claude-haiku-4-5 | blind | 10 | 10 | 16/20 (80%) | 20/20 (100%) | 0/20 (0%) | 20/20 (100%) | 9.7 | 6.1 |
| claude-opus-4-8 | blind | 10 | 10 | 14/20 (70%) | 20/20 (100%) | 14/20 (70%) | 20/20 (100%) | 5.9 | 8.6 |

Per-run artifacts (answer.json, evaluator.json, meta.json), raw workflow output, ground
truth, and candidates are under this directory. Read the cross-substrate synthesis
(`../alias-safety-SYNTHESIS.md`) for the conclusion and cited example answers.
