# Transcript: haven-recovery-v0-tooling-smoke

This smoke run recovered the Event JSON:API task through Drupal APIs on the same disposable Haven clone.

Commands represented:

- Ran `vendor/drush/drush/drush.php php:script agent_readiness/evaluators/recover_event_jsonapi.php`.
- Collected live Drupal state and evaluated the recovery task mechanically.

This is a tooling/evaluator smoke run, not a blinded independent-agent run.
