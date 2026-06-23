# Transcript: haven-inventory-v0-tooling-smoke

This run was materialized by `agent_readiness/scripts/materialize_inventory_run.py`.
It records the tool-assisted inventory path used to validate the v0 evaluator and publish assets.

Commands represented:

- Copied substrate `<workspace>/haven-clean-install` to `<workspace>/tmp/agent-readiness/haven-inventory-v0-tooling-smoke/site`.
- Collected live Drupal state via `vendor/bin/drush status --format=json`.
- Collected site facts via `vendor/bin/drush php:script agent_readiness/evaluators/drupal_state_collector.php`.
- Built `answer.json` from live state and evaluated it mechanically.

This is a tooling/evaluator smoke run, not a blinded independent-agent run.
