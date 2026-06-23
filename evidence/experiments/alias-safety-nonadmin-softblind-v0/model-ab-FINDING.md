# Finding: alias-safety A/B across models (claude-haiku-4-5 vs claude-opus-4-8)

Latent-claim accuracy, n=3 per cell. **verdict** = flagged the latent path unsafe (the
actionable answer). **reasoned** (supporting metric, free-text heuristic) = the reason
explicitly recognized the path is declared by a *disabled* view.

Discriminating cases = disabled-view latent claims: `/research-library`, `/admin/content/media/scheduled`, `/admin/structure/taxonomy/scheduled`.

| Model | Condition | raw verdict | equip verdict | raw reasoned | equip reasoned | raw cmds | equip cmds |
| --- | --- | --- | --- | --- | --- | ---: | ---: |
| claude-haiku-4-5 | blind | 9/9 (100%) | 9/9 (100%) | 3/9 (33%) | 9/9 (100%) | 10.3 | 6.0 |
| claude-opus-4-8 | blind | 9/9 (100%) | 9/9 (100%) | 9/9 (100%) | 8/9 (89%) | 7.0 | 9.7 |

Per-run artifacts (answer.json, evaluator.json, meta.json), raw workflow output, ground
truth, and candidates are under this directory. Read the cross-substrate synthesis
(`../alias-safety-SYNTHESIS.md`) for the conclusion and cited example answers.

