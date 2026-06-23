#!/usr/bin/env python3
"""Score the assess.alias_safety A/B experiment.

Reads agent-produced answer.json files from the two arms (raw drush vs
site_architecture-equipped), grades each against independently collected ground
truth, retains a reproducible experiment package, and writes a per-arm summary.

The headline metric is latent-claim accuracy: the share of disabled-view latent
claims each arm correctly flagged as unsafe. That is the case raw inspection
("does anything respond here?") misses and `site-architecture:path-owner`
surfaces directly.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.evaluators.alias_safety import evaluate


RUN_IDS = ["raw-1", "raw-2", "raw-3", "equipped-1", "equipped-2", "equipped-3"]


def _arm(run_id: str) -> str:
    return "site_architecture" if run_id.startswith("equipped") else "raw_drush"


def score(runs_root: Path, state_path: Path, out_dir: Path, verdict_only: bool = False) -> dict[str, Any]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    runs: list[dict[str, Any]] = []
    out_runs = out_dir / "runs"
    out_runs.mkdir(parents=True, exist_ok=True)
    (out_dir / "ground-truth.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    for run_id in RUN_IDS:
        src = runs_root / run_id
        answer_path = src / "answer.json"
        record: dict[str, Any] = {"run_id": run_id, "arm": _arm(run_id)}
        if not answer_path.exists():
            record.update({"status": "no_answer", "passed": False, "failures": ["no_answer"],
                           "latent_total": sum(1 for v in state.values() if v.get("blocker_kind") == "latent_disabled_view"),
                           "latent_correct": 0, "verdict_correct": 0})
            runs.append(record)
            continue
        try:
            answer = json.loads(answer_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            record.update({"status": "bad_json", "passed": False, "failures": ["bad_json"],
                           "latent_total": sum(1 for v in state.values() if v.get("blocker_kind") == "latent_disabled_view"),
                           "latent_correct": 0, "verdict_correct": 0})
            runs.append(record)
            continue
        result = evaluate(state, answer, verdict_only=verdict_only)
        dest = out_runs / run_id
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(answer_path, dest / "answer.json")
        transcript = src / "transcript.md"
        if transcript.exists():
            shutil.copy(transcript, dest / "transcript.md")
        (dest / "evaluator.json").write_text(
            json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        record.update({
            "status": "scored",
            "passed": result.passed,
            "failures": result.failures,
            "latent_total": result.details["latent_total"],
            "latent_correct": result.details["latent_correct"],
            "verdict_correct": result.details["verdict_correct"],
            "candidates_total": result.details["candidates_total"],
        })
        runs.append(record)

    summary = _aggregate(runs)
    (out_dir / "results.json").write_text(
        json.dumps({"runs": runs, "summary": summary, "verdict_only": verdict_only}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "summary.md").write_text(_render_summary(runs, summary, state, verdict_only), encoding="utf-8")
    return {"runs": runs, "summary": summary}


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in ["raw_drush", "site_architecture"]:
        arm_runs = [r for r in runs if r["arm"] == arm]
        latent_total = sum(r["latent_total"] for r in arm_runs)
        latent_correct = sum(r["latent_correct"] for r in arm_runs)
        out[arm] = {
            "runs": len(arm_runs),
            "passes": sum(1 for r in arm_runs if r["passed"]),
            "latent_total": latent_total,
            "latent_correct": latent_correct,
            "latent_accuracy": round(latent_correct / latent_total, 3) if latent_total else None,
        }
    return out


def _render_summary(runs: list[dict[str, Any]], summary: dict[str, Any], state: dict[str, Any], verdict_only: bool = False) -> str:
    latent_paths = [p for p, v in state.items() if v.get("blocker_kind") == "latent_disabled_view"]
    grading = (
        "Knowledge-blind condition: the agent is NOT told that disabled-view latent claims count, "
        "and is graded on the safe/unsafe verdict only (blocker_kind is not required)."
        if verdict_only
        else "Told-the-criterion condition: the agent is told latent disabled-view claims count, and is "
        "graded on both the safe/unsafe verdict and the blocker kind."
    )
    lines = [
        "# Experiment: assess.alias_safety (site_architecture A/B), v0",
        "",
        "Small controlled A/B (n=3 per arm) testing the package's candidate thesis: does live",
        "site self-description (`site-architecture:path-owner`) materially help an agent over raw",
        "Drupal inspection? Both arms get the same task and substrate; only the tooling differs.",
        "",
        grading,
        "",
        "This is early evidence, not a statistical result. n=3 per arm on one substrate.",
        "",
        "## Headline metric: latent-claim accuracy",
        "",
        "Latent claims in this substrate (currently unrouted, but declared by a DISABLED view):",
        "",
    ]
    for p in latent_paths:
        dv = state[p]["detail"].get("disabled_views", [{}])[0]
        lines.append(f"- `{p}` — disabled view `{dv.get('view_id')}:{dv.get('display_id')}`")
    lines.extend([
        "",
        "| Arm | Runs | Full passes | Latent claims caught | Latent accuracy |",
        "| --- | ---: | ---: | --- | ---: |",
    ])
    for arm in ["raw_drush", "site_architecture"]:
        s = summary[arm]
        acc = "n/a" if s["latent_accuracy"] is None else f"{s['latent_accuracy']:.0%}"
        lines.append(
            f"| {arm} | {s['runs']} | {s['passes']}/{s['runs']} | {s['latent_correct']}/{s['latent_total']} | {acc} |"
        )
    lines.extend(["", "## Per-run detail", "", "| Run | Arm | Passed | Latent caught | Verdicts correct | Failures |", "| --- | --- | --- | --- | --- | --- |"])
    for r in runs:
        failures = ", ".join(r["failures"]) if r["failures"] else "—"
        vc = f"{r.get('verdict_correct', 0)}/{r.get('candidates_total', len(state))}"
        lines.append(
            f"| {r['run_id']} | {r['arm']} | {str(r['passed']).lower()} | {r['latent_correct']}/{r['latent_total']} | {vc} | {failures} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "Read latent accuracy as the load-bearing number. The non-latent cases (active route/view/",
        "entity and the genuinely-free paths) are gettable by both arms; the latent disabled-view",
        "claims are the cases that separate live self-description from raw inspection.",
        "",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the alias-safety A/B experiment")
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--state-json", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--verdict-only", action="store_true", help="Grade the safe/unsafe verdict only (knowledge-blind condition)")
    args = parser.parse_args()
    out = score(args.runs_root, args.state_json, args.out_dir, verdict_only=args.verdict_only)
    print(json.dumps(out["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
