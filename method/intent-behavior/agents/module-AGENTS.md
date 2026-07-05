# Intent Protocol For Agents

When making site-building changes that may affect Drupal configuration, fields, content types, forms, displays, menus, blocks, views, permissions, workflows, SEO, analytics, or other site behavior, treat `third_party_settings.intent.value` as the plain-language reason the related config exists in its current shape.

Before changing, hiding, deleting, moving, or regenerating site-building configuration, read the relevant intent with `dr intent:get <config_name> --format=json`, `dr intent:list --format=json`, or by inspecting exported config directly.

Intent is context, not enforcement. You may change the config when the task requires it, but do not ignore the intent. If your change makes the intent false, misleading, or obsolete, update or delete the intent in the same change. If the right action is unclear, say so and recommend asking a human.
