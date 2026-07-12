# External evaluation reference registry

This directory is a community-editable index of relevant Drupal agent-evaluation work. Each JSON file describes one upstream source and points to concrete task suites, cases, datasets, graders, workflows, or substrates.

It is intentionally not a plugin registry. Merging a pointer means only that the source is relevant enough to discover. The registry never fetches or runs upstream code, accepts credentials, imports source-reported results as evidence, changes lifecycle coverage, or makes anything eligible for the Agent Readiness Scorecard.

This is Agent Readiness consumer-side curation. It is not an umbrella evaluation program, shared execution service, or standards body, and is intended to complement Eval Commons and upstream projects rather than replace them.

## Add or update a source

1. Add one file named for the source ID, such as `example-project.json`.
2. Validate it against `method/schema/eval-reference-v1.schema.json`.
3. Point each artifact at a concrete upstream object, not only a project homepage when a suite, file, work item, or merge request exists.
4. Set `mapping_scope` to `task_candidate` only for a concrete task-like artifact, then map it to lifecycle stages and candidate task families. Use `supporting_infrastructure` with empty mapping arrays for frameworks, contracts, graders, result formats, and substrates.
5. State what the artifact actually helps answer and the strongest claim it cannot support.
6. Record whether the pointer is immutable. Branches, project pages, work items, and merge requests are mutable.
7. Regenerate `docs/eval-landscape.json` and `docs/eval-landscape.md`.

Commit revisions must use a full 40-character lowercase Git hash. A repository, tree, or file pointer pinned to a commit must also include that hash as a URL path segment, for example `/-/tree/{commit}/path` or `/-/blob/{commit}/path`.

Run the focused check from the repository root:

```bash
python3 -m agent_readiness.scripts.build_eval_landscape --check
```

To regenerate after editing a source:

```bash
python3 -m agent_readiness.scripts.build_eval_landscape
```

## Maintainer review

A reference belongs here only when it supplies a concrete task, evaluator, dataset, workflow, or substrate relevant to agent performance with Drupal. Maintainers decide the local disposition; upstream projects cannot self-declare themselves validated, adopted, trusted, or scorecard-eligible.

A plan-only source may be retained once for discovery, but a `benchmark_plan` must remain `supporting_infrastructure` with disposition `reference_only`; it must not populate lifecycle or task-family views. Add a task candidate only when upstream supplies a concrete suite, case, dataset, grader, workflow, substrate, work item, or implementation merge request.

A source may retain at most one `benchmark_plan`. A task candidate must report an evaluator type and identify concrete inputs, observable completion criteria, and a plausible local oracle in its upstream artifact or mapping note. Otherwise retain it as supporting infrastructure without lifecycle or task-family mappings.

Records are closed metadata objects. Fields for commands, scripts, installation, credentials, secrets, tokens, or executable integration are prohibited. URLs must be credential-free HTTPS pointers.

The validator and generator use only the Python standard library. They do not require site packages or contact any listed URL.

Contributor-controlled names and prose are escaped when Markdown is generated. Keep text concise and do not rely on embedded Markdown or HTML for presentation.

## Operating bounds

This lane is judged by documented conversions, not inventory size. A conversion means that a listed reference informed a separately governed Agent Readiness task, evaluator, or coverage decision, or led to an accepted upstream task, evaluator, or harness change. Registry entries never change coverage themselves. Adding a pointer, running a diagnostic, filing an issue, or receiving a comment is not a conversion by itself.

As of 2026-07-12, no conversion is recorded. The retained diagnostics are findings awaiting downstream disposition.

Routine registry triage and curation is capped at one maintainer-hour per week and must not displace committed Agent Readiness measurement or publication work. Selected reproductions are separately scoped work.

Before starting a selected reproduction, name the specific Agent Readiness task or evaluator decision, or the upstream reproduction target, that the run could change. Also name the stop condition. A general-interest run without a decision target does not belong in this lane.

Review this lane on 2026-10-15. If no conversion has been recorded, stop soliciting entries and retain the registry as a read-only archive until a concrete planned use reopens it.

## From pointer to evidence

Local evidence is a separate contribution. A maintainer must explicitly select the reference, inspect and pin the upstream revision, adapt or reproduce it on a controlled substrate, retain the prompts/state/logs/evaluator output, and pass the trusted external-evidence checks. That diagnostic still has no scorecard or coverage effect. Affecting an Agent Readiness finding or coverage status requires a separate local task or measurement package that passes the normal publication gates.
