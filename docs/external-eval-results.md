# Maintainer-local external evaluation records

> These are bounded, maintainer-selected local records. Some retain auditable artifacts; others are explicitly unverified manifests. They do not make external registry entries executable, change Agent Readiness coverage, or enter the scorecard.

Each record declares its substrate fidelity and claim boundary; the current ABP agent run is prompt-only. No record is a general model score or upstream project verdict. Source validations are listed separately because they are **not agent performance**.

## Agent-performance diagnostics

### `2026-07-12-render-pipeline-b01-codex-gpt-5.4`

- Source: `ai-best-practices:skill-eval-cases` at commit `c45117130a4de1fe7d03d3fe225e3f09b8e4e803`
- Adapter: `ai_best_practices_run_evals_v1`
- Suite/case: `drupal-render-pipeline` / `B01`
- Treatment: `skill_injected`; `single_condition_no_ab`
- Agent: `codex 0.142.5` with `gpt-5.4`
- Automated upstream oracle: **0/1 cases passed** (1 oracle failure)
- Published diagnostic status: `upstream_oracle_fail_manual_adjudication_required`
- Manual adjudication: `required_unresolved`
- PHP lint: 1/1 extracted blocks passed syntax lint
- Substrate: `isolated_empty_git_worktree`; Drupal runtime `false`; real Drupal site `false`
- Runner change: upstream runner plus `--ignore-user-config, --ephemeral` only
- Evidence: `locally_run_diagnostic`; scorecard eligible `false`; coverage effect `none`
- Trace: `evidence/external-evals/ai-best-practices/2026-07-12-render-pipeline-b01-codex-gpt-5.4/traces/B01.json`; SHA-256 `f6efef30de423403ac9b9ebb1627c876d26d77a65c21544ff5294aa3b0bb9531`
- Reconstructed prompt: `evidence/external-evals/ai-best-practices/2026-07-12-render-pipeline-b01-codex-gpt-5.4/prompts/B01-full-injected.txt`; SHA-256 `0eefd8a06f3376ae1357d316a239dfc0f956ed4489bafd60b02059bb7ab036a0`

The upstream literal oracle marked B01 failed because it found none of \#cache, 'tags', or 'contexts'. The response instead used CacheableMetadata APIs, and the extracted PHP block passed syntax lint. This automated outcome requires manual or runtime adjudication.

Adjudication reason: The response uses semantically relevant CacheableMetadata APIs that the upstream literal-token oracle does not recognize, creating a likely oracle disagreement; Drupal correctness remains unresolved.

Manual observations:

- The response returns a render array and uses CacheableMetadata::addCacheTags\(\['node\_list'\]\) followed by applyTo\($build\).
- The upstream oracle searches only for literal \#cache, 'tags', or 'contexts' tokens and recorded none of them.
- The response says user.permissions is covered through an AccessResult, but no Drupal runtime check adjudicated that claim.
- The one extracted PHP block passed the upstream syntax-lint check.
- The --ignore-user-config flag removed an incompatible reasoning setting, but a separate direct diagnostic still emitted plugin and skill loading warnings; the retained trace captures neither provider stderr nor a loaded-context inventory.

Claim boundaries:

- The prompt ran in an isolated empty Git worktree with no Drupal runtime or real Drupal site.
- Only the skill-injected condition ran, so this result cannot estimate the effect of the skill against a no-skill baseline.
- One selected case cannot be generalized to Codex, GPT-5.4, Drupal agents, or the full upstream suite.
- The upstream substring-oracle failure is not adjudicated as a model or task failure and does not establish an AI Best Practices project failure.
- The trace omits the full injected skill prompt and final Codex CLI argv; the package retains a deterministic prompt reconstruction from pinned sources, while the final argv remains unretained.
- Filesystem isolation is verified only for the empty temporary Git worktree; ambient Codex plugin or skill context isolation is incomplete and unverified because provider stderr and loaded-context inventory were not retained.
- PHP syntax lint does not establish Drupal runtime correctness, cache behavior, access behavior, or functional success.
- This locally run diagnostic has no Agent Readiness scorecard eligibility and changes no benchmark coverage status.

## Source validation (not agent performance)

### `2026-07-12-drupal-cms-codebase-standard-profile-preflight-e06f11c3`

- Source: `ai-agents-test:drupal-cms-agent-test-suites` at commit `e06f11c33c2fda6beb09008e60bf8a65804a132c`
- Adapter: `ai_agents_test_drupal_cms_codebase_preflight_v1`
- Outcome model: `structured_observations` — intentionally not flattened into suite pass/fail counts
- Substrate: temporary `Drupal CMS 2.1.1 codebase with the Standard install profile` using Drupal `11.3.8` and `DDEV`; Drupal CMS install profile used `false`; containers stopped after `true`
- Agent-performance result: `false`
- Evidence support: `manifest_only_unverified`

Operator-recorded outcomes (manifest-only; independently unverified):

