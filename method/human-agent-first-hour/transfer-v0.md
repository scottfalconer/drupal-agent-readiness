# Unaided editor transfer v0

Session ID: __________  Evaluator: __________  UTC started: __________

Before starting, determine whether a usable minute-60 editor account,
credentials, and required team-member editing capability exist.

- `transfer_precondition`: `eligible` | `blocked_by_build` | `not_run`
- Build-precondition evidence: ____________________________________________

If eligible, hide the coding agent and give the participant `taylor.jpg`:

> Add Taylor Morgan, Volunteer Coordinator, using `taylor.jpg`. Make Taylor
> appear on `/team`. You have 10 minutes. Use only the browser and the staff
> editor account.

- `transfer_outcome`: `success` | `login_failure` | `navigation_failure` |
  `workflow_failure` | `listing_failure` | `timeout` | `assisted`
- `assistance`: `none` | `facilitator_hint` | `admin_fallback` | `agent` | `cli`
- Elapsed seconds: __________
- Evidence: _______________________________________________________________

Record a private transfer receipt with `result`, `observed_at`, and `method`.
The result must match the transfer outcome, or the precondition when ineligible.
An eligible attempt must end within 600 seconds. `blocked_by_build` and
`not_run` retain null outcome/assistance/elapsed values plus evidence and notes.

`blocked_by_build` is a build outcome, not a navigation failure. Use
`navigation_failure` only when a valid account and capability exist, login
succeeds, and the participant cannot locate the editing surface. Reclassify
after the evaluator establishes the minute-60 capability.
