#!/usr/bin/env python3
"""Assemble per-clone answer.json files from a CLI agent (codex, gemini, ...) into
the workflow-output shape that process_model_ab.py consumes, so any vendor's runs
score through the same path as the Claude workflow runs.

Reads <runs-dir>/{raw-N,equipped-N}/answer.json (answer = {assessments, command_count}).

Example:
  python3 agent_readiness/scripts/assemble_cli_runs.py \\
    --runs-dir tmp/agent-readiness/xvendor-runs/codex --model gpt-5.5-codex \\
    --out /tmp/codex-workflow-output.json
"""
import argparse
import json
import re
from pathlib import Path


def assemble(runs_dir: Path, model: str) -> dict:
    items = []
    for d in sorted(runs_dir.iterdir()):
        if not d.is_dir():
            continue
        m = re.match(r"^(raw|equipped)-(\d+)$", d.name)
        if not m:
            continue
        arm, n = m.group(1), int(m.group(2))
        answer_path = d / "answer.json"
        answer = None
        if answer_path.exists() and answer_path.stat().st_size > 0:
            try:
                answer = json.loads(answer_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                answer = None
        items.append({"condition": "blind", "model": model, "arm": arm, "n": n, "answer": answer})
    return {"blind": items}


def main() -> int:
    p = argparse.ArgumentParser(description="Assemble CLI-agent answer.json files into a workflow-output JSON")
    p.add_argument("--runs-dir", type=Path, required=True)
    p.add_argument("--model", required=True, help="Model/agent id to record (e.g. gpt-5.5-codex, gemini-2.5-pro)")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    data = assemble(args.runs_dir, args.model)
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    n = len(data["blind"])
    ok = sum(1 for i in data["blind"] if i["answer"])
    print(f"assembled {n} runs ({ok} with answers) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
