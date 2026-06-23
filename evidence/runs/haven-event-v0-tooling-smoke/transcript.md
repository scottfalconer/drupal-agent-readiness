# Transcript: haven-event-v0-tooling-smoke

This smoke run applied the Event JSON:API task through Drupal APIs on a disposable Haven clone.

Commands represented:

- Copied substrate `<workspace>/haven-clean-install` to `<workspace>/tmp/agent-readiness/haven-event-v0-tooling-smoke/site`.
- Ran `vendor/drush/drush/drush.php php:script agent_readiness/evaluators/apply_event_jsonapi.php`.
- Collected live Drupal state and evaluated the Event task mechanically.

This is a tooling/evaluator smoke run, not a blinded independent-agent run.
