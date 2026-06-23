import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_readiness.baseline_gate import audit_inventory_baseline


SCORECARD_FIELDS = [
    "run_id",
    "task_id",
    "task_success",
    "human_rescues",
    "elapsed_seconds",
    "tool_calls",
    "blast_radius",
    "verification_quality",
    "failure_labels",
    "failures",
    "answer_json",
    "transcript",
]

REQUIRED_RUN_RESULT_FIELDS = [
    "run_id",
    "task_id",
    "prompt_version",
    "substrate",
    "agent",
    "metrics",
    "evaluator",
    "failure_labels",
    "artifacts",
]

V0_COMPLETED_STEPS = [
    "De-leaked the inventory prompt (v0.2): expected values are no longer printed in the prompt, so passing requires live discovery.",
    "Retained a failing run to validate failure classification and demonstrate that the evaluator separates correct from incorrect answers on identical ground truth.",
    "Hardened the inventory evaluator: list fields are graded as sets (hallucinated surfaces fail) and Canvas page count must match exactly.",
    "Built and ran the assess.alias_safety A/B (`site-architecture:path-owner` vs Drush-only inspection) across two models, three stock Drupal starting sites plus a controlled non-admin hidden path claim, and three prompt framings; finding: the tool prevents hidden-path misses for lightly-prompted agents (stock Haven n=10: 80% haiku / 70% opus hidden-claim flags vs 100% with site self-description).",
]

V0_HARDENING_STEPS = [
    "Repeat the non-Claude alias-safety run at n=10 and add another non-Claude stack before making a claim across model providers.",
    "Repeated runs for act.event_jsonapi and recover.event_jsonapi, not only inventory.read_only.",
    "Token cost alongside elapsed time in the public scorecard.",
    "Raise n on the remaining Drupal starting sites (core, Convivial) for the condition where the agent is not told the hidden risk; stock Haven is done at n=10.",
    "A larger task set before any aggregate readiness claim.",
]

REQUIRED_PUBLISH_ASSETS = [
    "public/scorecard.csv",
    "public/readiness.json",
    "public/state-of-agents-in-drupal-v0.md",
    "public/finding-site-self-description-v0.md",
    "public/why-this-bench.md",
    "public/package-manifest.json",
]

FORBIDDEN_PUBLIC_CLAIMS = [
    "replicates across vendors",
    "would alias content",
    "public baseline ready",
    "benchmark verdict",
]

FULLY_BLIND_PROMPT_FORBIDDEN_HINTS = [
    "disabled view",
    "disabled views",
    "latent claim",
    "latent claims",
    "latent_disabled_view",
]


