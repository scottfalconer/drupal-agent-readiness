# Task: assess.alias_safety.told (control prompt v0.1)

You are assessing a running Drupal CMS/Haven site. Do not modify the site or
repository. Inspection commands that write normal Drupal cache data are
acceptable on the disposable cloned run site.

This is the told/control variant. It intentionally includes the safety criterion
that the headline fully blind prompt withholds.

## Goal

For each candidate path below, decide whether it is **safe** to claim with a new
node's URL alias - i.e. whether creating a node aliased to that path would be
free of collisions, now and after routine config changes.

A path is **UNSAFE** if ANY of these is true:

- An active route, Views page display, or entity canonical page already
  responds at that path (a new alias would be shadowed or would hijack it).
- A **disabled** view declares that path as a page-display path. This is a
  *latent claim*: if that view is ever enabled, it will collide with whatever
  you put there. Treat latent claims as unsafe.

Otherwise the path is **SAFE**.

Resolve this against the **live site** (router, alias system, and the full set
of views including disabled ones), not against source files.

## Candidate paths

- `/this-is-free-xyz`
- `/moderated-content`
- `/blog`
- `/search`
- `/admin/content/files`
- `/admin/content/media/scheduled`

## Produce answer.json with this shape

```json
{
  "assessments": {
    "/this-is-free-xyz": {"safe": "<bool>", "blocker_kind": "<'entity'|'view'|'route'|'latent_disabled_view'|null>"},
    "/moderated-content": {"safe": "<bool>", "blocker_kind": "<...>"},
    "/blog": {"safe": "<bool>", "blocker_kind": "<...>"},
    "/search": {"safe": "<bool>", "blocker_kind": "<...>"},
    "/admin/content/files": {"safe": "<bool>", "blocker_kind": "<...>"},
    "/admin/content/media/scheduled": {"safe": "<bool>", "blocker_kind": "<...>"}
  }
}
```

`blocker_kind` is `null` when the path is safe; otherwise it names what blocks
the path: `entity` (canonical entity page), `view` (active Views page),
`route` (module route), or `latent_disabled_view` (a disabled view declares it).

Record a transcript or command log beside `answer.json` showing the commands you
ran and what each candidate resolved to.
