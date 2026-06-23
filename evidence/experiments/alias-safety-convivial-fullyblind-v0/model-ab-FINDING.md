# Finding: alias-safety A/B across models (claude-haiku-4-5 vs claude-opus-4-8)

Latent-claim accuracy, n=3 per cell. **verdict** = flagged the latent path unsafe (the
actionable answer). **reasoned** (supporting metric, free-text heuristic) = the reason
explicitly recognized the path is declared by a *disabled* view.

Discriminating cases = disabled-view latent claims: `/admin/content/media/scheduled`, `/admin/structure/taxonomy/scheduled`.

| Model | Condition | raw verdict | equip verdict | raw reasoned | equip reasoned | raw cmds | equip cmds |
| --- | --- | --- | --- | --- | --- | ---: | ---: |
| claude-haiku-4-5 | blind | 6/6 (100%) | 6/6 (100%) | 0/6 (0%) | 6/6 (100%) | 6.7 | 5.0 |
| claude-opus-4-8 | blind | 4/6 (67%) | 6/6 (100%) | 4/6 (67%) | 6/6 (100%) | 5.3 | 7.3 |

Per-run artifacts (answer.json, evaluator.json, meta.json), raw workflow output, ground
truth, and candidates are under this directory. Read the cross-substrate synthesis
(`../alias-safety-SYNTHESIS.md`) for the conclusion and cited example answers.

