import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


class InventoryEvaluatorTest(unittest.TestCase):

    def test_inventory_passes_when_answer_matches_live_state(self) -> None:
        from agent_readiness.evaluators.inventory import evaluate

        result = evaluate(
            load_fixture("inventory_state_pass.json"),
            load_fixture("inventory_answer_pass.json"),
        )

        self.assertTrue(result.passed)
        self.assertEqual([], result.failures)

    def test_inventory_fails_when_answer_guesses_wrong_path_owner(self) -> None:
        from agent_readiness.evaluators.inventory import evaluate

        result = evaluate(
            load_fixture("inventory_state_pass.json"),
            load_fixture("inventory_answer_fail.json"),
        )

        self.assertFalse(result.passed)
        self.assertIn("paths./blog.owner_kind", result.failures)

    def test_inventory_fails_when_answer_hallucinates_extra_bundle(self) -> None:
        from agent_readiness.evaluators.inventory import evaluate

        answer = load_fixture("inventory_answer_pass.json")
        answer["content_model"]["bundles"] = answer["content_model"]["bundles"] + ["ghost"]

        result = evaluate(load_fixture("inventory_state_pass.json"), answer)

        self.assertFalse(result.passed)
        self.assertIn("content_model.bundles.unexpected", result.failures)

    def test_inventory_fails_when_answer_hallucinates_extra_pathauto_pattern(self) -> None:
        from agent_readiness.evaluators.inventory import evaluate

        answer = load_fixture("inventory_answer_pass.json")
        answer["pathauto"]["patterns"] = answer["pathauto"]["patterns"] + ["/ghost/[node:title]"]

        result = evaluate(load_fixture("inventory_state_pass.json"), answer)

        self.assertFalse(result.passed)
        self.assertIn("pathauto.patterns.unexpected", result.failures)

    def test_inventory_fails_when_answer_overcounts_canvas_pages(self) -> None:
        from agent_readiness.evaluators.inventory import evaluate

        answer = load_fixture("inventory_answer_pass.json")
        answer["canvas"]["page_count"] = 99

        result = evaluate(load_fixture("inventory_state_pass.json"), answer)

        self.assertFalse(result.passed)
        self.assertIn("canvas.page_count", result.failures)

    def test_inventory_fails_when_answer_invents_entity_type_for_unclaimed_path(self) -> None:
        from agent_readiness.evaluators.inventory import evaluate

        answer = load_fixture("inventory_answer_pass.json")
        answer["paths"]["/node"]["entity_type"] = "node"

        result = evaluate(load_fixture("inventory_state_pass.json"), answer)

        self.assertFalse(result.passed)
        self.assertIn("paths./node.entity_type.unexpected", result.failures)

    def test_inventory_accepts_rich_collection_rows_when_facts_match(self) -> None:
        from agent_readiness.evaluators.inventory import evaluate

        answer = load_fixture("inventory_answer_pass.json")
        answer["canvas"]["embedded_listings"] = [
            {"view": "blog", "display": "all", "label": "Blog: All blog posts"},
            {"view": "projects", "display": "all", "label": "Projects: All projects"},
        ]
        answer["content_model"]["bundles"] = [
            {"entity_type": "node", "bundle": "blog", "label": "Blog post"},
            {"entity_type": "node", "bundle": "person", "label": "Person"},
            {"entity_type": "node", "bundle": "project", "label": "Project"},
            {"entity_type": "node", "bundle": "resource", "label": "Resource"},
        ]
        answer["pathauto"]["patterns"] = [
            {
                "id": "blog_content",
                "pattern": "/blog/[node:created:custom:Y]/[node:title]",
                "status": True,
            }
        ]

        result = evaluate(load_fixture("inventory_state_pass.json"), answer)

        self.assertTrue(result.passed)
        self.assertEqual([], result.failures)


class EventEvaluatorTest(unittest.TestCase):

    def test_event_passes_when_bundle_sample_and_jsonapi_are_present(self) -> None:
        from agent_readiness.evaluators.event import evaluate

        result = evaluate(
            load_fixture("event_state_pass.json"),
            load_fixture("event_answer_pass.json"),
        )

        self.assertTrue(result.passed)
        self.assertEqual([], result.failures)

    def test_event_fails_when_jsonapi_is_not_verified(self) -> None:
        from agent_readiness.evaluators.event import evaluate

        result = evaluate(
            load_fixture("event_state_pass.json"),
            load_fixture("event_answer_fail.json"),
        )

        self.assertFalse(result.passed)
        self.assertIn("jsonapi.verified", result.failures)

    def test_event_fails_when_unrelated_surfaces_or_permissions_change(self) -> None:
        from agent_readiness.evaluators.event import evaluate

        state = deepcopy(load_fixture("event_state_pass.json"))
        state["views"] = ["blog", "changed"]
        state["aliases"] = ["/blog"]
        state["permissions"] = {
            "role_permissions": {
                "anonymous": ["access content", "administer nodes"],
            },
            "event_permissions_granted": ["create event content"],
        }

        result = evaluate(state, load_fixture("event_answer_pass.json"))

        self.assertFalse(result.passed)
        self.assertIn("blast_radius.unrelated_views_changed", result.failures)
        self.assertIn("blast_radius.unrelated_aliases_changed", result.failures)
        self.assertIn("blast_radius.unrelated_permissions_changed", result.failures)


