<?php

declare(strict_types=1);

use Drupal\node\Entity\Node;
use Drupal\path_alias\Entity\PathAlias;

$alias = '/seo-intent-live-proof';
$title = 'Visible editor headline for intent test';

$existing_aliases = \Drupal::entityTypeManager()
  ->getStorage('path_alias')
  ->loadByProperties(['alias' => $alias]);
foreach ($existing_aliases as $existing_alias) {
  $existing_alias->delete();
}

$existing_nodes = \Drupal::entityTypeManager()
  ->getStorage('node')
  ->loadByProperties(['type' => 'page', 'title' => $title]);
foreach ($existing_nodes as $existing_node) {
  $existing_node->delete();
}

$node = Node::create([
  'type' => 'page',
  'title' => $title,
  'uid' => 1,
  'status' => 1,
]);

$values = [
  'field_description' => 'Visible page summary for normal readers.',
  'field_content' => [
    'value' => '<p>This page exists so the intent experiment can verify editor form changes without changing public content.</p>',
    'format' => 'content_format',
  ],
  'field_seo_title' => 'Search-specific title preserved by recipe intent',
  'field_seo_description' => 'Search-specific description preserved separately from the visible page summary.',
];

foreach ($values as $field_name => $value) {
  if ($node->hasField($field_name)) {
    $node->set($field_name, $value);
  }
}

if ($node->hasField('moderation_state')) {
  $node->set('moderation_state', 'published');
}

$node->save();

PathAlias::create([
  'path' => '/node/' . $node->id(),
  'alias' => $alias,
  'langcode' => 'en',
])->save();

$out = [
  'alias' => $alias,
  'path' => '/node/' . $node->id(),
  'nid' => (int) $node->id(),
  'title' => $node->label(),
  'has_fields' => [],
];
foreach (['field_seo_title', 'field_seo_description', 'field_seo_image', 'field_seo_analysis'] as $field_name) {
  $out['has_fields'][$field_name] = $node->hasField($field_name);
}

echo json_encode($out, JSON_PRETTY_PRINT) . PHP_EOL;