- `php-lint` — `validated_clean`, command exit `0`, support `manifest_only_unverified`; facts: `{"lint_failures": 0, "scope": "all_upstream_php_files"}`
- `yaml-catalog-parse` — `parsed`, command exit `0`, support `manifest_only_unverified`; facts: `{"cases_counted": 81, "yaml_groups": 11}`
- `standard-profile-site-install` — `installed`, command exit `0`, support `manifest_only_unverified`; facts: `{"install_profile": "standard"}`
- `drupal-cms-ai-recipe` — `externally_blocked_partial`, command exit `173`, support `manifest_only_unverified`; facts: `{"default_chat_with_tools_provider_after": false, "external_service": "amazee_trial_provisioning", "http_status": 429, "recipe": "drupal_cms_ai"}`
- `module-enable` — `enabled`, command exit `0`, support `manifest_only_unverified`; facts: `{"module": "ai_agents_test"}`
- `content-type-group-import` — `imported`, command exit `0`, support `manifest_only_unverified`; facts: `{"cases_imported": 9, "group": "content-type"}`
- `real-test-1-no-provider` — `blocked_missing_precondition`, command exit `1`, support `manifest_only_unverified`; facts: `{"error": "No default AI provider set for chat with tools", "real_model_invoked": false, "test_id": 1}`
- `unsupported-echo-mock-smoke` — `presentation_result_disagreement`, command exit `0`, support `manifest_only_unverified`; facts: `{"attempts": [{"error_category": "permission_error", "observed_result_entity_status": "failure", "uid": 0}, {"error_category": "tool_output_type_error", "observed_result_entity_status": "failure", "uid": 1}], "drush_summary": "Success", "provider": "internal_unsupported_echo_mock"}`

Retention:

- Raw stdout retained: `false`
- Database dump retained: `false`
- Result entity export retained: `false`
- These maintainer-recorded observations are manifest-only and unverified because raw stdout, database state, and result entities were not retained.

Claim boundaries:

- No real model or configured AI provider evaluation completed, and no provider credential was used.
- The internal EchoAI mock provider was an unsupported harness smoke only and is not a substitute for a supported model provider.
- The Drush Success summary disagreed with failure statuses observed in result entities, so command presentation cannot be treated as a passed test result.
- No raw stdout, database dump, or result entity export was retained beyond this manifest, so none of its observations are independently auditable evidence.
- The substrate was a Drupal CMS 2.1.1 codebase installed with the Standard profile, not a Drupal CMS install-profile installation.
- This preflight establishes no project verdict, model score, Agent Readiness scorecard eligibility, or benchmark coverage effect.

### `2026-07-12-static-checks-c4511713`

- Source: `ai-best-practices:skill-eval-cases` at commit `c45117130a4de1fe7d03d3fe225e3f09b8e4e803`
- Adapter: `ai_best_practices_static_v1`
- Aggregate: **219/219 static checks passed** across 5 commands
- Default discovery: 144 checks
- Explicit nested suites: 75 checks
- Agent-performance result: `false`
- Evidence support: `retained_artifacts`

The default command discovers 144 checks in eight top-level suites; four nested accessibility suites require explicit --skill commands and add 75 checks.

Commands:

- `PYTHONPYCACHEPREFIX=/private/tmp/abp-static-pyc python3 -B evals/run-evals.py --static` -> 144/144 passed, exit 0; stdout `evidence/external-evals/ai-best-practices/2026-07-12-static-checks-c4511713/artifacts/default-discovery.stdout.txt`; SHA-256 `938bafa58e6d6d4cff8c0679da4122ddc47cc18fc6a02c158eebc61c7a84b189`
- `PYTHONPYCACHEPREFIX=/private/tmp/abp-a11y-fapi-pyc python3 -B evals/run-evals.py --static --skill drupal-accessibility/drupal-a11y-fapi` -> 14/14 passed, exit 0; stdout `evidence/external-evals/ai-best-practices/2026-07-12-static-checks-c4511713/artifacts/nested-a11y-fapi.stdout.txt`; SHA-256 `4b4e187577face1fd9976f5976e54948a3a0d9a9b62e514b1f5b10d42d5369c2`
- `PYTHONPYCACHEPREFIX=/private/tmp/abp-a11y-dom-pyc python3 -B evals/run-evals.py --static --skill drupal-accessibility/drupal-a11y-dom` -> 17/17 passed, exit 0; stdout `evidence/external-evals/ai-best-practices/2026-07-12-static-checks-c4511713/artifacts/nested-a11y-dom.stdout.txt`; SHA-256 `fbbb66ba439bfef9526af5f234ac9a4d45098b6b4c36f4e6bce5abb16a12e43f`
- `PYTHONPYCACHEPREFIX=/private/tmp/abp-a11y-dynamic-pyc python3 -B evals/run-evals.py --static --skill drupal-accessibility/drupal-a11y-dynamic` -> 21/21 passed, exit 0; stdout `evidence/external-evals/ai-best-practices/2026-07-12-static-checks-c4511713/artifacts/nested-a11y-dynamic.stdout.txt`; SHA-256 `1390ebc257f82e14687910e9283e78471a5f172bffe8f82eb5d2379d3db3df95`
- `PYTHONPYCACHEPREFIX=/private/tmp/abp-a11y-qa-pyc python3 -B evals/run-evals.py --static --skill drupal-accessibility/drupal-a11y-qa` -> 23/23 passed, exit 0; stdout `evidence/external-evals/ai-best-practices/2026-07-12-static-checks-c4511713/artifacts/nested-a11y-qa.stdout.txt`; SHA-256 `a521fb5048ff0e414f026a7118e3aa724f3c2ce320562fb6aedc9b5ebb37be07`

Claim boundaries:

- These 219 passing checks validate static source content and harness expectations; they do not evaluate an agent response.
- The 219/219 aggregate combines five separately executed commands and must not be described as one default-discovery run.
- Static source validation establishes neither Drupal runtime behavior nor the effectiveness of the skills for an agent.
- The five retained stdout artifacts support auditing the reported command-level counts; they do not retain a complete execution environment.
