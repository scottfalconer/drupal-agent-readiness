# Site inventory transcript

All drush invocations run from the site root with the raised-memory ini prefix:
`cd .../site && PHP_INI_SCAN_DIR=/tmp/ar-phpini vendor/bin/drush ...`

## 1. Site status
`drush status --format=json`
- Drupal 11.3.11, SQLite, theme `haven_theme`, admin theme `gin`.
- `install-profile: false`.
- config-sync dir = `<root>/config/sync`.
- command runner = `vendor/bin/drush` (drush 13.7.3, works directly; no ddev/dr needed).

## 2. Install profile / config source
`drush php:eval` — `\Drupal::installProfile()` => `false`; `core.extension` profile => NULL.
`ls config/sync | wc -l` => `0` (empty).
=> active_config_source = database; config_sync_status = empty.

## 3. Provenance (composer)
`cat composer.json` (python parse): root package name = `drupal/cms`, `version` = `2.1.3`.
Requires include `drupal/haven ^1`, `drupal/drupal_cms_starter ^2`, `drupal/webform @beta`, etc.
`composer.lock`: drupal/haven 1.0.2, drupal_cms_starter 2.1.3, drupal_cms_site_template_base 1.x-dev.

## 4. Site template (live state)
`drush php:eval` reading `\Drupal::state()->get('project_browser.applied_recipes')`
=> `["<workspace>/haven-clean-install/recipes/haven"]`.
`install_task` state = `done`.
=> applied site template recipe = `haven` (recipe type `Site`, name "Haven", confirmed from recipe.yml header read-only).
Profile is null because the site was installed via the self-uninstalling `drupal_cms_installer` profile (present in `system.profile.files` state).

## 5. Path ownership (resolved against live router + alias system)
`drush php:eval` using `path_alias.manager` + `router.no_access_checks`, cross-checked with `router.route_provider->getRoutesByPattern()`:
- `/blog` -> alias to `/page/2`, route `entity.canvas_page.canonical`, entity_type=canvas_page id=2 => claimed, entity.
- `/node` -> no alias, no pattern route, router throws ResourceNotFoundException; default `view.frontpage` route ABSENT => unclaimed.
- `/home` -> alias to `/page/6`, route `entity.canvas_page.canonical`, entity_type=canvas_page id=6 => claimed, entity.
(system.site front page = `/page/6`, consistent with /home alias.)

## 6. Canvas pages
`drush php:eval` loading `canvas_page` storage:
- page_count = 7: Careers(1), Blog(2), About us(3), Leadership(4), Projects(5), Home(6), Page not found(7).
Scanned each page's `components` field JSON for view blocks; pages 2, 5, 6 embed views:
- page 2 (Blog): `block.views_block.blog-all`
- page 5 (Projects): `block.views_block.projects-all`, `block.views_block.projects-featured`
- page 6 (Home): `block.views_block.blog-latest`
Verified view/display IDs by loading `view` storage for `blog` and `projects`:
- blog block displays: all, latest, related; projects block displays: all, featured, latest, related.
=> embedded_listings = blog:all, projects:all, projects:featured, blog:latest.

## 7. Content model
`drush php:eval` loading `node_type` storage => bundles: blog, page, person_profile, project.
`workflow` storage => `basic_editorial` (type content_moderation) covers node bundles blog,page,person_profile,project.
=> moderation_enabled = true.

## 8. Pathauto
`drush php:eval`: module `pathauto` enabled = yes. `pathauto_pattern` storage, all status=enabled:
- blog_content:    `/blog/[node:created:html_month]/[node:title]`
- menu_path:       `/[node:menu-link:parents:join-path]/[node:title]`
- page_content:    `/[node:title]`
- project_content: `/projects/[node:created:html_month]/[node:title]`
=> enabled = true; 4 active patterns.
