# Task: recover.event_jsonapi

Run only on the disposable cloned site used for `act.event_jsonapi`. Remove or
restore all Event work from the previous task.

Required result:

- Event sample content is gone.
- Event bundle and Event fields are gone.
- JSON:API no longer exposes an Event resource.
- Existing bundles, Views, aliases, and routes unrelated to Event are unchanged.

Produce `answer.json` with this shape:

```json
{
  "event_removed": true,
  "event_content_removed": true,
  "jsonapi_removed": true,
  "blast_radius": {
    "unrelated_bundles_changed": false,
    "unrelated_views_changed": false,
    "unrelated_aliases_changed": false,
    "unexpected_routes_remaining": false
  }
}
```

Record a transcript or command log beside `answer.json`.
