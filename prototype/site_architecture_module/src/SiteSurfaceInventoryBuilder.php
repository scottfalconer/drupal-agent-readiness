<?php

declare(strict_types=1);

namespace Drupal\site_architecture;

use Drupal\Core\Entity\ContentEntityInterface;
use Drupal\Core\Entity\EntityPublishedInterface;
use Drupal\Core\Entity\EntityTypeManagerInterface;
use Drupal\path_alias\AliasManagerInterface;
use Symfony\Component\DependencyInjection\Attribute\Autowire;

/**
 * Builds a generated inventory of site surfaces agents may need to reason about.
 */
class SiteSurfaceInventoryBuilder {

  public function __construct(
    protected EntityTypeManagerInterface $entityTypeManager,
    #[Autowire(service: 'path_alias.manager')]
    protected AliasManagerInterface $aliasManager,
  ) {}

  /**
   * Builds the full inventory.
   *
   * @return array
   *   Surface inventory grouped by source subsystem.
   */
  public function build(): array {
    $views = $this->buildViewsPages();
    $canvasPages = $this->buildCanvasPages();

    return [
      'views_pages' => $views,
      'entity_aliases' => $this->buildEntityAliases(),
      'canvas_pages' => $canvasPages,
      'embedded_views' => $this->flattenEmbeddedViews($canvasPages),
    ];
  }

  /**
   * Enumerates Views page displays.
   */
  protected function buildViewsPages(): array {
    if (!$this->entityTypeManager->hasDefinition('view')) {
      return [];
    }
    $surfaces = [];
    /** @var \Drupal\views\ViewEntityInterface $view */
    foreach ($this->entityTypeManager->getStorage('view')->loadMultiple() as $view) {
      foreach ($view->get('display') as $displayId => $display) {
        if (($display['display_plugin'] ?? '') !== 'page') {
          continue;
        }
        $surfaces[] = [
          'kind' => 'views_page',
          'path' => '/' . ($display['display_options']['path'] ?? ''),
          'view_id' => $view->id(),
          'display_id' => $displayId,
          'label' => $view->label(),
          'enabled' => $view->status(),
          'base_table' => $view->get('base_table'),
          'config_id' => 'views.view.' . $view->id(),
        ];
      }
    }
    usort($surfaces, static fn (array $a, array $b) => [$a['path'], $a['view_id'], $a['display_id']] <=> [$b['path'], $b['view_id'], $b['display_id']]);
    return $surfaces;
  }

  /**
   * Enumerates entity pages reachable through path aliases.
   */
  protected function buildEntityAliases(): array {
    if (!$this->entityTypeManager->hasDefinition('path_alias')) {
      return [];
    }
    $aliases = [];
    foreach ($this->entityTypeManager->getStorage('path_alias')->loadMultiple() as $alias) {
      $internalPath = $alias->getPath();
      $target = $this->loadEntityFromInternalPath($internalPath);
      if (!$target) {
        continue;
      }
      $aliases[] = $this->summarizeEntitySurface($target, [
        'kind' => 'entity_alias',
        'path' => $alias->getAlias(),
        'internal_path' => $internalPath,
        'langcode' => $alias->language()->getId(),
      ]);
    }
    usort($aliases, static fn (array $a, array $b) => [$a['path'], $a['entity_type'], $a['id']] <=> [$b['path'], $b['entity_type'], $b['id']]);
    return $aliases;
  }

  /**
   * Enumerates Canvas pages when the Canvas entity type exists.
   */
  protected function buildCanvasPages(): array {
    if (!$this->entityTypeManager->hasDefinition('canvas_page')) {
      return [];
    }
    $viewIds = $this->entityTypeManager->hasDefinition('view')
      ? array_keys($this->entityTypeManager->getStorage('view')->loadMultiple())
      : [];
    $pages = [];
    foreach ($this->entityTypeManager->getStorage('canvas_page')->loadMultiple() as $page) {
      if (!$page instanceof ContentEntityInterface) {
        continue;
      }
      $internalPath = '/page/' . $page->id();
      $alias = $this->aliasManager->getAliasByPath($internalPath);
      $pages[] = $this->summarizeEntitySurface($page, [
        'kind' => 'canvas_page',
        'path' => $alias !== $internalPath ? $alias : $internalPath,
        'internal_path' => $internalPath,
        'embedded_views' => array_values($this->findEmbeddedViews($page->toArray(), $viewIds)),
      ]);
    }
    usort($pages, static fn (array $a, array $b) => [$a['path'], $a['id']] <=> [$b['path'], $b['id']]);
    return $pages;
  }

