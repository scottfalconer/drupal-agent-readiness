<?php

declare(strict_types=1);

namespace Drupal\site_architecture\Command;

use Drupal\site_architecture\SiteSurfaceInventoryBuilder;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Input\InputOption;
use Symfony\Component\Console\Output\OutputInterface;
use Symfony\Component\Console\Style\SymfonyStyle;

/**
 * Lists generated site surfaces.
 *
 * @internal
 */
#[AsCommand(
  name: 'site-architecture:surfaces',
  description: 'List site surfaces the site exposes, with their producing subsystem.',
  aliases: ['site:surfaces'],
)]
class SurfacesCommand extends Command {

  public function __construct(
    protected SiteSurfaceInventoryBuilder $builder,
  ) {
    parent::__construct();
  }

  /**
   * {@inheritdoc}
   */
  protected function configure(): void {
    $this->addOption('format', NULL, InputOption::VALUE_REQUIRED, 'Output format: text or json', 'text');
  }

  /**
   * {@inheritdoc}
   */
  protected function execute(InputInterface $input, OutputInterface $output): int {
    $inventory = $this->builder->build();

    if ($input->getOption('format') === 'json') {
      $output->writeln(json_encode($inventory, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
      return Command::SUCCESS;
    }

    $io = new SymfonyStyle($input, $output);
    $io->title('Site surfaces');
    $rows = [];
    foreach ($inventory['views_pages'] as $surface) {
      $rows[] = [
        'Views page',
        $surface['path'],
        $surface['view_id'] . ':' . $surface['display_id'],
        $surface['enabled'] ? 'enabled' : 'disabled',
      ];
    }
    foreach ($inventory['entity_aliases'] as $surface) {
      $rows[] = [
        'Entity alias',
        $surface['path'],
        $surface['entity_type'] . ':' . $surface['id'],
        $surface['bundle'],
      ];
    }
    foreach ($inventory['canvas_pages'] as $surface) {
      $rows[] = [
        'Canvas page',
        $surface['path'],
        'canvas_page:' . $surface['id'],
        ($surface['embedded_views'] ?? []) ? 'embeds view(s)' : 'static',
      ];
    }
    usort($rows, static fn (array $a, array $b) => [$a[1], $a[0], $a[2]] <=> [$b[1], $b[0], $b[2]]);
    $io->table(
      ['Type', 'Path', 'Owner', 'Detail'],
      $rows,
    );
    $io->text('Use site-architecture:path-owner <path> for full ownership details of any path.');
    return Command::SUCCESS;
  }

}
