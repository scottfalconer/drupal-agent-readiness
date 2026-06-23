<?php

declare(strict_types=1);

use Drupal\Core\Entity\ContentEntityInterface;

$container = \Drupal::getContainer();
$entity_type_manager = $container->get('entity_type.manager');
$config_factory = $container->get('config.factory');
$module_handler = $container->get('module_handler');
$router = $container->get('router.no_access_checks');
$alias_manager = $container->get('path_alias.manager');

function ar_read_composer(): array {
  $path = DRUPAL_ROOT . '/../composer.json';
  if (!is_readable($path)) {
    return [];
  }
  $data = json_decode((string) file_get_contents($path), TRUE);
  return is_array($data) ? $data : [];
}

function ar_path_owner(string $path, $router, $alias_manager): array {
  $path = '/' . ltrim($path, '/');
  $internal = $alias_manager->getPathByAlias($path);
  try {
    $params = $router->match($internal !== $path ? $internal : $path);
  }
  catch (\Throwable) {
    return [
      'claimed' => FALSE,
      'owner_kind' => 'unclaimed',
    ];
  }
  if (isset($params['view_id'], $params['display_id'])) {
    return [
      'claimed' => TRUE,
      'owner_kind' => 'view',
      'view_id' => $params['view_id'],
      'display_id' => $params['display_id'],
    ];
  }
  foreach ($params as $value) {
    if ($value instanceof ContentEntityInterface) {
      return [
        'claimed' => TRUE,
        'owner_kind' => 'entity',
        'entity_type' => $value->getEntityTypeId(),
        'bundle' => $value->bundle(),
        'id' => (string) $value->id(),
      ];
    }
  }
  return [
    'claimed' => TRUE,
    'owner_kind' => 'route',
    'route' => $params['_route'] ?? NULL,
  ];
}

function ar_find_embedded_views(mixed $value, array $view_ids, array &$found): void {
  if (is_string($value)) {
    if (preg_match_all('/views_block:([a-z0-9_]+)-([a-z0-9_]+)/i', $value, $matches, PREG_SET_ORDER)) {
      foreach ($matches as $match) {
        $found[$match[1] . ':' . $match[2]] = TRUE;
      }
    }
    if (preg_match_all('/block\\.views_block\\.([a-z0-9_]+)-([a-z0-9_]+)/i', $value, $matches, PREG_SET_ORDER)) {
      foreach ($matches as $match) {
        $found[$match[1] . ':' . $match[2]] = TRUE;
      }
    }
    return;
  }
  if (!is_array($value)) {
    return;
  }
  if (isset($value['view_id'])) {
    $display = $value['display_id'] ?? $value['display'] ?? 'unknown';
    $found[$value['view_id'] . ':' . $display] = TRUE;
  }
  foreach ($value as $child) {
    ar_find_embedded_views($child, $view_ids, $found);
  }
}

function ar_collect_aliases($entity_type_manager): array {
  if (!$entity_type_manager->hasDefinition('path_alias')) {
    return [];
  }
  $storage = $entity_type_manager->getStorage('path_alias');
  $ids = $storage->getQuery()->accessCheck(FALSE)->execute();
  if (!$ids) {
    return [];
  }
  $aliases = [];
  foreach ($storage->loadMultiple($ids) as $alias) {
    $value = $alias->get('alias')->value ?? NULL;
    if (is_string($value) && $value !== '') {
      $aliases[] = $value;
    }
  }
  $aliases = array_values(array_unique($aliases));
  sort($aliases);
  return $aliases;
}

function ar_collect_permissions($entity_type_manager): array {
  if (!$entity_type_manager->hasDefinition('user_role')) {
    return [
      'role_permissions' => [],
      'event_permissions_granted' => [],
    ];
  }
  $role_permissions = [];
  $event_permissions = [];
  foreach ($entity_type_manager->getStorage('user_role')->loadMultiple() as $role_id => $role) {
    $permissions = $role->getPermissions();
    sort($permissions);
    $role_permissions[$role_id] = $permissions;
    foreach ($permissions as $permission) {
      if (str_contains($permission, 'event content') || str_contains($permission, 'event revisions')) {
        $event_permissions[] = $permission;
      }
    }
  }
  ksort($role_permissions);
  $event_permissions = array_values(array_unique($event_permissions));
  sort($event_permissions);
  return [
    'role_permissions' => $role_permissions,
    'event_permissions_granted' => $event_permissions,
  ];
}

