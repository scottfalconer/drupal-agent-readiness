#!/usr/bin/env python3
"""Demux an alias-safety model-A/B workflow output and score it into an auditable
experiment package.

The workflow returns {told?: [...], blind: [...]} where each item is
{condition, model, arm, n, answer:{assessments, command_count}}. For each run this
persists answer.json + evaluator.json + meta.json under the experiment dir, copies
the raw workflow output + ground truth + candidates, records exact model IDs and a
processing timestamp, scores each cell, and writes a per-substrate finding.

Metrics per latent claim:
  - verdict: did the agent flag the path unsafe at all (the actionable answer).
  - reasoned (SUPPORTING, not headline): did the agent's free-text reason explicitly
    recognize the DISABLED/latent nature of the view (strict: the reason must say
    "disabl"/"latent"), vs. getting the verdict right via "admin path is reserved" or
    by treating the disabled view as if it were active ("claimed by view X"). This is a
    heuristic on free text; treat it as supporting evidence and read the cited example
    answers in the synthesis, not as a precise score.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.evaluators.alias_safety import evaluate
from agent_readiness.evaluators.result import EvaluationResult

MODEL_IDS = {"haiku": "claude-haiku-4-5", "opus": "claude-opus-4-8"}


def reason_recognizes_latent(reason: str) -> bool:
    """Strict: the reason must name the disabled / latent nature of the view.

    Excludes verdict-correct-but-shallow reasons like "claimed by view files" or
    "admin path is reserved" that do not show the agent understood the path is
    declared by a *disabled* view that would collide only once enabled.
    """
    r = (reason or "").lower()
    return "disabl" in r or "latent" in r


def process(workflow_output: Path, state_path: Path, out_dir: Path) -> dict[str, Any]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    raw = json.loads(workflow_output.read_text(encoding="utf-8"))
    result = raw.get("result", raw)
    items = (result.get("told") or []) + (result.get("blind") or [])
    latent_keys = [p for p, v in state.items() if v.get("blocker_kind") == "latent_disabled_view"]
    stamp = datetime.now(timezone.utc).isoformat()

    out_dir.mkdir(parents=True, exist_ok=True)
    runs_root = out_dir / "runs"
    # Persist raw inputs for auditability.
    shutil.copyfile(workflow_output, out_dir / "raw-workflow-output.json")
    (out_dir / "ground-truth.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "candidates.json").write_text(json.dumps({
        "candidates": [{"path": p, "blocker_kind": v.get("blocker_kind"), "safe": v.get("safe")} for p, v in state.items()],
        "latent_paths": latent_keys,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    cells: dict[str, dict[str, Any]] = {}
    for item in items:
        model, condition, arm, n = item.get("model"), item.get("condition"), item.get("arm"), item.get("n")
        cell = f"ab-{model}-{condition}"
        cells.setdefault(cell, {"model": model, "model_id": MODEL_IDS.get(model, model), "condition": condition, "runs": []})
        verdict_only = condition == "blind"
        run_id = f"{arm}-{n}"
        answer = (item.get("answer") or {})
        command_count = answer.get("command_count")
        assessments = {"assessments": answer.get("assessments", {})}

        dest = runs_root / cell / run_id
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "answer.json").write_text(json.dumps(assessments, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        if not answer.get("assessments"):
            result_obj = EvaluationResult(passed=False, failures=["no_answer"], details={})
            latent_correct = latent_reasoned = verdict_correct = 0
        else:
            result_obj = evaluate(state, assessments, verdict_only=verdict_only)
            latent_correct = result_obj.details["latent_correct"]
            verdict_correct = result_obj.details["verdict_correct"]
            latent_reasoned = 0
            for p in latent_keys:
                a = answer["assessments"].get(p, {})
                if a.get("safe") is not False:
                    continue
                if verdict_only:
                    if reason_recognizes_latent(a.get("reason", "")):
                        latent_reasoned += 1
                elif a.get("blocker_kind") == "latent_disabled_view":
                    latent_reasoned += 1
        (dest / "evaluator.json").write_text(json.dumps(result_obj.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        meta = {
            "run_id": run_id, "cell": cell, "model": model, "model_id": MODEL_IDS.get(model, model),
            "condition": condition, "arm": arm, "n": n, "command_count": command_count,
            "harness": "Claude Code workflow subagent (general-purpose)", "processed_at": stamp,
            "workflow_output": workflow_output.name,
        }
        (dest / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        cells[cell]["runs"].append({
            "run_id": run_id, "arm": arm, "passed": result_obj.passed, "failures": result_obj.failures,
            "latent_total": len(latent_keys), "latent_correct": latent_correct,
            "latent_reasoned": latent_reasoned, "verdict_correct": verdict_correct,
            "command_count": command_count,
        })

    summary = _summarize(cells)
    (out_dir / "model-ab-results.json").write_text(
        json.dumps({"generated_at": stamp, "model_ids": MODEL_IDS, "latent_paths": latent_keys,
                    "cells": cells, "summary": summary}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "model-ab-FINDING.md").write_text(_render(summary, state), encoding="utf-8")
    return summary


def _arm_stats(runs: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    arm_runs = [r for r in runs if r["arm"] == arm]
    lt = sum(r["latent_total"] for r in arm_runs)
    lc = sum(r["latent_correct"] for r in arm_runs)
    lr = sum(r.get("latent_reasoned", 0) for r in arm_runs)
    vc = sum(r["verdict_correct"] for r in arm_runs)
    cmds = [r["command_count"] for r in arm_runs if isinstance(r.get("command_count"), int)]
    return {
        "n": len(arm_runs), "passes": sum(1 for r in arm_runs if r["passed"]),
        "latent_total": lt, "latent_correct": lc,
        "latent_accuracy": round(lc / lt, 3) if lt else None,
        "latent_reasoned": lr, "latent_reasoned_accuracy": round(lr / lt, 3) if lt else None,
        "verdict_correct": vc, "verdict_total": len(arm_runs) * 6,
        "avg_commands": round(sum(cmds) / len(cmds), 1) if cmds else None,
    }


def _summarize(cells: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for cell, data in cells.items():
        out[cell] = {
            "model": data["model"], "model_id": data["model_id"], "condition": data["condition"],
            "raw_drush": _arm_stats(data["runs"], "raw"),
            "site_architecture": _arm_stats(data["runs"], "equipped"),
        }
    return out


def _render(summary: dict[str, Any], state: dict[str, Any]) -> str:
    latent_paths = [p for p, v in state.items() if v.get("blocker_kind") == "latent_disabled_view"]
    order = ["ab-haiku-told", "ab-opus-told", "ab-haiku-blind", "ab-opus-blind"]
    lines = [
        "# Finding: alias-safety A/B across models (claude-haiku-4-5 vs claude-opus-4-8)",
        "",
        "Latent-claim accuracy, n=3 per cell. **verdict** = flagged the latent path unsafe (the",
        "actionable answer). **reasoned** (supporting metric, free-text heuristic) = the reason",
        "explicitly recognized the path is declared by a *disabled* view.",
        "",
        f"Discriminating cases = disabled-view latent claims: {', '.join('`'+p+'`' for p in latent_paths)}.",
        "",
        "| Model | Condition | raw verdict | equip verdict | raw reasoned | equip reasoned | raw cmds | equip cmds |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for cell in order:
        s = summary.get(cell)
        if not s:
            continue
        r, e = s["raw_drush"], s["site_architecture"]
        def vacc(a):
            return "n/a" if a["latent_accuracy"] is None else f"{a['latent_correct']}/{a['latent_total']} ({a['latent_accuracy']:.0%})"
        def racc(a):
            return "n/a" if a["latent_reasoned_accuracy"] is None else f"{a['latent_reasoned']}/{a['latent_total']} ({a['latent_reasoned_accuracy']:.0%})"
        lines.append(f"| {s['model_id']} | {s['condition']} | {vacc(r)} | {vacc(e)} | {racc(r)} | {racc(e)} | {r['avg_commands']} | {e['avg_commands']} |")
    lines.extend([
        "",
        "Per-run artifacts (answer.json, evaluator.json, meta.json), raw workflow output, ground",
        "truth, and candidates are under this directory. Read the cross-substrate synthesis",
        "(`../alias-safety-SYNTHESIS.md`) for the conclusion and cited example answers.",
        "",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Process an alias-safety model-A/B workflow output into an auditable package")
    parser.add_argument("--workflow-output", type=Path, required=True)
    parser.add_argument("--state-json", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = process(args.workflow_output, args.state_json, args.out_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
