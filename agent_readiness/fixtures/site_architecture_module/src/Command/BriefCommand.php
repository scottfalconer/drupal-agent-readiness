<?php

declare(strict_types=1);

namespace Drupal\site_architecture\Command;

use Drupal\site_architecture\SiteBriefBuilder;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Output\OutputInterface;

/**
 * Emits a distilled, generated orientation brief about the site.
 *
 * @internal
 */
#[AsCommand(
  name: 'site-architecture:brief',
  description: 'Emit a distilled orientation brief about this site (generated from live config, agent-ready markdown).',
  aliases: ['site:brief'],
)]
class BriefCommand extends Command {

  public function __construct(
    protected SiteBriefBuilder $builder,
  ) {
    parent::__construct();
  }

  /**
   * {@inheritdoc}
   */
  protected function execute(InputInterface $input, OutputInterface $output): int {
    $output->write($this->builder->build());
    return Command::SUCCESS;
  }

}
