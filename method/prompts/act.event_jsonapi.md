# Task: act.event_jsonapi

Run only on a disposable cloned site. Create a minimal Event content type that
an external agent can verify through JSON:API.

This is a minimal write/evaluator smoke task, not the fuller editorial
Events-section roadmap task.

Required result:

- `event` node bundle exists.
- Required fields exist: `field_event_date`, `field_event_location`.
- One published sample Event exists.
- JSON:API access to the sample Event is verified.
- Existing bundles, Views, and aliases unrelated to Event are unchanged.

Produce `answer.json` with this shape:

```json
{
  "event": {
    "bundle_created": true,
    "required_fields": ["field_event_date", "field_event_location"],
    "published_sample_created": true
  },
  "jsonapi": {
    "verified": true,
    "sample_fetch_status": 200
  },
  "blast_radius": {
    "unrelated_bundles_changed": false,
    "unrelated_views_changed": false,
    "unrelated_aliases_changed": false
  }
}
```

Record a transcript or command log beside `answer.json`.
