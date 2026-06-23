# Inventory Read-only Transcript

Run ID: `inventory-independent-pass3-20260620150332`

Site inspected: `<workspace>/tmp/agent-readiness/inventory-independent-pass3-20260620150332/site`

Output files:

- `<workspace>/tmp/agent-readiness/inventory-independent-pass3-20260620150332/answer.json`
- `<workspace>/tmp/agent-readiness/inventory-independent-pass3-20260620150332/transcript.md`

Notes:

- This was a read-only inventory of the disposable run site.
- No generated smoke-run answers under `agent_readiness/runs` were read or copied.
- The baseline substrate at `<workspace>/haven-clean-install` was not modified.
- Normal Drupal reads may have touched cache state inside the disposable site.

## Command Log

1. `rg -n "Agent Readiness|inventory\\.read_only|agent-readiness|agent_readiness|Drupal Agent Readiness" <codex-home>/memories/MEMORY.md`
   - Purpose: quick memory pass for repository-specific agent-readiness context.
   - Result: found only broad framing notes, not prior inventory answers.

2. `pwd`
   - Workdir: site root.
   - Result: confirmed the disposable site root.

3. `ls`
   - Workdir: site root.
   - Result: confirmed Composer-managed Drupal site files, including `vendor`, `web`, `config`, and `recipes`.

4. `git status --short`
   - Workdir: `<workspace>`.
   - Result: parent worktree had unrelated existing changes; no repository files were edited.

5. `test -x vendor/bin/drush && vendor/bin/drush --version`
   - Result: `Drush Commandline Tool 13.7.3.0`.

6. `sed -n '1,220p' AGENTS.md`
   - Workdir: site root.
   - Result: read site-local agent guidance.

7. `vendor/bin/drush status --fields=bootstrap,drupal-version,db-status,site-uri,root --format=json`
   - Result: failed because `site-uri` is not a valid Drush status field.

8. `composer show drupal/cms --format=json`
   - Result: failed because `drupal/cms` is the root package, not an installed package entry.

9. `vendor/bin/drush config:get system.site --format=json`
   - Result: site name `Haven Clean Test`, front page `/page/6`, 404 page `/404`.

10. `vendor/bin/drush config:get core.extension --format=json`
    - Result: confirmed enabled modules and themes, including `canvas`, `content_moderation`, `pathauto`, `node`, `views`, and `haven_theme`.

11. `vendor/bin/drush status --format=json`
    - Result: bootstrap successful, Drupal `11.3.11`, SQLite DB connected, default theme `haven_theme`, config sync path `config/sync`.

12. `composer show --self --format=json`
    - Result: root package `drupal/cms`, version `2.1.3`, requires `drupal/haven`.

13. `composer show --locked --format=json`
    - Result: lock data confirmed installed Drupal CMS component versions; terminal output was truncated because it was large.

14. `vendor/bin/drush config:get core.extension module.pathauto --format=json`
    - Result: Pathauto enabled with module weight `1`.

15. `vendor/bin/drush php:eval '<raw probe for config storage, path resolution, entity definitions, bundles, config names, and Canvas pages>'`
    - Result: active config had 676 names in the DB-backed config table; `/blog` resolved to canvas page 2, `/home` to canvas page 6, `/node` was invalid; Canvas had 7 pages.

16. `vendor/bin/drush php:eval '<focused active config and sync storage probe>'`
    - Result: active config table exists with 676 rows; sync directory had 0 `.yml` files.

17. `vendor/bin/drush php:eval '<focused /blog, /node, /home alias and route probe>'`
    - Result: `/blog` -> `/page/2` -> `entity.canvas_page.canonical`; `/home` -> `/page/6` -> `entity.canvas_page.canonical`; `/node` invalid/unclaimed.

18. `vendor/bin/drush php:eval '<node bundle probe>'`
    - Result: node bundles: `blog`, `page`, `person_profile`, `project`.

19. `vendor/bin/drush php:eval '<content moderation and workflow probe>'`
    - Result: `content_moderation` enabled; workflow `basic_editorial` applies to node content.

20. `vendor/bin/drush php:eval '<Pathauto pattern probe>'`
    - Result: Pathauto enabled; patterns `blog_content`, `menu_path`, `page_content`, and `project_content`.

21. `vendor/bin/drush php:eval '<Canvas page and component usage probe>'`
    - Result: Canvas page count `7`; Canvas components included `block.views_block.blog-all`, `block.views_block.blog-latest`, `block.views_block.projects-all`, and `block.views_block.projects-featured`.

22. `vendor/bin/drush php:eval '<Views config entity probe>'`
    - Result: confirmed active Views block displays for `blog` and `projects`.

23. `vendor/bin/drush config:get system.site page.front page.404 --format=json`
    - Result: failed because `config:get` accepts only one key argument.

24. `composer show drupal/haven --format=json`
    - Result: template package `drupal/haven`, version `1.0.2`, installed at `recipes/haven`.

25. `vendor/bin/drush php:eval '<theme/front-page probe>'`
    - Result: default theme `haven_theme`, admin theme `gin`, front page `/page/6`, 404 path `/404`.

26. `vendor/bin/drush php:eval '<focused Canvas embedded Views block probe>'`
    - Result: embedded listings found on `/blog`, `/projects`, and `/home`.

27. `vendor/bin/drush php:eval '<Canvas page count and node content count probe>'`
    - Result: Canvas page count `7`; node counts: blog `3`, page `2`, person_profile `1`, project `3`.

28. `ls -l answer.json transcript.md`
    - Workdir: run output directory.
    - Result: both requested output files did not exist before writing.

## Key Evidence

- Command runner: `vendor/bin/drush`.
- Project provenance: `composer show --self --format=json` reported root package `drupal/cms` version `2.1.3`.
- Site template: root package required `drupal/haven`; `composer show drupal/haven --format=json` reported installed template package `drupal/haven`.
- Active config source: Drupal active config was present in the `config` database table with 676 rows.
- Config sync status: configured sync directory had 0 `.yml` files.
- Path ownership:
  - `/blog` resolved through alias `/page/2` to `entity.canvas_page.canonical` for Canvas page `Blog`.
  - `/node` did not validate as a live path.
  - `/home` resolved through alias `/page/6` to `entity.canvas_page.canonical` for Canvas page `Home`.
- Canvas: 7 Canvas pages; embedded Views blocks: `blog-all`, `blog-latest`, `projects-all`, and `projects-featured`.
- Content model: node bundles `blog`, `page`, `person_profile`, and `project`; content moderation enabled through `basic_editorial`.
- Pathauto: enabled, with four active patterns.
