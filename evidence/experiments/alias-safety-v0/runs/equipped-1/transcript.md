# Alias-safety assessment transcript

Site: `<workspace>/tmp/agent-readiness/aliassafety-equipped/site`
Tool: `site-architecture:path-owner` (site_architecture module installed)
All drush invocations prefixed with `PHP_INI_SCAN_DIR=/tmp/ar-phpini` and run from the site dir.

A path is UNSAFE if an active route / active Views page display / entity canonical
already responds, OR a DISABLED view declares it as a page-display path (latent claim).
Otherwise SAFE.

---

## /this-is-free-xyz

Command:
```
vendor/bin/drush site-architecture:path-owner /this-is-free-xyz --format=json
```
Resolved to: `claimed=false`, owner=null, latent_claims=none, negative_contracts=[].
No route/alias/view/entity responds; no latent disabled-view claim.

**Verdict: SAFE** (blocker_kind: null)

---

## /moderated-content

Command:
```
vendor/bin/drush site-architecture:path-owner /moderated-content --format=json
```
Resolved to: `claimed=false`, owner=null, latent_claims KEY ABSENT, negative_contracts=[].
Re-verified via JSON parse: claimed=False, latent_claims=KEY_ABSENT, negative_contracts=[].
No active surface and no latent disabled-view claim.

**Verdict: SAFE** (blocker_kind: null)

---

## /blog

Command:
```
vendor/bin/drush site-architecture:path-owner /blog --format=json
```
Resolved to: `claimed=true`. Owner kind=`entity`, entity_type=`canvas_page`,
id=2, label="Blog", route=`entity.canvas_page.canonical`, canonical=true, published=true.
Alias `/blog` -> internal `/page/2`.
An entity canonical page already responds here.

**Verdict: UNSAFE** (blocker_kind: entity)

---

## /search

Command:
```
vendor/bin/drush site-architecture:path-owner /search --format=json
```
Resolved to: `claimed=true`. Owner kind=`view`, view_id=`search`, display_id=`page`,
route=`view.search.page`, path_pattern=`/search`, base_table=`search_api_index_content`.
An active Views page display already responds here.

**Verdict: UNSAFE** (blocker_kind: view)

---

## /admin/content/files

Command:
```
vendor/bin/drush site-architecture:path-owner /admin/content/files --format=json
```
Resolved to: `claimed=false`, owner=null, but latent_claims present:
`disabled_view` files:page_1 (config views.view.files) declares this path.
Negative contract warns: enabling that view would collide.

**Verdict: UNSAFE** (blocker_kind: latent_disabled_view)

---

## /admin/content/media/scheduled

Command:
```
vendor/bin/drush site-architecture:path-owner /admin/content/media/scheduled --format=json
```
Resolved to: `claimed=false`, owner=null, but latent_claims present:
`disabled_view` scheduler_scheduled_media:overview (config views.view.scheduler_scheduled_media)
declares this path. Negative contract warns: enabling that view would collide.

**Verdict: UNSAFE** (blocker_kind: latent_disabled_view)

---

## Summary

| Path | Safe | Blocker kind |
|------|------|--------------|
| /this-is-free-xyz | true | null |
| /moderated-content | true | null |
| /blog | false | entity |
| /search | false | view |
| /admin/content/files | false | latent_disabled_view |
| /admin/content/media/scheduled | false | latent_disabled_view |
