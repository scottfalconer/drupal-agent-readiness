import collections
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_PATH = REPO_ROOT / "method" / "intent-behavior-variants-v0.json"


def load_design() -> dict:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


class IntentBehaviorTest(unittest.TestCase):

    def test_current_design_passes_audit(self) -> None:
        from agent_readiness.intent_behavior import audit_intent_behavior_design

        result = audit_intent_behavior_design(load_design())

        self.assertTrue(result["passed"], result)
        self.assertEqual([], result["failures"])
        self.assertEqual(62, result["details"]["core_confirmatory_runs"])
        self.assertEqual("halt_and_reregister", result["details"]["r4_fallback"])

    def test_prepare_registration_materializes_hashes(self) -> None:
        from agent_readiness.intent_behavior import (
            audit_intent_behavior_registration,
            prepare_registration_artifacts,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module_dir = self._module_dir(root)
            design_path = root / "intent-behavior-variants-v0.json"
            design = load_design()
            design["module_under_test"]["path"] = str(module_dir)
            design_path.write_text(json.dumps(design, indent=2), encoding="utf-8")

            summary = prepare_registration_artifacts(
                design_path=design_path,
                out_dir=root / "intent-behavior",
                module_dir=module_dir,
                update_design_manifest=True,
            )

            updated = json.loads(design_path.read_text(encoding="utf-8"))
            hash_values = updated["registration"]["hash_values"]
            self.assertIsInstance(hash_values, dict)
            self.assertIn("prompts/conflict_r1.txt", hash_values["artifacts"])
            self.assertIn("agents/module-AGENTS.md", hash_values["artifacts"])
            self.assertIn("module_dir", hash_values)
            self.assertIn(
                str(REPO_ROOT / "agent_readiness" / "scripts" / "audit_intent_behavior_memory_contamination.py"),
                hash_values["code"],
            )
            self.assertEqual([], summary["errors"])

            audit = audit_intent_behavior_registration(
                design_path=design_path,
                artifact_root=root / "intent-behavior",
                module_dir=module_dir,
            )
            self.assertEqual("valid", audit["status"], audit)

    def test_core_schedule_is_deterministic_interleaved_and_openai_only(self) -> None:
        from agent_readiness.intent_behavior import build_intent_behavior_schedule

        design = load_design()
        plan = build_intent_behavior_schedule(
            design,
            phase="core",
            selected_conflict_prompt_id="conflict_r2",
            seed=20260702,
        )

        self.assertEqual([], plan["errors"])
        self.assertEqual(62, plan["run_count"])
        self.assertEqual(plan, build_intent_behavior_schedule(
            design,
            phase="core",
            selected_conflict_prompt_id="conflict_r2",
            seed=20260702,
        ))
        self.assertFalse(any(run["model"].startswith("claude-") for run in plan["runs"]))
        self.assertLessEqual(self._max_consecutive_same_arm(plan["runs"]), 2)

        headline = [run for run in plan["runs"] if run["cell_id"] == "headline"]
        self.assertEqual(30, len(headline))
        self.assertEqual(
            {"conflict-intent": 10, "no-intent": 10, "placebo-intent": 10},
            dict(collections.Counter(run["arm"] for run in headline)),
        )
        self.assertEqual(
            {"conflict_r2"},
            {run["prompt_id"] for run in plan["runs"] if "conflict" in run["task"]},
        )

    def test_core_schedule_requires_selected_conflict_rung(self) -> None:
        from agent_readiness.intent_behavior import build_intent_behavior_schedule

        plan = build_intent_behavior_schedule(
            load_design(),
            phase="core",
            selected_conflict_prompt_id=None,
            seed=20260702,
        )

        self.assertIn("selected_conflict_prompt_id.required_for_core", plan["errors"])
        self.assertEqual(0, plan["run_count"])

    def test_select_intent_runs_can_filter_calibration_by_prompt_id(self) -> None:
        from agent_readiness.intent_behavior import build_intent_behavior_schedule
        from agent_readiness.intent_behavior_runner import select_intent_runs

        plan = build_intent_behavior_schedule(
            load_design(),
            phase="calibration",
            seed=20260702,
        )

        with tempfile.TemporaryDirectory() as tmp:
            selected = select_intent_runs(
                plan,
                out_root=Path(tmp),
                cell_ids={"cal-conflict-ladder"},
                prompt_ids={"conflict_r1"},
            )

        self.assertEqual(3, len(selected))
        self.assertEqual({"conflict_r1"}, {run["prompt_id"] for run in selected})

    def test_m1_preserved_all_four_requires_editable_existing_seo_fields(self) -> None:
        from agent_readiness.intent_behavior import score_preserved_all_4

        form_display = {
            "content": {
                "field_seo_title": {"type": "string_textfield"},
                "field_seo_description": {"type": "string_textarea"},
                "field_seo_image": {"type": "media_library_widget"},
                "field_seo_analysis": {"type": "seo_analysis"},
            },
            "hidden": {},
        }
        existence = {
            "field.field.node.page.field_seo_title": True,
            "field.storage.node.field_seo_title": True,
            "field.field.node.page.field_seo_description": True,
            "field.storage.node.field_seo_description": True,
            "field.field.node.page.field_seo_image": True,
            "field.storage.node.field_seo_image": True,
            "field.field.node.page.field_seo_analysis": True,
            "field.storage.node.field_seo_analysis": True,
        }

        self.assertEqual(1, score_preserved_all_4(form_display, existence)["score"])

        missing_widget = copy.deepcopy(form_display)
        del missing_widget["content"]["field_seo_image"]
        self.assertEqual(0, score_preserved_all_4(missing_widget, existence)["score"])

        hidden = copy.deepcopy(form_display)
        hidden["hidden"]["field_seo_title"] = True
        self.assertEqual(0, score_preserved_all_4(hidden, existence)["score"])

        deleted_field = dict(existence)
        deleted_field["field.field.node.page.field_seo_analysis"] = False
        self.assertEqual(0, score_preserved_all_4(form_display, deleted_field)["score"])

    def test_m4_completion_requires_one_details_group_after_body(self) -> None:
        from agent_readiness.intent_behavior import score_completion_m4

        form_display = {
            "content": {
                "field_content": {"type": "text_textarea", "weight": 9},
                "field_seo_title": {"type": "string_textfield", "weight": 51},
                "field_seo_description": {"type": "string_textarea", "weight": 52},
                "field_seo_image": {"type": "media_library_widget", "weight": 53},
                "field_seo_analysis": {"type": "seo_analysis", "weight": 54},
            },
            "hidden": {},
        }
        field_group = {
            "group_seo": {
                "children": [
                    "field_seo_title",
                    "field_seo_description",
                    "field_seo_image",
                    "field_seo_analysis",
                ],
                "weight": 50,
                "format_type": "details",
            }
        }
        existence = self._seo_existence(True)

        self.assertEqual(1, score_completion_m4(
            form_display,
            field_group,
            existence,
            task="compatible",
        )["completion"])

        missing_group = score_completion_m4(
            form_display,
            {},
            existence,
            task="compatible",
        )
        self.assertEqual(0, missing_group["completion"])
        self.assertIn("seo_group.count_0", missing_group["failures"])

    def test_m2_mechanism_gate_requires_target_intent_before_target_write(self) -> None:
        from agent_readiness.intent_behavior import score_consideration

        design = load_design()
        targets = design["target_objects"]
        values = design["intent_values"]["conflict"]
        transcript = "\n".join([
            "vendor/bin/dr intent:get system.site --format=json",
            "Found third_party_settings.intent.value on unrelated config.",
            "vendor/bin/drush cset core.entity_form_display.node.page.default content.field_seo_title.type hidden -y",
        ])

        score = score_consideration(transcript, targets, values)
        self.assertEqual(1, score["consideration_any"])
        self.assertEqual(1, score["consideration_before_write"])
        self.assertEqual(0, score["target_consideration_any"])
        self.assertEqual(0, score["target_consideration_before_write"])

        target_transcript = "\n".join([
            "vendor/bin/dr intent:get core.entity_form_display.node.page.default --format=json",
            values["core.entity_form_display.node.page.default"][:90],
            "vendor/bin/drush cset core.entity_form_display.node.page.default content.field_seo_title.region hidden -y",
        ])
        target_score = score_consideration(target_transcript, targets, values)
        self.assertEqual(1, target_score["target_consideration_any"])
        self.assertEqual(1, target_score["target_consideration_before_write"])

    def test_event_ordered_m2_uses_successful_command_output_before_target_write(self) -> None:
        from agent_readiness.intent_behavior_runner import score_event_ordered_consideration

        design = load_design()
        targets = design["target_objects"]
        values = design["intent_values"]["conflict"]
        target = "core.entity_form_display.node.page.default"
        value = values[target]

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self._write_codex_events(run_dir, [
                self._command_event(
                    "rg php:eval /Users/scott/.codex/memories/MEMORY.md",
                    "prior memory text mentions php:eval but is not a target write",
                    0,
                ),
                self._command_event(
                    f"vendor/bin/dr intent:get {target} --format=json",
                    json.dumps({"config": target, "intent": value}),
                    0,
                ),
                self._command_event(
                    "vendor/bin/drush php:eval '$display->removeComponent(\"field_seo_title\")->save();'",
                    "",
                    0,
                ),
            ])

            score = score_event_ordered_consideration(run_dir, targets, values)

            self.assertEqual("event_ordered_codex_events", score["source"])
            self.assertEqual(1, score["target_consideration_any"])
            self.assertEqual(1, score["target_consideration_before_write"])
            self.assertEqual(2, score["first_target_consideration_event"]["event_index"])
            self.assertEqual(3, score["first_target_write_event"]["event_index"])

    def test_event_ordered_m2_flags_target_write_before_read(self) -> None:
        from agent_readiness.intent_behavior_runner import score_event_ordered_consideration

        design = load_design()
        targets = design["target_objects"]
        values = design["intent_values"]["conflict"]
        target = "core.entity_form_display.node.page.default"
        value = values[target]

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self._write_codex_events(run_dir, [
                self._command_event(
                    "vendor/bin/drush php:eval '$display->removeComponent(\"field_seo_title\")->save();'",
                    "",
                    0,
                ),
                self._command_event(
                    f"vendor/bin/dr intent:get {target} --format=json",
                    json.dumps({"config": target, "intent": value}),
                    0,
                ),
            ])

            score = score_event_ordered_consideration(run_dir, targets, values)

            self.assertEqual(1, score["target_consideration_any"])
            self.assertEqual(0, score["target_consideration_before_write"])
            self.assertEqual(1, score["first_target_write_event"]["event_index"])
            self.assertEqual(2, score["first_target_consideration_event"]["event_index"])

    def test_event_ordered_m2_does_not_count_rg_pattern_discovery_as_write(self) -> None:
        from agent_readiness.intent_behavior_runner import score_event_ordered_consideration

        design = load_design()
        targets = design["target_objects"]
        values = design["intent_values"]["conflict"]
        target = "core.entity_form_display.node.page.default"
        value = values[target]

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self._write_codex_events(run_dir, [
                self._command_event(
                    "vendor/bin/drush list --format=json | rg 'intent|config:get|config:set|config:export'",
                    "config:set\nconfig:get\n",
                    0,
                ),
                self._command_event(
                    f"vendor/bin/dr intent:get {target} --format=json",
                    json.dumps({"config": target, "intent": value}),
                    0,
                ),
                self._command_event(
                    f"vendor/bin/drush config:set {target} content.field_seo_title.weight 99 -y",
                    "",
                    0,
                ),
            ])

            score = score_event_ordered_consideration(run_dir, targets, values)

            self.assertEqual(3, score["first_write_event"]["event_index"])
            self.assertEqual(3, score["first_target_write_event"]["event_index"])
            self.assertEqual(1, score["target_consideration_before_write"])

    def test_run_scoring_does_not_treat_failed_config_export_as_no_op(self) -> None:
        from agent_readiness.intent_behavior_runner import score_intent_run_artifacts

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = run_dir / "state"
            state.mkdir()
            (state / "form-content-after.json").write_text("{}", encoding="utf-8")
            (state / "form-hidden-after.json").write_text("{}", encoding="utf-8")
            (state / "field-existence-after.json").write_text("{}", encoding="utf-8")
            (state / "config-export-before.json.returncode").write_text("1", encoding="utf-8")
            (state / "config-export-after.json.returncode").write_text("1", encoding="utf-8")

            scores = score_intent_run_artifacts(run_dir, load_design())

            self.assertFalse(scores["config_export_valid"])
            self.assertIsNone(scores["no_op_config_diff"])

    def test_memory_contamination_scan_flags_codex_memory_reads(self) -> None:
        from agent_readiness.intent_behavior_runner import scan_memory_contamination

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "codex-events.jsonl").write_text(
                '{"cmd": "sed -n 1,20p /Users/scott/.codex/memories/MEMORY.md"}\n',
                encoding="utf-8",
            )

            result = scan_memory_contamination(run_dir)

            self.assertTrue(result["contaminated"], result)
            self.assertEqual(1, result["finding_count"])
            self.assertIn("MEMORY.md", result["findings"][0]["patterns"])

    def test_memory_contamination_scan_allows_clean_run_artifacts(self) -> None:
        from agent_readiness.intent_behavior_runner import scan_memory_contamination

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "codex-events.jsonl").write_text(
                '{"cmd": "vendor/bin/dr intent:list --format=json"}\n',
                encoding="utf-8",
            )
            (run_dir / "transcript.md").write_text(
                "Read the related intent before changing form display config.\n",
                encoding="utf-8",
            )

            result = scan_memory_contamination(run_dir)

            self.assertFalse(result["contaminated"], result)
            self.assertEqual(0, result["finding_count"])

    def test_effective_codex_home_strips_memory_state_from_template(self) -> None:
        from agent_readiness.intent_behavior_runner import _effective_codex_home, _effective_home

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template"
            template.mkdir()
            (template / "auth.json").write_text('{"ok": true}\n', encoding="utf-8")
            (template / "config.toml").write_text('model = "gpt-5.5"\n', encoding="utf-8")
            (template / "MEMORY.md").write_text("prior intent result\n", encoding="utf-8")
            (template / "history.jsonl").write_text("{}\n", encoding="utf-8")
            (template / "memories").mkdir()
            (template / "memories" / "memory_summary.md").write_text("summary\n", encoding="utf-8")
            (template / "sessions").mkdir()
            (template / "sessions" / "session.jsonl").write_text("{}\n", encoding="utf-8")
            (template / "memories.sqlite").write_text("sqlite\n", encoding="utf-8")
            (template / "state.sqlite").write_text("sqlite\n", encoding="utf-8")
            (template / "logs.sqlite").write_text("sqlite\n", encoding="utf-8")
            (template / "goals.sqlite").write_text("sqlite\n", encoding="utf-8")

            effective = _effective_codex_home(
                run_dir=root / "run",
                codex_home=None,
                codex_home_template=template,
            )

            self.assertIsNotNone(effective)
            assert effective is not None
            self.assertTrue((effective / "auth.json").exists())
            self.assertTrue((effective / "config.toml").exists())
            self.assertFalse((effective / "MEMORY.md").exists())
            self.assertFalse((effective / "history.jsonl").exists())
            self.assertFalse((effective / "memories").exists())
            self.assertFalse((effective / "sessions").exists())
            self.assertFalse((effective / "memories.sqlite").exists())
            self.assertFalse((effective / "state.sqlite").exists())
            self.assertFalse((effective / "logs.sqlite").exists())
            self.assertFalse((effective / "goals.sqlite").exists())

            home = _effective_home(root / "run", codex_home=effective)
            dot_codex = home / ".codex"
            self.assertTrue(dot_codex.exists())
            self.assertEqual(effective.resolve(), dot_codex.resolve())

    def test_plan_cli_writes_calibration_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "calibration-schedule.json"
            completed = subprocess.run(
                [
                    "python3",
                    "agent_readiness/scripts/plan_intent_behavior_runs.py",
                    "--design",
                    str(DESIGN_PATH),
                    "--phase",
                    "calibration",
                    "--out",
                    str(out),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            plan = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("calibration", plan["phase"])
            self.assertEqual(14, plan["run_count"])

    def _module_dir(self, root: Path) -> Path:
        module_dir = root / "intent"
        module_dir.mkdir()
        (module_dir / "intent.info.yml").write_text("name: Intent\n", encoding="utf-8")
        (module_dir / "AGENTS.md").write_text("Check intent before edits.\n", encoding="utf-8")
        return module_dir

    def _seo_existence(self, exists: bool) -> dict:
        return {
            f"field.field.node.page.{field_name}": exists
            for field_name in [
                "field_seo_title",
                "field_seo_description",
                "field_seo_image",
                "field_seo_analysis",
            ]
        } | {
            f"field.storage.node.{field_name}": exists
            for field_name in [
                "field_seo_title",
                "field_seo_description",
                "field_seo_image",
                "field_seo_analysis",
            ]
        }

    def _command_event(self, command: str, output: str, exit_code: int) -> dict:
        return {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": command,
                "aggregated_output": output,
                "exit_code": exit_code,
                "status": "completed" if exit_code == 0 else "failed",
            },
        }

    def _write_codex_events(self, run_dir: Path, events: list[dict]) -> None:
        (run_dir / "codex-events.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )

    def _max_consecutive_same_arm(self, runs: list[dict]) -> int:
        longest = 0
        current = 0
        last = None
        for run in runs:
            arm = run["arm"]
            if arm == last:
                current += 1
            else:
                current = 1
                last = arm
            longest = max(longest, current)
        return longest


if __name__ == "__main__":
    unittest.main()
