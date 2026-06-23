<?php

declare(strict_types=1);

namespace Drupal\site_architecture\Command;

use Drupal\site_architecture\PathOwnershipResolver;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputArgument;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Input\InputOption;
use Symfony\Component\Console\Output\OutputInterface;
use Symfony\Component\Console\Style\SymfonyStyle;

/**
 * Explains which subsystem owns a given path.
 *
 * @internal
 */
#[AsCommand(
  name: 'site-architecture:path-owner',
  description: 'Explain which subsystem owns (produces) a path, and what an agent may safely do there.',
  aliases: ['path:owner'],
)]
class PathOwnerCommand extends Command {

  public function __construct(
    protected PathOwnershipResolver $resolver,
  ) {
    parent::__construct();
  }

  /**
   * {@inheritdoc}
   */
  protected function configure(): void {
    $this
      ->addArgument('path', InputArgument::REQUIRED, 'Site-relative path, e.g. /recipes')
      ->addOption('format', NULL, InputOption::VALUE_REQUIRED, 'Output format: text or json', 'text');
  }

  /**
   * {@inheritdoc}
   */
  protected function execute(InputInterface $input, OutputInterface $output): int {
    $result = $this->resolver->resolve($input->getArgument('path'));

    if ($input->getOption('format') === 'json') {
      $output->writeln(json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
      return $result['claimed'] ? Command::SUCCESS : Command::FAILURE;
    }

    $io = new SymfonyStyle($input, $output);
    $io->title('Path ownership: ' . $result['path']);
    if ($result['alias']) {
      $io->text(sprintf('Alias of internal path: %s', $result['alias']['internal_path']));
    }
    if (!$result['claimed']) {
      $io->success('UNCLAIMED — ' . $result['advice']);
      return Command::FAILURE;
    }
    $owner = $result['owner'];
    $rows = [];
    foreach ($owner as $key => $value) {
      $rows[] = [$key, is_scalar($value) || $value === NULL ? (string) $value : json_encode($value)];
    }
    $io->table(['Property', 'Value'], $rows);
    $io->section('Advice');
    $io->text($result['advice']);
    if ($result['negative_contracts']) {
      $io->section('Never do this here');
      $io->listing($result['negative_contracts']);
    }
    return Command::SUCCESS;
  }

}
