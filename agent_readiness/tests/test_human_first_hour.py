import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_readiness.human_first_hour import (
    StudyError,
    collect_belief_responses,
    evaluate_session,
    freeze_session,
    load_json,
    materialize_team_state,
    prepare_session,
    start_session,
    steering_status,
    validate_session,
    write_json,
)


FAKE_HARNESS = r"""#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text())
OUT = ROOT / CONFIG["out_root"]

parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest="command", required=True)
for name in ("prep", "score"):
    child = sub.add_parser(name)
    child.add_argument("--run-id", required=True)
poll = sub.add_parser("poll")
poll.add_argument("--run-id", required=True)
poll.add_argument("--seconds", required=True, type=int)
args = parser.parse_args()

run_dir = OUT / args.run_id
if args.command == "prep":
    if args.run_id == "human-dcms-0f":
        print(json.dumps({"ok": False, "error": "fixture refusal"}))
        raise SystemExit(0)
    work = run_dir / "work"
    (work / ".ddev").mkdir(parents=True)
    if args.run_id != "human-dcms-03":
        config_root = work / "site" if args.run_id == "human-dcms-0b" else work
        (config_root / ".ddev").mkdir(parents=True, exist_ok=True)
        (config_root / ".ddev" / "config.yaml").write_text(
            "name: fh-" + args.run_id + "\ntype: drupal11\ndocroot: web\n"
        )
    (run_dir / "prompt.md").write_text("autonomous prompt: do not show participant\n")
    (run_dir / "run-meta.json").write_text(json.dumps({
        "run_id": args.run_id,
        "platform": "drupal-cms",
        "work": str(work),
        "ddev_project": "fh-" + args.run_id,
        "access_marker": "RESTRICTED-FEEDBEEF",
        "port": 8000,
    }))
    print(json.dumps({"ok": True, "run_id": args.run_id}))
elif args.command == "poll":
    milestones = {"M1": 2.0, "M4": 4.0, "MG": 6.0}
    (run_dir / "poll-result.json").write_text(json.dumps({
        "run_id": args.run_id, "milestones": milestones
    }))
    (run_dir / "milestones.jsonl").write_text(
        "\n".join(json.dumps({"t": value, "milestone": name})
                  for name, value in milestones.items()) + "\n"
    )
    (run_dir / "captured-http.json").write_text(json.dumps({
        "paths": {"/": {"code": 200}, "/team": {"code": 200}}
    }))
    print(json.dumps({"run_id": args.run_id, "milestones": milestones}))
else:
    score = {
        "run_id": args.run_id,
        "platform": "drupal-cms",
        "milestones": {"M1": 2.0, "M4": 4.0, "MG": 6.0},
        "rungs_verified": {
            "rung3_content_model": False,
            "team_bundle_detected": None,
            "team_count": None,
        },
        "verified_count": 999,
        "honesty_gap": -999,
        "contamination": {"strong": True},
        "valid": False,
    }
    (run_dir / "score.json").write_text(json.dumps(score))
    print(json.dumps(score))
"""


FAKE_DDEV = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
stopped = (Path.cwd() / ".ddev" / "stopped-at-freeze").exists()
if args[:2] == ["describe", "-j"]:
    print(json.dumps({"raw": {
        "name": "fake-human-session",
        "status": "stopped" if stopped else "running",
        "primary_url": "https://fake-human-session.test",
    }}))
elif stopped:
    (Path.cwd() / ".ddev" / "unexpected-command-after-stopped").write_text(repr(args))
    print("capture attempted to start a stopped project", file=sys.stderr)
    raise SystemExit(2)
elif args[:2] == ["drush", "status"]:
    print(json.dumps({"bootstrap": "Successful", "uri": "https://fake-human-session.test"}))
elif args[:2] == ["drush", "php:eval"]:
    php = args[2]
    if "Role::loadMultiple" in php:
        print(json.dumps({
            "anonymous": ["access content"],
            "staff_editor": [
                "access content",
                "create team_member content",
                "edit any team_member content",
            ],
        }))
    else:
        print(json.dumps([
            {
                "bundle": "page",
                "label": "Basic page",
                "fields": {"title": "string", "body": "text_with_summary"},
                "node_count": 1,
                "nodes": [],
            },
            {
                "bundle": "team_member",
                "label": "Team member",
                "fields": {
                    "title": "string",
                    "field_role": "string",
                    "field_photo": "image",
                },
                "node_count": 3,
                "nodes": [
                    {"id": 1, "label": "Alex Rivera", "fields": {}},
                    {"id": 2, "label": "Jordan Lee", "fields": {}},
                    {"id": 3, "label": "Sam Patel", "fields": {}},
                ],
            },
        ]))
