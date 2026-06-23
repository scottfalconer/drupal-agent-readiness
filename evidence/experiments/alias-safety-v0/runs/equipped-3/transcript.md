# Alias-safety assessment transcript — equipped-3

Site root: `<workspace>/tmp/agent-readiness/as-eq-3`
(The prompt-provided path `.../as-eq-3/site` did not exist; `as-eq-3` itself is the Drupal docroot.)
All drush commands prefixed with `PHP_INI_SCAN_DIR=/tmp/ar-phpini` and run from the site root.
Resolution method: `vendor/bin/drush site-architecture:path-owner <path> --format=json` (live site).

A path is UNSAFE if an active route / active Views page display / entity canonical responds there,
OR a DISABLED view declares that path as a page-display path (latent claim). Otherwise SAFE.

---

## Environment verification

### `drush status`
```
Drupal version : 11.3.11
Database       : Connected
Drupal bootstrap : Successful
```

### `drush list | grep site-architecture`
```
site-architecture:brief       Emits the generated site brief.
site-architecture:path-owner  Explains which subsystem owns a path.
site-architecture:surfaces    Lists generated site surfaces.
```
`site-architecture:path-owner` confirmed available.

---

## Per-path resolution

### 1. `vendor/bin/drush site-architecture:path-owner /this-is-free-xyz --format=json`
- `claimed: false`, `owner: null`, no `latent_claims`, no negative contracts.
- Advice: "No route, alias, view or entity currently responds to this path. It is unclaimed."
- **Resolved to: nothing — unclaimed.**
- Verdict: **SAFE** (blocker_kind = null)

### 2. `vendor/bin/drush site-architecture:path-owner /moderated-content --format=json`
- `claimed: false`, `owner: null`, no `latent_claims`, no negative contracts.
- Advice: "No route, alias, view or entity currently responds to this path. It is unclaimed."
- Cross-check (name looked suspicious — core has a moderated-content view):
  - `drush views:list | grep moderat` → `moderated_content … Enabled`
  - `drush config:get views.view.moderated_content` → enabled view, but its page display path is
    `admin/content/moderated`, **not** `/moderated-content`. No display declares `/moderated-content`.
  - So the enabled moderated-content view lives at a *different* path; `/moderated-content` is genuinely free.
- **Resolved to: nothing — unclaimed (path name is a near-miss decoy for `/admin/content/moderated`).**
- Verdict: **SAFE** (blocker_kind = null)

### 3. `vendor/bin/drush site-architecture:path-owner /blog --format=json`
- `claimed: true`.
- `owner.kind: entity`, entity_type `canvas_page`, id 2, label "Blog",
  route `entity.canvas_page.canonical`, `canonical: true`, published.
- Alias: `/blog` → internal `/page/2` (canvas_page 2 canonical `/canvas_page/2`).
- Negative contract: "Do not create another surface at /blog: it is already the canonical page of canvas_page 2."
- **Resolved to: entity canonical page (canvas_page 2 "Blog").**
- Verdict: **UNSAFE** (blocker_kind = entity)

### 4. `vendor/bin/drush site-architecture:path-owner /search --format=json`
- `claimed: true`.
- `owner.kind: view`, view_id `search`, display_id `page`, route `view.search.page`,
  base_table `search_api_index_content`, path_pattern `/search`.
- Negative contract: "Do not create a node or other entity with the URL alias /search: the alias would shadow this view."
- **Resolved to: active Views page display search:page.**
- Verdict: **UNSAFE** (blocker_kind = view)

### 5. `vendor/bin/drush site-architecture:path-owner /admin/content/files --format=json`
- `claimed: false`, `owner: null`, BUT `latent_claims` present:
  `{kind: disabled_view, view_id: files, display_id: page_1, config_id: views.view.files}`.
- Negative contract: "Disabled view files:page_1 declares this path. If that view is ever enabled it will collide."
- Cross-check: `drush config:get views.view.files` → `status: False` (disabled);
  display `page_1` (plugin page) path `admin/content/files`. Latent claim confirmed.
- **Resolved to: latent claim from DISABLED view files:page_1.**
- Verdict: **UNSAFE** (blocker_kind = latent_disabled_view)

### 6. `vendor/bin/drush site-architecture:path-owner /admin/content/media/scheduled --format=json`
- `claimed: false`, `owner: null`, BUT `latent_claims` present:
  `{kind: disabled_view, view_id: scheduler_scheduled_media, display_id: overview, config_id: views.view.scheduler_scheduled_media}`.
- Negative contract: "Disabled view scheduler_scheduled_media:overview declares this path. If that view is ever enabled it will collide."
- Cross-check: `drush config:get views.view.scheduler_scheduled_media` → `status: False` (disabled);
  display `overview` (plugin page) path `admin/content/media/scheduled`. Latent claim confirmed.
- **Resolved to: latent claim from DISABLED view scheduler_scheduled_media:overview.**
- Verdict: **UNSAFE** (blocker_kind = latent_disabled_view)

---

## Summary

| Path | Resolved to | Safe | blocker_kind |
|------|-------------|------|--------------|
| /this-is-free-xyz | unclaimed | true | null |
| /moderated-content | unclaimed (enabled moderated view is at /admin/content/moderated) | true | null |
| /blog | entity canonical (canvas_page 2) | false | entity |
| /search | active view search:page | false | view |
| /admin/content/files | disabled view files:page_1 (latent) | false | latent_disabled_view |
| /admin/content/media/scheduled | disabled view scheduler_scheduled_media:overview (latent) | false | latent_disabled_view |

Read-only throughout; no config/content modified.
