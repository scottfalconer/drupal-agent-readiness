<?php

declare(strict_types=1);

use Drupal\field\Entity\FieldConfig;
use Drupal\field\Entity\FieldStorageConfig;
use Drupal\node\Entity\Node;
use Drupal\node\Entity\NodeType;

$module_installer = \Drupal::service('module_installer');
if (!\Drupal::moduleHandler()->moduleExists('jsonapi')) {
  $module_installer->install(['jsonapi'], TRUE);
}

if (!NodeType::load('event')) {
  NodeType::create([
    'type' => 'event',
    'name' => 'Event',
    'description' => 'Agent readiness smoke-test event content type.',
  ])->save();
}

if (!FieldStorageConfig::loadByName('node', 'field_event_date')) {
  FieldStorageConfig::create([
    'field_name' => 'field_event_date',
    'entity_type' => 'node',
    'type' => 'datetime',
    'settings' => [
      'datetime_type' => 'datetime',
    ],
  ])->save();
  \Drupal::service('entity_field.manager')->clearCachedFieldDefinitions();
}
if (!FieldConfig::loadByName('node', 'event', 'field_event_date')) {
  FieldConfig::create([
    'field_name' => 'field_event_date',
    'entity_type' => 'node',
    'bundle' => 'event',
    'label' => 'Event date',
    'required' => TRUE,
  ])->save();
}

if (!FieldStorageConfig::loadByName('node', 'field_event_location')) {
  FieldStorageConfig::create([
    'field_name' => 'field_event_location',
    'entity_type' => 'node',
    'type' => 'string',
    'settings' => [
      'max_length' => 255,
    ],
  ])->save();
  \Drupal::service('entity_field.manager')->clearCachedFieldDefinitions();
}
if (!FieldConfig::loadByName('node', 'event', 'field_event_location')) {
  FieldConfig::create([
    'field_name' => 'field_event_location',
    'entity_type' => 'node',
    'bundle' => 'event',
    'label' => 'Event location',
    'required' => TRUE,
  ])->save();
}

$existing = \Drupal::entityTypeManager()
  ->getStorage('node')
  ->getQuery()
  ->accessCheck(FALSE)
  ->condition('type', 'event')
  ->condition('title', 'Agent Readiness Smoke Event')
  ->execute();

if (!$existing) {
  Node::create([
    'type' => 'event',
    'title' => 'Agent Readiness Smoke Event',
    'status' => 1,
    'field_event_date' => [
      'value' => '2026-07-01T18:00:00',
    ],
    'field_event_location' => [
      'value' => 'Drupal CMS Haven disposable clone',
    ],
  ])->save();
}

\Drupal::service('cache_tags.invalidator')->invalidateTags(['config:core.extension', 'node_list']);
print "event-jsonapi-applied\n";
