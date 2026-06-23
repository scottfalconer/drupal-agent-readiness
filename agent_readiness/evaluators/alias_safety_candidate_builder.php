<?php

declare(strict_types=1);

/**
 * Auto-derive alias-safety candidate paths for ANY Drupal substrate.
 *
 * Different site templates / profiles ship different views, so the disabled-view
 * latent claims differ per substrate. This enumerates the live site and picks a
 * candidate set: a couple of genuinely-free paths, one active Views page, and up
 * to three concrete disabled-view page paths (the latent-claim discriminators).
 *
 * Emits the same JSON shape as prompts/assess.alias_safety.candidates.json, plus
 * `latent_available` so the runner can report when a substrate has no latent
 * discriminator (which is itself a finding, not a failure).
 *
 * Uses only core services. Output: JSON to stdout.
 */

$router = \Drupal::service('router.no_access_checks');
$etm = \Drupal::entityTypeManager();

// Index Views page-display paths by status, skipping wildcard paths (which a
// node alias cannot collide with).
$enabled = [];
$disabled = [];
// Views is not guaranteed to be enabled (a minimal site is valid). Degrade to
// "no view page paths" rather than throwing on a missing 'view' entity type.
$all_views = $etm->hasDefinition('view') ? $etm->getStorage('view')->loadMultiple() : [];
foreach ($all_views as $view) {
  foreach ($view->get('display') as $display_id => $display) {
    if (($display['display_plugin'] ?? '') !== 'page') {
      continue;
    }
    $path = $display['display_options']['path'] ?? '';
    if ($path === '' || str_contains($path, '%') || str_contains($path, '{')) {
      continue;
    }
    $full = '/' . ltrim($path, '/');
    $rec = ['view' => $view->id(), 'display' => $display_id, 'path' => $full];
    if ($view->status()) {
      $enabled[$full] = $rec;
    }
    else {
      $disabled[$full] = $rec;
    }
  }
}

// A disabled-view path is a usable latent candidate only if nothing currently
// routes there.
$latent = [];
foreach ($disabled as $full => $rec) {
  if (isset($enabled[$full])) {
    continue;
  }
  try {
    $router->match($full);
    // Something routes here despite the view being disabled — not a clean latent.
  }
  catch (\Throwable $e) {
    $latent[$full] = $rec;
    if (count($latent) >= 3) {
      break;
    }
  }
}

// One active Views page as a non-latent "unsafe" control.
$active = NULL;
foreach ($enabled as $full => $rec) {
  if (!str_starts_with($full, '/admin')) {
    $active = $rec;
    break;
  }
}
if ($active === NULL) {
  $active = $enabled ? reset($enabled) : NULL;
}

$candidates = [
  ['path' => '/this-is-free-xyz', 'note' => 'control: no route/alias/view declares it'],
  ['path' => '/zzz-unclaimed-' . substr(md5((string) array_sum(array_map('crc32', array_keys($disabled + $enabled)))), 0, 6), 'note' => 'control: synthetic free path'],
];
if ($active !== NULL) {
  $candidates[] = ['path' => $active['path'], 'note' => "active Views page {$active['view']}:{$active['display']}"];
}
foreach ($latent as $rec) {
  $candidates[] = ['path' => $rec['path'], 'note' => "latent: disabled view {$rec['view']}:{$rec['display']} declares this path"];
}

print json_encode([
  'task_id' => 'assess.alias_safety',
  'latent_available' => !empty($latent),
  'latent_count' => count($latent),
  'enabled_view_pages' => count($enabled),
  'disabled_view_pages' => count($disabled),
  'candidates' => $candidates,
], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . PHP_EOL;
