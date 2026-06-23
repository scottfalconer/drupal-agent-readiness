# act.event_jsonapi transcript

Run ID: `event-independent-20260620151052`

Disposable site root: `<workspace>/tmp/agent-readiness/event-independent-20260620151052/site`

Answer file: `<workspace>/tmp/agent-readiness/event-independent-20260620151052/event-answer.json`

## Context and baseline

- `pwd`
  - Confirmed working repository: `<workspace>`.
- `ls -la <workspace>/tmp/agent-readiness/event-independent-20260620151052`
  - Confirmed run directory with `baseline-state.json`, `run.json`, and `site/`.
- `ls -la <workspace>/tmp/agent-readiness/event-independent-20260620151052/site`
  - Confirmed disposable Composer Drupal site.
- `test -x vendor/bin/drush && vendor/bin/drush --version`
  - Confirmed site-local Drush `13.7.3.0`.
- `sed -n '1,220p' AGENTS.md`
  - Read disposable site guidance.
- `vendor/bin/drush status --fields=drupal-version,site,db-status,bootstrap,root,uri --format=json`
  - Drupal `11.3.11`; database connected; bootstrap successful.
- `sed -n '1,240p' baseline-state.json`
  - Baseline had bundles `blog`, `page`, `person_profile`, `project`; no Event sample; JSON:API Event resource unavailable.
- `vendor/bin/drush pm:list --type=module --filter=jsonapi --format=json`
  - JSON:API was initially disabled.
- `vendor/bin/drush php:eval '<snapshot bundles/views/aliases/permissions>'`
  - Confirmed baseline Drupal state from the active site.

## Site mutation

- `vendor/bin/drush pm:enable jsonapi --yes`
  - Attempted to enable JSON:API and Serialization. The command hit PHP CLI memory exhaustion at `128M` during shutdown/container work.
- `php -r 'echo ini_get("memory_limit"), PHP_EOL;'`
  - Confirmed PHP CLI memory limit was `128M`.
- `vendor/bin/drush php:eval '<moduleHandler jsonapi/serialization check>'`
  - Confirmed the prior enable attempt did install both `jsonapi` and `serialization`.
- `php -d memory_limit=512M vendor/bin/drush.php php:eval '<create event bundle, fields, and sample>'`
  - Created `event`, `field_event_date`, and `field_event_location` storage; failed while attaching `field_event_location` because field-definition cache had not picked up the newly-created storage.
- `php -d memory_limit=512M vendor/bin/drush.php php:eval '<inspect partial Event state>'`
  - Confirmed Event bundle existed, date storage/field existed, location storage existed, location field did not yet exist, and zero Event nodes existed.
- `php -d memory_limit=512M vendor/bin/drush.php cache:rebuild`
  - Rebuilt caches successfully.
- `php -d memory_limit=512M vendor/bin/drush.php php:eval '<attach location field and create sample Event>'`
  - Created the required location field and one published sample Event:
  - Node ID: `10`
  - UUID: `994fa752-136b-486d-870d-7b3277d9259a`
  - Title: `Agent readiness sample event`
  - Date: `2026-07-01`
  - Location: `Boise, Idaho`

## Verification

- `php -d memory_limit=512M vendor/bin/drush.php php:eval '<verify Event bundle, required fields, sample node>'`
  - Verified `event` bundle exists.
  - Verified required fields: `field_event_date`, `field_event_location`.
  - Verified one published Event sample with UUID `994fa752-136b-486d-870d-7b3277d9259a`.
- `php -d memory_limit=512M vendor/bin/drush.php php:eval '<post-change bundles/views/aliases/permissions snapshot>'`
  - Confirmed Views and aliases matched baseline; only content-type addition was `event`.
- `php -d memory_limit=512M vendor/bin/drush.php --uri=http://127.0.0.1:8897 runserver 127.0.0.1:8897 --no-browser`
  - Started temporary local server for HTTP verification.
- `curl --silent --show-error --output /tmp/event-independent-20260620151052-jsonapi-response.json --write-out '%{http_code}\n' http://127.0.0.1:8897/jsonapi/node/event/994fa752-136b-486d-870d-7b3277d9259a`
  - Returned HTTP status `200`.
- `php -r '<parse JSON:API response summary>'`
  - Verified JSON:API response type `node--event`, UUID `994fa752-136b-486d-870d-7b3277d9259a`, title `Agent readiness sample event`, date `2026-07-01`, and location `Boise, Idaho`.
- Sent Ctrl-C to the runserver session.
  - Stopped the temporary server.
- `php -d memory_limit=512M vendor/bin/drush.php php:eval '<compare baseline blast-radius surfaces>'`
  - Final corrected comparison:
  - `unrelated_bundles_changed`: `false`
  - `unrelated_views_changed`: `false`
  - `unrelated_aliases_changed`: `false`
  - `unrelated_permissions_changed`: `false`

## Notes

- No changes were made to `<workspace>/haven-clean-install`.
- No repository files outside the disposable site state and the two requested run output files were intentionally modified.
- The JSON:API verification used a real HTTP fetch against the disposable clone.
