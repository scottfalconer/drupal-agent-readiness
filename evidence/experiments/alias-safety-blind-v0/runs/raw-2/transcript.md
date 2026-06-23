# Alias safety check — transcript (raw-2)

Site: Drupal 11.3.11, Haven theme (haven_theme), SQLite. Core drush only; site_architecture NOT installed.
Site root: <workspace>/tmp/agent-readiness/as-raw-2
All drush invoked from that dir with `PHP_INI_SCAN_DIR=/tmp/ar-phpini` (128M system PHP OOM workaround).
Read-only throughout — no config/content modified.

Candidate paths:
/this-is-free-xyz, /moderated-content, /blog, /search, /admin/content/files, /admin/content/media/scheduled

## 1. drush status
Confirmed Drupal 11.3.11, SQLite db at sites/default/files/.sqlite, bootstrap OK, theme haven_theme.

## 2. Alias manager forward lookup (getPathByAlias)
```
/this-is-free-xyz => /this-is-free-xyz        (unchanged => no alias)
/moderated-content => /moderated-content      (unchanged => no alias)
/blog => /page/2                              (ALIAS EXISTS, points to /page/2)
/search => /search                            (unchanged => no alias)
/admin/content/files => /admin/content/files  (unchanged => no alias)
/admin/content/media/scheduled => /admin/content/media/scheduled (unchanged => no alias)
```

## 3. Router match (router.no_access_checks)
```
/this-is-free-xyz => NO_ROUTE
/moderated-content => NO_ROUTE
/blog => entity.canvas_page.canonical   (resolves via alias to canvas_page)
/search => view.search.page             (static route — search View page)
/admin/content/files => NO_ROUTE
/admin/content/media/scheduled => NO_ROUTE
```

## 4. Exact static route scan (router.route_provider getAllRoutes)
Only `/search` has an exact static route: `view.search.page => /search`.
None of the others have an exact static route *currently*.

## 5. Enabled modules of interest
content_moderation, workflows, file, media, media_library, node, views, views_ui,
path, path_alias, canvas (1.5.1), pathauto (1.15), scheduler (2.3.0),
scheduler_content_moderation_integration, search_api(+db), media_file_delete,
media_library_bulk_upload, focal_point, crop, svg_image. Scheduler is installed.

## 6. ALL view page-display paths (enabled AND disabled) — the key step
```
canvas_pages [ENABLED]    /admin/content/pages
content [ENABLED]         /admin/content/node
files [DISABLED]          /admin/content/files          <-- candidate collision
files [DISABLED]          /admin/content/files/usage/%
media [ENABLED]           /admin/content/media
media_library [ENABLED]   /admin/content/media-grid, -widget, -widget-table
moderated_content [ENABLED] /admin/content/moderated     <-- NOT /moderated-content
scheduler_scheduled_content [ENABLED] /admin/content/scheduled
scheduler_scheduled_media [DISABLED]  /admin/content/media/scheduled  <-- candidate collision
scheduler_scheduled_taxonomy_term [DISABLED] /admin/structure/taxonomy/scheduled
search [ENABLED]          /search                        <-- candidate collision (live route)
taxonomy_term [ENABLED]   /taxonomy/term/%
... (user_admin_people, watchdog, redirect, etc.)
```

## 7. Confirmation of disabled-view details
- `files`: DISABLED, page display path exactly `/admin/content/files`. Enabling the
  (core-shipped, default-off) Files view registers a route at this path.
- `scheduler_scheduled_media`: DISABLED, page display path exactly
  `/admin/content/media/scheduled`. Scheduler module installed; enabling media
  scheduling / this view registers a route here. (No media type currently has
  third_party_settings.scheduler set — all null — confirming it's off by default
  and would be turned on via routine config.)
- `moderated_content`: ENABLED, but at `/admin/content/moderated` — does NOT match
  the candidate `/moderated-content`.

## 8. path_alias table rows for candidates
```
/this-is-free-xyz              NO_ALIAS_ROW
/moderated-content             NO_ALIAS_ROW
/blog                          EXISTING_ALIAS id=23 -> /page/2
/search                        NO_ALIAS_ROW
/admin/content/files           NO_ALIAS_ROW
/admin/content/media/scheduled NO_ALIAS_ROW
canvas_page 2 exists: YES, title="Blog"
```

## 9. Final route/view confirms
`view.search.page` path = /search; search view = ENABLED (live conflict).

## Verdicts
- /this-is-free-xyz — SAFE: no route/view/alias.
- /moderated-content — SAFE: moderated_content view is at /admin/content/moderated; no route/alias here.
- /blog — NOT SAFE: existing alias id=23 -> /page/2 (canvas_page "Blog").
- /search — NOT SAFE: live static route view.search.page (enabled search View).
- /admin/content/files — NOT SAFE: disabled core 'files' View page display at this exact path; enabling it claims the route.
- /admin/content/media/scheduled — NOT SAFE: disabled 'scheduler_scheduled_media' View page display at this exact path; enabling media scheduling claims the route.