elif args and args[0] == "snapshot":
    name = args[args.index("--name") + 1]
    target = Path.cwd() / ".ddev" / "db_snapshots" / (name + ".txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("snapshot-created-before-archive\n")
    print(name)
else:
    print("unsupported fake ddev invocation: " + repr(args), file=sys.stderr)
    raise SystemExit(2)
"""


FAKE_CURL = r'''#!/usr/bin/env python3
import sys
from pathlib import Path

args = sys.argv[1:]
headers = Path(args[args.index("-D") + 1])
body = Path(args[args.index("-o") + 1])
url = args[-1]
headers.write_text("HTTP/1.1 200 OK\nContent-Type: text/html\n\n")
if url.endswith("/team"):
    body.write_text("""<!doctype html><html><body>
    <article><h2>Alex Rivera</h2><p>Executive Director</p><img src=alex.jpg></article>
    <article><h2>Jordan Lee</h2><p>Program Manager</p><img src=jordan.jpg></article>
    <article><h2>Sam Patel</h2><p>Communications Lead</p><img src=sam.jpg></article>
    </body></html>""")
else:
    body.write_text("<!doctype html><html><body>" + ("Drupal CMS home " * 30) + "</body></html>")
'''


class HumanFirstHourTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.harness = self.root / "first-hour-experience"
        self.facilitator_root = self.root / "facilitator-private"
        self.assets = self.root / "assets"
        self.bin = self.root / "bin"
        self.agent_stack = {
            "product": "fixture-agent",
            "version": "1.0-test",
            "model_or_selector": "fixture-model",
            "mode": "agent",
            "approval_policy": "fixture-auto",
            "enabled_tools": ["shell", "files"],
            "workspace_boundary": "assigned work directory only",
            "workspace_shell": True,
        }
        (self.harness / "scripts").mkdir(parents=True)
        (self.harness / "state").mkdir()
        self.assets.mkdir()
        self.bin.mkdir()
        write_json(
            self.harness / "config.json",
            {
                "out_root": "evidence/runs",
                "schedule_path": "state/schedule.json",
            },
        )
        write_json(
            self.harness / "state" / "schedule.json",
            {
                "id": "first-hour-v0",
                "runs": [
                    {
                        "run_id": "existing-01",
                        "platform": "drupal-cms",
                    }
                ],
            },
        )
        self._executable(self.harness / "scripts" / "firsthour.py", FAKE_HARNESS)
        self._executable(self.bin / "ddev", FAKE_DDEV)
        self._executable(self.bin / "curl", FAKE_CURL)
        for name in ("alex.jpg", "jordan.jpg", "sam.jpg", "taylor.jpg"):
            (self.assets / name).write_bytes(("fixture-" + name).encode())
        self.path_patch = patch.dict(
            os.environ,
            {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "")},
        )
        self.path_patch.start()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def _executable(path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _run_dir(self, run_id: str) -> Path:
        return self.harness / "evidence" / "runs" / run_id

    def _submit_belief(self, run_id: str) -> None:
        path = self.facilitator_root / run_id / "belief-inventory.json"
        belief = load_json(path)
        for answer in belief["answers"]:
            answer.update(
                {
                    "answer": "yes",
                    "confidence": 5,
                    "main_reason": "agent_said_so",
                }
            )
        belief["submitted_at"] = "2026-07-12T18:00:00+00:00"
        write_json(path, belief)

    def _complete_forms(self, run_id: str) -> Path:
        human = self.facilitator_root / run_id
        belief = load_json(human / "belief-inventory.json")
        for answer in belief["answers"]:
            if answer["answer"] is None:
                answer.update(
                    {
                        "answer": "yes",
                        "confidence": 5,
                        "main_reason": "agent_said_so",
                    }
                )
        belief["submitted_at"] = belief["submitted_at"] or "2026-07-12T18:00:00+00:00"
        write_json(human / "belief-inventory.json", belief)

        belief_coding = load_json(human / "belief-coding.json")
        handoff = next(
            row
            for row in belief_coding["claims"]
            if row["claim_id"] == "handoff_continuable"
        )
        # Leave these absent first so the validator proves that a confident false
        # belief must be routed to a scope and a candidate intervention.
        handoff["failure_scope"] = None
        handoff["candidate_fix"] = None
        handoff["evidence_refs"] = ["transcript:handoff-claim"]
        write_json(human / "belief-coding.json", belief_coding)

        evaluator = load_json(human / "evaluator.json")
        evaluator["evaluator_id"] = "E01"
        evaluator["completed_at"] = "2026-07-12T18:00:00+00:00"
        evidence_dir = human / "evaluator-evidence"
        evidence_dir.mkdir(exist_ok=True)
        for criterion in evaluator["criteria"]:
            criterion["result"] = "pass"
            criterion["evidence_refs"] = []
            for kind in criterion["required_pass_evidence"]:
                native = {
                    ("T1", "root_http"): "minute-60/root.headers",
                    ("T1", "composer_identity"): "minute-60/composer-identity.json",
                    ("T1", "drush_bootstrap"): "minute-60/drush-status.json",
                    ("T4", "anonymous_team_http"): "minute-60/team.headers",
                }
                ref = native.get((criterion["criterion_id"], kind))
                if ref is None:
                    ref = f"evaluator-evidence/{criterion['criterion_id'].lower()}-{kind}.json"
                    write_json(
                        human / ref,
                        {
                            "criterion_id": criterion["criterion_id"],
                            "evidence_kind": kind,
                            "result": "pass",
                            "observed_at": "2026-07-12T18:00:00+00:00",
                            "method": f"fixture check for {kind}",
                        },
                    )
                criterion["evidence_by_kind"][kind] = ref
                criterion["evidence_refs"].append(ref)
        write_json(
            evidence_dir / "belief-truth.json",
            {
                "result": "recorded",
                "observed_at": "2026-07-12T18:00:00+00:00",
                "method": "fixture belief truth merge",
            },
        )
        for row in evaluator["belief_truth"]:
            row["truth"] = (
                "fail" if row["claim_id"] == "handoff_continuable" else "pass"
            )
            row["evidence_refs"] = ["evaluator-evidence/belief-truth.json"]
        write_json(human / "evaluator.json", evaluator)

        events = {
            "coding_status": "complete",
            "unavailable_reason": None,
            "coder_id": "C01",
            "participant_turns": 10,
            "coded_at": "2026-07-12T18:05:00+00:00",
            "events": [
                {
                    "event_id": "e-hard",
                    "event_code": "DL-HARD",
                    "description": "Asked the novice to choose a View or block.",
                    "decision_object": "view_vs_block",
                    "failure_layer": "rendering_or_routing",
                    "failure_scope": "drupal_specific",
                    "candidate_fix": "platform_default_or_recipe",
                    "minutes_lost": 1,
                    "affected_outcome": "T4",
                    "evidence_ref": "transcript:12",
                },
                {
                    "event_id": "e-soft",
                    "event_code": "DL-SOFT",
                    "description": "Recommended permission strings without consequences.",
                    "decision_object": "permission_strings",
                    "failure_layer": "permissions",
                    "failure_scope": "drupal_specific",
                    "candidate_fix": "verification_affordance",
                    "minutes_lost": 5,
                    "affected_outcome": "T6",
                    "evidence_ref": "transcript:20",
                },
                {
                    "event_id": "e-dead-end",
                    "event_code": "DE",
                    "description": "Tried an incompatible setup path.",
                    "failure_layer": "setup",
                    "failure_scope": "mixed",
                    "candidate_fix": "onboarding_material",
                    "minutes_lost": 3,
                    "affected_outcome": "T1",
                    "evidence_ref": "transcript:4",
                },
                {
                    "event_id": "e-rescue",
                    "event_code": "R-HUMAN",
                    "description": "Facilitator supplied a Drupal command.",
                    "failure_layer": "drupal_discovery",
                    "failure_scope": "drupal_specific",
                    "candidate_fix": "introspection_affordance",
                    "minutes_lost": 7,
                    "affected_outcome": "T2",
                    "evidence_ref": "observer:44",
                },
            ],
        }
        write_json(human / "coded-events.json", events)
        write_json(
            human / "transfer.json",
            {
                "transfer_precondition": "blocked_by_build",
                "transfer_outcome": None,
                "assistance": None,
                "elapsed_seconds": None,
                "evidence_refs": ["evaluator-evidence/transfer.json"],
                "notes": "No editor account existed at minute 60.",
            },
        )
        write_json(
            human / "evaluator-evidence" / "transfer.json",
            {
                "result": "blocked_by_build",
                "observed_at": "2026-07-12T18:00:00+00:00",
                "method": "Fixture minute-60 account-state inspection",
            },
        )
        comprehension = load_json(human / "comprehension.json")
        for response in comprehension["responses"]:
            response["answer"] = "Fixture operational answer."
            response["score"] = 2
        for rating in comprehension["ratings"]:
            comprehension["ratings"][rating] = 4
        comprehension["one_change_debrief"] = (
            "Show the safe default and how to verify it."
        )
        write_json(human / "comprehension.json", comprehension)
        write_json(
            human / "evaluator-evidence" / "steering.json",
            {
                "result": "pass",
                "observed_at": "2026-07-12T18:00:04+00:00",
                "method": "Fixture homepage and team-page browser check",
            },
        )
        write_json(
            human / "steering.json",
            {
                "steering_exposed": True,
                "steering_trigger_source": "m4",
                "trigger_clock": "00:04",
                "result": "pass",
                "evidence_refs": ["evaluator-evidence/steering.json"],
            },
        )
        return human

    def test_fake_harness_session_from_prepare_through_readout(self) -> None:
        run_id = "human-dcms-01"
        prepared = prepare_session(
            run_id=run_id,
            participant_id="P01",
            install_guidance="full_recipe_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
            rehearsal=True,
        )
        run_dir = self._run_dir(run_id)
        work = Path(prepared["work"])
        build_assets = work / ".ddev" / "study-assets"

        self.assertEqual({".ddev"}, {path.name for path in work.iterdir()})
        self.assertEqual(
            {"alex.jpg", "jordan.jpg", "sam.jpg"},
            {path.name for path in build_assets.iterdir()},
        )
        self.assertFalse(any(path.name == "taylor.jpg" for path in work.rglob("*")))
        self.assertTrue(
            (
                self.facilitator_root / run_id / "facilitator-only" / "taylor.jpg"
            ).is_file()
        )
        task_card = (work / ".ddev" / "study-packet" / "task-card.md").read_text()
        self.assertIn(str(build_assets), task_card)
        self.assertNotIn("taylor", task_card.lower())
        guidance = (
            work / ".ddev" / "study-packet" / "install-guidance-card.md"
        ).read_text()
        self.assertIn(
            "ddev config --project-name=fh-human-dcms-01 --project-type=drupal11 --docroot=web",
            guidance,
        )
        self.assertIn("ddev composer create-project drupal/cms:^2", guidance)
        metadata = load_json(self.facilitator_root / run_id / "session-metadata.json")
        self.assertTrue(metadata["install_discovery_pre_solved"])
        self.assertIn(
            "M1 measures install execution", metadata["install_guidance_claim_boundary"]
        )
        self.assertEqual({"core", "cli"}, set(metadata["study_runner_identity"]))
        self.assertEqual("", load_json(run_dir / "run-meta.json")["access_marker"])
        self.assertFalse((run_dir / "human").exists())
        self.assertFalse((run_dir / "prompt.md").exists())
        self.assertTrue(
            (
                self.facilitator_root
                / run_id
                / "autonomous-prompt-not-for-participant.md"
            ).is_file()
        )
        exposed_meta = load_json(run_dir / "run-meta.json")["human_study"]
        self.assertNotIn("participant_id", exposed_meta)
        self.assertNotIn("held_out_asset", exposed_meta)
        self.assertNotIn("facilitator", str(exposed_meta).lower())

        start = start_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            seconds=0,
        )
        self.assertEqual(0, start["poll_seconds"])
        self.assertEqual(
            {"M1": 2.0, "M4": 4.0, "MG": 6.0}, start["poll_result"]["milestones"]
        )
        live_steering = steering_status(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertTrue(live_steering["m4_trigger_reached"])
        self.assertEqual(4.0, live_steering["m4_seconds"])

        # Simulate the participant/agent build after asserting that prepare left
        # the create-project target clean apart from DDEV's permitted directory.
        write_json(work / "composer.json", {"name": "drupal/cms", "type": "project"})
        (work / "web").mkdir()
        (work / "web" / "index.php").write_text("<?php // fixture\n")
        self._submit_belief(run_id)

        frozen = freeze_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            poll_wait_seconds=0,
            belief_wait_seconds=0,
        )
        minute_60 = Path(frozen["minute_60"])
        self.assertTrue(minute_60.is_dir())
        self.assertFalse((run_dir / "minute-60.staging").exists())
        self.assertTrue((minute_60 / "capture-manifest.json").is_file())
        self.assertFalse((minute_60 / "human").exists())
        self.assertTrue(
            (
                self.facilitator_root
                / run_id
                / "frozen-minute-60"
                / "belief-inventory.json"
            ).is_file()
        )
        candidates = load_json(minute_60 / "bundle-candidates.json")
        self.assertEqual("team_member", candidates[1]["bundle"])
        self.assertEqual(3, candidates[1]["node_count"])
        with tarfile.open(minute_60 / "workspace.tar.gz", "r:gz") as archive:
            names = archive.getnames()
        self.assertTrue(
            any(
                name.endswith(".ddev/db_snapshots/human-dcms-01-minute60.txt")
                for name in names
            ),
            names,
        )
        self.assertEqual(999, load_json(minute_60 / "score.json")["verified_count"])
        self.assertEqual(
            [], load_json(minute_60 / "capture-status.json")["runtime_identity_drift"]
        )

        materialize_team_state(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            bundle_id="team_member",
            rationale="Only frozen candidate with the three named records and team fields.",
        )

        human = self._complete_forms(run_id)
        invalid = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        invalid_codes = {issue["code"] for issue in invalid["issues"]}
        self.assertIn("false_confident_missing_failure_scope", invalid_codes)
        self.assertIn("false_confident_missing_candidate_fix", invalid_codes)

        belief = load_json(human / "belief-coding.json")
        handoff = next(
            answer
            for answer in belief["claims"]
            if answer["claim_id"] == "handoff_continuable"
        )
        handoff["failure_scope"] = "agent_generic"
        handoff["candidate_fix"] = "verification_affordance"
        handoff["coder_id"] = "C01"
        write_json(human / "belief-coding.json", belief)
        self.assertTrue(
            validate_session(
                run_id=run_id,
                facilitator_root=self.facilitator_root,
                harness_root=self.harness,
            )["ok"]
        )

        bound_receipt_path = human / "evaluator-evidence" / "t5-editor_create.json"
        bound_receipt = load_json(bound_receipt_path)
        misbound_receipt = dict(bound_receipt)
        misbound_receipt["criterion_id"] = "T6"
        write_json(bound_receipt_path, misbound_receipt)
        misbound = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertIn(
            "invalid_criterion_pass_evidence",
            {issue["code"] for issue in misbound["issues"]},
        )
        write_json(bound_receipt_path, bound_receipt)

        steering_path = human / "steering.json"
        original_steering = load_json(steering_path)
        late_statement = dict(original_steering)
        late_statement["steering_trigger_source"] = "participant_statement"
        late_statement["trigger_clock"] = "00:05"
        write_json(steering_path, late_statement)
        wrong_earliest_trigger = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertIn(
            "participant_statement_after_m4",
            {issue["code"] for issue in wrong_earliest_trigger["issues"]},
        )
        write_json(steering_path, original_steering)

        unlisted = minute_60 / "unlisted-after-freeze.txt"
        unlisted.write_text("must not become admissible evidence\n")
        closed_set = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertIn(
            "unlisted_frozen_artifact",
            {issue["code"] for issue in closed_set["issues"]},
        )
        unlisted.unlink()

        readout = evaluate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertEqual(
            "blocked_by_build", readout["transfer"]["transfer_precondition"]
        )
        self.assertIsNone(readout["transfer"]["transfer_outcome"])
        self.assertEqual({"M1": 2.0, "M4": 4.0, "MG": 6.0}, readout["milestones"])
        self.assertEqual(8, readout["comprehension"]["total"])
        self.assertEqual("fixture-agent", readout["agent_stack"]["product"])
        self.assertEqual(1, readout["interaction"]["DL-HARD"]["count"])
        self.assertEqual(
            1.0, readout["interaction"]["DL-HARD"]["per_10_participant_turns"]
        )
        self.assertEqual(1, readout["interaction"]["DL-SOFT"]["count"])
        self.assertEqual(
            ["e-rescue", "e-soft", "e-dead-end"],
            [item["event_id"] for item in readout["top_frictions"]],
        )
        false_confident = next(
            item for item in readout["beliefs"] if item["category"] == "false_confident"
        )
        self.assertEqual("agent_generic", false_confident["failure_scope"])
        self.assertEqual("verification_affordance", false_confident["candidate_fix"])
        self.assertEqual(
            ["contamination", "honesty_gap", "valid", "verified_count"],
            readout["autonomous_score_fields_preserved_but_not_interpreted"],
        )
        self.assertIsNone(readout["verified_governed_value_at_60"])
        self.assertTrue(readout["verified_governed_value_at_registered_stop"])
        self.assertEqual(
            1, readout["interaction"]["decision_object_counts"]["view_vs_block"]
        )
        self.assertEqual(
            1, readout["interaction"]["decision_object_counts"]["permission_strings"]
        )

        coded_path = human / "coded-events.json"
        comprehension_path = human / "comprehension.json"
        complete_coded = load_json(coded_path)
        complete_comprehension = load_json(comprehension_path)
        incomplete_coded = load_json(coded_path)
        incomplete_coded.update(
            {
                "coding_status": "unavailable",
                "unavailable_reason": "Participant declined recording and no transcript exists.",
                "participant_turns": None,
                "events": [],
            }
        )
        write_json(coded_path, incomplete_coded)
        incomplete_comprehension = load_json(comprehension_path)
        incomplete_comprehension["ratings"]["frustration"] = None
        write_json(comprehension_path, incomplete_comprehension)
        partial = evaluate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertEqual("partial", partial["readout_status"])
        self.assertTrue(partial["verified_governed_value_at_registered_stop"])
        self.assertIsNone(partial["interaction"])
        self.assertIsNone(partial["comprehension"])
        self.assertIsNotNone(partial["beliefs"])
        write_json(coded_path, complete_coded)
        write_json(comprehension_path, complete_comprehension)

        live_belief = load_json(human / "belief-inventory.json")
        live_belief["answers"][0]["note"] = "edited after evaluator feedback"
        write_json(human / "belief-inventory.json", live_belief)
        changed = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertIn(
            "participant_belief_changed_after_freeze",
            {issue["code"] for issue in changed["issues"]},
        )

        (minute_60 / "root.html").write_text("tampered after freeze\n")
        tampered = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertIn(
            "manifest_size_mismatch",
            {issue["code"] for issue in tampered["issues"]},
        )

    def test_failed_build_without_ddev_is_still_frozen(self) -> None:
        run_id = "human-dcms-03"
        prepare_session(
            run_id=run_id,
            participant_id="P03",
            install_guidance="full_recipe_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
            rehearsal=True,
        )
        start_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            seconds=0,
        )
        self._submit_belief(run_id)
        frozen = freeze_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            poll_wait_seconds=0,
            belief_wait_seconds=0,
        )
        minute_60 = Path(frozen["minute_60"])
        self.assertFalse(frozen["site_detected"])
        self.assertTrue((minute_60 / "ddev-capture-errors.json").is_file())
        self.assertTrue((minute_60 / "workspace.tar.gz").is_file())
        self.assertFalse((self._run_dir(run_id) / "minute-60.staging").exists())
        with tarfile.open(minute_60 / "workspace.tar.gz", "r:gz") as archive:
            names = archive.getnames()
        self.assertTrue(
            any(name.endswith(".ddev/study-assets/alex.jpg") for name in names)
        )
        self.assertFalse(any("db_snapshots" in name for name in names))

        human = self._complete_forms(run_id)
        belief = load_json(human / "belief-coding.json")
        handoff = next(
            item
            for item in belief["claims"]
            if item["claim_id"] == "handoff_continuable"
        )
        handoff["failure_scope"] = "study_infrastructure"
        handoff["candidate_fix"] = "harness_or_infrastructure"
        handoff["evidence_refs"] = ["observer:blocked-build"]
        handoff["coder_id"] = "C01"
        write_json(human / "belief-coding.json", belief)
        evaluator = load_json(human / "evaluator.json")
        for criterion in evaluator["criteria"]:
            criterion["result"] = "fail"
            criterion["notes"] = "The no-site fixture cannot satisfy this criterion."
            ref = f"evaluator-evidence/{criterion['criterion_id'].lower()}-fail.json"
            write_json(
                human / ref,
                {
                    "criterion_id": criterion["criterion_id"],
                    "result": "fail",
                    "observed_at": "2026-07-12T18:00:00+00:00",
                    "method": "Fixture no-site evidence inspection",
                },
            )
            criterion["evidence_refs"] = [ref]
        write_json(human / "evaluator.json", evaluator)
        self.assertTrue(
            validate_session(
                run_id=run_id,
                facilitator_root=self.facilitator_root,
                harness_root=self.harness,
            )["ok"]
        )

    def test_stopped_ddev_is_not_started_or_scored_during_freeze(self) -> None:
        run_id = "human-dcms-04"
        prepared = prepare_session(
            run_id=run_id,
            participant_id="P04",
            install_guidance="full_recipe_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
        )
        work = Path(prepared["work"])
        (work / ".ddev" / "stopped-at-freeze").write_text("stopped\n")
        start_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            seconds=0,
        )
        self._submit_belief(run_id)
        frozen = freeze_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            poll_wait_seconds=0,
            belief_wait_seconds=0,
        )
        minute_60 = Path(frozen["minute_60"])
        self.assertTrue(frozen["site_detected"])
        self.assertFalse(frozen["site_running_at_freeze"])
        self.assertFalse((work / ".ddev" / "unexpected-command-after-stopped").exists())
        capture = load_json(minute_60 / "capture-status.json")
        self.assertEqual(
            "ddev_not_running_at_freeze",
            capture["external_score_skipped_reason"],
        )
        self.assertFalse((minute_60 / "snapshot.command.json").exists())
        self.assertFalse((minute_60 / "score.json").exists())

    def test_nested_ddev_site_uses_nested_composer_identity(self) -> None:
        run_id = "human-dcms-0b"
        prepared = prepare_session(
            run_id=run_id,
            participant_id="P11",
            install_guidance="full_recipe_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
            rehearsal=True,
        )
        work = Path(prepared["work"])
        site = work / "site"
        write_json(site / "composer.json", {"name": "drupal/cms", "type": "project"})
        (site / "web").mkdir()
        (site / "web" / "index.php").write_text("<?php // nested fixture\n")
        start_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            seconds=0,
        )
        self._submit_belief(run_id)
        frozen = freeze_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            poll_wait_seconds=0,
            belief_wait_seconds=0,
        )
        identity = load_json(Path(frozen["minute_60"]) / "composer-identity.json")
        self.assertEqual("drupal/cms", identity["name"])
        self.assertEqual("site/composer.json", identity["source"])
        self.assertEqual("site", identity["site_relative_to_work"])

    def test_prep_ok_false_rolls_back_only_the_added_schedule_entry(self) -> None:
        before = load_json(self.harness / "state" / "schedule.json")
        with self.assertRaisesRegex(StudyError, "prep refused"):
            prepare_session(
                run_id="human-dcms-0f",
                participant_id="P-bad",
                install_guidance="constraints_only_v0",
                asset_dir=self.assets,
                facilitator_root=self.facilitator_root,
                harness_root=self.harness,
                agent_stack=self.agent_stack,
                facilitator_isolation_confirmed=True,
            )
        self.assertEqual(before, load_json(self.harness / "state" / "schedule.json"))
        self.assertFalse(self._run_dir("human-dcms-0f").exists())

    def test_private_facilitator_root_is_required_outside_harness(self) -> None:
        with self.assertRaisesRegex(StudyError, "outside the external harness"):
            prepare_session(
                run_id="human-dcms-05",
                participant_id="P05",
                install_guidance="full_recipe_v0",
                asset_dir=self.assets,
                facilitator_root=self.harness / "private",
                harness_root=self.harness,
                agent_stack=self.agent_stack,
                facilitator_isolation_confirmed=True,
            )
        self.assertFalse(self._run_dir("human-dcms-05").exists())

    def test_complete_agent_stack_is_required_before_harness_mutation(self) -> None:
        before = load_json(self.harness / "state" / "schedule.json")
        with self.assertRaisesRegex(
            StudyError, "agent stack is missing required fields"
        ):
            prepare_session(
                run_id="human-dcms-08",
                participant_id="P08",
                install_guidance="full_recipe_v0",
                asset_dir=self.assets,
                facilitator_root=self.facilitator_root,
                harness_root=self.harness,
                agent_stack={"product": "underspecified"},
                facilitator_isolation_confirmed=True,
            )
        self.assertEqual(before, load_json(self.harness / "state" / "schedule.json"))

    def test_existing_facilitator_root_permissions_are_never_rewritten(self) -> None:
        existing = self.root / "existing-facilitator"
        existing.mkdir(mode=0o755)
        existing.chmod(0o755)
        before_mode = existing.stat().st_mode & 0o777
        before_schedule = load_json(self.harness / "state" / "schedule.json")
        with self.assertRaisesRegex(StudyError, "runner will not change permissions"):
            prepare_session(
                run_id="human-dcms-0a",
                participant_id="P10",
                install_guidance="full_recipe_v0",
                asset_dir=self.assets,
                facilitator_root=existing,
                harness_root=self.harness,
                agent_stack=self.agent_stack,
                facilitator_isolation_confirmed=True,
            )
        self.assertEqual(before_mode, existing.stat().st_mode & 0o777)
        self.assertEqual(
            before_schedule, load_json(self.harness / "state" / "schedule.json")
        )

    def test_incomplete_session_is_retained_as_null_readout(self) -> None:
        run_id = "human-dcms-09"
        prepare_session(
            run_id=run_id,
            participant_id="P09",
            install_guidance="full_recipe_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
        )
        readout = evaluate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertFalse(readout["ok"])
        self.assertEqual("incomplete", readout["readout_status"])
        self.assertIsNone(readout["verified_governed_value_at_60"])
        self.assertTrue(readout["retained_in_census"])
        self.assertTrue(
            (self.facilitator_root / run_id / "session-readout.json").is_file()
        )

    def test_late_freeze_is_not_labeled_a_standard_hour(self) -> None:
        run_id = "human-dcms-07"
        prepare_session(
            run_id=run_id,
            participant_id="P07",
            install_guidance="full_recipe_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
        )
        start_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            seconds=0,
        )
        receipt_path = self.facilitator_root / run_id / "start-receipt.json"
        receipt = load_json(receipt_path)
        receipt["poll_seconds"] = 3600
        receipt["canonical_start_monotonic_ns"] -= 7_200_000_000_000
        write_json(receipt_path, receipt)
        self._submit_belief(run_id)
        freeze_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            poll_wait_seconds=0,
            belief_wait_seconds=0,
        )
        validation = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertIn(
            "nonstandard_participant_timing",
            {issue["code"] for issue in validation["issues"]},
        )
        capture = load_json(self._run_dir(run_id) / "minute-60" / "capture-status.json")
        self.assertFalse(capture["standard_60_minute_duration"])

    def test_registered_hour_boundary_is_accepted(self) -> None:
        run_id = "human-dcms-0c"
        prepared = prepare_session(
            run_id=run_id,
            participant_id="P12",
            install_guidance="full_recipe_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
        )
        start_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            seconds=0,
        )
        receipt_path = self.facilitator_root / run_id / "start-receipt.json"
        receipt = load_json(receipt_path)
        receipt["poll_seconds"] = 3600
        receipt["canonical_start_monotonic_ns"] -= 3_600_000_000_000
        write_json(receipt_path, receipt)
        work = Path(prepared["work"])
        write_json(work / "composer.json", {"name": "drupal/cms", "type": "project"})
        (work / "web").mkdir()
        (work / "web" / "index.php").write_text("<?php // hour boundary fixture\n")
        self._submit_belief(run_id)
        freeze_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            poll_wait_seconds=0,
            belief_wait_seconds=0,
        )
        capture = load_json(self._run_dir(run_id) / "minute-60" / "capture-status.json")
        self.assertTrue(capture["standard_60_minute_duration"])
        validation = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertNotIn(
            "nonstandard_participant_timing",
            {issue["code"] for issue in validation["issues"]},
        )

    def test_plain_language_respond_command_submits_without_posthoc_fields(
        self,
    ) -> None:
        run_id = "human-dcms-06"
        prepare_session(
            run_id=run_id,
            participant_id="P06",
            install_guidance="full_recipe_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
        )
        responses = iter(value for _ in range(9) for value in ("yes", "4", "3", ""))
        output: list[str] = []
        result = collect_belief_responses(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            input_func=lambda _prompt: next(responses),
            output_func=output.append,
        )
        self.assertEqual(9, result["claim_count"])
        form = load_json(self.facilitator_root / run_id / "belief-inventory.json")
        self.assertTrue(form["submitted_at"])
        self.assertEqual("saw_in_browser", form["answers"][0]["main_reason"])
        self.assertNotIn("failure_scope", form["answers"][0])
        self.assertNotIn("candidate_fix", form["answers"][0])
        self.assertTrue(any("I can open the Drupal site" in line for line in output))

    def test_direct_cli_entrypoint_loads_the_package(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "human_first_hour.py"
        result = subprocess.run(
            [sys.executable, "-B", str(script), "--help"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Prepare, capture, and evaluate", result.stdout)

    def test_duplicate_fixed_form_rows_are_rejected_without_overwrite(self) -> None:
        run_id = "human-dcms-0d"
        prepare_session(
            run_id=run_id,
            participant_id="P0D",
            install_guidance="constraints_only_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
        )
        human = self._complete_forms(run_id)

        belief = load_json(human / "belief-inventory.json")
        belief["answers"].append(dict(belief["answers"][0]))
        write_json(human / "belief-inventory.json", belief)
        coding = load_json(human / "belief-coding.json")
        coding["claims"].append(dict(coding["claims"][0]))
        write_json(human / "belief-coding.json", coding)
        evaluator = load_json(human / "evaluator.json")
        evaluator["criteria"].append(dict(evaluator["criteria"][0]))
        evaluator["belief_truth"].append(dict(evaluator["belief_truth"][0]))
        write_json(human / "evaluator.json", evaluator)

        validation = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        codes = {issue["code"] for issue in validation["issues"]}
        self.assertTrue(
            {
                "belief_claim_row_count_mismatch",
                "duplicate_belief_claim_id",
                "belief_coding_claim_row_count_mismatch",
                "duplicate_belief_coding_claim_id",
                "criterion_row_count_mismatch",
                "duplicate_criterion_id",
                "belief_truth_claim_row_count_mismatch",
                "duplicate_belief_truth_claim_id",
            }.issubset(codes)
        )
        self.assertEqual(
            "incomplete",
            evaluate_session(
                run_id=run_id,
                facilitator_root=self.facilitator_root,
                harness_root=self.harness,
            )["readout_status"],
        )

    def test_malformed_fixed_form_ids_return_structured_issues(self) -> None:
        run_id = "human-dcms-0e"
        prepare_session(
            run_id=run_id,
            participant_id="P0E",
            install_guidance="constraints_only_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
        )
        human = self._complete_forms(run_id)

        belief = load_json(human / "belief-inventory.json")
        belief["answers"][0]["claim_id"] = ["not", "hashable"]
        write_json(human / "belief-inventory.json", belief)
        coding = load_json(human / "belief-coding.json")
        coding["claims"][0]["claim_id"] = {"not": "a string"}
        write_json(human / "belief-coding.json", coding)
        evaluator = load_json(human / "evaluator.json")
        evaluator["criteria"][0]["criterion_id"] = ["not", "hashable"]
        evaluator["belief_truth"][0]["claim_id"] = {"not": "a string"}
        write_json(human / "evaluator.json", evaluator)

        validation = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        codes = {issue["code"] for issue in validation["issues"]}
        self.assertTrue(
            {
                "invalid_belief_claim_id",
                "invalid_belief_coding_claim_id",
                "invalid_criterion_id",
                "invalid_belief_truth_claim_id",
            }.issubset(codes)
        )
        self.assertEqual(
            "incomplete",
            evaluate_session(
                run_id=run_id,
                facilitator_root=self.facilitator_root,
                harness_root=self.harness,
            )["readout_status"],
        )

    def test_hard_and_soft_leakage_require_registered_coding(self) -> None:
        run_id = "human-dcms-02"
        prepare_session(
            run_id=run_id,
            participant_id="P02",
            install_guidance="constraints_only_v0",
            asset_dir=self.assets,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
            agent_stack=self.agent_stack,
            facilitator_isolation_confirmed=True,
        )
        human = self._complete_forms(run_id)
        belief = load_json(human / "belief-coding.json")
        handoff = next(
            item
            for item in belief["claims"]
            if item["claim_id"] == "handoff_continuable"
        )
        handoff["failure_scope"] = "agent_generic"
        handoff["candidate_fix"] = "verification_affordance"
        handoff["evidence_refs"] = ["transcript:handoff"]
        write_json(human / "belief-coding.json", belief)

        evaluator = load_json(human / "evaluator.json")
        original_evidence_refs = list(evaluator["criteria"][0]["evidence_refs"])
        evaluator["criteria"][0]["evidence_refs"] = []
        write_json(human / "evaluator.json", evaluator)
        missing_proof = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertIn(
            "criterion_missing_evidence_ref",
            {issue["code"] for issue in missing_proof["issues"]},
        )
        evaluator["criteria"][0]["evidence_refs"] = original_evidence_refs
        write_json(human / "evaluator.json", evaluator)

        coded = load_json(human / "coded-events.json")
        coded["events"][0].pop("decision_object")
        coded["events"][1]["candidate_fix"] = "invented_fix"
        write_json(human / "coded-events.json", coded)
        validation = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        codes = {issue["code"] for issue in validation["issues"]}
        self.assertIn("missing_or_invalid_decision_object", codes)
        self.assertIn("missing_or_invalid_candidate_fix", codes)

        transfer = load_json(human / "transfer.json")
        transfer["transfer_outcome"] = "navigation_failure"
        write_json(human / "transfer.json", transfer)
        validation = validate_session(
            run_id=run_id,
            facilitator_root=self.facilitator_root,
            harness_root=self.harness,
        )
        self.assertIn(
            "outcome_present_when_transfer_ineligible",
            {issue["code"] for issue in validation["issues"]},
        )

        metadata = load_json(human / "session-metadata.json")
        self.assertFalse(metadata["install_discovery_pre_solved"])
        self.assertIn("M1 includes", metadata["install_guidance_claim_boundary"])
        guidance = (
            Path(load_json(human / "session-metadata.json")["work"])
            / ".ddev"
            / "study-packet"
            / "install-guidance-card.md"
        ).read_text()
        self.assertIn("identify and execute a supported way", guidance)
        self.assertNotIn("ddev config --project-name", guidance)
        self.assertNotIn("composer create-project", guidance)
        self.assertNotIn("site:install", guidance)


if __name__ == "__main__":
    unittest.main()
