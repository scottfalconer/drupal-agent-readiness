# Alias-safety resolution transcript

Site: Drupal 11.3.11, SQLite, Haven theme. Core drush only; site_architecture NOT installed.
All resolution done against the LIVE site via `php:eval` (router.no_access_checks, path_alias.manager, view entity storage). Read-only.

Candidate paths: /this-is-free-xyz, /moderated-content, /blog, /search, /admin/content/files, /admin/content/media/scheduled

## Command 1 — drush status (sanity)
`vendor/bin/drush status`
Drupal 11.3.11, SQLite at sites/default/files/.sqlite, bootstrap successful. Site is live.

## Command 2 — router match (router.no_access_checks) for all candidates
```
$router = \Drupal::service("router.no_access_checks");
foreach ($paths as $p) { $router->match($p); }
```
Result:
- /this-is-free-xyz             => NO ROUTE (ResourceNotFoundException)
- /moderated-content           => NO ROUTE (ResourceNotFoundException)
- /blog                        => ROUTE: entity.canvas_page.canonical
- /search                      => ROUTE: view.search.page
- /admin/content/files         => NO ROUTE (ResourceNotFoundException)
- /admin/content/media/scheduled => NO ROUTE (ResourceNotFoundException)

## Command 3 — alias resolution (path_alias.manager getPathByAlias) for all candidates
```
$am = \Drupal::service("path_alias.manager");
foreach ($paths as $p) { $am->getPathByAlias($p); }
```
Result:
- /this-is-free-xyz             => /this-is-free-xyz   (NO ALIAS)
- /moderated-content           => /moderated-content   (NO ALIAS)
- /blog                        => /page/2              (ALIAS EXISTS -> canvas_page canonical)
- /search                      => /search              (NO ALIAS)
- /admin/content/files         => /admin/content/files (NO ALIAS)
- /admin/content/media/scheduled => /admin/content/media/scheduled (NO ALIAS)

## Command 4 — scan ALL views (incl. DISABLED) for page-display paths matching candidates
```
$views = \Drupal::entityTypeManager()->getStorage("view")->loadMultiple();  // 21 views
```
Matches against candidates:
- VIEW files                      [DISABLED] display page_1   path=/admin/content/files            <<< MATCH (latent)
- VIEW scheduler_scheduled_media  [DISABLED] display overview path=/admin/content/media/scheduled   <<< MATCH (latent)
- VIEW search                     [ENABLED]  display page     path=/search                          <<< MATCH (active)

## Command 5 — full dump of every view page-display path + status (completeness check)
Confirms no other candidate is claimed. Notably the moderated_content view's page path is
/admin/content/moderated (ENABLED), NOT /moderated-content — so /moderated-content is unclaimed.
Relevant rows:
- files [DISABLED] page_1 => /admin/content/files
- files [DISABLED] page_2 => /admin/content/files/usage/%
- scheduler_scheduled_media [DISABLED] overview => /admin/content/media/scheduled
- moderated_content [ENABLED] moderated_content => /admin/content/moderated
- search [ENABLED] page => /search
(no view declares /this-is-free-xyz or /moderated-content)

## Command 6 — confirm /blog and /search route targets
```
$router->match("/blog");   => entity.canvas_page.canonical, canvas_page id=2 label="Blog"
$router->match("/page/2"); => entity.canvas_page.canonical
$router->match("/search"); => view.search.page, view_id=search, display=page
```

## Command 7 — confirm no path_alias rows claim the free / disabled-view paths
```
SELECT COUNT(*) FROM path_alias WHERE alias = :p
```
- /this-is-free-xyz             => 0
- /moderated-content           => 0
- /admin/content/files         => 0
- /admin/content/media/scheduled => 0

## Final assessments
| Path | Safe | Blocker kind | Reason |
|---|---|---|---|
| /this-is-free-xyz | true | null | No route, no alias, no view page-display |
| /moderated-content | true | null | No route, no alias; moderated_content view lives at /admin/content/moderated |
| /blog | false | entity | Alias to /page/2, canvas_page entity id=2 "Blog" canonical responds here |
| /search | false | view | Active view.search.page (search view, enabled) responds here |
| /admin/content/files | false | latent_disabled_view | DISABLED view "files" declares this page-display path |
| /admin/content/media/scheduled | false | latent_disabled_view | DISABLED view "scheduler_scheduled_media" declares this page-display path |
