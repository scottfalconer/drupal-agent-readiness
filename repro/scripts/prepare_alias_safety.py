#!/usr/bin/env python3
"""Prepare an alias-safety substrate reproducibly: clone a Drupal site into N
raw + M equipped (site_architecture-installed) copies, auto-derive the candidate
paths from the site's own disabled views, and collect ground truth.

This replaces the hand-edited per-substrate setup. Output dir then contains:
  raw-1..N/ eq-1..M/        disposable clones (raw = no module; eq = module)
  candidates.json           auto-derived candidate paths only (the agent sees these)
  candidate-notes.json      human/provenance notes, not passed to agents
  ground-truth.json         core-only ground truth (the referee)
  substrate.json            manifest: base, clones, candidate paths

Example:
  python3 agent_readiness/scripts/prepare_alias_safety.py \\
    --base haven-clean-install --out tmp/agent-readiness/sub-X --n-raw 5 --n-eq 5

See HARNESS.md for the full run/score flow.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[0]))

from agent_readiness.site_architecture_tools import install_site_architecture

BUILDER = ROOT / "evaluators" / "alias_safety_candidate_builder.php"
COLLECTOR = ROOT / "evaluators" / "alias_safety_collector.php"


def _drush_script(site: Path, script: Path, php_ini_scan_dir: str | None, env_extra: dict | None = None) -> str:
    import os
    env = dict(os.environ)
    if php_ini_scan_dir:
        env["PHP_INI_SCAN_DIR"] = php_ini_scan_dir
    if env_extra:
        env.update(env_extra)
    out = subprocess.run([str(site / "vendor" / "bin" / "drush"), "php:script", str(script)],
                         cwd=site, text=True, capture_output=True, check=True, env=env)
    return out.stdout


def main() -> int:
    p = argparse.ArgumentParser(description="Prepare an alias-safety substrate (clones + candidates + ground truth)")
    p.add_argument("--base", type=Path, required=True, help="Drupal site root to clone (must boot via vendor/bin/drush)")
    p.add_argument("--out", type=Path, required=True, help="Output substrate directory")
    p.add_argument("--n-raw", type=int, default=5)
    p.add_argument("--n-eq", type=int, default=5)
    p.add_argument("--php-ini-scan-dir", default=None, help="Dir with a memory-limit .ini (drush OOMs at low limits)")
    args = p.parse_args()

    base = args.base.resolve()
    out = args.out.resolve()
    if out.exists():
        raise SystemExit(f"Output dir already exists: {out}")
    out.mkdir(parents=True)

    print(f"Cloning {base.name} -> {args.n_raw} raw + {args.n_eq} equipped ...")
    raw_dirs, eq_dirs = [], []
    for i in range(1, args.n_raw + 1):
        d = out / f"raw-{i}"
        shutil.copytree(base, d, symlinks=True)
        raw_dirs.append(d)
    if args.n_eq:
        seed = out / "eq-1"
        shutil.copytree(base, seed, symlinks=True)
        install_site_architecture(site_root=seed, output_dir=out)
        eq_dirs.append(seed)
        for i in range(2, args.n_eq + 1):
            d = out / f"eq-{i}"
            shutil.copytree(seed, d, symlinks=True)
            eq_dirs.append(d)

    print("Deriving candidate paths from the site's own views ...")
    candidates_raw = _drush_script(raw_dirs[0], BUILDER, args.php_ini_scan_dir)
    candidate_notes = json.loads(candidates_raw)
    agent_candidates = {
        key: value
        for key, value in candidate_notes.items()
        if key not in {"candidates"}
    }
    agent_candidates["description"] = (
        "Agent-facing path list only. Notes and expected outcomes are stored "
        "separately so fully blind runs are not prompt-leaked."
    )
    agent_candidates["candidates"] = [
        {"path": c["path"]}
        for c in candidate_notes.get("candidates", [])
    ]
    (out / "candidates.json").write_text(json.dumps(agent_candidates, indent=2) + "\n", encoding="utf-8")
    (out / "candidate-notes.json").write_text(json.dumps(candidate_notes, indent=2) + "\n", encoding="utf-8")
    candidate_paths = [c["path"] for c in agent_candidates.get("candidates", [])]

    print("Collecting ground truth (core-only referee) ...")
    gt_raw = _drush_script(raw_dirs[0], COLLECTOR, args.php_ini_scan_dir,
                           env_extra={"AR_ALIAS_CANDIDATES": str(out / "candidates.json")})
    (out / "ground-truth.json").write_text(gt_raw, encoding="utf-8")

    # Per-substrate strict output schema (explicit candidate-path keys) so CLI
    # agents with structured-output (e.g. codex --output-schema) can be pinned.
    props = {p: {"type": "object", "additionalProperties": False,
                 "properties": {"safe": {"type": "boolean"}, "reason": {"type": "string"}},
                 "required": ["safe", "reason"]} for p in candidate_paths}
    (out / "alias_safety.schema.json").write_text(json.dumps({
        "type": "object", "additionalProperties": False,
        "properties": {"assessments": {"type": "object", "additionalProperties": False, "properties": props, "required": candidate_paths},
                       "command_count": {"type": "integer"}},
        "required": ["assessments", "command_count"],
    }, indent=2) + "\n", encoding="utf-8")

    (out / "substrate.json").write_text(json.dumps({
        "base": str(base),
        "raw_clones": [str(d) for d in raw_dirs],
        "eq_clones": [str(d) for d in eq_dirs],
        "candidate_paths": candidate_paths,
        "latent_paths": [p for p, v in json.loads(gt_raw).items() if v.get("blocker_kind") == "latent_disabled_view"],
    }, indent=2) + "\n", encoding="utf-8")

    gt = json.loads(gt_raw)
    print(f"Ready: {out}")
    print(f"  candidate paths: {candidate_paths}")
    print(f"  latent (disabled-view) claims: {[p for p,v in gt.items() if v.get('blocker_kind')=='latent_disabled_view']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
