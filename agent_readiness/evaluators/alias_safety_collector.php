<?php

declare(strict_types=1);

/**
 * Ground-truth collector for the assess.alias_safety task.
 *
 * For each candidate path, decides whether it is SAFE to claim with a new node
 * URL alias. A path is unsafe if a route/view/entity already responds there, or
 * if a DISABLED view declares it as a page path (a latent claim that would
 * collide if the view were ever enabled).
 *
 * Uses only Drupal core services (router, alias manager, view storage). It does
 * NOT use the site_architecture module, so it is a valid independent ground
 * truth for both the raw-drush and site_architecture arms of the experiment.
 *
 * Candidate paths are read from the JSON file named in the AR_ALIAS_CANDIDATES
 * environment variable.
 */

$router = \Drupal::service('router.no_access_checks');
$alias_manager = \Drupal::service('path_alias.manager');
$etm = \Drupal::entityTypeManager();

$candidates_file = getenv('AR_ALIAS_CANDIDATES');
$paths = [];
if ($candidates_file && is_readable($candidates_file)) {
  $data = json_decode((string) file_get_contents($candidates_file), TRUE);
  foreach (($data['candidates'] ?? []) as $candidate) {
    if (!empty($candidate['path'])) {
      $paths[] = $candidate['path'];
    }
  }
}

// Index every Views page-display path by status, so an unrouted path can be
// checked for a latent (disabled-view) claim.
// Views may not be enabled (a minimal site is valid); degrade to no view page
// paths rather than throwing on a missing 'view' entity type.
$view_page_paths = [];
$all_views = $etm->hasDefinition('view') ? $etm->getStorage('view')->loadMultiple() : [];
foreach ($all_views as $view) {
  foreach ($view->get('display') as $display_id => $display) {
    if (($display['display_plugin'] ?? '') === 'page' && isset($display['display_options']['path'])) {
      $p = '/' . $display['display_options']['path'];
      $view_page_paths[$p][] = [
        'view_id' => $view->id(),
        'display_id' => $display_id,
        'status' => $view->status(),
      ];
    }
  }
}

$out = [];
foreach ($paths as $raw_path) {
  $path = '/' . ltrim(trim($raw_path), '/');
  $internal = $alias_manager->getPathByAlias($path);
  $match_path = ($internal !== $path) ? $internal : $path;
  $entry = ['safe' => TRUE, 'blocker_kind' => NULL, 'detail' => []];

  try {
    $params = $router->match($match_path);
    $entry['safe'] = FALSE;
    $route_name = $params['_route'] ?? '';
    if (isset($params['view_id'], $params['display_id'])) {
      $entry['blocker_kind'] = 'view';
      $entry['detail'] = [
        'view_id' => $params['view_id'],
        'display_id' => $params['display_id'],
        'route' => $route_name,
      ];
    }
    else {
      $is_entity = FALSE;
      foreach ($params as $value) {
        if ($value instanceof \Drupal\Core\Entity\ContentEntityInterface) {
          $entry['blocker_kind'] = 'entity';
          $entry['detail'] = [
            'entity_type' => $value->getEntityTypeId(),
            'id' => $value->id(),
            'route' => $route_name,
          ];
          $is_entity = TRUE;
          break;
        }
      }
      if (!$is_entity) {
        $entry['blocker_kind'] = 'route';
        $entry['detail'] = [
          'route' => $route_name,
          'provider' => explode('.', $route_name)[0] ?: 'unknown',
        ];
      }
    }
  }
  catch (\Throwable $e) {
    // Unrouted: a disabled view declaring this path is a latent claim.
    $latent = [];
    foreach ($view_page_paths[$path] ?? [] as $decl) {
      if (!$decl['status']) {
        $latent[] = $decl;
      }
    }
    if ($latent) {
      $entry['safe'] = FALSE;
      $entry['blocker_kind'] = 'latent_disabled_view';
      $entry['detail'] = ['disabled_views' => $latent];
    }
  }

  $out[$path] = $entry;
}

print json_encode($out, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . PHP_EOL;
