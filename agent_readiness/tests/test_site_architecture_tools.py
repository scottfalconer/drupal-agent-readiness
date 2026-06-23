import unittest
from pathlib import Path


class SiteArchitectureToolsTest(unittest.TestCase):

    def test_install_plan_uses_run_directory_for_command_artifacts(self) -> None:
        from agent_readiness.site_architecture_tools import build_install_plan

        plan = build_install_plan(
            site_root=Path("/tmp/agent-readiness/inventory/site"),
            module_source=Path("/repo/site_architecture/module"),
        )

        self.assertEqual(
            Path("/tmp/agent-readiness/inventory/site/web/modules/custom/site_architecture").resolve(),
            plan["module_target"],
        )
        self.assertEqual(
            Path("/tmp/agent-readiness/inventory/site-architecture-surfaces.json").resolve(),
            plan["surfaces_json"],
        )
        self.assertEqual(
            Path("/tmp/agent-readiness/inventory/site-architecture-brief.md").resolve(),
            plan["brief_md"],
        )

    def test_install_plan_resolves_relative_paths_for_execution(self) -> None:
        from agent_readiness.site_architecture_tools import build_install_plan

        plan = build_install_plan(
            site_root=Path("tmp/agent-readiness/inventory/site"),
            module_source=Path("site_architecture/module"),
        )

        self.assertTrue(plan["site_root"].is_absolute())
        self.assertTrue(plan["drush"].is_absolute())
        self.assertTrue(plan["module_source"].is_absolute())

    def test_default_module_source_points_to_bundled_prototype(self) -> None:
        from agent_readiness.site_architecture_tools import DEFAULT_MODULE_SOURCE

        self.assertEqual("site_architecture_module", DEFAULT_MODULE_SOURCE.name)
        self.assertTrue((DEFAULT_MODULE_SOURCE / "site_architecture.info.yml").exists())


if __name__ == "__main__":
    unittest.main()
