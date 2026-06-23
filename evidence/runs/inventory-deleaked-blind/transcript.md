# Static inventory transcript — inventory-deleaked-blind

Read-only static inference. The site is NOT bootable (no vendor/, no DB). Every
value below was derived purely from files under `source-only/`. Where a value is
a runtime fact not provable from static source, that is flagged explicitly.

## Files read, in order, with conclusions

1. `source-only/` (directory listing via find) — Confirmed layout: top-level
   `composer.json`, `composer.lock`, `AGENTS.md`, `README.md`, empty `config/sync/`
   (only `.gitkeep` + `.htaccess`), and a populated `recipes/` tree. Recipe dirs
   include three Site templates: `byte`, `haven`, `drupal_cms_starter`.

2. `composer.json` —
   - `name` = `drupal/cms`, `version` = `2.1.3` → provenance.project_name / version.
   - Requires `drupal/haven ^1`, `drupal/byte ^1`, `drupal/drupal_cms_starter ^2`,
     `drupal/drupal_cms_installer ^2`, plus Drupal CMS feature recipes.
   - No `vendor/bin/dr` and no DDEV-independent runner declared; combined with
     AGENTS.md this points to `ddev drush` as the command runner.
   - `web-root: web/`, standard Drupal CMS scaffold.

3. `AGENTS.md` — "Local development uses `ddev`"; all Drush examples are
   `ddev drush <command>`. → command_runner = `ddev drush`.

4. `README.md` — Confirms this is the Drupal CMS product distribution. No template
   selection recorded here (installer chooses at runtime).

5. `config/sync/.gitkeep` (empty) and directory contents — `config/sync/` holds
   only `.gitkeep` and `.htaccess`, no exported config. → config_sync_status =
   `empty`; therefore the live/active config lives in the database →
   active_config_source = `database`.

6. `recipes/README.txt` — generic recipes-dir readme; no signal.

7. `recipes/haven/recipe.yml` — Site template "Haven" (type: Site).
   - `system.theme.default` = `haven_theme`; `system.site.page.front` = `/home`.
   - Installs `content_moderation`, `pathauto`, `canvas`, `views`, etc.
   - Description: non-profit template with blog, projects, people profiles.

8. `recipes/drupal_cms_starter/recipe.yml` — Site template "Starter" (type: Site),
   default theme `mercury`, also front `/home`. A competing template; not the one
   whose content/config matches the built site (see step 11+).

9. `recipes/drupal_cms_site_template_base/recipe.yml` — Base "Blank" template that
   other templates build on; default theme `blank`. Not a content-bearing template.

10. `recipes/drupal_cms_content_type_base/recipe.yml` — "Content Basics"; defines
    `node.type.page` and the base `page_content` pathauto pattern; enables pathauto.

11. Node type configs across recipes (`node.type.*.yml`) — Haven defines four node
    bundles: `blog` ("Blog post"), `page` ("Utility page"), `person_profile`,
    `project`. Matches Haven's stated content model.

12. `recipes/haven/config/views.view.blog.yml` — Blog view displays are
    `default`, `all` (block), `latest` (block), `related` (block), `rss` (feed at
    `blog/feed`). **No page display** → the view does NOT claim `/blog`.

13. `recipes/haven/config/views.view.projects.yml` (display scan) — Projects view
    displays are `default`, blocks (`all`, `featured`, `latest`, `related`),
    `rss` feed. **No page display** → does NOT claim `/projects`.

14. Haven pathauto patterns:
    - `pathauto.pattern.blog_content.yml` → `/blog/[node:created:html_month]/[node:title]`
    - `pathauto.pattern.page_content.yml` → `/[node:title]`
    - `pathauto.pattern.project_content.yml` → `/projects/[node:created:html_month]/[node:title]`
    - `pathauto.pattern.menu_path.yml` → `[node:menu-link:parents:join-path]/[node:title]`
    → pathauto.enabled = true (module also in install list), patterns as above.

