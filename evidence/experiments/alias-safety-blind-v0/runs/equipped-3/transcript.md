# Alias-safety transcript — equipped-3

Site root: <workspace>/tmp/agent-readiness/as-eq-3
All drush calls prefixed with `PHP_INI_SCAN_DIR=/tmp/ar-phpini`.
Site: Drupal 11.3.11, Haven theme, SQLite. Read-only; no config/content modified.

## Commands run

1. `vendor/bin/drush status`
   - Confirmed site bootstraps; SQLite DB connected; Drupal root present.

2. `vendor/bin/drush site-architecture:path-owner /this-is-free-xyz --format=json`
   - claimed=false, alias=null, owner=null, no negative_contracts, no latent_claims.
   - => UNCLAIMED. SAFE.

3. `vendor/bin/drush site-architecture:path-owner /moderated-content --format=json`
   - claimed=false, alias=null, owner=null, no latent_claims.
   - => UNCLAIMED per tool. SAFE (verified below the view does not live here).

4. `vendor/bin/drush site-architecture:path-owner /blog --format=json`
   - claimed=true. alias is_alias=true internal_path=/page/2.
   - owner: entity canvas_page id=2 label="Blog", route entity.canvas_page.canonical, published.
   - negative_contract: "Do not create another surface at /blog: already canonical page of canvas_page 2."
   - => TAKEN NOW. NOT SAFE.

5. `vendor/bin/drush site-architecture:path-owner /search --format=json`
   - claimed=true. owner: view search:page, route view.search.page, base search_api_index_content, path_pattern /search.
   - negative_contract: a node alias here would shadow the view and hijack the page.
   - => OWNED BY ENABLED VIEW. NOT SAFE.

6. `vendor/bin/drush site-architecture:path-owner /admin/content/files --format=json`
   - claimed=false BUT latent_claims: disabled_view files:page_1 (views.view.files).
   - negative_contract: "Disabled view files:page_1 declares this path. If enabled it will collide."
   - => LATENT CLAIM. NOT SAFE.

7. `vendor/bin/drush site-architecture:path-owner /admin/content/media/scheduled --format=json`
   - claimed=false BUT latent_claims: disabled_view scheduler_scheduled_media:overview.
   - negative_contract: "Disabled view scheduler_scheduled_media:overview declares this path. If enabled it will collide."
   - => LATENT CLAIM. NOT SAFE.

## Independent cross-verification

8. `vendor/bin/drush config:get views.view.moderated_content status`
   - status: true (the moderated_content view IS enabled).

9. `vendor/bin/drush config:get views.view.moderated_content display --format=json`
   - display "moderated_content" path = `admin/content/moderated` (NOT `/moderated-content`).
   - `vendor/bin/drush site-architecture:path-owner /admin/content/moderated` => claimed=true, owner view moderated_content.
   - Confirms the candidate hyphenated top-level `/moderated-content` does NOT collide with this view. SAFE stands.

10. `vendor/bin/drush config:get views.view.files status` => false (disabled).
    `...display.page_1.display_options.path` => `admin/content/files`. Confirms latent claim.

11. `vendor/bin/drush config:get views.view.scheduler_scheduled_media status` => false (disabled).
    `...display.overview.display_options.path` => `admin/content/media/scheduled`. Confirms latent claim.

12. `vendor/bin/drush pm:list --status=enabled`
    - Enabled: content_moderation, file, media, media_library, workflows, scheduler,
      scheduler_content_moderation_integration, media_file_delete, media_library_bulk_upload.
    - scheduler enabled => scheduler_scheduled_media view could be routinely enabled.
    - file/media enabled => Files view is the standard admin view, commonly enabled.
    - Both latent claims are realistic routine-config collisions.

13. `vendor/bin/drush php:eval` path_alias.repository lookupByAlias for the four content paths:
    - /this-is-free-xyz => (no alias)
    - /moderated-content => (no alias)
    - /blog => /page/2 (confirms existing alias)
    - /search => (no alias; it is a route, not an alias)

(Note: a direct `drush sqlq` attempt failed with environmental "no such collation sequence: NOCASE_UTF8";
re-ran alias lookups via php:eval instead, step 13.)

## Conclusions

| Path | Safe | Why |
|------|------|-----|
| /this-is-free-xyz | YES | Fully unclaimed, no latent claim. |
| /moderated-content | YES | Unclaimed; moderated_content view is at /admin/content/moderated, not here. |
| /blog | NO | Canonical alias of canvas_page 2 ("Blog") right now. |
| /search | NO | Enabled search view page; node alias would shadow it. |
| /admin/content/files | NO | Disabled Files view declares it; enabling (routine) collides. |
| /admin/content/media/scheduled | NO | Disabled scheduler_scheduled_media view declares it; enabling (routine) collides. |
