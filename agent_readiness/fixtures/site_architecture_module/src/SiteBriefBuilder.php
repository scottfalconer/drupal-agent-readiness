<?php

declare(strict_types=1);

namespace Drupal\site_architecture;

use Drupal\Core\Config\ConfigFactoryInterface;
use Drupal\Core\Entity\EntityTypeManagerInterface;
use Drupal\Core\Extension\ModuleHandlerInterface;
use Drupal\Core\Language\LanguageManagerInterface;
use Symfony\Component\DependencyInjection\Attribute\Autowire;

/**
 * Builds a distilled, generated orientation brief for agents.
 *
 * Deterministic projection of live configuration: patterns and production
 * rules, not instance inventories. Instances stay behind the query commands
 * the brief points at.
 */
class SiteBriefBuilder {

  public function __construct(
    protected ConfigFactoryInterface $configFactory,
    protected EntityTypeManagerInterface $entityTypeManager,
    #[Autowire(service: 'module_handler')]
    protected ModuleHandlerInterface $moduleHandler,
    protected LanguageManagerInterface $languageManager,
    protected PathOwnershipResolver $resolver,
  ) {}

  /**
   * Renders the brief as markdown.
   */
  public function build(): string {
    $site = $this->configFactory->get('system.site');
    $theme = $this->configFactory->get('system.theme');
    $profile = $this->configFactory->get('core.extension')->get('profile') ?: 'none';

    $languages = $this->languageManager->getLanguages();
    $default = $this->languageManager->getDefaultLanguage()->getId();
    $langSummary = implode(', ', array_map(
      fn ($l) => $l->getId() === $default ? $l->getId() . ' (default)' : $l->getId(),
      $languages,
    ));

    $moderation = $this->moduleHandler->moduleExists('content_moderation');

    $bundles = [];
    if ($this->entityTypeManager->hasDefinition('node_type')) {
      $bundles = array_keys($this->entityTypeManager->getStorage('node_type')->loadMultiple());
    }

    // Views page surfaces: public vs admin, enabled vs latent.
    $public = [];
    $latent = [];
    $adminCount = 0;
    foreach ($this->entityTypeManager->getStorage('view')->loadMultiple() as $view) {
      foreach ($view->get('display') as $display) {
        if (($display['display_plugin'] ?? '') !== 'page') {
          continue;
        }
        $path = '/' . ($display['display_options']['path'] ?? '');
        if (str_starts_with($path, '/admin')) {
          $adminCount++;
          continue;
        }
        if (!$view->status()) {
          $latent[] = "$path (disabled view: {$view->id()})";
          continue;
        }
        $public[] = "$path (view: {$view->id()})";
      }
    }
    sort($public);
    sort($latent);

    // Alias conventions: group current aliases by first segment and target
    // entity type. Patterns, not the alias list itself.
    $prefixes = [];
    if ($this->entityTypeManager->hasDefinition('path_alias')) {
      foreach ($this->entityTypeManager->getStorage('path_alias')->loadMultiple() as $alias) {
        $segment = explode('/', ltrim($alias->getAlias(), '/'), 2)[0];
        $target = str_starts_with($alias->getPath(), '/node/') ? 'nodes'
          : (str_starts_with($alias->getPath(), '/taxonomy/term/') ? 'taxonomy terms' : 'other');
        $prefixes["/$segment/* → $target"] = ($prefixes["/$segment/* → $target"] ?? 0) + 1;
      }
    }
    arsort($prefixes);
    $aliasLines = array_map(
      fn ($pattern, $count) => "$pattern ($count aliases)",
      array_keys($prefixes),
      $prefixes,
    );
    $pathauto = $this->moduleHandler->moduleExists('pathauto');

    // Resolve the configured front page through the resolver itself.
    $frontPath = $site->get('page.front') ?: '/node';
    $front = $this->resolver->resolve($frontPath);
    $frontOwner = match ($front['owner']['kind'] ?? NULL) {
      'view' => sprintf('view %s:%s', $front['owner']['view_id'], $front['owner']['display_id']),
      'entity' => sprintf('%s %s', $front['owner']['entity_type'], $front['owner']['id']),
      'route' => sprintf('route %s', $front['owner']['route']),
      default => 'unresolved',
    };

    $lines = [];
    $lines[] = '# Site brief: ' . ($site->get('name') ?: 'Drupal site');
    $lines[] = '';
    $lines[] = 'Generated from live configuration by `site-architecture:brief`. Patterns below describe how this site works; for any specific fact, prefer the live queries listed at the end.';
    $lines[] = '';
    $lines[] = '## Identity';
    $lines[] = '- Drupal ' . \Drupal::VERSION . ', install profile: ' . $profile;
    $lines[] = '- Default theme: ' . $theme->get('default') . '; admin theme: ' . $theme->get('admin');
    $lines[] = '- Languages: ' . $langSummary . (count($languages) > 1 ? ' — content and aliases exist per language; public URLs carry a language prefix (/' . implode('/..., /', array_keys($languages)) . '/...)' : '');
    if ($moderation) {
      $lines[] = '- Editorial workflow: content_moderation is enabled — saved content is NOT public until its moderation_state is "published"';
    }
    $lines[] = '';
    $lines[] = '## How this site produces pages';
    $lines[] = '- Listing pages may be Views page displays or Canvas pages embedding Views blocks. Views page listings are not editable content. Public Views page listings: ' . ($public ? implode(', ', $public) : 'none') . '. ' . $adminCount . ' more Views page displays serve /admin/* paths.';
    if ($latent) {
      $lines[] = '- Latent path claims (disabled views, collide if re-enabled): ' . implode(', ', $latent);
    }
    $lines[] = '- The configured front page is ' . $frontPath . ', produced by ' . $frontOwner . '.';
    $lines[] = '- Regular content pages are nodes (bundles: ' . implode(', ', $bundles) . ') served at canonical /node/{id} behind per-language URL aliases.';
    $lines[] = '- Current alias conventions: ' . ($aliasLines ? implode('; ', array_slice($aliasLines, 0, 6)) : 'no aliases yet') . '. ' . ($pathauto ? 'Pathauto generates aliases from patterns.' : 'Pathauto is NOT installed: aliases are created manually.');
    $lines[] = '- A path is claimed by exactly one responder (route, view page, or alias). Creating a content alias matching an existing route or view path will shadow it and break that page.';
    $lines[] = '';
    $lines[] = '## Site-specific knowledge that cannot be derived from config';
    $lines[] = '(human-recorded annotations merge in here when present — none recorded on this site)';
    $lines[] = '';
    $lines[] = '## Live queries (prefer these over guessing or re-deriving)';
    $lines[] = '- Who/what owns a path, is it safe to claim: `site-architecture:path-owner <path> [--format=json]`';
    $lines[] = '- Site surfaces incl. Views pages, aliased entities, Canvas pages, and embedded view references: `site-architecture:surfaces [--format=json]`';
    $lines[] = '- System status: `system:status`; inspect content entities: `content:export <type> <id>`';

    return implode("\n", $lines) . "\n";
  }

}
