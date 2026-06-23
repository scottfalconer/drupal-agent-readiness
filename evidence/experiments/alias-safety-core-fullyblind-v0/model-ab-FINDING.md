# Finding: alias-safety A/B across models (claude-haiku-4-5 vs claude-opus-4-8)

Latent-claim accuracy, n=3 per cell. **verdict** = flagged the latent path unsafe (the
actionable answer). **reasoned** (supporting metric, free-text heuristic) = the reason
explicitly recognized the path is declared by a *disabled* view.

Discriminating cases = disabled-view latent claims: `/admin/content/files`, `/admin/content/media/scheduled`, `/admin/structure/taxonomy/scheduled`.

| Model | Condition | raw verdict | equip verdict | raw reasoned | equip reasoned | raw cmds | equip cmds |
| --- | --- | --- | --- | --- | --- | ---: | ---: |
| claude-haiku-4-5 | blind | 6/9 (67%) | 9/9 (100%) | 0/9 (0%) | 9/9 (100%) | 5.7 | 6.3 |
| claude-opus-4-8 | blind | 9/9 (100%) | 9/9 (100%) | 9/9 (100%) | 9/9 (100%) | 5.3 | 8.3 |

Per-run artifacts (answer.json, evaluator.json, meta.json), raw workflow output, ground
truth, and candidates are under this directory. Read the cross-substrate synthesis
(`../alias-safety-SYNTHESIS.md`) for the conclusion and cited example answers.

