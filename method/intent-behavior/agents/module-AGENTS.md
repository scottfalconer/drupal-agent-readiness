# Intent Protocol For Agents

When working on Drupal configuration in a project that uses this module, treat `third_party_settings.intent.value` as the plain-language reason a config entity exists in its current shape.

Before changing related config, read the relevant intent with `dr intent:get <config_name> --format=json` or inspect exported config directly.

Intent is context, not enforcement. You may change the config when the task requires it, but do not ignore the intent. If your change makes the intent false, misleading, or obsolete, update or delete the intent in the same change. If the right action is unclear, say so and recommend asking a human.