  /**
   * Loads an entity from common Drupal canonical internal paths.
   */
  protected function loadEntityFromInternalPath(string $internalPath): ?ContentEntityInterface {
    $matches = [];
    if (preg_match('#^/node/(\d+)$#', $internalPath, $matches)) {
      $entityType = 'node';
      $id = $matches[1];
    }
    elseif (preg_match('#^/taxonomy/term/(\d+)$#', $internalPath, $matches)) {
      $entityType = 'taxonomy_term';
      $id = $matches[1];
    }
    elseif (preg_match('#^/(?:canvas_page|page)/(\d+)$#', $internalPath, $matches)) {
      $entityType = 'canvas_page';
      $id = $matches[1];
    }
    else {
      return NULL;
    }
    if (!$this->entityTypeManager->hasDefinition($entityType)) {
      return NULL;
    }
    $entity = $this->entityTypeManager->getStorage($entityType)->load($id);
    return $entity instanceof ContentEntityInterface ? $entity : NULL;
  }

  /**
   * Converts a content entity into a surface row.
   */
  protected function summarizeEntitySurface(ContentEntityInterface $entity, array $base): array {
    $summary = $base + [
      'entity_type' => $entity->getEntityTypeId(),
      'bundle' => $entity->bundle(),
      'id' => (string) $entity->id(),
      'label' => $entity->label(),
    ];
    if ($entity instanceof EntityPublishedInterface || method_exists($entity, 'isPublished')) {
      $summary['published'] = (bool) $entity->isPublished();
    }
    return $summary;
  }

  /**
   * Finds likely embedded Views references inside an entity render/composition tree.
   */
  protected function findEmbeddedViews(mixed $value, array $viewIds): array {
    $found = [];
    $this->scanEmbeddedViews($value, $viewIds, $found);
    ksort($found);
    return array_values($found);
  }

  /**
   * Recursively scans for common Views identifiers in nested field values.
   */
  protected function scanEmbeddedViews(mixed $value, array $viewIds, array &$found): void {
    if (is_string($value)) {
      if (preg_match_all('/views_block:([a-z0-9_]+)-([a-z0-9_]+)/i', $value, $matches, PREG_SET_ORDER)) {
        foreach ($matches as $match) {
          $found[$match[1] . ':' . $match[2]] = [
            'view_id' => $match[1],
            'display_id' => $match[2],
          ];
        }
      }
      if (preg_match_all('/block\\.views_block\\.([a-z0-9_]+)-([a-z0-9_]+)/i', $value, $matches, PREG_SET_ORDER)) {
        foreach ($matches as $match) {
          $found[$match[1] . ':' . $match[2]] = [
            'view_id' => $match[1],
            'display_id' => $match[2],
          ];
        }
      }
      return;
    }
    if (!is_array($value)) {
      return;
    }
    if (isset($value['view_id'])) {
      $displayId = $value['display_id'] ?? $value['display'] ?? 'unknown';
      $found[$value['view_id'] . ':' . $displayId] = [
        'view_id' => $value['view_id'],
        'display_id' => $displayId,
      ];
    }
    foreach ($value as $child) {
      $this->scanEmbeddedViews($child, $viewIds, $found);
    }
  }

  /**
   * Flattens embedded view references across Canvas pages.
   */
  protected function flattenEmbeddedViews(array $canvasPages): array {
    $rows = [];
    foreach ($canvasPages as $page) {
      foreach ($page['embedded_views'] ?? [] as $view) {
        $rows[] = [
          'canvas_page_id' => $page['id'],
          'canvas_page_path' => $page['path'],
          'view_id' => $view['view_id'],
          'display_id' => $view['display_id'],
        ];
      }
    }
    usort($rows, static fn (array $a, array $b) => [$a['canvas_page_path'], $a['view_id'], $a['display_id']] <=> [$b['canvas_page_path'], $b['view_id'], $b['display_id']]);
    return $rows;
  }

}