def validate_run_result(run_result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_RUN_RESULT_FIELDS:
        if field not in run_result:
            errors.append(field)
    for field in ["answer_json", "transcript"]:
        if "artifacts" in run_result and field not in run_result.get("artifacts", {}):
            errors.append(f"artifacts.{field}")
    for field in ["elapsed_seconds", "tool_calls", "human_rescues"]:
        if "metrics" in run_result and field not in run_result.get("metrics", {}):
            errors.append(f"metrics.{field}")
    for field in ["passed", "failures"]:
        if "evaluator" in run_result and field not in run_result.get("evaluator", {}):
            errors.append(f"evaluator.{field}")
    return errors


def scorecard_rows(run_results: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for run in run_results:
        errors = validate_run_result(run)
        if errors:
            raise ValueError(f"Invalid run result {run.get('run_id', '<unknown>')}: {', '.join(errors)}")
        evaluator = run["evaluator"]
        metrics = run["metrics"]
        artifacts = run["artifacts"]
        failure_labels = run.get("failure_labels", [])
        rows.append({
            "run_id": run["run_id"],
            "task_id": run["task_id"],
            "task_success": str(bool(evaluator["passed"])).lower(),
            "human_rescues": str(metrics["human_rescues"]),
            "elapsed_seconds": str(metrics["elapsed_seconds"]),
            "tool_calls": str(metrics["tool_calls"]),
            "blast_radius": _blast_radius(failure_labels, evaluator.get("failures", [])),
            "verification_quality": _verification_quality(run),
            "failure_labels": ";".join(failure_labels),
            "failures": ";".join(evaluator.get("failures", [])),
            "answer_json": artifacts["answer_json"],
            "transcript": artifacts["transcript"],
        })
    return rows


def write_scorecard_csv(run_results: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCORECARD_FIELDS)
        writer.writeheader()
        writer.writerows(scorecard_rows(run_results))


def render_report(run_results: list[dict[str, Any]]) -> str:
    rows = scorecard_rows(run_results)
    passed = sum(1 for row in rows if row["task_success"] == "true")
    public_errors = audit_inventory_baseline(run_results, required_passes=1)
    numeric_errors = audit_inventory_baseline(run_results, required_passes=3)
    smoke_rows = [
        row
        for run, row in zip(run_results, rows)
        if _is_smoke_run(run)
    ]
    independent_rows = [
        row
        for run, row in zip(run_results, rows)
        if not _is_smoke_run(run)
    ]
    lines = [
        "# State of Agents in Drupal v0: a repeatable evidence loop for constrained Drupal agent tasks",
        "",
        "Short version: this is a qualitative baseline and first finding, not a statistical benchmark. It records a small, repeatable evidence loop for Drupal CMS/Haven so the team can inspect what agents can verify today and what the running site still needs to expose.",
        "",
        "This is not a cross-CMS comparison, not a model leaderboard, and not a migration-to-launch claim.",
        "",
        "**This is an instrument and a first finding, not a readiness verdict.** The loop below is a Drupal agent-evaluation harness; the scorecard shows the loop runs and discriminates, not that Drupal is agent-ready.",
        "",
        "## What we found",
        "",
        "We tested a simple question: can an external AI agent safely decide if a URL path is free to use in Drupal?",
        "",
        "Some Drupal paths look unused but are still claimed by disabled configuration. An agent using ordinary Drush-only inspection can ask whether anything currently routes there and still miss the safer Drupal question: what Drupal will do with this path for the proposed operation, and whether the change could collide with active or inactive site state.",
        "",
        "In the headline run on stock Drupal CMS / Haven, each run asked the agent to judge two hidden path claims. Ten runs produced 20 latent-claim judgments per arm.",
        "",
        "| Model | Drush-only: hidden claims flagged | With site self-description: hidden claims flagged |",
        "| --- | --- | --- |",
        "| claude-haiku-4-5 | 16/20 (80%) | 20/20 (100%) |",
        "| claude-opus-4-8 | 14/20 (70%) | 20/20 (100%) |",
        "",
        "Put differently: Drush-only agents incorrectly judged hidden claimed paths as safe in roughly 20-30% of latent-claim judgments. With site self-description through `site-architecture:path-owner`, we observed 0 such misses in the headline run.",
        "",
        "Initial non-Claude evidence shows the same pattern: OpenAI Codex (gpt-5.5) missed 6/6 hidden claims with Drush-only inspection and flagged 6/6 with site self-description. That is encouraging breadth evidence, not yet a claim across model providers.",
        "",
        "Full write-up: `public/finding-site-self-description-v0.md`. Why this bench exists: `public/why-this-bench.md`. Full method and reproduction steps: `HARNESS.md`.",
        "",
        "## What the method proves",
        "",
        "The package is an evidence loop: fixed public tasks, prompts, transcripts, live-state capture, mechanical evaluators, scorecard rows, readiness flags, and package hashes.",
        "",
        "**This release makes three claims:**",
        "",
        "1. **Finding:** site self-description prevents a measured alias-safety failure in this constrained task.",
        "2. **Method:** Drupal agent-readiness can be measured with public tasks, transcripts, state capture, and mechanical evaluators.",
        "3. **Roadmap signal:** site self-description is a concrete Drupal roadmap item because it changes agent behavior.",
        "",
        "The package may include tooling/evaluator smoke runs. Treat those as proof that the evidence loop works, not as blinded independent-agent results.",
        "",
        "## What we are not claiming yet",
        "",
        "- Drupal is broadly agent-ready.",
        "- This result is statistically powered.",
        "- This is a cross-CMS comparison or model leaderboard.",
        "- The public tasks are held out or uncontaminated.",
        "- The prototype resolver is production-ready.",
        "- That the initial Codex result proves behavior across model providers.",
        "",
        "## Method",
        "",
        "- Hold the Drupal starting site fixed: Drupal CMS/Haven.",
        "- Keep prompts and evaluators versioned.",
        "- Require `answer.json`, transcript, live-state collection, evaluator output, and run-result JSON for each scored run.",
        "- Treat low v0 numbers as baseline evidence, not a failed initiative.",
        "",
        "## Scorecard",
        "",
        f"- Constrained task runs in this scorecard: {len(rows)}",
        f"- Constrained evaluator passes: {passed}/{len(rows)}",
        f"- Failing runs retained: {len(rows) - passed}",
        (
            "- Discrimination: demonstrated — the evaluator fails an incorrect answer on identical ground truth."
            if (len(rows) - passed) > 0
            else "- Discrimination: not yet demonstrated (no failing run retained)."
        ),
        "- Inventory prompt: v0.2 (de-leaked) — answers must be discovered from the live site, not transcribed from the prompt. Some earlier passes used v0.1 (leaked) prompts; see prompt_version per run.",
        "",
        "These are constrained v0 tasks. They prove the evidence loop and evaluator contract, not broad Drupal agent-readiness.",
        "",
        "| This scorecard proves | This scorecard does not prove |",
        "| --- | --- |",
        "| The harness can collect runs, transcripts, state, and evaluator output. | Drupal is broadly agent-ready. |",
        "| The evaluator can pass correct answers and fail incorrect answers. | Agents can complete realistic Drupal projects. |",
        "| Public, repeatable Drupal agent tasks are feasible. | The task set is statistically powered. |",
        "| A retained failure can identify concrete missing context. | The current pass rate generalizes beyond these constrained tasks. |",
        "",
        "### Tooling/evaluator smoke runs",
        "",
        "These runs prove the package, evaluator, and reporting loop work.",
        "",
    ]
    lines.extend(_scorecard_table(smoke_rows))
    lines.extend([
        "",
        "### Independent/constrained agent runs",
        "",
        "These runs provide early evidence about agent performance on constrained Drupal tasks.",
        "",
    ])
    lines.extend(_scorecard_table(independent_rows))
    lines.extend([
        "",
        "## Readiness",
        "",
        "- Private circulation: ready",
        "- Public v0 package: " + ("ready" if not public_errors else "not ready"),
        "- Constrained v0 mechanical-pass claims: " + ("ready" if not numeric_errors else "not ready"),
        "",
        "Provenance — what these flags do NOT certify:",
        "",
        "- Metrics for the inventory/event/recovery runs are operator-supplied, not instrumented (the v0.2 de-leaked inventory run and the alias-safety runs are instrumented).",
        "- 'Independent' is asserted via free-text agent metadata, not bound to the answer.",
        "- The flags certify the evidence-loop method plus N genuine evaluator passes on a fixed Drupal starting site — not a blinded or statistically-powered benchmark.",
    ])
    if public_errors or numeric_errors:
        lines.extend([
            "- Remaining gate: " + (public_errors[0] if public_errors else numeric_errors[0]),
        ])
    lines.extend([
        "",
        "## Current interpretation",
        "",
        "The candidate solution is simple:",
        "",
        "- Static `AGENTS.md` should explain how to inspect safely.",
        "- The running Drupal site should answer current site facts through live commands, config reads, path ownership, generated briefs, and machine-readable inventories.",
        "",
        "The alias-safety finding is the first example of a wrong-layer failure pattern: the agent checks the current routing layer and misses operation-specific Drupal state. It is not the full scope of path ownership or agent readiness.",
        "",
        "The controlled tests support that second point narrowly. Live self-description helps lightly prompted agents avoid hidden path conflicts. When an agent is already told exactly what hidden state to check, the extra tool adds little correctness value.",
        "",
        "## Experiments",
        "",
        "`assess.alias_safety` compares `site-architecture:path-owner` with Drush-only inspection.",
        "",
        "What varied:",
        "",
        "- Models: claude-haiku-4-5 and claude-opus-4-8.",
        "- Drupal starting sites: Haven, core-std, Convivial, plus one controlled non-admin hidden path claim.",
        "- Prompt framing: told, soft-blind, and fully blind.",
        "",
        "What the experiment found:",
        "",
        "- When the agent is told the safety criterion, both arms are near 100%; the tool gives little correctness edge.",
        "- When the agent is not told the hidden risk, Drush-only inspection misses disabled-View hidden path claims.",
        "- On stock Haven at n=10 runs per arm, with two hidden-claim judgments per run, Drush-only inspection flagged 80% (haiku) and 70% (opus) of hidden claims.",
        "- With `path-owner`, both models flagged 100% of those hidden claims.",
        "- Initial OpenAI Codex evidence shows the same direction: Drush-only missed 6/6 hidden claims and site self-description flagged 6/6. That is non-Claude breadth evidence, not a provider-general claim.",
        "",
        "So the tool's narrow correctness value is preventing hidden-path misses for lightly prompted agents. Evidence, not proof. See `experiments/alias-safety-SYNTHESIS.md`.",
        "",
        "## Publication Notes",
        "",
        "- Publish the method, prompts, evaluator contract, and sample runs together.",
        "- Keep v0 claims Drupal-first until repeated runs and more tasks exist.",
        "- Do not present v0 as statistically significant; use it to make failure modes concrete and rerunnable.",
        "",
        "## Next hardening steps",
        "",
        "This v0 package proves the evidence loop and now demonstrates discrimination. It does not yet prove broad Drupal agent-readiness.",
        "",
        "Completed in v0.2:",
        "",
    ])
    for step in V0_COMPLETED_STEPS:
        lines.append(f"- {step}")
    lines.extend([
        "",
        "Remaining:",
        "",
    ])
    for step_number, step in enumerate(V0_HARDENING_STEPS, start=1):
        lines.append(f"{step_number}. {step}")
    return "\n".join(lines) + "\n"


def write_report(run_results: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_report(run_results), encoding="utf-8")


def build_package_manifest(base_dir: Path, run_results: list[dict[str, Any]]) -> dict[str, Any]:
    paths = {
        "README.md",
        "PUBLISHING.md",
        "tasks.yml",
        "schema/run-result.schema.json",
        "public/scorecard.csv",
        "public/readiness.json",
        "public/state-of-agents-in-drupal-v0.md",
        "public/finding-site-self-description-v0.md",
        "public/why-this-bench.md",
    }
    for directory in ["prompts", "evaluators", "scripts", "fixtures", "tests", "experiments"]:
        root = base_dir / directory
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    paths.add(path.relative_to(base_dir).as_posix())
    for pattern in ["*.py", "*.md"]:
        for path in base_dir.glob(pattern):
            paths.add(path.relative_to(base_dir).as_posix())
    public_dir = base_dir / "public"
    if public_dir.exists():
        for path in public_dir.glob("*.md"):
            paths.add(path.relative_to(base_dir).as_posix())
    for run_result in run_results:
        paths.add(f"runs/{run_result['run_id']}/run-result.json")
        for artifact in run_result["artifacts"].values():
            paths.add(artifact)

    files = []
    for relative in sorted(paths):
        path = base_dir / relative
        if not path.exists() or not path.is_file():
            continue
        files.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })

    return {
        "schema_version": "drupal_agent_readiness_package_manifest.v0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package": "State of Agents in Drupal v0 evidence package",
        "run_ids": [run_result["run_id"] for run_result in run_results],
        "files": files,
    }


