<?php

declare(strict_types=1);

use Drupal\field\Entity\FieldConfig;
use Drupal\field\Entity\FieldStorageConfig;
use Drupal\node\Entity\NodeType;

function ar_delete_event_aliases(array $node_paths): void {
  if (!\Drupal::entityTypeManager()->hasDefinition('path_alias')) {
    return;
  }
  $alias_storage = \Drupal::entityTypeManager()->getStorage('path_alias');
  $alias_ids = [];
  if ($node_paths) {
    $alias_ids = $alias_storage->getQuery()
      ->accessCheck(FALSE)
      ->condition('path', $node_paths, 'IN')
      ->execute();
  }
  $smoke_alias_ids = $alias_storage->getQuery()
    ->accessCheck(FALSE)
    ->condition('alias', '/agent-readiness-smoke-event')
    ->execute();
  $alias_ids = array_unique(array_merge(array_values($alias_ids), array_values($smoke_alias_ids)));
  if ($alias_ids) {
    $alias_storage->delete($alias_storage->loadMultiple($alias_ids));
  }
}

$storage = \Drupal::entityTypeManager()->getStorage('node');
$ids = $storage->getQuery()
  ->accessCheck(FALSE)
  ->condition('type', 'event')
  ->execute();
$node_paths = array_map(static fn ($id): string => '/node/' . $id, array_values($ids));
if ($ids) {
  ar_delete_event_aliases($node_paths);
  $storage->delete($storage->loadMultiple($ids));
}
ar_delete_event_aliases($node_paths);

foreach (['field_event_date', 'field_event_location'] as $field_name) {
  $field = FieldConfig::loadByName('node', 'event', $field_name);
  if ($field) {
    $field->delete();
  }
}

$type = NodeType::load('event');
if ($type) {
  $type->delete();
}

foreach (['field_event_date', 'field_event_location'] as $field_name) {
  $storage_config = FieldStorageConfig::loadByName('node', $field_name);
  if ($storage_config) {
    $storage_config->delete();
  }
}

if (\Drupal::moduleHandler()->moduleExists('jsonapi')) {
  \Drupal::service('module_installer')->uninstall(['jsonapi'], TRUE);
}

\Drupal::service('cache_tags.invalidator')->invalidateTags(['config:core.extension', 'node_list']);
print "event-jsonapi-recovered\n";