class RecoveryEvaluatorTest(unittest.TestCase):

    def test_recovery_passes_when_event_state_is_removed_without_blast_radius(self) -> None:
        from agent_readiness.evaluators.recovery import evaluate

        result = evaluate(
            load_fixture("recovery_state_pass.json"),
            load_fixture("recovery_answer_pass.json"),
        )

        self.assertTrue(result.passed)
        self.assertEqual([], result.failures)

    def test_recovery_fails_when_unrelated_bundles_changed(self) -> None:
        from agent_readiness.evaluators.recovery import evaluate

        result = evaluate(
            load_fixture("recovery_state_fail.json"),
            load_fixture("recovery_answer_fail.json"),
        )

        self.assertFalse(result.passed)
        self.assertIn("blast_radius.unrelated_bundles_changed", result.failures)

    def test_recovery_fails_when_event_route_or_permissions_remain(self) -> None:
        from agent_readiness.evaluators.recovery import evaluate

        state = deepcopy(load_fixture("recovery_state_pass.json"))
        state["routes"] = {"event_add_route_available": True}
        state["permissions"] = {
            "role_permissions": {
                "authenticated": ["access content", "create event content"],
            },
            "event_permissions_granted": ["create event content"],
        }

        result = evaluate(state, load_fixture("recovery_answer_pass.json"))

        self.assertFalse(result.passed)
        self.assertIn("routes.event_add_route_available", result.failures)
        self.assertIn("permissions.event_permissions_granted", result.failures)


class CommandLineEvaluatorTest(unittest.TestCase):

    def test_inventory_cli_returns_nonzero_for_failing_answer(self) -> None:
        command = [
            sys.executable,
            str(ROOT / "evaluators" / "evaluate_inventory.py"),
            "--state-json",
            str(FIXTURES / "inventory_state_pass.json"),
            "--answer-json",
            str(FIXTURES / "inventory_answer_fail.json"),
        ]

        completed = subprocess.run(command, text=True, capture_output=True)

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("paths./blog.owner_kind", completed.stdout)


class LiveStateCollectorTest(unittest.TestCase):

    def test_collector_falls_back_to_ddev_without_shell_interpolation(self) -> None:
        from agent_readiness.evaluators.common import collect_live_state

        state = {
            "provenance": {},
            "paths": {},
            "canvas": {"page_count": 0, "embedded_listings": []},
            "content_model": {"bundles": [], "moderation_enabled": False},
            "pathauto": {"enabled": False, "patterns": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "vendor/bin").mkdir(parents=True)
            (site / "vendor/bin/drush").write_text("#!/bin/sh\n", encoding="utf-8")
            (site / ".ddev").mkdir()
            (site / "config/sync").mkdir(parents=True)
            (site / "config/sync/system.site.yml").write_text(
                "name: test\n", encoding="utf-8"
            )
            results = [
                subprocess.CompletedProcess(
                    ["local-drush", "status"],
                    0,
                    json.dumps({"bootstrap": "Failed"}),
                    "",
                ),
                subprocess.CompletedProcess(
                    ["local-drush", "php:script"], 1, "", "db failed"
                ),
                subprocess.CompletedProcess(
                    ["ddev", "drush", "status"],
                    0,
                    json.dumps({"config-sync": "/var/www/html/config/sync"}),
                    "",
                ),
                subprocess.CompletedProcess(
                    ["ddev", "drush", "php:eval"],
                    0,
                    json.dumps(state),
                    "",
                ),
            ]
            with patch(
                "agent_readiness.evaluators.common.subprocess.run",
                side_effect=results,
            ) as run:
                collected = collect_live_state(site)

        self.assertEqual("populated", collected["provenance"]["config_sync_status"])
        self.assertTrue(collected["command_runner"]["ddev"])
        self.assertEqual("ddev", run.call_args_list[2].args[0][0])
        self.assertEqual("php:eval", run.call_args_list[3].args[0][2])
        self.assertNotIn("<?php", run.call_args_list[3].args[0][3])


if __name__ == "__main__":
    unittest.main()