15. `recipes/haven/content/canvas_page/*.yml` (7 files) — canvas_page page_count = 7.
    Path aliases declared in each:
    - `/home` (title "Home") — canvas_page
    - `/blog` — canvas_page
    - `/projects` — canvas_page
    - `/careers`, `/leadership`, `/about`, `/404` — canvas_page
    → `/blog` and `/home` are owned by canvas_page entities, not by a view page.

16. Embedded view listings inside the canvas pages (component_id scan):
    - `/home` embeds `block.views_block.blog-latest` → `blog:latest`
    - `/blog` embeds `block.views_block.blog-all` → `blog:all`
    - `/projects` embeds `block.views_block.projects-all` + `projects-featured`
      → `projects:all`, `projects:featured`
    → canvas.embedded_listings = [blog:all, blog:latest, projects:all, projects:featured].

17. `recipes/haven/config/workflows.workflow.basic_editorial.yml` — content_moderation
    workflow covering node bundles `blog`, `page`, `person_profile`, `project`.
    → content_model.moderation_enabled = true.

18. `recipes/haven/content/node/**` (alias scan) — node aliases follow the pathauto
    patterns (`/blog/2026-03/...`, `/projects/2026-03/...`, `/dr-alice-grossmann`,
    `/privacy-policy`, `/terms-service`). **No node** owns `/blog`, `/home`, or
    `/node`. Confirms those top-level paths are not node-canonical.

19. `composer.lock` (version blocks) — `drupal/cms` 2.1.3, `drupal/haven` 1.0.2,
    `drupal/byte` 1.0.2, `drupal/drupal_cms_starter` 2.1.3, `drupal/drupal_cms_installer`
    2.1.3. Confirms installed versions.

20. `recipes/byte/recipe.yml` (head) — "Byte" SaaS Site template; its content model
    is `drupal_cms_content_type_base` (page-centric), not the blog/projects/people
    model present in the built content. Ruled out as the applied template.

## Path-ownership conclusions

- `/blog` → claimed; owner_kind = `entity`; entity_type = `canvas_page`
  (canvas_page alias `/blog`, embedding the `blog:all` listing). The Blog *view*
  has no page display, so the view does not own this path.
- `/home` → claimed; owner_kind = `entity`; entity_type = `canvas_page`
  (front page is `/home` per recipe; alias `/home` belongs to a canvas_page).
- `/node` → claimed; owner_kind = `route` (Drupal core node front-page/listing
  route; not overridden by any entity alias and not the configured front page).

## Fields that could NOT be determined from static source (honest gaps)

- **site_template (`haven`)**: The *applied* install profile/site template is a
  runtime fact stored in the database (`core.extension` / the selected installer
  recipe). It is NOT recoverable with certainty from static source, because three
  Site recipes (`haven`, `byte`, `drupal_cms_starter`) ship in `recipes/`. `haven`
  is the best-supported inference: it is the only template whose shipped
  `config/` + `content/` (4 bundles blog/page/person_profile/project, the
  `/home /blog /projects /about /careers /leadership` canvas pages, `haven_theme`)
  matches a fully built site, and the task frames this as a Haven site. Treated as
  inferred, not proven. The Drupal CMS install *profile* is `drupal_cms_installer`.

- **`/node` ownership**: Asserted as the core node route by Drupal convention;
  the live router table (which could in principle be overridden) cannot be read
  statically. No override was found in any recipe, so `route` is the honest call.

- **canvas.page_count = 7**: This counts canvas_page *content* shipped by the
  Haven recipe. The live database could contain additional or fewer canvas pages
  created/deleted after install; the true runtime count is not knowable statically.

- **Exact runtime pathauto enablement state**: pathauto module is in Haven's
  install list and patterns ship enabled (`status: true`); a post-install admin
  could have disabled them. Reported as enabled per shipped config.
