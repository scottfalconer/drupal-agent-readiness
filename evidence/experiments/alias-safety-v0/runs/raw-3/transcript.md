# Alias-safety assessment transcript — raw-3

Site: Drupal 11.3.11 (Haven), SQLite. Site root: `<workspace>/tmp/agent-readiness/as-raw-3`
(Note: the prompt-suggested `.../as-raw-3/site` did not exist; the Drupal root is `as-raw-3` itself, with `web/`, `vendor/`, `composer.json`.)

All drush invoked as: `cd <site root> && PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush ...`

Method: resolve every candidate against (1) `router.no_access_checks`, (2) `path_alias.manager` (alias -> internal path, then re-match router on the internal path), and (3) ALL `view` config entities — enumerating every page-display path and its enabled/disabled status to catch latent disabled-view claims.

---

## Command 1 — drush status (environment verify)

`drush status`

Result: Drupal 11.3.11, SQLite DB connected, default theme haven_theme, Drush 13.7.3. Bootstrap successful.

## Command 2 — router match on each candidate (raw incoming path)

`php:eval` matching each path via `router.no_access_checks`:

```
/this-is-free-xyz              => NO MATCH (ResourceNotFound)
/moderated-content             => NO MATCH (ResourceNotFound)
/blog                          => MATCH route=entity.canvas_page.canonical
/search                        => MATCH route=view.search.page
/admin/content/files           => NO MATCH (ResourceNotFound)
/admin/content/media/scheduled => NO MATCH (ResourceNotFound)
```

## Command 3 — alias resolution (path_alias.manager::getPathByAlias)

```
/this-is-free-xyz              => internal: /this-is-free-xyz        (identity: no alias)
/moderated-content             => internal: /moderated-content       (identity: no alias)
/blog                          => internal: /page/2                  (ALIAS -> /page/2)
/search                        => internal: /search                  (identity)
/admin/content/files           => internal: /admin/content/files     (identity)
/admin/content/media/scheduled => internal: /admin/content/media/scheduled (identity)
```

`/blog` is an alias pointing at internal path `/page/2`.

## Command 4 — enumerate ALL view page displays (enabled + disabled)

`php:eval` over `view` storage, listing each `display_plugin === "page"` display, its path, and status:

```
canvas_pages                [ENABLED]  page_1            /admin/content/pages
content                     [ENABLED]  page_1            /admin/content/node
files                       [DISABLED] page_1            /admin/content/files          <-- candidate
files                       [DISABLED] page_2            /admin/content/files/usage/%
media                       [ENABLED]  media_page_list   /admin/content/media
media_library               [ENABLED]  page              /admin/content/media-grid
media_library               [ENABLED]  widget            /admin/content/media-widget
media_library               [ENABLED]  widget_table      /admin/content/media-widget-table
moderated_content           [ENABLED]  moderated_content /admin/content/moderated      (NOT /moderated-content)
redirect                    [ENABLED]  page_1            /admin/config/search/redirect
redirect_404                [ENABLED]  page_1            /admin/config/search/redirect/404
scheduler_scheduled_content [ENABLED]  overview          /admin/content/scheduled
scheduler_scheduled_content [ENABLED]  user_page         /user/%user/scheduled
scheduler_scheduled_media   [DISABLED] overview          /admin/content/media/scheduled <-- candidate
scheduler_scheduled_media   [DISABLED] user_page         /user/%user/scheduled_media
scheduler_scheduled_taxonomy_term [DISABLED] overview    /admin/structure/taxonomy/scheduled
search                      [ENABLED]  page              /search                        <-- candidate
taxonomy_term               [ENABLED]  page_1            /taxonomy/term/%
user_admin_people           [ENABLED]  page_1            /admin/people/list
watchdog                    [ENABLED]  page              /admin/reports/dblog
```

Key findings:
- `/admin/content/files` is claimed by the **DISABLED** `files` view (page_1) -> latent claim.
- `/admin/content/media/scheduled` is claimed by the **DISABLED** `scheduler_scheduled_media` view (overview) -> latent claim.
- `/moderated-content` is NOT a view path; the `moderated_content` view lives at `/admin/content/moderated`.

## Command 5 — confirm /blog entity + /moderated-content emptiness

`php:eval`:
```
/blog internal = /page/2
  router(internal) route=entity.canvas_page.canonical
  entity: canvas_page id=2 label=Blog          <-- real canonical entity page
/moderated-content internal = /moderated-content
  router(internal) NO MATCH
  getAliasByPath(/moderated-content) = /moderated-content  (no alias either direction)
```

## Command 6 — final route re-check on the three remaining paths (on internal path)

`php:eval`:
```
/this-is-free-xyz              | internal=/this-is-free-xyz              | aliasByPath=/this-is-free-xyz              | NO MATCH (ResourceNotFound)
/admin/content/files           | internal=/admin/content/files           | aliasByPath=/admin/content/files           | NO MATCH (ResourceNotFound)
/admin/content/media/scheduled | internal=/admin/content/media/scheduled | aliasByPath=/admin/content/media/scheduled | NO MATCH (ResourceNotFound)
```

Confirms the disabled views register no active route — but their declared page-display paths are latent claims (would collide if re-enabled).

---

## Final assessments

| Path | Active route? | Active view page? | Entity page? | Disabled-view latent claim? | Verdict | blocker_kind |
|------|---------------|-------------------|--------------|-----------------------------|---------|--------------|
| /this-is-free-xyz | no | no | no | no | SAFE | null |
| /moderated-content | no | no | no | no (view is at /admin/content/moderated) | SAFE | null |
| /blog | yes (entity.canvas_page.canonical via alias->/page/2) | no | yes (canvas_page id=2 "Blog") | n/a | UNSAFE | entity |
| /search | yes (view.search.page) | yes (search view ENABLED @ /search) | no | n/a | UNSAFE | view |
| /admin/content/files | no | no | no | yes (files view DISABLED @ /admin/content/files) | UNSAFE | latent_disabled_view |
| /admin/content/media/scheduled | no | no | no | yes (scheduler_scheduled_media DISABLED @ /admin/content/media/scheduled) | UNSAFE | latent_disabled_view |
