# Alias safety check — raw-3 (live site)

Site: Drupal 11.3.11, Haven theme, sqlite. Site root: tmp/agent-readiness/as-raw-3
All drush run with `PHP_INI_SCAN_DIR=/tmp/ar-phpini` from the site root. CORE drush only; site_architecture NOT installed.

## Commands run

### 1. `drush status`
Confirmed Drupal 11.3.11, DB connected (sqlite), bootstrap successful.

### 2. Router match (`router.no_access_checks->match()`) for each candidate
- /this-is-free-xyz => NO ROUTE (ResourceNotFoundException)
- /moderated-content => NO ROUTE
- /blog => ROUTE: entity.canvas_page.canonical
- /search => ROUTE: view.search.page
- /admin/content/files => NO ROUTE
- /admin/content/media/scheduled => NO ROUTE

### 3. Alias resolution (`path_alias.manager->getPathByAlias()`)
- /blog => /page/2  (EXISTING ALIAS — taken)
- all others resolve to themselves (no alias)

### 4. path_alias table dump
- /blog => /page/2 (id=23). Confirmed /blog is a live alias to a canvas_page node.
- No alias rows for /this-is-free-xyz, /moderated-content, /search, /admin/content/files, /admin/content/media/scheduled.

### 5. Route-by-pattern lookup + module check
- /search => view.search.page [/search] (active)
- /admin/content/scheduled => view.scheduler_scheduled_content.overview (active, sibling)
- /admin/content/media => entity.media.collection + view.media.media_page_list (active, sibling)
- /moderated-content, /admin/content/files, /admin/content/media/scheduled => no route by pattern currently.
- Modules ENABLED: search_api, content_moderation, workflows, media, scheduler, file, views, node, path, path_alias, canvas. (core `search` module NOT enabled.)

### 6. All views: status + page display paths
Key findings:
- views.view.search [ENABLED] page:/search  -> /search is live now.
- views.view.files [DISABLED] page_1:/admin/content/files  -> path exists in config, claimed if view enabled.
- views.view.scheduler_scheduled_media [DISABLED] overview:/admin/content/media/scheduled -> claimed if view enabled.
- views.view.moderated_content [ENABLED] moderated_content:/admin/content/moderated -> NOT /moderated-content.
- views.view.content -> /admin/content/node; media_library -> /admin/content/media-grid etc.

### 7. Cross-check aliases, paths, menu links
- path_alias rows touching each candidate: only /blog has 1.
- No menu_link_content points at any candidate path.

### 8. Provenance of the two DISABLED page views
- views.view.files: status=false, module deps = file,user. `file` module is ENABLED -> enabling the Files admin view is a routine action that claims /admin/content/files.
- views.view.scheduler_scheduled_media: status=false, module deps = media,user. `scheduler` + `media` ENABLED -> enabling media scheduling (routine Scheduler config) activates this view at /admin/content/media/scheduled.

### 9. /moderated-content final confirm
- moderated_content view path = /admin/content/moderated (only display path).
- No route anywhere with path exactly /moderated-content.
- => /moderated-content is a free top-level path; node aliases live at root, so safe.

## Conclusions
- /this-is-free-xyz : SAFE (nothing claims it now or via routine config).
- /moderated-content : SAFE (the moderation view is at /admin/content/moderated, not here).
- /blog : NOT SAFE (existing alias /blog => /page/2).
- /search : NOT SAFE (active view route view.search.page).
- /admin/content/files : NOT SAFE (disabled views.view.files claims it once enabled; file module already on; also /admin namespace).
- /admin/content/media/scheduled : NOT SAFE (disabled views.view.scheduler_scheduled_media claims it once media scheduling enabled; also /admin namespace).
