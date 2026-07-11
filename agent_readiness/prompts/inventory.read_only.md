# Task: inventory.read_only (prompt v0.2, de-leaked)

You are evaluating a Drupal CMS/Haven site for agent readiness. Do not modify
the site or repository. If inspection commands write normal Drupal cache data,
that is acceptable only on the disposable cloned run site.

Inspect the **running site** and report what is actually true. The shape below is
a **schema with type/enum placeholders, not an answer key**. Every value must be
derived from live inspection of this specific site. Do not copy the placeholder
text. List only surfaces that actually exist on the site — fabricated or
guessed-but-absent entries (extra bundles, listings, or pathauto patterns) are
scored as errors, not as harmless extras.

Produce `answer.json` with this shape:

```json
{
  "command_runner": "<command that runs Drush on this site: 'vendor/bin/drush' | 'ddev drush' | 'vendor/bin/dr'>",
  "provenance": {
    "project_name": "<composer package that defines this distribution, or null>",
    "project_version": "<installed version of that package>",
    "site_template": "<install profile / site template machine name>",
    "active_config_source": "<where active config is read from: 'database' | 'sync'>",
    "config_sync_status": "<'empty' | 'populated'>"
  },
  "paths": {
    "/blog": {"claimed": "<bool>", "owner_kind": "<'entity' | 'view' | 'route' | 'unclaimed'>", "entity_type": "<entity type id if owner_kind=entity, else null>"},
    "/node": {"claimed": "<bool>", "owner_kind": "<...>"},
    "/home": {"claimed": "<bool>", "owner_kind": "<...>", "entity_type": "<entity type id or null>"}
  },
  "canvas": {
    "page_count": "<int: number of Canvas pages>",
    "embedded_listings": ["<each embedded Views listing as 'view_id:display_id'>"]
  },
  "content_model": {
    "bundles": ["<each node bundle machine name>"],
    "moderation_enabled": "<bool: is content moderation active for the content model?>"
  },
  "pathauto": {
    "enabled": "<bool>",
    "patterns": ["<each active pathauto pattern string>"]
  }
}
```

Resolve path ownership against the live router and alias system, not against
source files (an alias or a Canvas page can claim a path that no source file
mentions). Use live site truth, not source-file inference. Record a transcript
or command log beside `answer.json` showing the commands you ran and their
results.
