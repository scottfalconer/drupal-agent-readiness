# External Drupal Agent Eval Landscape

This generated discovery index contains 6 sources and 9 indexed artifact pointers: 2 task candidates and 7 supporting-infrastructure references.

> Discovery only. Listing a source does not trust, fetch, run, validate, endorse, or import it. It has no effect on Agent Readiness claims, lifecycle coverage, results, or scorecard eligibility.

This is consumer-side curation for Agent Readiness, intended to complement Eval Commons and upstream projects rather than act as a competing umbrella.

Inventory counts describe scope, not success. Success is a documented downstream conversion; listing and running alone are not conversions.

## Operating bounds

- Recorded conversions: 0
- Routine curation cap: 1 maintainer-hour per week
- Intake state: Open Pending Review
- Review date: 2026-10-15; if no conversion is recorded, freeze new intake and retain the registry as a read-only archive
- Plan-only pointer ratio: 1/9

## How this becomes evidence

A maintainer may select a pointer, inspect and pin it, adapt or reproduce it on a controlled substrate, retain the local run evidence, and pass the normal Agent Readiness publication gates. Until that separate work happens, the entry remains only a reference.

The generator performs no network access. It reads only the checked-in metadata files under `method/eval-references/`.

## Lifecycle view

| Lifecycle stage | Indexed references |
| --- | --- |
| Choose Onboard | None indexed |
| Connect | None indexed |
| Understand | [AI Agents Test and DrupalForge testing template: Drupal CMS agent tool-behavior YAML suites](<https://git.drupalcode.org/project/ai_agents_test/-/tree/e06f11c33c2fda6beb09008e60bf8a65804a132c/examples/drupal_cms>)<br>[AI Best Practices for Drupal: Drupal skill evaluation cases](<https://git.drupalcode.org/project/ai_best_practices/-/tree/1.0.x/evals>) |
| Plan Clarify | [AI Agents Test and DrupalForge testing template: Drupal CMS agent tool-behavior YAML suites](<https://git.drupalcode.org/project/ai_agents_test/-/tree/e06f11c33c2fda6beb09008e60bf8a65804a132c/examples/drupal_cms>)<br>[AI Best Practices for Drupal: Drupal skill evaluation cases](<https://git.drupalcode.org/project/ai_best_practices/-/tree/1.0.x/evals>) |
| Act | [AI Agents Test and DrupalForge testing template: Drupal CMS agent tool-behavior YAML suites](<https://git.drupalcode.org/project/ai_agents_test/-/tree/e06f11c33c2fda6beb09008e60bf8a65804a132c/examples/drupal_cms>)<br>[AI Best Practices for Drupal: Drupal skill evaluation cases](<https://git.drupalcode.org/project/ai_best_practices/-/tree/1.0.x/evals>) |
| Verify | [AI Best Practices for Drupal: Drupal skill evaluation cases](<https://git.drupalcode.org/project/ai_best_practices/-/tree/1.0.x/evals>) |
| Recover | None indexed |
| Handoff | None indexed |

## Candidate task-family view

These mappings identify candidates to inspect. They do not make a task family covered.

| Task family | Indexed references |
| --- | --- |
| Supported Cold Start | None indexed |
| Governed Editorial Change | [AI Agents Test and DrupalForge testing template: Drupal CMS agent tool-behavior YAML suites](<https://git.drupalcode.org/project/ai_agents_test/-/tree/e06f11c33c2fda6beb09008e60bf8a65804a132c/examples/drupal_cms>)<br>[AI Best Practices for Drupal: Drupal skill evaluation cases](<https://git.drupalcode.org/project/ai_best_practices/-/tree/1.0.x/evals>) |
| Diagnosis And Rollback | [AI Best Practices for Drupal: Drupal skill evaluation cases](<https://git.drupalcode.org/project/ai_best_practices/-/tree/1.0.x/evals>) |

## Sources

### AI Agents Test and DrupalForge testing template

Drupal-native agent tool-behavior test suites plus a hosted Drupal CMS template that runs them on a site.

- Source: [https://www.drupal.org/project/ai\_agents\_test](<https://www.drupal.org/project/ai_agents_test>)
- Last reviewed: 2026-07-11
- Roles: Task Source, Workflow Source, Substrate Source
- Registry effect: reference only; no claim or coverage effect

#### [Drupal CMS agent tool-behavior YAML suites](<https://git.drupalcode.org/project/ai_agents_test/-/tree/e06f11c33c2fda6beb09008e60bf8a65804a132c/examples/drupal_cms>)

- Kind: Task Suite
- Mapping scope: Task Candidate
- Agent classes: Drupal Native Agent
- Substrate fidelity: Drupal Runtime
- Evaluator types: Deterministic, Llm Judge
- Question: Does a Drupal-native agent select the expected tools, avoid forbidden tools, respect tool order, and pass parameter checks for the supplied prompts?
- Lifecycle: Understand, Plan Clarify, Act
- Candidate families: Governed Editorial Change
- Local disposition: Candidate For Local Adaptation
- Upstream revision: Commit e06f11c33c2fda6beb09008e60bf8a65804a132c (immutable)
- Mapping note: Most rules deterministically inspect tool presence, absence, order, and parameters; optional rules can ask an LLM to score a tool parameter or text response. Drupal-native agents must remain a separate class from external coding agents.
- Claim boundary: The shipped rules do not independently inspect final Drupal state, so a passing suite does not prove that the requested content or configuration outcome actually exists.

#### [Hosted Drupal CMS AI Agents Testing Framework](<https://www.drupalforge.org/template/drupal-cms-ai-agents-testing-framework>)

- Kind: Runtime Substrate
- Mapping scope: Supporting Infrastructure
- Agent classes: Drupal Native Agent
- Substrate fidelity: Hosted Drupal Runtime
- Evaluator types: Deterministic, Llm Judge
- Question: Can the Drupal-native agent tool-behavior suites be exercised on a real hosted Drupal CMS runtime with inspectable run results?
- Lifecycle: None (supporting infrastructure)
- Candidate families: None (supporting infrastructure)
- Local disposition: Candidate For Substrate Reuse
- Upstream revision: Unversioned hosted-template-reviewed-2026-07-11 (mutable pointer)
- Mapping note: The hosted page is substrate prior art, not a task mapping; it states that tests mutate actual content and are not easily rerun without reset or cleanup.
- Claim boundary: A convenient hosted template is not a pinned, reset-proven evaluation substrate and does not make its displayed results comparable to local Agent Readiness runs.

### AI Bench

A proposed public program for Drupal-specific model and agent benchmark tasks and community-submitted runs.

- Source: [https://www.drupal.org/project/ai\_bench](<https://www.drupal.org/project/ai_bench>)
- Last reviewed: 2026-07-11
- Roles: Benchmark Program
- Registry effect: reference only; no claim or coverage effect

#### [Drupal model and agent benchmark program plan](<https://www.drupal.org/project/ai_bench>)

- Kind: Benchmark Plan
- Mapping scope: Supporting Infrastructure
- Agent classes: External Coding Agent, Browser Agent, Drupal Native Agent, Model Only
- Substrate fidelity: Not Reported
- Evaluator types: Not Reported
- Question: Which proposed Drupal benchmark directions should be monitored for concrete, locally adaptable task and evaluator artifacts?
- Lifecycle: None (supporting infrastructure)
- Candidate families: None (supporting infrastructure)
- Local disposition: Reference Only
- Upstream revision: Unversioned project-plan-reviewed-2026-07-11 (mutable pointer)
- Mapping note: The project proposes issue resolution, tool and MCP use, code-audit score deltas, translation, and community-submitted runs. Promote each direction separately only when a concrete suite, case, dataset, grader, workflow, substrate, work item, or implementation merge request exists.
- Claim boundary: This project page records benchmark intentions, not an available task package, evaluator, retained result, or Agent Readiness coverage candidate.

### AI Best Practices for Drupal

Drupal-specific guidance and behavioral evaluation cases for external coding agents.

- Source: [https://www.drupal.org/project/ai\_best\_practices](<https://www.drupal.org/project/ai_best_practices>)
- Last reviewed: 2026-07-11
- Roles: Task Source, Grader Source
- Registry effect: reference only; no claim or coverage effect

#### [Drupal skill evaluation cases](<https://git.drupalcode.org/project/ai_best_practices/-/tree/1.0.x/evals>)

- Kind: Task Suite
- Mapping scope: Task Candidate
- Agent classes: External Coding Agent
- Substrate fidelity: Prompt Only
- Evaluator types: Deterministic
- Question: Does Drupal-specific guidance improve an external coding agent's behavior on bounded Drupal development tasks?
- Lifecycle: Understand, Plan Clarify, Act, Verify
- Candidate families: Governed Editorial Change, Diagnosis And Rollback
- Local disposition: Candidate For Local Adaptation
- Upstream revision: Branch 1.0.x (mutable pointer)
- Mapping note: The cases are candidates for skill versus no-skill treatments on a locally controlled Drupal substrate.
- Claim boundary: The upstream cases do not by themselves show successful work against a real Drupal runtime or establish that Drupal improved.

#### [Inspect AI runner migration](<https://git.drupalcode.org/project/ai_best_practices/-/merge_requests/69>)

- Kind: Evaluation Framework
- Mapping scope: Supporting Infrastructure
- Agent classes: Not Agent Specific
- Substrate fidelity: None
- Evaluator types: Not Reported
- Question: How can the Drupal skill cases be expressed in a reusable runner rather than a project-specific evaluation loop?
- Lifecycle: None (supporting infrastructure)
- Candidate families: None (supporting infrastructure)
- Local disposition: Reference Only
- Upstream revision: Unversioned merge-request-69 (mutable pointer)
- Mapping note: Runner convergence can lower adaptation cost but does not map to a lifecycle stage or task family until a concrete task uses it.
- Claim boundary: Adopting the same runner improves interoperability only; it supplies no agent-performance result and has no scorecard effect.

### AI Eval

A Drupal evaluation framework with versioned dataset, rubric, judge, deterministic-grader, and result-contract implementations.

- Source: [https://www.drupal.org/project/ai\_eval](<https://www.drupal.org/project/ai_eval>)
- Last reviewed: 2026-07-11
- Roles: Grader Source, Dataset Source
- Registry effect: reference only; no claim or coverage effect

#### [Shipped dataset, rubric, and judge schemas](<https://git.drupalcode.org/project/ai_eval/-/tree/97d8660b3cb3815572e7ddd9e3898b53f4c81e84/schema>)

- Kind: Grader Contract
- Mapping scope: Supporting Infrastructure
- Agent classes: Not Agent Specific
- Substrate fidelity: None
- Evaluator types: Deterministic, Human Label, Llm Judge
- Question: Which portable case, rubric, and calibrated-judge contracts can describe and score agent evaluations consistently?
- Lifecycle: None (supporting infrastructure)
- Candidate families: None (supporting infrastructure)
- Local disposition: Candidate For Evaluator Reuse
- Upstream revision: Commit 97d8660b3cb3815572e7ddd9e3898b53f4c81e84 (immutable)
- Mapping note: These are cross-cutting contracts and therefore do not map to lifecycle stages or task families on their own.
- Claim boundary: A schema or calibrated judge is evaluation infrastructure, not evidence that any agent completed a Drupal task successfully.

#### [Shipped deterministic grader implementations](<https://git.drupalcode.org/project/ai_eval/-/tree/97d8660b3cb3815572e7ddd9e3898b53f4c81e84/src/Plugin/AiEvalGrader>)

- Kind: Grader Contract
- Mapping scope: Supporting Infrastructure
- Agent classes: Not Agent Specific
- Substrate fidelity: Not Reported
- Evaluator types: Deterministic
- Question: Which shipped graders can deterministically validate response format and expected-versus-forbidden tool usage without another LLM call?
- Lifecycle: None (supporting infrastructure)
- Candidate families: None (supporting infrastructure)
- Local disposition: Candidate For Evaluator Reuse
- Upstream revision: Commit 97d8660b3cb3815572e7ddd9e3898b53f4c81e84 (immutable)
- Mapping note: The pinned implementation includes deterministic format and tool-usage graders; a concrete local task must still define the relevant lifecycle, oracle, and anti-gaming guards.
- Claim boundary: Shipped grader code is reusable infrastructure, not evidence that a Drupal task was executed, correctly scoped, or validly scored.

### AI Ongoing Evaluations

A Drupal-native framework for capturing human feedback, comparing AI outputs, and importing or exporting evaluation records.

- Source: [https://www.drupal.org/project/ai\_evaluations](<https://www.drupal.org/project/ai_evaluations>)
- Last reviewed: 2026-07-11
- Roles: Dataset Source
- Registry effect: reference only; no claim or coverage effect

#### [Human feedback capture and comparison framework](<https://www.drupal.org/project/ai_evaluations/releases/0.1.0>)

- Kind: Evaluation Framework
- Mapping scope: Supporting Infrastructure
- Agent classes: Not Agent Specific
- Substrate fidelity: Drupal Runtime
- Evaluator types: Human Label
- Question: How can a Drupal site capture human votes or comparisons with prompt and model context, then import or export those evaluation records?
- Lifecycle: None (supporting infrastructure)
- Candidate families: None (supporting infrastructure)
- Local disposition: Candidate For Dataset Reuse
- Upstream revision: Release 0.1.0 (immutable)
- Mapping note: Release 0.1.0 captures and compares human feedback and supports record transfer; a separate evaluation design would be needed to turn those records into an agent task or validated grader.
- Claim boundary: Release 0.1.0 does not ship an LLM judge or judge-calibration workflow and does not show that an external agent acted correctly on Drupal state.

### AI Maintenance Skills

Drupal.org issue-triage and maintenance workflows for coding agents within a constrained DDEV design.

- Source: [https://www.drupal.org/project/ai\_maintenance\_skills](<https://www.drupal.org/project/ai_maintenance_skills>)
- Last reviewed: 2026-07-11
- Roles: Workflow Source, Substrate Source
- Registry effect: reference only; no claim or coverage effect

#### [Drupal issue maintenance workflow and trust boundary](<https://git.drupalcode.org/project/ai_maintenance_skills/-/blob/1.0.x/README.md>)

- Kind: Workflow
- Mapping scope: Supporting Infrastructure
- Agent classes: External Coding Agent
- Substrate fidelity: Drupal Runtime
- Evaluator types: Not Reported
- Question: Can an external coding agent safely triage and prepare Drupal.org maintenance work that reduces total maintainer burden?
- Lifecycle: None (supporting infrastructure)
- Candidate families: None (supporting infrastructure)
- Local disposition: Candidate For Local Reproduction
- Upstream revision: Branch 1.0.x (mutable pointer)
- Mapping note: This is workflow prior art. Promote a separately defined local task only after fixing its inputs, observable completion criteria, evaluator, decision target, and stop condition.
- Claim boundary: The workflow description does not provide a locally reproduced Agent Readiness result or a formal evaluator, so it cannot enter the scorecard directly.
