# Alias-safety check transcript — equipped-1

Site root: <workspace>/tmp/agent-readiness/aliassafety-equipped/site
Drupal 11.3.11, Haven theme, SQLite. All drush prefixed with `PHP_INI_SCAN_DIR=/tmp/ar-phpini`.
Tooling: site_architecture module's `site-architecture:path-owner` plus core drush php:eval cross-checks.

## Command log

1. `drush status` — confirmed live site: Drupal 11.3.11, sqlite, bootstrap successful.

2. `drush site-architecture:path-owner /this-is-free-xyz --format=json`
   → claimed=false, no alias/owner, no negative_contracts. UNCLAIMED → SAFE.

3. `drush site-architecture:path-owner` for the remaining five (single loop):
   - `/moderated-content` → claimed=false, no owner, no latent claims. UNCLAIMED.
   - `/blog` → claimed=true. alias of /page/2; owner = entity canvas_page 2 ("Blog"), canonical. Negative contract: "Do not create another surface at /blog". NOT SAFE.
   - `/search` → claimed=true. owner = view search:page (route view.search.page) over search_api_index_content. Negative contract: node alias would shadow/hijack the view. NOT SAFE.
   - `/admin/content/files` → claimed=false BUT latent_claims: disabled view files:page_1 declares this path. Tool warns "if enabled it will collide". RISKY → NOT SAFE.
   - `/admin/content/media/scheduled` → claimed=false BUT latent_claims: disabled view scheduler_scheduled_media:overview declares this path. RISKY → NOT SAFE.

## Independent cross-checks (core drush)

4. `drush sqlq` for aliases/view status — FAILED (sqlite "no such collation sequence: NOCASE_UTF8" and "no such column: status"). Switched to php:eval.

5. `drush php:eval` view status + display paths:
   - search: ENABLED, [page => /search]  (confirms /search owner)
   - files: DISABLED, [page_1 => /admin/content/files], [page_2 => /admin/content/files/usage/%]  (confirms latent claim)
   - scheduler_scheduled_media: DISABLED, [overview => /admin/content/media/scheduled], [user_page => /user/%user/scheduled_media]  (confirms latent claim)

6. `drush php:eval` alias lookups + route match + moderated_content view:
   - path_alias lookups: /this-is-free-xyz no alias; /moderated-content no alias; /blog => /page/2; /search no alias.
   - moderated_content view: ENABLED; content_moderation module: enabled.
   - router.no_access_checks match: /moderated-content, /this-is-free-xyz, /admin/content/files, /admin/content/media/scheduled all → NO ROUTE (ResourceNotFoundException).

7. `drush php:eval` resolve moderated_content view path + scan all views for literal "moderated-content":
   - moderated_content view path = /admin/content/moderated (NOT /moderated-content).
   - No view declares path "moderated-content".
   → Confirms /moderated-content is genuinely unclaimed; the enabled Moderated content view occupies a different path. SAFE.

## Conclusion

| Path | Safe | Conflict |
|---|---|---|
| /this-is-free-xyz | yes | none |
| /moderated-content | yes | none (Moderated content view is at /admin/content/moderated) |
| /blog | no | canonical alias of canvas_page 2 ("Blog") |
| /search | no | enabled view search:page would be shadowed |
| /admin/content/files | no | disabled view files:page_1 latent claim (collides if enabled) |
| /admin/content/media/scheduled | no | disabled view scheduler_scheduled_media:overview latent claim (collides if enabled) |
