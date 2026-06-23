# Alias-safety assessment — equipped-2

Site (drush root): `<workspace>/tmp/agent-readiness/as-eq-2`
(The expected `/site` subdir did not exist; the as-eq-2 directory itself is the Drupal root — confirmed via `drush status`: Drupal 11.3.11, Haven theme, sqlite, bootstrap successful.)

All drush invocations prefixed with `PHP_INI_SCAN_DIR=/tmp/ar-phpini` and run from the drush root. Resolved against the LIVE site via the `site_architecture` module. Read-only; no config/content modified.

## Rule
UNSAFE if any of: active route, active Views page display, or entity canonical page already responds there; OR a DISABLED view declares the path as a page-display path (latent claim). Otherwise SAFE.

## Commands and resolutions

### 1. Setup / verification
```
PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush status
PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush list | grep -i path-owner
```
→ Site bootstraps; `site-architecture:path-owner` command present.

### 2. /this-is-free-xyz
```
PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush site-architecture:path-owner /this-is-free-xyz --format=json
```
→ `claimed: false`, owner null, no negative_contracts, no latent_claims.
→ No route, alias, view, or entity. **SAFE** (blocker_kind: null).

### 3. /moderated-content
```
PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush site-architecture:path-owner /moderated-content --format=json
```
→ `claimed: false`, owner null, no negative_contracts, no latent_claims.
→ **SAFE** (blocker_kind: null).

Cross-check (php:eval over all views for "moderated" in any display path):
```
PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush php:eval '...scan views.view.* display paths for "moderated"...'
```
→ Only match: `views.view.moderated_content :: moderated_content :: ENABLED :: /admin/content/moderated`.
→ The standard Moderated-content view serves `/admin/content/moderated`, NOT `/moderated-content`. No enabled or disabled view declares `/moderated-content`. Confirms SAFE.

### 4. /blog
```
PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush site-architecture:path-owner /blog --format=json
```
→ `claimed: true`. Owner kind `entity`: canvas_page 2 ("Blog"), route `entity.canvas_page.canonical`, canonical: true, published. Alias of internal `/page/2`.
→ Entity canonical page already responds. **UNSAFE** (blocker_kind: entity).

### 5. /search
```
PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush site-architecture:path-owner /search --format=json
```
→ `claimed: true`. Owner kind `view`: `search:page` (config `views.view.search`), route `view.search.page`, path_pattern `/search`, base table `search_api_index_content`.
→ Active Views page display responds. **UNSAFE** (blocker_kind: view).

### 6. /admin/content/files
```
PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush site-architecture:path-owner /admin/content/files --format=json
```
→ `claimed: false`, but `latent_claims`: disabled_view `files:page_1` (config `views.view.files`) declares this path. negative_contract warns of collision if enabled.
→ Latent claim from a DISABLED view. **UNSAFE** (blocker_kind: latent_disabled_view).

### 7. /admin/content/media/scheduled
```
PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush site-architecture:path-owner /admin/content/media/scheduled --format=json
```
→ `claimed: false`, but `latent_claims`: disabled_view `scheduler_scheduled_media:overview` (config `views.view.scheduler_scheduled_media`) declares this path. negative_contract warns of collision if enabled.
→ Latent claim from a DISABLED view. **UNSAFE** (blocker_kind: latent_disabled_view).

## Summary
| Path | safe | blocker_kind |
|------|------|--------------|
| /this-is-free-xyz | true | null |
| /moderated-content | true | null |
| /blog | false | entity |
| /search | false | view |
| /admin/content/files | false | latent_disabled_view |
| /admin/content/media/scheduled | false | latent_disabled_view |
