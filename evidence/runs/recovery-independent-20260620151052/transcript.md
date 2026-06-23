# Recovery Transcript: recovery-independent-20260620151052

Task: `recover.event_jsonapi`

Disposable site root:
`<workspace>/tmp/agent-readiness/event-independent-20260620151052/site`

Baseline:
`<workspace>/tmp/agent-readiness/event-independent-20260620151052/baseline-state.json`

## Command Log

1. `pwd`
   - Confirmed the working directory was the disposable site root.
2. `ls <workspace>/tmp/agent-readiness/event-independent-20260620151052`
   - Confirmed the run directory contained `baseline-state.json`, prior act outputs, and `site`.
3. `jq 'keys' baseline-state.json`
   - Confirmed baseline keys: aliases, blast radius, content model, JSON:API, permissions, routes, Views, and related state.
4. `ls vendor/bin`
   - Confirmed local `vendor/bin/drush` and `vendor/bin/drush.php` were available.
5. `jq '.content_model' baseline-state.json`
   - Confirmed baseline bundles were `blog`, `page`, `person_profile`, and `project`; no Event bundle was present.
6. `jq '.jsonapi' baseline-state.json`
   - Confirmed baseline did not expose an Event JSON:API resource.
7. `./vendor/bin/drush status --fields=bootstrap,db-status,drupal-version,site-uri --format=json`
   - Failed because this Drush version does not define the `site-uri` status field.
8. `./vendor/bin/drush status --format=json`
   - Confirmed Drupal 11.3.11, SQLite, and successful bootstrap for the disposable site.
9. `./vendor/bin/drush config:get node.type.event --format=json`
   - Confirmed `node.type.event` existed before cleanup.
10. `./vendor/bin/drush php:eval 'load node type IDs'`
   - Confirmed current bundles included `event`.
11. `./vendor/bin/drush php:eval 'query Event node IDs'`
   - Found Event node ID `10`.
12. `jq '.aliases, .views, .permissions, .routes' baseline-state.json`
   - Recorded baseline alias strings, view IDs, permissions, and route expectations.
13. `./vendor/bin/drush php:eval 'inspect Event field definitions'`
   - Found `field_event_date` and `field_event_location`.
14. `./vendor/bin/drush php:eval 'query aliases for /node/10'`
   - Found no path aliases for the Event node.
15. `./vendor/bin/drush php:eval 'probe route names'`
   - Failed because one returned route object was a Symfony route alias without `getPath()`.
16. `./vendor/bin/drush php:eval 'query role permissions containing event'`
   - Found no role permissions containing `event`.
17. `./vendor/bin/drush config:list | rg '(^|\.)event($|\.)|event_'`
   - Failed because this Drush version does not provide `config:list`.
18. `./vendor/bin/drush php:eval 'query aliases containing event'`
   - Found no aliases containing `event`.
19. `./vendor/bin/drush php:eval 'probe JSON:API Event routes'`
   - Confirmed `jsonapi.node--event.collection` and `jsonapi.node--event.individual` existed before cleanup.
20. `./vendor/bin/drush php:eval 'list config names matching Event patterns'`
   - Found `field.field.node.event.field_event_date`, `field.field.node.event.field_event_location`, both field storages, `node.type.event`, and `simple_sitemap.bundle_settings.default.node.event`.
21. `./vendor/bin/drush php:eval 'delete Event nodes, aliases, permissions, field/display/type config, simple_sitemap Event config, rebuild router/cache'`
   - Deleted the Event node and Event config, then hit PHP's 128 MB memory limit during cache/router rebuild. The command exited non-zero after the deletions had been applied.
22. `php -d memory_limit=512M ./vendor/bin/drush php:eval '...'`
   - Incorrect entrypoint: printed the shell wrapper for `vendor/bin/drush` instead of running Drush.
23. `php -d memory_limit=512M ./vendor/bin/drush.php php:eval 'inspect bundles/Event content/Event config/Event JSON:API routes'`
   - Confirmed the Event bundle, Event node, Event config, and Event JSON:API routes were gone.
24. `php -d memory_limit=512M ./vendor/bin/drush.php cache:rebuild`
   - Completed successfully.
25. `php -d memory_limit=512M ./vendor/bin/drush.php php:eval 'baseline comparison script'`
   - First attempt had a PHP bracket typo; no mutation occurred.
26. `php -d memory_limit=512M ./vendor/bin/drush.php php:eval 'baseline comparison script'`
   - Confirmed Event removal and JSON:API removal. A strict raw alias-record comparison reported alias drift because Webform aliases exist in both `en` and `und`.
27. `php -d memory_limit=512M ./vendor/bin/drush.php php:eval 'diff baseline alias strings against current alias strings'`
   - Confirmed no alias strings were missing or added compared with baseline.
28. `php -d memory_limit=512M ./vendor/bin/drush.php php:eval 'list duplicate alias records'`
   - Confirmed duplicates were Webform aliases by language, not Event aliases.
29. `jq '.paths, .aliases' baseline-state.json`
   - Confirmed baseline stores alias strings, not per-language alias records.
30. `jq '.blast_radius' baseline-state.json`
   - Confirmed baseline blast-radius booleans were all false.
31. `php -d memory_limit=512M ./vendor/bin/drush.php php:eval 'query aliases containing event'`
   - Confirmed no Event aliases remained.
32. `php -d memory_limit=512M ./vendor/bin/drush.php php:eval 'normalized final comparison'`
   - Produced the final answer JSON: Event removed, Event content removed, Event JSON:API removed, and all blast-radius checks false.

## Final Verification Output

```json
{
    "event_removed": true,
    "event_content_removed": true,
    "jsonapi_removed": true,
    "blast_radius": {
        "unrelated_bundles_changed": false,
        "unrelated_views_changed": false,
        "unrelated_aliases_changed": false,
        "unrelated_permissions_changed": false,
        "unexpected_routes_remaining": false
    }
}
```

## Notes

- No changes were made to `<workspace>/haven-clean-install`.
- No repository files were modified.
- No generated smoke-run answers under `agent_readiness/runs` were read or copied.
- The final alias comparison follows the baseline artifact's representation: unique alias strings.
