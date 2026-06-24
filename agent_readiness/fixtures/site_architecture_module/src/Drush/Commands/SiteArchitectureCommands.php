<?php

declare(strict_types=1);

namespace Drupal\site_architecture\Drush\Commands;

use Drupal\site_architecture\PathOwnershipResolver;
use Drupal\site_architecture\SiteBriefBuilder;
use Drupal\site_architecture\SiteSurfaceInventoryBuilder;
use Drush\Attributes as CLI;
use Drush\Boot\DrupalBootLevels;
use Drush\Commands\DrushCommands;

/**
 * Drush projection for the site architecture services.
 */
final class SiteArchitectureCommands extends DrushCommands {

  private const PATH_OWNER = 'site-architecture:path-owner';

  private const SURFACES = 'site-architecture:surfaces';

  private const BRIEF = 'site-architecture:brief';

  public function __construct(
    private readonly PathOwnershipResolver $pathOwnershipResolver,
    private readonly SiteSurfaceInventoryBuilder $surfaceInventoryBuilder,
    private readonly SiteBriefBuilder $siteBriefBuilder,
  ) {
    parent::__construct();
  }

  /**
   * Explains which subsystem owns a path.
   *
   * @param string $path
   *   Site-relative path, e.g. /recipes.
   * @param array<string, mixed> $options
   *   Command options.
   */
  #[CLI\Command(name: self::PATH_OWNER, aliases: ['path:owner'])]
  #[CLI\Argument(name: 'path', description: 'Site-relative path, e.g. /recipes')]
  #[CLI\Option(name: 'format', description: 'Output format: text or json')]
  #[CLI\Bootstrap(level: DrupalBootLevels::FULL)]
  public function pathOwner(string $path, array $options = ['format' => 'text']): void {
    $result = $this->pathOwnershipResolver->resolve($path);
    if (($options['format'] ?? 'text') === 'json') {
      $this->output()->writeln($this->encodeJson($result));
      return;
    }
    $this->output()->writeln($result['path']);
    $this->output()->writeln($result['advice']);
    if (!empty($result['negative_contracts'])) {
      $this->output()->writeln('Never do this here:');
      foreach ($result['negative_contracts'] as $contract) {
        $this->output()->writeln('- ' . $contract);
      }
    }
  }

  /**
   * Lists generated site surfaces.
   *
   * @param array<string, mixed> $options
   *   Command options.
   */
  #[CLI\Command(name: self::SURFACES, aliases: ['site:surfaces'])]
  #[CLI\Option(name: 'format', description: 'Output format: text or json')]
  #[CLI\Bootstrap(level: DrupalBootLevels::FULL)]
  public function surfaces(array $options = ['format' => 'text']): void {
    $inventory = $this->surfaceInventoryBuilder->build();
    if (($options['format'] ?? 'text') === 'json') {
      $this->output()->writeln($this->encodeJson($inventory));
      return;
    }
    $this->output()->writeln('Views page surfaces: ' . count($inventory['views_pages']));
    $this->output()->writeln('Aliased entity surfaces: ' . count($inventory['entity_aliases']));
    $this->output()->writeln('Canvas pages: ' . count($inventory['canvas_pages']));
    $this->output()->writeln('Embedded view references: ' . count($inventory['embedded_views']));
  }

  /**
   * Emits the generated site brief.
   */
  #[CLI\Command(name: self::BRIEF, aliases: ['site:brief'])]
  #[CLI\Bootstrap(level: DrupalBootLevels::FULL)]
  public function brief(): void {
    $this->output()->write($this->siteBriefBuilder->build());
  }

  /**
   * Encodes JSON consistently for command consumers.
   *
   * @param array<mixed> $data
   *   JSON data.
   */
  private function encodeJson(array $data): string {
    $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    if ($json === FALSE) {
      throw new \RuntimeException('Could not encode site architecture JSON output.');
    }
    return $json;
  }

}
