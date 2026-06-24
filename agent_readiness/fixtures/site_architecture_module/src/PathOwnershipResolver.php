<?php

declare(strict_types=1);

namespace Drupal\site_architecture;

use Drupal\Core\Entity\ContentEntityInterface;
use Drupal\Core\Entity\EntityTypeManagerInterface;
use Drupal\Core\Language\LanguageManagerInterface;
use Drupal\path_alias\AliasManagerInterface;
use Symfony\Component\DependencyInjection\Attribute\Autowire;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcherInterface;

/**
 * Resolves which subsystem owns (produces) a given site path.
 *
 * Joins routing, path aliases, Views page displays and entity canonical
 * routes into a single ownership answer an agent can act on.
 */
class PathOwnershipResolver {

  public function __construct(
    #[Autowire(service: 'path_alias.manager')]
    protected AliasManagerInterface $aliasManager,
    #[Autowire(service: 'router.no_access_checks')]
    protected UrlMatcherInterface $router,
    protected EntityTypeManagerInterface $entityTypeManager,
    protected LanguageManagerInterface $languageManager,
  ) {}

  /**
   * Resolves ownership of a site-relative path.
   *
   * @param string $path
   *   A site-relative path such as "/recipes".
   *
   * @return array
   *   Structured ownership data: path, alias info, owner, advice and
   *   negative contracts (things an agent must not do at this path).
   */
  public function resolve(string $path): array {
    $path = '/' . ltrim(trim($path), '/');
    $result = [
      'path' => $path,
      'claimed' => FALSE,
      'alias' => NULL,
      'owner' => NULL,
      'negative_contracts' => [],
      'advice' => '',
    ];

    // Strip a leading language prefix so alias lookups run in the right
    // language. Aliases are stored unprefixed and per-langcode; the CLI has
    // no negotiated language context, so resolve it from the path itself.
    $langcode = NULL;
    $unprefixed = $path;
    $segments = explode('/', ltrim($path, '/'), 2);
    if (isset($this->languageManager->getLanguages()[$segments[0]])) {
      $langcode = $segments[0];
      $unprefixed = '/' . ($segments[1] ?? '');
    }

    $internal = $this->aliasManager->getPathByAlias($unprefixed, $langcode);
    if ($internal !== $unprefixed) {
      $result['alias'] = [
        'is_alias' => TRUE,
        'internal_path' => $internal,
        'langcode' => $langcode ?: $this->languageManager->getDefaultLanguage()->getId(),
      ];
    }

    try {
      // The router applies inbound processing (language prefix stripping,
      // alias resolution) itself, but its alias lookup is bound to the
      // process-wide language context. Feed it the resolved internal path
      // with the prefix re-applied so prefixed routes still match.
      $params = $this->router->match($result['alias'] ? ($langcode ? "/$langcode$internal" : $internal) : $path);
    }
    catch (ResourceNotFoundException | MethodNotAllowedException) {
      $result['advice'] = 'No route, alias, view or entity currently responds to this path. It is unclaimed: an agent may create a surface here (e.g. a node with this URL alias, a view page, or a module route).';
      // A disabled view that declares this path is a latent claim: enabling
      // it later would collide with anything created here now.
      foreach ($this->entityTypeManager->getStorage('view')->loadMultiple() as $view) {
        foreach ($view->get('display') as $displayId => $display) {
          if (($display['display_plugin'] ?? '') === 'page'
            && '/' . ($display['display_options']['path'] ?? '') === $unprefixed
            && !$view->status()) {
            $result['latent_claims'][] = [
              'kind' => 'disabled_view',
              'view_id' => $view->id(),
              'display_id' => $displayId,
              'config_id' => 'views.view.' . $view->id(),
            ];
            $result['negative_contracts'][] = sprintf('Disabled view %s:%s declares this path. If that view is ever enabled it will collide with whatever you create here.', $view->id(), $displayId);
            $result['advice'] = 'No enabled route currently responds to this path, but a DISABLED view declares it (see latent_claims). Claiming this path is risky.';
          }
        }
      }
      return $result;
    }

    $result['claimed'] = TRUE;
    $routeName = $params['_route'] ?? '';

    // Views page display.
    if (isset($params['view_id'], $params['display_id'])) {
      $owner = [
        'kind' => 'view',
        'view_id' => $params['view_id'],
        'display_id' => $params['display_id'],
        'config_id' => 'views.view.' . $params['view_id'],
        'route' => $routeName,
      ];
      /** @var \Drupal\views\ViewEntityInterface|null $view */
      $view = $this->entityTypeManager->getStorage('view')->load($params['view_id']);
      if ($view) {
        $owner['label'] = $view->label();
        $owner['base_table'] = $view->get('base_table');
        $display = $view->getDisplay($params['display_id']);
        $owner['display_title'] = $display['display_title'] ?? NULL;
        $owner['path_pattern'] = isset($display['display_options']['path']) ? '/' . $display['display_options']['path'] : NULL;
      }
      $result['owner'] = $owner;
      $result['negative_contracts'] = [
        sprintf('Do not create a node or other entity with the URL alias %s: the alias would shadow this view and hijack the page.', $path),
        sprintf('Do not try to edit the content of this page directly: it is a computed listing. Change the view config (%s) instead.', $owner['config_id']),
      ];
      $result['advice'] = sprintf(
        'This path is produced by the Views page display %s:%s ("%s"). It is a computed listing over %s. To change what appears here, modify that view; to add an item to the listing, create content that matches its filters.',
        $owner['view_id'],
        $owner['display_id'],
        $owner['label'] ?? $owner['view_id'],
        $owner['base_table'] ?? 'its base table',
      );
      return $result;
    }

    // Entity canonical (or other entity-parameter) route.
    foreach ($params as $key => $value) {
      if ($value instanceof ContentEntityInterface) {
        $entityType = $value->getEntityTypeId();
        $isCanonical = $routeName === "entity.$entityType.canonical";
        $internalPath = "/$entityType/" . $value->id();
        $owner = [
          'kind' => 'entity',
          'entity_type' => $entityType,
          'bundle' => $value->bundle(),
          'id' => $value->id(),
          'label' => $value->label(),
          'route' => $routeName,
          'canonical' => $isCanonical,
          'internal_path' => $internalPath,
        ];
        $canonicalAlias = $this->aliasManager->getAliasByPath($internalPath);
        if ($canonicalAlias !== $internalPath) {
          $owner['canonical_alias'] = $canonicalAlias;
        }
        if ($value->getEntityType()->hasKey('published') || $value instanceof \Drupal\Core\Entity\EntityPublishedInterface) {
          $owner['published'] = (bool) (method_exists($value, 'isPublished') ? $value->isPublished() : TRUE);
        }
        $result['owner'] = $owner;
        $result['negative_contracts'] = [
          sprintf('Do not create another surface at %s: it is already the canonical page of %s %s.', $path, $entityType, $value->id()),
        ];
        $result['advice'] = sprintf(
          'This path is the canonical page of %s %s ("%s", bundle: %s)%s. To change this page, edit that entity. Its rendered output is controlled by the view display configuration for bundle "%s".',
          $entityType,
          $value->id(),
          $value->label(),
          $value->bundle(),
          isset($owner['published']) && !$owner['published'] ? ' — currently UNPUBLISHED' : '',
          $value->bundle(),
        );
        return $result;
      }
    }

    // Some other route: report provider and controller.
    $provider = explode('.', $routeName)[0] ?: 'unknown';
    $controller = NULL;
    if (isset($params['_route_object'])) {
      $defaults = $params['_route_object']->getDefaults();
      $controller = $defaults['_controller'] ?? $defaults['_form'] ?? $defaults['_entity_form'] ?? $defaults['_entity_list'] ?? NULL;
    }
    $result['owner'] = [
      'kind' => 'route',
      'route' => $routeName,
      'provider' => $provider,
      'controller' => $controller,
    ];
    $result['negative_contracts'] = [
      sprintf('Do not create content with the URL alias %s: a module route already claims this path.', $path),
    ];
    $result['advice'] = sprintf(
      'This path is claimed by route "%s" (probably provided by the "%s" module%s). Its output is code-defined; changing it means changing module code or configuration, not content.',
      $routeName,
      $provider,
      $controller ? ', controller: ' . (is_string($controller) ? $controller : gettype($controller)) : '',
    );
    return $result;
  }

}
