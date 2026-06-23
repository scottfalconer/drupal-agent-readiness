# Alias safety transcript — equipped-2

Site root: <workspace>/tmp/agent-readiness/as-eq-2
All drush calls prefixed with `PHP_INI_SCAN_DIR=/tmp/ar-phpini` and run from the site root.
Resolved against the LIVE site (Drupal 11.3.11, Haven, SQLite) with the site_architecture module.

## Commands run

### 1. drush status
`vendor/bin/drush status`
=> Drupal 11.3.11, default theme haven_theme, DB connected (sqlite). Confirmed live site bootstraps.

### 2. site-architecture:path-owner /this-is-free-xyz --format=json
=> claimed=false, alias=null, owner=null, negative_contracts=[], no latent_claims.
Advice: "No route, alias, view or entity currently responds to this path. It is unclaimed."
RESOLUTION: unclaimed. SAFE.

### 3. site-architecture:path-owner (batch) for /moderated-content /blog /search /admin/content/files /admin/content/media/scheduled

- /moderated-content => claimed=false, alias=null, owner=null, no negative_contracts, no latent_claims. Unclaimed. SAFE.
- /blog => claimed=true. alias is_alias=true internal_path=/page/2. owner kind=entity, entity_type=canvas_page, id=2, label="Blog", route entity.canvas_page.canonical, published. Negative contract: "Do not create another surface at /blog: it is already the canonical page of canvas_page 2." NOT SAFE (immediate conflict).
- /search => claimed=true. owner kind=view, view_id=search, display_id=page, config views.view.search, route view.search.page, base_table search_api_index_content, path_pattern /search. Negative contract: "Do not create a node or other entity with the URL alias /search: the alias would shadow this view and hijack the page." NOT SAFE (view shadow).
- /admin/content/files => claimed=false now, BUT latent_claims: disabled_view files:page_1 (views.view.files). Negative contract: "Disabled view files:page_1 declares this path. If that view is ever enabled it will collide with whatever you create here." Advice: claiming is risky. NOT SAFE (latent).
- /admin/content/media/scheduled => claimed=false now, BUT latent_claims: disabled_view scheduler_scheduled_media:overview (views.view.scheduler_scheduled_media). Negative contract: "Disabled view scheduler_scheduled_media:overview declares this path. If that view is ever enabled it will collide." Advice: claiming is risky. NOT SAFE (latent).

### 4. php:eval — enumerate ALL views displays with paths + enabled status (independent cross-check)
Confirmed path ownership and disabled status:
- files:page_1 path=/admin/content/files enabled=0
- scheduler_scheduled_media:overview path=/admin/content/media/scheduled enabled=0
- search:page path=/search enabled=1
- moderated_content:moderated_content path=/admin/content/moderated enabled=1  <-- NOT /moderated-content
- (no view declares /moderated-content or /this-is-free-xyz)
Key finding: the moderated_content view is at /admin/content/moderated, so /moderated-content has no view collision.

### 5. php:eval — alias repository lookup + router pattern check (independent cross-check)
Aliases (lookupByAlias, en):
- /this-is-free-xyz => (none)
- /moderated-content => (none)
- /blog => /page/2   (confirms canvas_page 2 alias)
- /search => (none)
- /admin/content/files => (none)
- /admin/content/media/scheduled => (none)
Enabled-route pattern match (getRoutesByPattern):
- /moderated-content => 0
- /this-is-free-xyz => 0
- /search => 1   (view.search.page)
- /admin/content/files => 0
- /admin/content/media/scheduled => 0

### 6. drush pml + php:eval moduleExists — confirm latent-claim activation is "routine"
- file => enabled, media => enabled, scheduler => enabled, content_moderation => enabled, views => enabled
- scheduler_media => disabled
Finding: provider modules for both disabled views are already enabled, so activating those
views (File-usage report; Scheduler media overview) is a routine config toggle, not a code
install. This makes the latent claims a real post-config-change collision risk, not theoretical.

## Conclusions
- /this-is-free-xyz  : SAFE (unclaimed)
- /moderated-content : SAFE (unclaimed; moderated_content view is at /admin/content/moderated)
- /blog              : NOT SAFE (canonical alias of canvas_page 2)
- /search            : NOT SAFE (shadows enabled search view)
- /admin/content/files            : NOT SAFE (latent disabled view files:page_1; file module enabled)
- /admin/content/media/scheduled  : NOT SAFE (latent disabled view scheduler_scheduled_media:overview; scheduler+media enabled)
