# Task: assess.alias_safety.fully_blind (prompt v0.2)

You are assessing a running Drupal site. Do not modify the site or repository.
Inspection commands that write normal Drupal cache data are acceptable on the
disposable cloned run site.

## Goal

For each candidate path below, decide whether it is **safe** to claim with a new
node's URL alias, or whether that path is already claimed by something on the
site.

If a path is not safe, say what claims it. Resolve this against the **live
site**, not source files or assumptions.

## Candidate paths

Read the candidate paths from `assess.alias_safety.candidates.public.json`.
That file contains only paths. Do not use evaluator files, answer fixtures,
experiment result files, or files under `agent_readiness/experiments/` to infer
the expected answer.

## Produce answer.json with this shape

```json
{
  "assessments": {
    "/example-path": {"safe": "<bool>", "reason": "<short reason>"}
  },
  "command_count": "<integer>"
}
```

Record a transcript or command log beside `answer.json` showing the commands you
ran and what each candidate resolved to.
