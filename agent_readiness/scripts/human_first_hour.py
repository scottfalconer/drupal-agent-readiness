#!/usr/bin/env python3
"""CLI for the real-participant human-agent first-hour Drupal study."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.human_first_hour import (
    DEFAULT_HARNESS_ROOT,
    StudyError,
    collect_belief_responses,
    evaluate_session,
    freeze_session,
    load_agent_stack,
    materialize_team_state,
    prepare_session,
    start_session,
    steering_status,
    validate_session,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Prepare, capture, and evaluate a human-agent first-hour session."
    )
    root.add_argument(
        "--harness-root",
        type=Path,
        default=DEFAULT_HARNESS_ROOT,
        help=f"external first-hour harness root (default: {DEFAULT_HARNESS_ROOT})",
    )
    root.add_argument(
        "--facilitator-root",
        type=Path,
        required=True,
        help=(
            "private study directory outside the external harness; it must be "
            "inaccessible to the participant agent"
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser(
        "prepare", help="create a fresh run and participant packet"
    )
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--participant-id", required=True)
    prepare.add_argument(
        "--install-guidance",
        required=True,
        choices=("full_recipe_v0", "constraints_only_v0"),
    )
    prepare.add_argument("--asset-dir", required=True, type=Path)
    prepare.add_argument("--agent-stack-json", type=Path, required=True)
    prepare.add_argument("--rehearsal", action="store_true")
    prepare.add_argument(
        "--facilitator-isolation-confirmed",
        action="store_true",
        help=(
            "confirm hidden forms/assets are outside agent-readable state; "
            "unrestricted agents require a separate OS account or device"
        ),
    )

    start = commands.add_parser(
        "start", help="record minute 0 and run the milestone poller"
    )
    start.add_argument("--run-id", required=True)
    start.add_argument("--seconds", type=int)

    respond = commands.add_parser(
        "respond", help="run the participant's plain-language minute-60 belief form"
    )
    respond.add_argument("--run-id", required=True)

    freeze = commands.add_parser("freeze", help="atomically capture minute-60 state")
    freeze.add_argument("--run-id", required=True)
    freeze.add_argument("--transcript", type=Path)
    freeze.add_argument("--poll-wait-seconds", type=int, default=20)
    freeze.add_argument("--belief-wait-seconds", type=int, default=600)

    steering = commands.add_parser(
        "steering-status",
        help="show whether the live M4 steering trigger is observable",
    )
    steering.add_argument("--run-id", required=True)

    bundle = commands.add_parser(
        "select-bundle", help="materialize one frozen team-bundle candidate"
    )
    bundle.add_argument("--run-id", required=True)
    bundle.add_argument("--bundle-id", required=True)
    bundle.add_argument("--rationale", required=True)
    bundle.add_argument("--source", choices=("manual", "automatic"), default="manual")

    validate = commands.add_parser("validate", help="validate completed study forms")
    validate.add_argument("--run-id", required=True)

    evaluate = commands.add_parser("evaluate", help="build the session readout")
    evaluate.add_argument("--run-id", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_session(
                run_id=args.run_id,
                participant_id=args.participant_id,
                install_guidance=args.install_guidance,
                asset_dir=args.asset_dir,
                facilitator_root=args.facilitator_root,
                harness_root=args.harness_root,
                agent_stack=load_agent_stack(args.agent_stack_json),
                facilitator_isolation_confirmed=args.facilitator_isolation_confirmed,
                rehearsal=args.rehearsal,
            )
        elif args.command == "start":
            result = start_session(
                run_id=args.run_id,
                facilitator_root=args.facilitator_root,
                harness_root=args.harness_root,
                seconds=args.seconds,
            )
        elif args.command == "respond":
            result = collect_belief_responses(
                run_id=args.run_id,
                facilitator_root=args.facilitator_root,
                harness_root=args.harness_root,
            )
        elif args.command == "freeze":
            result = freeze_session(
                run_id=args.run_id,
                facilitator_root=args.facilitator_root,
                harness_root=args.harness_root,
                transcript=args.transcript,
                poll_wait_seconds=args.poll_wait_seconds,
                belief_wait_seconds=args.belief_wait_seconds,
            )
        elif args.command == "steering-status":
            result = steering_status(
                run_id=args.run_id,
                facilitator_root=args.facilitator_root,
                harness_root=args.harness_root,
            )
        elif args.command == "select-bundle":
            result = materialize_team_state(
                run_id=args.run_id,
                facilitator_root=args.facilitator_root,
                harness_root=args.harness_root,
                bundle_id=args.bundle_id,
                rationale=args.rationale,
                source=args.source,
            )
        elif args.command == "validate":
            result = validate_session(
                run_id=args.run_id,
                facilitator_root=args.facilitator_root,
                harness_root=args.harness_root,
            )
        else:
            result = evaluate_session(
                run_id=args.run_id,
                facilitator_root=args.facilitator_root,
                harness_root=args.harness_root,
            )
    except (StudyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
