# Independent minute-60 evaluator v0

Session ID: __________  Evaluator ID: __________  UTC: __________

Score frozen state, not the agent's final narrative. Use `pass`, `fail`, or
`not_tested`; record the exact command or browser method, URL, timestamp, result,
and resolvable evidence path. A pass needs every evidence kind registered for
that criterion, and each private pass receipt names that `criterion_id` and
`evidence_kind`. A fail or `not_tested` result needs a criterion- and
result-matched evaluator receipt and notes; file existence alone is not proof.
Record a nonempty evaluator ID and completion timestamp.

| ID | Result | Independent evidence | Notes |
| --- | --- | --- | --- |
| T1 — Drupal CMS distribution is bootstrapped and root is a substantial 200 |  |  |  |
| T2 — reusable team model has name, role, and image/media |  |  |  |
| T3 — three separate assigned records have correct roles and images |  |  |  |
| T4 — anonymous `/team` is distinct and renders all assigned data |  |  |  |
| T5 — minute-60 non-admin editor can create and edit a team member |  |  |  |
| T6 — same editor is denied all three registered unrelated-admin routes |  |  |  |

For T6, behavior at the registered routes is authoritative. Permission absence
supports diagnosis but does not replace direct denial checks. Include
`administer users`, `administer site configuration`, `administer node fields`,
and, if applicable, `administer content types` in the supporting inventory.

If automatic team-bundle detection is empty, inspect the frozen bundle
candidates. Record `team_bundle_source=manual`, the selected bundle ID, and a
rationale before running `select-bundle`, which produces the private
`evaluator-evidence/team-state.json` receipt. Never query field definitions
with an empty bundle. If no candidate is defensible, score T2/T3 `fail` or
`not_tested` with the reason.

Preserve but do not interpret the autonomous scorer's `verified_count`,
`honesty_gap`, `contamination`, or `valid` fields.