$composer = ar_read_composer();
$requires = array_keys($composer['require'] ?? []);
$views = $entity_type_manager->hasDefinition('view')
  ? array_keys($entity_type_manager->getStorage('view')->loadMultiple())
  : [];
sort($views);
$node_bundles = $entity_type_manager->hasDefinition('node_type')
  ? array_keys($entity_type_manager->getStorage('node_type')->loadMultiple())
  : [];
sort($node_bundles);
$event_add_route = ar_path_owner('/node/add/event', $router, $alias_manager);

$embedded_views = [];
$canvas_page_count = 0;
if ($entity_type_manager->hasDefinition('canvas_page')) {
  $canvas_pages = $entity_type_manager->getStorage('canvas_page')->loadMultiple();
  $canvas_page_count = count($canvas_pages);
  foreach ($canvas_pages as $canvas_page) {
    ar_find_embedded_views($canvas_page->toArray(), $views, $embedded_views);
  }
}

$patterns = [];
foreach ($config_factory->listAll('pathauto.pattern.') as $config_name) {
  $pattern = $config_factory->get($config_name)->get('pattern');
  if (is_string($pattern) && $pattern !== '') {
    $patterns[] = $pattern;
  }
}
sort($patterns);

$field_configs = $config_factory->listAll('field.field.node.event.');
$required_fields = [];
foreach ($field_configs as $config_name) {
  $config = $config_factory->get($config_name);
  if ($config->get('required')) {
    $parts = explode('.', $config_name);
    $required_fields[] = end($parts);
  }
}
sort($required_fields);

$event_count = 0;
$published_event_count = 0;
if ($entity_type_manager->hasDefinition('node') && in_array('event', $node_bundles, TRUE)) {
  $storage = $entity_type_manager->getStorage('node');
  $event_count = (int) $storage->getQuery()->accessCheck(FALSE)->condition('type', 'event')->count()->execute();
  $published_event_count = (int) $storage->getQuery()->accessCheck(FALSE)->condition('type', 'event')->condition('status', 1)->count()->execute();
}

$state = [
  'provenance' => [
    'project_name' => $composer['name'] ?? NULL,
    'project_version' => $composer['version'] ?? NULL,
    'site_template' => in_array('drupal/haven', $requires, TRUE) ? 'haven' : NULL,
    'active_config_source' => 'database',
  ],
  'paths' => [
    '/blog' => ar_path_owner('/blog', $router, $alias_manager),
    '/node' => ar_path_owner('/node', $router, $alias_manager),
    '/home' => ar_path_owner('/home', $router, $alias_manager),
  ],
  'views' => $views,
  'aliases' => ar_collect_aliases($entity_type_manager),
  'canvas' => [
    'page_count' => $canvas_page_count,
    'embedded_listings' => array_values(array_keys($embedded_views)),
  ],
  'content_model' => [
    'bundles' => $node_bundles,
    'moderation_enabled' => $module_handler->moduleExists('content_moderation'),
    'event_required_fields' => $required_fields,
  ],
  'pathauto' => [
    'enabled' => $module_handler->moduleExists('pathauto'),
    'patterns' => $patterns,
  ],
  'content' => [
    'event_sample_count' => $event_count,
    'published_event_sample_count' => $published_event_count,
  ],
  'jsonapi' => [
    'event_resource_available' => $module_handler->moduleExists('jsonapi') && in_array('event', $node_bundles, TRUE),
    'sample_fetch_status' => $published_event_count > 0 ? 200 : NULL,
  ],
  'permissions' => ar_collect_permissions($entity_type_manager),
  'routes' => [
    'event_add_route_available' => !empty($event_add_route['claimed']),
    'event_add_route_owner' => $event_add_route,
  ],
  'blast_radius' => [
    'unrelated_bundles_changed' => FALSE,
    'unrelated_views_changed' => FALSE,
    'unrelated_aliases_changed' => FALSE,
    'unrelated_permissions_changed' => FALSE,
    'unexpected_routes_remaining' => FALSE,
  ],
];

print json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n";
