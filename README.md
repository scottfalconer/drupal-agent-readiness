# Drupal Agent Readiness

Drupal Agent Readiness is a public test bench for AI agents that operate Drupal
sites. It provides tasks, test tools, retained evidence, and rules for reporting
results. Developers can use this evidence to identify Drupal problems and design
tests for proposed fixes.

The current package supports one historical path-safety observation. Neither
registered experiment meets the full measurement contract (`claim_grade: false`).
The package does not establish an overall Drupal readiness score.

This repository contains the public `State of Agents in Drupal` v0 package and
tools for future studies.

## Start Here

| Your task | Start with |
| --- | --- |
| Understand the finding | [Path-safety finding](docs/finding-site-self-description-v0.md) |
| Review the project purpose | [Why this bench exists](docs/why-this-bench.md) |
| Check the supported claims | [Claims ledger](docs/claims-ledger.md) and [review status](REVIEW-READINESS.md) |
| Check the local package | [Run local checks](#run-local-checks) |
| Run a new alias-safety experiment | [Harness guide](method/HARNESS.md) |
| Prepare a human-agent study | [First-hour protocol](method/human-agent-first-hour-experience-v0.md) and [study kit](method/human-agent-first-hour/README.md) |
| Review the measurement design | [Measurement v1 guide](method/MEASUREMENT-V1.md) |
| Review related projects | [Evaluation landscape](docs/eval-landscape.md) and [external evaluation records](docs/external-eval-results.md) |
| Contribute a change | [Contributor guide](CONTRIBUTING.md) |
| Prepare a release | [Publishing checklist](method/PUBLISHING.md) |

An **evaluator** checks a result against a task's rules. A **harness** prepares
and runs an experiment. A **fixture** is a test component or sample input.
**Claim-grade** evidence meets the measurement contract for a named experiment.

## Run Local Checks

Use Git and Python 3.12. Continuous integration (CI) uses Python 3.12.
Older Python versions are not supported.

1. Clone the repository.

   ```bash
   git clone https://github.com/scottfalconer/drupal-agent-readiness.git
   ```

2. Open the repository directory.

   ```bash
   cd drupal-agent-readiness
   ```

3. Check the Python version.

   ```bash
   python3 --version
   ```

4. Run the unit tests.

   ```bash
   python3 -B -m unittest discover -s agent_readiness/tests -v
   ```

These tests check code and stored evidence. They do not run a new agent
experiment. Live experiments require the environment and setup specified in
the applicable study guide.

The [contributor guide](CONTRIBUTING.md) explains further local checks. The
[publishing checklist](method/PUBLISHING.md) includes the complete release
checks, file hashes, and clean-checkout audit.

## The v0 Finding

The first task asks whether an agent can safely select a URL alias for a new
Drupal content item. A **URL alias** is an alternate path for content.

A path can appear unused while site configuration still claims it. For example,
a disabled **View**, a Drupal content listing, can declare a path. The View can
use that path again when an administrator enables it. A check of the current
HTTP response can miss this conflict.

The experiment used stock Drupal CMS with the Haven test profile. Agents
classified candidate paths in two conditions:

- Drush only. Drush is Drupal's command-line tool.
- Drush with a prompt that named the `site-architecture:path-owner` helper.
  The helper reports path ownership and gives a safety verdict.

Retained judgments differed between these conditions. The experiment combined
the helper and prompt guidance. It did not isolate discovery, installation,
facts-only output, advice, or an actual write.

The hidden paths were under `/admin`. An agent could reject those paths by
convention without finding the disabled View. The evaluator records both the
safety verdict and the stated reason.

The historical Claude runs provide the main observation. The Codex runs provide
limited additional evidence. Neither set supports general claims about a model
provider. The unit of analysis is a run. Judgments within one run are related.

The [generated experiment results](docs/experiments-v1.json) contain the exact
counts, denominators, evidence classes, and source hashes. Retained artifacts
permit review and repeat scoring. Missing prompt, harness, starting-site, model,
and budget records prevent exact historical replication.

The registry therefore labels this observation `frontier_observation`,
`exploratory_legacy_unpinned`, and `claim_grade: false`.

## Where This Fits In The Ecosystem

This bench tests bounded work by external agents on Drupal sites. It aims to
connect an observed failure to a Drupal change and a controlled repeat test.

The table provides maintainer-curated orientation. Project names and descriptions
come from the checked-in reference registry. The generated
[evaluation landscape](docs/eval-landscape.md) contains the archived source
records and review dates.

| Project | What it is | Use in this bench |
| --- | --- | --- |
| [AI Best Practices for Drupal](https://www.drupal.org/project/ai_best_practices) | Drupal-specific guidance and behavioral evaluation cases for external coding agents. | Candidate tasks and skill comparisons. One local diagnostic is retained. |
| [AI Eval](https://www.drupal.org/project/ai_eval) | A Drupal evaluation framework with versioned dataset, rubric, judge, deterministic-grader, and result-contract implementations. | Candidate evaluation tools and result formats. |
| [AI Agents Test and DrupalForge testing template](https://www.drupal.org/project/ai_agents_test) | Drupal-native agent tool-behavior test suites plus a hosted Drupal CMS template that runs them on a site. | Candidate test sites and methods. Drupal-native agents require a separate study from external coding agents. |
| [AI Ongoing Evaluations](https://www.drupal.org/project/ai_evaluations) | A Drupal-native framework for capturing human feedback, comparing AI outputs, and importing or exporting evaluation records. | Candidate human-feedback data and comparison methods. |
| [AI Bench](https://www.drupal.org/project/ai_bench) | A proposed public program for Drupal-specific model and agent benchmark tasks and community-submitted runs. | A reference for future tasks and evaluators. |
| [AI Maintenance Skills](https://www.drupal.org/project/ai_maintenance_skills) | Drupal.org issue-triage and maintenance workflows for coding agents within a constrained DDEV design. | Candidate maintenance workflows for a separately defined local task. |

References support discovery. They do not establish endorsement, task coverage,
or a score. [External evaluation records](docs/external-eval-results.md) remain
separate from the scorecard. The [reference guide](method/eval-references/README.md)
defines how to maintain this inventory.

## Current Status

| Area | Available evidence | Limit |
| --- | --- | --- |
| Alias safety | Historical judgments and evaluator outputs | Exploratory observation; incomplete records prevent exact replication. |
| Intent preservation | A retained summary with no observed preservation difference | Does not establish general intent value or conflict handling. |
| Inventory, Event creation, and recovery | Legacy run packages and evaluator examples | Useful for package checks; insufficient for independent performance or improvement claims. |
| Frontier canary | Tested runner for a task with no tools | No public canary run. The task interprets an inline site snapshot; it does not operate Drupal. |
| Human-agent first-hour study | Protocol, forms, runner, and an excluded technical rehearsal record | Requires an external harness and isolated facilitator storage. No participant results are included. |
| Measurement v1 | Schemas, audit tools, and registration rules | No reportable fixed-regression result. |
| Improvement decisions | One proposed action with status `pending_registration` | No completed improvement decision. |

The **frontier canary** checks runner behavior, evidence handling, and scoring
for an inline snapshot. Its containment requires a pinned macOS environment
that blocks child processes. It does not establish hosted-model identity or
virtual-machine isolation.

## Tasks And Files

The [task definitions](method/tasks.yml) specify these current tasks:

| Task | Required behavior |
| --- | --- |
| `inventory.read_only` | Discover live site state without changes. |
| `act.event_jsonapi` | Create a minimal Event content type, fields, and sample content. Verify access through Drupal's JSON:API interface. |
| `recover.event_jsonapi` | Remove or restore the Event work. Check for remaining resources and unrelated changes. |
| `assess.alias_safety` | Classify candidate paths from a path-only list. Identify the owner of each unsafe path. |

The fuller editorial Events task remains future work.

| Path | Purpose |
| --- | --- |
| [`agent_readiness/`](agent_readiness/README.md) | Active Python source, evaluators, scripts, tests, prompts, and fixtures. Make behavior changes here. |
| [`docs/`](docs/) | Public findings, claim limits, generated results, and scorecard files. |
| [`method/`](method/) | Study protocols, task definitions, prompts, schemas, and publishing instructions. |
| [`evidence/experiments/`](evidence/experiments/) | Historical experiment packages with source hashes. |
| [`evidence/runs/`](evidence/runs/) | Retained Inventory, Event, and recovery run packages. |
| [`repro/`](repro/README.md) | Frozen historical v0 source for evidence review. It does not track current implementation changes. |
| [`agent_readiness/fixtures/site_architecture_module/`](agent_readiness/fixtures/site_architecture_module/) | Internal Drupal fixture for disposable test sites. It is not a supported public module. |

## Evidence Rules

Passing package checks confirms package integrity only. It does not establish
measurement validity or Drupal readiness. A test result applies to its stated
task, starting site, agent configuration, and evaluation rules.

A stronger claim requires the exact prompt, model, harness, tools, task version,
starting-site hash, evaluator, rubric, budget, and scoring rules. Missing records
require exploratory language, even when retained answers receive the same score
again.

The [Measurement v1 guide](method/MEASUREMENT-V1.md) defines the required evidence
and separate reporting gates. The
[experiment schema](agent_readiness/schema/benchmark-experiment-v1.schema.json)
and [run schema](agent_readiness/schema/benchmark-run-v1.schema.json) define the
machine-readable contracts.

The [coverage registry](method/benchmark-coverage-v1.json) separates existing
evidence from target designs. Planning and clarification, and handoff to another
agent, remain `not_covered`. The [task-family registry](method/task-families-v1.json)
defines target tasks for clean and messy sites.

The [improvement registry](method/improvement-registry-v1.json) requires an owner,
an upstream issue, a fixed study design, complete reruns, and a recorded decision.
A statistical `registered_effect_rule_met` result alone cannot establish
`improvement_ready`.

## Contribute

Useful contributions include a task, a difficult starting site, an evaluator
fix, a controlled rerun, or evidence that a published claim is too broad.

1. Identify the task or claim that needs work.
2. Describe the expected result.
3. Include the relevant files, commands, or retained evidence.
4. State any missing evidence or setup requirements.

An evaluator implements a specific task contract. An incorrect evaluation rule
is a task defect. It is not evidence of an agent failure.

The next measurement priority is a complete fixed-regression study. This study
must hold the agent configuration constant while testing a Drupal change.
Further priorities include repeated write and recovery tasks, measured token
cost, more starting sites, and richer editorial tasks.

## License

Original project work uses the [MIT license](LICENSE). Third-party evaluation
artifacts retain their upstream licenses. [Third-party notices](THIRD_PARTY_NOTICES.md)
and [REUSE.toml](REUSE.toml) identify the applicable files and license texts.
