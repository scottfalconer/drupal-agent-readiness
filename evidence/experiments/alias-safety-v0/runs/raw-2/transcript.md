# Alias Safety Assessment — Transcript (raw-2)

Site root (actual): `<workspace>/tmp/agent-readiness/as-raw-2`
(Note: task pointed at `.../as-raw-2/site` which does not exist; the Drupal root is `as-raw-2` itself, web root at `as-raw-2/web`.)
Drush: CORE only, v13.7.3, Drupal 11.3.11, SQLite. All commands prefixed with `PHP_INI_SCAN_DIR=/tmp/ar-phpini`.

A path is UNSAFE if any of: active route, active Views page display, or entity canonical responds there; OR a DISABLED view declares it as a page-display path (latent claim). Otherwise SAFE.

---

## Command 1 — drush status (locate/verify site)

```
vendor/bin/drush status
```
Confirmed: Drupal 11.3.11, SQLite, bootstrap successful, web root `as-raw-2/web`.

## Command 2 — Router + alias resolution per candidate

```
vendor/bin/drush php:eval '... router.no_access_checks->match() + path_alias.manager->getPathByAlias() per path ...'
```

Resolution results:

| Path | alias -> internal | router(raw) |
|------|-------------------|-------------|
| /this-is-free-xyz | /this-is-free-xyz (no alias) | NO MATCH (ResourceNotFoundException) |
| /moderated-content | /moderated-content (no alias) | NO MATCH (ResourceNotFoundException) |
| /blog | **/page/2** (alias) | MATCH route=`entity.canvas_page.canonical` |
| /search | /search (no alias) | MATCH route=`view.search.page` |
| /admin/content/files | /admin/content/files (no alias) | NO MATCH (ResourceNotFoundException) |
| /admin/content/media/scheduled | /admin/content/media/scheduled (no alias) | NO MATCH (ResourceNotFoundException) |

## Command 3 — Enumerate ALL views (enabled + disabled), every page display path

```
vendor/bin/drush php:eval '... loadMultiple() over view storage; print status + page-display path for each ...'
```

Total views: 21. Page displays found:

```
canvas_pages                  [ENABLED]  page_1          /admin/content/pages
content                       [ENABLED]  page_1          /admin/content/node
files                         [DISABLED] page_1          /admin/content/files            <<< CANDIDATE
files                         [DISABLED] page_2          /admin/content/files/usage/%
media                         [ENABLED]  media_page_list /admin/content/media
media_library                 [ENABLED]  page            /admin/content/media-grid
media_library                 [ENABLED]  widget          /admin/content/media-widget
media_library                 [ENABLED]  widget_table    /admin/content/media-widget-table
moderated_content             [ENABLED]  moderated_content /admin/content/moderated
redirect                      [ENABLED]  page_1          /admin/config/search/redirect
redirect_404                  [ENABLED]  page_1          /admin/config/search/redirect/404
scheduler_scheduled_content   [ENABLED]  overview        /admin/content/scheduled
scheduler_scheduled_content   [ENABLED]  user_page       /user/%user/scheduled
scheduler_scheduled_media     [DISABLED] overview        /admin/content/media/scheduled  <<< CANDIDATE
scheduler_scheduled_media     [DISABLED] user_page       /user/%user/scheduled_media
scheduler_scheduled_taxonomy_term [DISABLED] overview    /admin/structure/taxonomy/scheduled
search                        [ENABLED]  page            /search                         <<< CANDIDATE
taxonomy_term                 [ENABLED]  page_1          /taxonomy/term/%
user_admin_people             [ENABLED]  page_1          /admin/people/list
watchdog                      [ENABLED]  page            /admin/reports/dblog
```

Note: `moderated_content` view sits at `/admin/content/moderated`, NOT at the candidate `/moderated-content`. No view (enabled or disabled) declares `/moderated-content` or `/this-is-free-xyz`.

## Command 4 — Confirm /blog target is a real entity canonical; re-verify moderated_content path

```
vendor/bin/drush php:eval '... match(/page/2) entity present; moderated_content display path ...'
```
- `/blog` -> `/page/2` -> route `entity.canvas_page.canonical`, entity present (canvas_page).
- `moderated_content` view display path = `/admin/content/moderated` (ENABLED) — does not collide with `/moderated-content`.

## Command 5 — Confirm entity exists; re-confirm safe paths unclaimed

```
vendor/bin/drush php:eval '... load canvas_page id=2; re-check alias resolution for the two safe paths ...'
```
- canvas_page entity id=2 exists, label="Blog" — `/blog` canonical page responds. → UNSAFE (entity).
- `/this-is-free-xyz` -> internal unchanged (no alias). `/moderated-content` -> internal unchanged (no alias).

---

## Conclusions

| Path | Safe | blocker_kind | Reason |
|------|------|--------------|--------|
| /this-is-free-xyz | true | null | No route, no alias, no view (enabled or disabled) claims it. |
| /moderated-content | true | null | No route/alias; the moderated_content view lives at /admin/content/moderated, not here. |
| /blog | false | entity | Alias -> /page/2, route entity.canvas_page.canonical; canvas_page id=2 ("Blog") exists. |
| /search | false | view | ENABLED view `search` page display + active route view.search.page. |
| /admin/content/files | false | latent_disabled_view | DISABLED view `files` (page_1) declares this exact page path. |
| /admin/content/media/scheduled | false | latent_disabled_view | DISABLED view `scheduler_scheduled_media` (overview) declares this exact page path. |