def write_package_manifest(base_dir: Path, run_results: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _json_dumps(build_package_manifest(base_dir, run_results)),
        encoding="utf-8",
    )


def audit_publication_package(base_dir: Path, run_results: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for run_result in run_results:
        errors.extend(validate_run_result(run_result))
        for artifact in run_result.get("artifacts", {}).values():
            artifact_path = base_dir / artifact
            if not artifact_path.exists():
                errors.append(f"missing artifact: {artifact}")
    for required in REQUIRED_PUBLISH_ASSETS:
        if not (base_dir / required).exists():
            errors.append(f"missing publish asset: {required}")
    _audit_prompt_leaks(base_dir, errors)
    _audit_public_claims(base_dir, errors)
    manifest_path = base_dir / "public/package-manifest.json"
    if manifest_path.exists():
        manifest = _load_manifest(manifest_path, errors)
        for entry in manifest.get("files", []):
            path = base_dir / entry.get("path", "")
            if not path.exists():
                errors.append(f"manifest file missing: {entry.get('path')}")
                continue
            digest = _sha256(path)
            if digest != entry.get("sha256"):
                errors.append(f"manifest hash mismatch: {entry.get('path')}")
    return errors


def _audit_prompt_leaks(base_dir: Path, errors: list[str]) -> None:
    prompt_path = base_dir / "prompts" / "assess.alias_safety.fully_blind.md"
    if prompt_path.exists():
        text = prompt_path.read_text(encoding="utf-8").lower()
        for forbidden in FULLY_BLIND_PROMPT_FORBIDDEN_HINTS:
            if forbidden in text:
                errors.append(f"fully blind prompt leak: {prompt_path.relative_to(base_dir)} contains {forbidden!r}")

    candidates_path = base_dir / "prompts" / "assess.alias_safety.candidates.public.json"
    if candidates_path.exists():
        try:
            candidates = _json_load(candidates_path)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            for index, candidate in enumerate(candidates.get("candidates", [])):
                extra_keys = set(candidate) - {"path"}
                if extra_keys:
                    errors.append(
                        "fully blind candidate leak: "
                        f"{candidates_path.relative_to(base_dir)} candidate {index} includes {sorted(extra_keys)}"
                    )

    told_path = base_dir / "prompts" / "assess.alias_safety.told.md"
    if told_path.exists():
        text = told_path.read_text(encoding="utf-8").lower()
        if "told/control" not in text and "control variant" not in text:
            errors.append(f"told prompt unlabeled: {told_path.relative_to(base_dir)}")


def _audit_public_claims(base_dir: Path, errors: list[str]) -> None:
    public_dir = base_dir / "public"
    if not public_dir.exists():
        return
    for path in sorted(public_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_PUBLIC_CLAIMS:
            if forbidden in text:
                errors.append(f"deprecated public claim: {path.relative_to(base_dir)} contains {forbidden!r}")


def _blast_radius(failure_labels: list[str], failures: list[str]) -> str:
    if "blast_radius" in failure_labels or any(failure.startswith("blast_radius.") for failure in failures):
        return "failed"
    return "clean"


def _verification_quality(run_result: dict[str, Any]) -> str:
    evaluator = run_result["evaluator"]
    artifacts = run_result.get("artifacts", {})
    if artifacts.get("evaluator_json") and evaluator.get("passed"):
        return "mechanical-pass"
    if artifacts.get("evaluator_json"):
        return "mechanical-fail"
    return "self-report-only"


def _scorecard_table(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["No runs in this section."]
    lines = [
        "| Run | Task | Success | Human rescues | Elapsed seconds | Tool calls | Verification | Blast radius |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['run_id']} | {row['task_id']} | {row['task_success']} | {row['human_rescues']} | {row['elapsed_seconds']} | {row['tool_calls']} | {row['verification_quality']} | {row['blast_radius']} |"
        )
    return lines


def _is_smoke_run(run: dict[str, Any]) -> bool:
    agent = run.get("agent", {})
    return (
        "tooling-smoke" in run.get("run_id", "")
        or agent.get("name") == "Tooling smoke"
        or agent.get("model") == "none"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_dumps(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _load_manifest(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        data = _json_load(path)
    except ValueError as exc:
        errors.append(f"invalid manifest json: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def _json_load(path: Path) -> dict[str, Any]:
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    return data
