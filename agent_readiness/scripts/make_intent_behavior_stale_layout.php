<?php

declare(strict_types=1);

$display = \Drupal::entityTypeManager()
  ->getStorage('entity_form_display')
  ->load('node.page.default');

if (!$display) {
  fwrite(STDERR, "Missing node.page.default form display\n");
  exit(1);
}

$weight = -40;
foreach (['field_seo_title', 'field_seo_description', 'field_seo_image', 'field_seo_analysis'] as $field_name) {
  $component = $display->getComponent($field_name);
  if (!$component) {
    fwrite(STDERR, "Missing component $field_name\n");
    exit(1);
  }
  $component['weight'] = $weight++;
  $display->setComponent($field_name, $component);
}

$display->save();
echo json_encode(['status' => 'ok'], JSON_PRETTY_PRINT) . PHP_EOL;
