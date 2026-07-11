import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path
from typing import Any

from agent_readiness.baseline_gate import audit_inventory_baseline
from agent_readiness.benchmark_registries_v1 import (
    SchemaValidationError,
    validate_schema_instance,
)
from agent_readiness.evaluators.event import evaluate as evaluate_event
from agent_readiness.evaluators.inventory import evaluate as evaluate_inventory
from agent_readiness.evaluators.recovery import evaluate as evaluate_recovery
from agent_readiness.published_experiments import (
    PublishedExperimentError,
    load_published_experiments,
    render_experiment_markdown,
)


SCORECARD_FIELDS = [
    "run_id",
    "task_id",
    "run_class",
    "experiment_id",
    "arm",
    "attempt",
    "started_at",
    "prompt_version",
    "substrate_id",
    "agent_name",
    "model",
    "harness",
    "allowed_tools",
    "task_success",
    "human_rescues",
    "elapsed_seconds",
    "tool_calls",
    "tokens_input",
    "tokens_output",
    "metrics_provenance",
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

RUN_RESULT_SCHEMA_PATH = Path(__file__).resolve().parent / "schema/run-result.schema.json"

LEGACY_EVALUATORS = {
    "inventory.read_only": evaluate_inventory,
    "act.event_jsonapi": evaluate_event,
    "recover.event_jsonapi": evaluate_recovery,
}

V0_COMPLETED_STEPS = [
    "De-leaked the inventory prompt (v0.2): expected values are no longer printed in the prompt, so passing requires live discovery.",
    "Retained a failing run so the package exercises and recomputes both passing and failing evaluator outputs.",
    "Hardened the inventory evaluator: list fields are graded as sets (hallucinated surfaces fail) and Canvas page count must match exactly.",
    "Registered the historical alias-safety and intent studies with source hashes, explicit evidence classes, and narrow claim boundaries; the generated experiment tables above are the only numeric source for this report.",
]

V0_HARDENING_STEPS = [
    "Run paired pre/post fixed-agent experiments with identical model, harness, prompt, tools, substrate, attempt policy, and evaluator pins before attributing a change to Drupal.",
    "Factor decision helpers into discovery, facts-only, advice, and actual-write conditions so the benchmark can locate which layer changes behavior.",
    "Measure intent conflict handling and authority resolution, not preservation alone.",
    "Exercise the Drupal lifecycle on clean and messy sites, including onboarding, selection, planning, acting, verification, recovery, and handoff.",
    "Capture harness-derived timing, token, cost, tool-call, rescue, invalid-attempt, and trajectory events for every claim-grade run.",
    "Keep fixed-agent regression and frontier-observation lanes separate; do not publish an aggregate readiness score until coverage and construct-validity evidence justify it.",
]

REQUIRED_PUBLISH_ASSETS = [
    "README.md",
    "PUBLISHING.md",
    "tasks.yml",
    "baseline_gate.py",
    "publishing.py",
    "readiness.py",
    "published_experiments.py",
    "benchmark_registries_v1.py",
    "alias_safety_metrics.py",
    "evaluators/__init__.py",
    "evaluators/common.py",
    "evaluators/result.py",
    "evaluators/inventory.py",
    "evaluators/event.py",
    "evaluators/recovery.py",
    "evaluators/drupal_state_collector.php",
    "schema/run-result.schema.json",
    "schema/benchmark-experiment-v1.schema.json",
    "schema/benchmark-run-v1.schema.json",
    "measurement_v1.py",
    "scripts/audit_publication_package.py",
    "scripts/audit_readiness.py",
    "scripts/build_publish_assets.py",
    "scripts/audit_measurement_v1.py",
    "experiments/published-experiments-v1.json",
    "public/scorecard.csv",
    "public/experiments-v1.json",
    "public/readiness.json",
    "public/state-of-agents-in-drupal-v0.md",
    "public/claims-ledger.md",
    "public/finding-site-self-description-v0.md",
    "public/why-this-bench.md",
    "public/package-manifest.json",
]

GENERATED_DISTRIBUTION_MIRRORS = [
    "scorecard.csv",
    "experiments-v1.json",
    "readiness.json",
    "state-of-agents-in-drupal-v0.md",
    "claims-ledger.md",
    "finding-site-self-description-v0.md",
    "why-this-bench.md",
]

# The publication audit imports these files from the auditor checkout.  A
# package must ship byte-identical copies so a host-only evaluator cannot make
# an otherwise incomplete package look valid.
EXECUTED_SOURCE_CLOSURE = [
    "baseline_gate.py",
    "publishing.py",
    "readiness.py",
    "published_experiments.py",
    "benchmark_registries_v1.py",
    "alias_safety_metrics.py",
    "measurement_v1.py",
    "evaluators/__init__.py",
    "evaluators/common.py",
    "evaluators/result.py",
    "evaluators/inventory.py",
    "evaluators/event.py",
    "evaluators/recovery.py",
    "evaluators/drupal_state_collector.php",
    "scripts/audit_publication_package.py",
    "scripts/audit_readiness.py",
    "scripts/build_publish_assets.py",
    "scripts/audit_measurement_v1.py",
]

CIRCULATED_REPOSITORY_MARKDOWN = [
    "README.md",
    "REVIEW-READINESS.md",
    "docs/claims-ledger.md",
    "docs/finding-site-self-description-v0.md",
    "docs/state-of-agents-in-drupal-v0.md",
    "docs/why-this-bench.md",
    "method/HARNESS.md",
    "method/PUBLISHING.md",
    "method/MEASUREMENT-V1.md",
    "evidence/experiments/alias-safety-SYNTHESIS.md",
    "repro/README.md",
]

REPOSITORY_DEPENDENCIES = [
    *CIRCULATED_REPOSITORY_MARKDOWN,
    "method/benchmark-coverage-v1.json",
    "method/task-families-v1.json",
    "method/improvement-registry-v1.json",
    "method/schema/benchmark-coverage-v1.schema.json",
    "method/schema/task-families-v1.schema.json",
    "method/schema/improvement-registry-v1.schema.json",
]

FORBIDDEN_PUBLIC_CLAIMS = [
    "replicates across vendors",
    "would alias content",
    "public baseline ready",
    "benchmark verdict",
    "discrimination: demonstrated",
    "proves the evidence loop",
    "proof that the evidence loop works",
    "these runs prove",
    "runs and discriminates",
]

# This is a fail-closed tripwire for common broad-readiness paraphrases, not a
# complete semantic classifier.  The claims ledger and human review remain the
# authority for deciding whether a bounded public statement is supported.
BROAD_PUBLIC_CLAIM_PATTERNS = [
    re.compile(
        r"\bdrupal\s+(?:is|is\s+now|has\s+become)\s+"
        r"(?:an?\s+)?(?:(?:broadly|fully|completely|comprehensively|"
        r"production[- ]grade)\s+)?agent[- ]ready\b"
    ),
    re.compile(
        r"\bdrupal\s+"
        r"(?:(?:has\s+)?(?:now\s+)?(?:achieved|attained|reached)|"
        r"(?:now\s+)?(?:provides?|delivers?|offers?))\s+"
        r"(?:(?:broad|complete|comprehensive|full|general|"
        r"production[- ]grade)\s+)?agent[- ]readiness\b"
    ),
    re.compile(
        r"\bdrupal\s+(?:is|is\s+now|has\s+become)\s+"
        r"(?:(?:broadly|fully|generally|completely)\s+)?"
        r"(?:suitable|suited|fit|ready|prepared|equipped)\s+for\s+"
        r"(?:(?:autonomous|ai|production)\s+)*"
        r"(?:agents?|agent(?:ic)?\s+(?:use|workflows?|operations?|systems?))\b"
    ),
    re.compile(
        r"\bdrupal\s+(?:can|could|may|should)\s+(?:now\s+)?be\s+"
        r"(?:considered|called|deemed|classified\s+as)\s+(?:an?\s+)?"
        r"(?:(?:broadly|fully|completely|production[- ]grade)\s+)?"
        r"agent[- ]ready\b"
    ),
    re.compile(
        r"\bdrupal(?:['’]s)\s+"
        r"(?:(?:broad|complete|comprehensive|full)\s+)?"
        r"(?:agent[- ]readiness|suitability\s+for\s+(?:autonomous\s+)?agents?)\s+"
        r"(?:is|has\s+been)\s+"
        r"(?:proven|demonstrated|established|confirmed|validated|certified)\b"
    ),
    re.compile(
        r"\bdrupal\s+(?:provides?|delivers?|offers?)\s+(?:an?\s+)?"
        r"(?:(?:broadly|fully|completely|comprehensively|production[- ]grade)\s+)?"
        r"agent[- ]ready\s+(?:experience|platform|system|environment|workflow)\b"
    ),
    re.compile(
        r"\bagent[- ]readiness\s+in\s+drupal\s+(?:is|has\s+been)\s+"
        r"(?:proven|demonstrated|established|confirmed|validated|certified)\b"
    ),
    re.compile(
        r"\b(?:autonomous|ai)\s+agents?\s+can\s+"
        r"(?:(?:now\s+(?:(?:reliably|safely|successfully|autonomously)\s+)?)|"
        r"(?:(?:reliably|safely|successfully|autonomously)\s+))"
        r"(?:operate|manage|administer|build\s+with|work\s+with)\s+drupal(?:\s+now)?\b"
    ),
    re.compile(r"\bbenchmark\s+verdict\s*(?::|=|\bis\b)"),
    re.compile(
        r"\b(?:(?:this|the|these|our)\s+)?"
        r"(?:benchmark|evaluation|study|evidence|results?|findings?|runs?)\s+"
        r"(?:clearly\s+|conclusively\s+)?"
        r"(?:prove(?:s|d)?|demonstrat(?:e|es|ed)|establish(?:es|ed)?|"
        r"show(?:s|ed)?|confirm(?:s|ed)?|validat(?:e|es|ed)|"
        r"certif(?:y|ies|ied)|verif(?:y|ies|ied))\s+"
        r"(?:the\s+(?:claim|conclusion)\s+)?(?:that\s+)?drupal\b"
    ),
]

FULLY_BLIND_PROMPT_FORBIDDEN_HINTS = [
    "disabled view",
    "disabled views",
    "latent claim",
    "latent claims",
    "latent_disabled_view",
]


def validate_run_result(run_result: dict[str, Any]) -> list[str]:
    """Validate a legacy run result against the checked public JSON Schema.

    The readiness path must not rely on Python truthiness or coercion.  In
    particular, strings such as ``"false"`` and ``"0"`` are invalid rather
    than truthy/convertible substitutes for JSON booleans and integers.
    """
    if not isinstance(run_result, dict):
        return ["$: expected object"]
    try:
        schema = _json_load(RUN_RESULT_SCHEMA_PATH)
        validate_schema_instance(run_result, schema)
    except (OSError, ValueError, SchemaValidationError) as exc:
        return [str(exc)]

    elapsed = run_result["metrics"]["elapsed_seconds"]
    if not math.isfinite(float(elapsed)):
        return ["$.metrics.elapsed_seconds: expected a finite number"]
    return []


def audit_legacy_run_evidence(
    base_dir: Path,
    run_result: dict[str, Any],
) -> list[str]:
    """Recompute a retained legacy evaluator from its answer and live state.

    This proves only that the current package's evidence loop is internally
    coherent. It does not upgrade a legacy run to independent or claim-grade
    evidence because the original agent stack and evaluator revision were not
    preregistered.
    """
    schema_errors = validate_run_result(run_result)
    if schema_errors:
        return [f"legacy run schema invalid: {error}" for error in schema_errors]

    run_id = run_result["run_id"]
    task_id = run_result["task_id"]
    evaluator = LEGACY_EVALUATORS.get(task_id)
    if evaluator is None:
        return [f"legacy run {run_id} has no recomputable evaluator for {task_id}"]

    artifacts = run_result["artifacts"]
    missing = [name for name in ("state_json", "evaluator_json") if name not in artifacts]
    if missing:
        return [
            f"legacy run {run_id} lacks recomputation artifacts: {', '.join(missing)}"
        ]

    expected_root = f"runs/{run_id}/"
    errors: list[str] = []
    resolved: dict[str, Path] = {}
    for role in ("answer_json", "state_json", "evaluator_json", "transcript"):
        relative = artifacts[role]
        if not relative.startswith(expected_root):
            errors.append(
                f"legacy run {run_id} artifact is not run-bound: {role}={relative!r}"
            )
            continue
        try:
            path = _contained_package_path(base_dir, relative)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not path.is_file():
            errors.append(f"missing artifact: {relative}")
            continue
        resolved[role] = path
    if errors:
        return errors
    if resolved["transcript"].stat().st_size == 0:
        return [f"legacy run {run_id} transcript is empty"]

    try:
        answer = _json_load(resolved["answer_json"])
        state = _json_load(resolved["state_json"])
        retained_evaluator = _json_load(resolved["evaluator_json"])
    except ValueError as exc:
        return [str(exc)]
    if not all(
        isinstance(value, dict)
        for value in (answer, state, retained_evaluator)
    ):
        return [f"legacy run {run_id} recomputation artifacts must be JSON objects"]

    recomputed = evaluator(state, answer).to_dict()
    if retained_evaluator != recomputed:
        errors.append(
            f"legacy run {run_id} retained evaluator differs from recomputation"
        )
    embedded = run_result["evaluator"]
    expected_embedded = {
        key: recomputed[key] for key in ("passed", "failures", "warnings")
    }
    if embedded != expected_embedded:
        errors.append(
            f"legacy run {run_id} embedded evaluator differs from recomputation"
        )
    return errors


def _duplicate_run_ids(run_results: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for run in run_results:
        run_id = run.get("run_id") if isinstance(run, dict) else None
        if not isinstance(run_id, str):
            continue
        if run_id in seen:
            duplicates.add(run_id)
        seen.add(run_id)
    return sorted(duplicates)


def scorecard_rows(run_results: list[dict[str, Any]]) -> list[dict[str, str]]:
    duplicate_ids = _duplicate_run_ids(run_results)
    if duplicate_ids:
        raise ValueError(f"Duplicate run_id values: {', '.join(duplicate_ids)}")
    rows = []
    for run in sorted(run_results, key=lambda item: str(item.get("run_id", ""))):
        errors = validate_run_result(run)
        if errors:
            raise ValueError(f"Invalid run result {run.get('run_id', '<unknown>')}: {', '.join(errors)}")
        evaluator = run["evaluator"]
        metrics = run["metrics"]
        artifacts = run["artifacts"]
        agent = run.get("agent", {})
        substrate = run.get("substrate", {})
        failure_labels = run.get("failure_labels", [])
        agent_name = str(agent.get("name", "")).replace(
            "metrics harness-instrumented",
            "legacy metric provenance unverified",
        )
        rows.append({
            "run_id": run["run_id"],
            "task_id": run["task_id"],
            "run_class": _run_class(run),
            "experiment_id": str(run.get("experiment_id", "")),
            "arm": str(run.get("arm", "")),
            "attempt": str(run.get("attempt", "")),
            "started_at": str(run.get("started_at", "")),
            "prompt_version": str(run.get("prompt_version", "")),
            "substrate_id": str(substrate.get("id", "")),
            "agent_name": agent_name,
            "model": str(agent.get("model", "")),
            "harness": str(agent.get("harness", "")),
            "allowed_tools": ";".join(agent.get("tooling", [])),
            "task_success": str(evaluator["passed"] is True).lower(),
            "human_rescues": str(metrics["human_rescues"]),
            "elapsed_seconds": str(metrics["elapsed_seconds"]),
            "tool_calls": str(metrics["tool_calls"]),
            "tokens_input": str(metrics.get("tokens_input", "")),
            "tokens_output": str(metrics.get("tokens_output", "")),
            "metrics_provenance": str(metrics.get("provenance", "operator_supplied_or_unknown")),
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
    output_path.write_text(render_scorecard_csv(run_results), encoding="utf-8")


def render_scorecard_csv(run_results: list[dict[str, Any]]) -> str:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=SCORECARD_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(scorecard_rows(run_results))
    return handle.getvalue()


def render_report(
    run_results: list[dict[str, Any]],
    published_experiments: dict[str, Any] | None = None,
) -> str:
    ordered_runs = sorted(
        run_results,
        key=lambda item: str(item.get("run_id", "")),
    )
    rows = scorecard_rows(ordered_runs)
    passed = sum(1 for row in rows if row["task_success"] == "true")
    public_errors = audit_inventory_baseline(ordered_runs, required_passes=1)
    numeric_errors = audit_inventory_baseline(ordered_runs, required_passes=3)
    smoke_rows = [
        row
        for run, row in zip(ordered_runs, rows)
        if _is_smoke_run(run)
    ]
    independent_rows = [
        row
        for run, row in zip(ordered_runs, rows)
        if not _is_smoke_run(run)
    ]
    experiments = (published_experiments or {}).get("experiments", [])
    estimate_ids = [
        experiment["experiment_id"]
        for experiment in experiments
        if experiment.get("estimate_reportable") is True
    ]
    fixed_estimate_ids = [
        experiment["experiment_id"]
        for experiment in experiments
        if experiment.get("fixed_estimate_reportable") is True
    ]
    effect_rule_ids = [
        experiment["experiment_id"]
        for experiment in experiments
        if experiment.get("registered_effect_rule_met") is True
    ]
    improvement_ids = [
        experiment["experiment_id"]
        for experiment in experiments
        if experiment.get("improvement_ready") is True
    ]
    lines = [
        "# State of Agents in Drupal v0: a runnable evidence loop for constrained Drupal agent tasks",
        "",
        "Short version: this is a qualitative v0 snapshot and historical observation, not a statistical benchmark. It records a small, rerunnable evidence loop for Drupal CMS with the Haven testbed profile so the team can inspect what agents can verify today and what the running site still needs to expose.",
        "",
        "This is not a cross-CMS comparison, not a model leaderboard, and not a migration-to-launch claim.",
        "",
        "**This is an instrument and a historical observation, not a readiness verdict.** The loop below is a Drupal agent-evaluation harness; the scorecard reports retained evaluator outcomes, not evidence that Drupal is agent-ready or that the instrument is a validated discriminator.",
        "",
        "## What we found",
        "",
    ]
    lines.extend(
        render_experiment_markdown(published_experiments)
        if published_experiments is not None
        else [
            "No hashed experiment registry was supplied to this render. Numeric findings are intentionally omitted rather than copied from prose constants.",
            "",
        ]
    )
    lines.extend([
        "",
        "## What the package demonstrates",
        "",
        "The package is an evidence loop: fixed public tasks, prompts, retained answers, scorecard run transcripts, live-state capture, mechanical evaluators, scorecard rows, readiness flags, and package hashes.",
        "",
        "**This release makes one method claim:**",
        "",
        "Constrained Drupal agent tasks can be packaged with public tasks, retained evidence, state capture, mechanical evaluators, and explicit claim boundaries. Each experiment above carries its own narrower evidence class; package validity does not promote an experiment to claim-grade.",
        "",
        "The package may include tooling/evaluator smoke runs. Treat those as evidence that the mechanics execute, not as blinded independent-agent results.",
        "",
        "## What we are not claiming yet",
        "",
        "- Drupal is broadly agent-ready.",
        "- This result is statistically powered.",
        "- This is a cross-CMS comparison or model leaderboard.",
        "- The public tasks are held out or uncontaminated.",
        "- The bundled resolver fixture is production-ready.",
        "- That the initial Codex result proves behavior across model providers.",
        "",
        "## Method",
        "",
        "Context and claim policy: `public/why-this-bench.md`. Reproduction details: the repository-root `method/HARNESS.md`.",
        "",
        "- Hold the Drupal starting site fixed: Drupal CMS with the Haven testbed profile.",
        "- Keep prompts and evaluators versioned.",
        "- Require `answer.json`, transcript or command log, live-state collection, evaluator output, and run-result JSON for each scored run.",
        "- Treat low v0 numbers as baseline evidence, not a failed initiative.",
        "",
        "## Scorecard",
        "",
        f"- Constrained task runs in this scorecard: {len(rows)}",
        f"- Constrained evaluator passes: {passed}/{len(rows)}",
        f"- Failing runs retained: {len(rows) - passed}",
        (
            "- Failing evidence: retained — at least one evaluator result is a failure; this alone does not establish matched discriminator validity."
            if (len(rows) - passed) > 0
            else "- Failing evidence: none retained; matched discriminator validity is not established."
        ),
        "- Inventory prompt: v0.2 (de-leaked) — answers must be discovered from the live site, not transcribed from the prompt. Some earlier passes used v0.1 (leaked) prompts; see prompt_version per run.",
        "",
        "These constrained v0 tasks exercise the evidence loop and evaluator contract; they do not establish broad Drupal agent-readiness.",
        "",
        "| This scorecard demonstrates | This scorecard does not establish |",
        "| --- | --- |",
        "| The harness can collect runs, retained answers, transcripts/logs, state, and evaluator output. | Drupal is broadly agent-ready. |",
        "| The current evaluator code can recompute the retained pass/fail outputs from retained state and answers. | Agents can complete realistic Drupal projects, or that the evaluator has matched discriminator validity. |",
        "| Public, rerunnable Drupal agent tasks are feasible. | The task set is statistically powered. |",
        "| A retained failure can identify concrete missing context. | The current pass rate generalizes beyond these constrained tasks. |",
        "",
        "### Tooling/evaluator smoke runs",
        "",
        "These runs exercise the package, evaluator, and reporting loop.",
        "",
    ])
    lines.extend(_scorecard_table(smoke_rows))
    lines.extend([
        "",
        "### Non-smoke constrained agent runs",
        "",
        "These runs provide early evidence about agent performance on constrained Drupal tasks. The label does not certify independence, pinning, or longitudinal comparability; use each row's provenance columns and run artifacts.",
        "",
    ])
    lines.extend(_scorecard_table(independent_rows))
    lines.extend([
        "",
        "## Readiness",
        "",
        "`public/readiness.json` is a generated, non-authoritative source-gate snapshot. It does not audit the live package tree. Run `scripts/audit_readiness.py` against the files and complete run census being circulated for the authoritative package result. This report render exposes only the run and experiment source gates it can derive directly:",
        "",
        "- At least one no-rescue legacy inventory example: " + ("yes" if not public_errors else "no"),
        "- Three-example legacy evidence-loop check: " + ("yes" if not numeric_errors else "no") + " (not a numeric-claim gate)",
        "- Reportable measurement-v1 estimate: " + (", ".join(estimate_ids) if estimate_ids else "none"),
        "- Reportable fixed-regression estimate: " + (", ".join(fixed_estimate_ids) if fixed_estimate_ids else "none"),
        "- Registered measurement effect rule met: " + (", ".join(effect_rule_ids) if effect_rule_ids else "none"),
        "- Canonical action-registry improvement decision ready: " + (", ".join(improvement_ids) if improvement_ids else "none"),
        "",
        "Provenance — what the legacy example gates do NOT certify:",
        "",
        "- Outcome judgments for the v0.2 inventory and alias-safety examples can be mechanically re-scored from retained answers and ground truth. Tool invocation, token/cost, and complete trajectory evidence are not independently instrumented or retained; legacy timing and tool counts may be operator-supplied or self-reported.",
        "- Non-smoke status is inferred from legacy free-text metadata; it does not establish independence or complete pins.",
        "- Passing examples certify the evidence-loop mechanics only; they do not establish a treatment effect, statistical power, or longitudinal improvement.",
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
        "The historical alias-safety observation is one example of a wrong-layer failure pattern: an agent can check the current routing layer while operation-relevant Drupal state exists elsewhere. It is not the full scope of path ownership or agent readiness.",
        "",
        "The historical comparison bundled module/tool availability with prompt guidance naming a verdict-bearing helper. Retained judgments differed between that condition and Drush-only inspection, but the experiment does not isolate discoverability, installation, facts-only output, advice, or an actual write. `method/improvement-registry-v1.json` therefore requires those layers to be factored in the next frozen rerun.",
        "",
        "## Publication Notes",
        "",
        "- Publish the method, prompts, evaluator contract, and sample runs together.",
        "- Keep v0 claims Drupal-first until repeated runs and more tasks exist.",
        "- Do not present v0 as statistically significant; use it to make failure modes concrete and rerunnable.",
        "",
        "## Next hardening steps",
        "",
        "This v0 package exercises the evidence loop and recomputes retained passing and failing evaluator examples. It does not establish matched discriminator validity or broad Drupal agent-readiness.",
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


def write_report(
    run_results: list[dict[str, Any]],
    output_path: Path,
    published_experiments: dict[str, Any] | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_report(run_results, published_experiments),
        encoding="utf-8",
    )


def build_package_manifest(
    base_dir: Path,
    run_results: list[dict[str, Any]],
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    repository_root = _package_repository_root(base_dir, repository_root)
    base_dir = base_dir.resolve()
    duplicate_ids = _duplicate_run_ids(run_results)
    if duplicate_ids:
        raise ValueError(f"duplicate run_id values: {', '.join(duplicate_ids)}")
    required_paths = set(REQUIRED_PUBLISH_ASSETS) - {"public/package-manifest.json"}
    paths = set(required_paths)
    # The package manifest is a file census, not a Git-index census. Registered
    # measurement sources and artifacts must remain covered even before they are
    # staged. Repository hygiene is enforced separately by CLEAN-MANIFEST.
    if base_dir.exists():
        for path in base_dir.rglob("*"):
            relative_parts = path.relative_to(base_dir).parts
            if ".git" in relative_parts:
                continue
            if "__pycache__" in relative_parts or path.suffix in {".pyc", ".pyo"}:
                raise ValueError(
                    "forbidden executable cache in package: "
                    f"{path.relative_to(base_dir).as_posix()}"
                )
            if path.is_symlink():
                raise ValueError(
                    "unsafe package symlink path: "
                    f"{path.relative_to(base_dir).as_posix()!r}"
                )
            if path.is_file():
                paths.add(path.relative_to(base_dir).as_posix())
    # A content manifest cannot include its own digest without a circular hash.
    paths.discard("public/package-manifest.json")
    public_dir = base_dir / "public"
    if public_dir.exists():
        for path in public_dir.glob("*.md"):
            paths.add(path.relative_to(base_dir).as_posix())
    ordered_runs = sorted(
        run_results,
        key=lambda item: str(item.get("run_id", "")),
    )
    for run_result in ordered_runs:
        run_id = str(run_result["run_id"])
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id) is None:
            raise ValueError(f"unsafe run id in package manifest: {run_id!r}")
        run_result_path = f"runs/{run_id}/run-result.json"
        paths.add(run_result_path)
        required_paths.add(run_result_path)
        for artifact in run_result["artifacts"].values():
            artifact_relative = str(artifact)
            paths.add(artifact_relative)
            required_paths.add(artifact_relative)

    files = []
    for relative in sorted(paths):
        path = _contained_package_path(base_dir, relative)
        if not path.is_file():
            if relative in required_paths:
                raise FileNotFoundError(f"required package file is missing: {relative}")
            continue
        files.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })

    repository_dependencies = []
    for relative in REPOSITORY_DEPENDENCIES:
        path = _contained_repository_dependency(repository_root, relative)
        if not path.is_file():
            raise FileNotFoundError(
                f"required repository dependency is missing: {relative}"
            )
        repository_dependencies.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })

    return {
        "schema_version": "drupal_agent_readiness_package_manifest.v1",
        "package": "State of Agents in Drupal v0 evidence package",
        "run_ids": [run_result["run_id"] for run_result in ordered_runs],
        "files": files,
        "repository_dependencies": repository_dependencies,
    }


def write_package_manifest(
    base_dir: Path,
    run_results: list[dict[str, Any]],
    output_path: Path,
    *,
    repository_root: Path | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _json_dumps(
            build_package_manifest(
                base_dir,
                run_results,
                repository_root=repository_root,
            )
        ),
        encoding="utf-8",
    )


def audit_publication_package(
    base_dir: Path,
    run_results: list[dict[str, Any]],
    *,
    repository_root: Path | None = None,
) -> list[str]:
    repository_root = _package_repository_root(base_dir, repository_root)
    base_dir = base_dir.resolve()
    errors: list[str] = []
    verified_legacy_run_ids: set[str] = set()
    _audit_forbidden_executable_caches(base_dir, errors)
    _audit_executed_source_closure(base_dir, errors)
    _audit_run_result_census(base_dir, run_results, errors)
    duplicate_ids = _duplicate_run_ids(run_results)
    if duplicate_ids:
        errors.append(f"duplicate run_id values: {', '.join(duplicate_ids)}")
    for run_result in run_results:
        schema_errors = validate_run_result(run_result)
        errors.extend(schema_errors)
        if schema_errors:
            continue
        run_id = str(run_result.get("run_id", ""))
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id) is None:
            errors.append(f"unsafe run id: {run_id!r}")
        else:
            run_relative = f"runs/{run_id}/run-result.json"
            try:
                retained_run_path = _contained_package_path(base_dir, run_relative)
            except ValueError as exc:
                errors.append(str(exc))
            else:
                if not retained_run_path.is_file():
                    errors.append(f"missing retained run result: {run_relative}")
                else:
                    try:
                        retained_run = _json_load(retained_run_path)
                    except ValueError as exc:
                        errors.append(str(exc))
                    else:
                        if retained_run != run_result:
                            errors.append(f"retained run result differs from supplied run: {run_relative}")
        for artifact in run_result.get("artifacts", {}).values():
            try:
                artifact_path = _contained_package_path(base_dir, artifact)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if not artifact_path.is_file():
                errors.append(f"missing artifact: {artifact}")
        evidence_errors = audit_legacy_run_evidence(base_dir, run_result)
        errors.extend(evidence_errors)
        if not evidence_errors:
            verified_legacy_run_ids.add(run_result["run_id"])
    for required in REQUIRED_PUBLISH_ASSETS:
        if not (base_dir / required).is_file():
            errors.append(f"missing publish asset: {required}")
    _audit_prompt_leaks(base_dir, errors)
    _audit_public_claims(base_dir, repository_root, errors)
    manifest_path = base_dir / "public/package-manifest.json"
    if manifest_path.exists():
        manifest = _load_manifest(manifest_path, errors)
        for entry in manifest.get("files", []):
            relative = entry.get("path", "")
            try:
                path = _contained_package_path(base_dir, relative)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if not path.is_file():
                errors.append(f"manifest file missing: {entry.get('path')}")
                continue
            digest = _sha256(path)
            if digest != entry.get("sha256"):
                errors.append(f"manifest hash mismatch: {entry.get('path')}")
        for entry in manifest.get("repository_dependencies", []):
            if not isinstance(entry, dict):
                errors.append("invalid repository dependency manifest entry")
                continue
            relative = entry.get("path")
            if relative not in REPOSITORY_DEPENDENCIES:
                errors.append(f"unexpected repository dependency: {relative!r}")
                continue
            try:
                path = _contained_repository_dependency(repository_root, relative)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if not path.is_file():
                errors.append(f"repository dependency missing: {relative}")
                continue
            if _sha256(path) != entry.get("sha256"):
                errors.append(f"repository dependency hash mismatch: {relative}")
        try:
            expected_manifest = build_package_manifest(
                base_dir,
                run_results,
                repository_root=repository_root,
            )
        except (OSError, ValueError) as exc:
            errors.append(f"package manifest cannot be derived: {exc}")
        else:
            if manifest != expected_manifest:
                errors.append("package manifest drift or incomplete file census")
    registry_path = base_dir / "experiments" / "published-experiments-v1.json"
    if registry_path.exists():
        try:
            experiments = load_published_experiments(base_dir, registry_path)
        except PublishedExperimentError as exc:
            errors.append(f"published experiment evidence invalid: {exc}")
        else:
            for experiment in experiments.get("experiments", []):
                if (
                    experiment.get("adapter") == "measurement_v1"
                    and experiment.get("audit", {}).get("audit_valid") is not True
                ):
                    errors.append(
                        "registered measurement-v1 audit invalid: "
                        f"{experiment.get('experiment_id', '<unknown>')}"
                    )
            experiments_path = base_dir / "public" / "experiments-v1.json"
            if experiments_path.exists() and experiments_path.read_text(encoding="utf-8") != _json_dumps(experiments):
                errors.append("generated artifact drift: public/experiments-v1.json")
            try:
                expected_report = render_report(run_results, experiments)
                expected_scorecard = render_scorecard_csv(run_results)
                # Import lazily: readiness imports this module for the package audit.
                from agent_readiness.readiness import derive_readiness_snapshot

                expected_readiness = derive_readiness_snapshot(
                    run_results,
                    experiments,
                    verified_legacy_run_ids=verified_legacy_run_ids,
                )
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"generated artifacts cannot be derived: {exc}")
            else:
                report_path = base_dir / "public" / "state-of-agents-in-drupal-v0.md"
                if report_path.exists() and report_path.read_text(encoding="utf-8") != expected_report:
                    errors.append("generated artifact drift: public/state-of-agents-in-drupal-v0.md")
                scorecard_path = base_dir / "public" / "scorecard.csv"
                if scorecard_path.exists() and scorecard_path.read_text(encoding="utf-8") != expected_scorecard:
                    errors.append("generated artifact drift: public/scorecard.csv")
                readiness_path = base_dir / "public" / "readiness.json"
                if (
                    readiness_path.exists()
                    and readiness_path.read_text(encoding="utf-8")
                    != _json_dumps(expected_readiness)
                ):
                    errors.append("generated artifact drift: public/readiness.json")
    return errors


def audit_distribution_mirrors(
    source_dir: Path,
    distribution_dir: Path,
) -> list[str]:
    """Require every docs mirror to match its explicit canonical transform."""
    errors: list[str] = []
    for filename in GENERATED_DISTRIBUTION_MIRRORS:
        source = source_dir / filename
        mirror = distribution_dir / filename
        if source.is_symlink():
            errors.append(f"generated mirror source is a symlink: {source}")
            continue
        if not source.is_file():
            errors.append(f"generated mirror source missing: {source}")
            continue
        if mirror.is_symlink():
            errors.append(f"generated distribution mirror is a symlink: {mirror}")
            continue
        if not mirror.is_file():
            errors.append(f"generated distribution mirror missing: {mirror}")
            continue
        if _render_distribution_mirror(filename, source.read_bytes()) != mirror.read_bytes():
            errors.append(f"generated distribution mirror drift: {mirror}")
    return errors


def write_distribution_mirrors(source_dir: Path, distribution_dir: Path) -> None:
    """Write docs mirrors using the sole audited transforms."""
    distribution_dir.mkdir(parents=True, exist_ok=True)
    for filename in GENERATED_DISTRIBUTION_MIRRORS:
        source = source_dir / filename
        destination = distribution_dir / filename
        if source.is_symlink():
            raise ValueError(f"generated mirror source is a symlink: {source}")
        if not source.is_file():
            raise FileNotFoundError(f"generated mirror source missing: {source}")
        if destination.is_symlink():
            raise ValueError(
                f"generated distribution mirror is a symlink: {destination}"
            )
        destination.write_bytes(
            _render_distribution_mirror(filename, source.read_bytes())
        )


def _render_distribution_mirror(filename: str, source: bytes) -> bytes:
    """Apply the only allowed package-public to repo-docs transformation."""
    if filename not in GENERATED_DISTRIBUTION_MIRRORS:
        raise ValueError(f"unknown generated distribution mirror: {filename}")
    if filename not in {
        "claims-ledger.md",
        "finding-site-self-description-v0.md",
    }:
        return source
    text = source.decode("utf-8")
    text = text.replace(
        "../../docs/experiments-v1.json",
        "experiments-v1.json",
    )
    if filename == "claims-ledger.md":
        text = text.replace(
            "`scorecard.csv`; `../runs/*`",
            "`docs/scorecard.csv`; `evidence/runs/*`",
        ).replace(
            "`../runs/inventory-deleaked-blind/*`",
            "`evidence/runs/inventory-deleaked-blind/*`",
        )
    return text.encode("utf-8")


def _audit_forbidden_executable_caches(
    base_dir: Path,
    errors: list[str],
) -> None:
    if not base_dir.exists():
        return
    for path in sorted(base_dir.rglob("*")):
        relative = path.relative_to(base_dir)
        if path.is_symlink():
            errors.append(f"unsafe package symlink path: {relative.as_posix()!r}")
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            errors.append(
                f"forbidden executable cache in package: {relative.as_posix()}"
            )


def _audit_executed_source_closure(
    base_dir: Path,
    errors: list[str],
) -> None:
    auditor_source_root = Path(__file__).resolve().parent
    for relative in EXECUTED_SOURCE_CLOSURE:
        try:
            packaged = _contained_package_path(base_dir, relative)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not packaged.is_file():
            errors.append(f"executed source closure missing: {relative}")
            continue
        auditor_source = auditor_source_root / relative
        if not auditor_source.is_file():
            errors.append(f"auditor source closure missing: {relative}")
            continue
        if packaged.read_bytes() != auditor_source.read_bytes():
            errors.append(f"executed source differs from auditor source: {relative}")


def _audit_run_result_census(
    base_dir: Path,
    run_results: list[dict[str, Any]],
    errors: list[str],
) -> None:
    runs_dir = base_dir / "runs"
    discovered: dict[str, Any] = {}
    if runs_dir.exists():
        if runs_dir.is_symlink():
            errors.append("unsafe package symlink path: 'runs'")
            return
        for path in sorted(runs_dir.rglob("run-result.json")):
            relative = path.relative_to(base_dir).as_posix()
            match = re.fullmatch(
                r"runs/([A-Za-z0-9][A-Za-z0-9._-]*)/run-result\.json",
                relative,
            )
            if match is None:
                errors.append(f"unexpected retained run result path: {relative}")
                continue
            if path.is_symlink():
                errors.append(f"unsafe package symlink path: {relative!r}")
                continue
            try:
                retained = _json_load(path)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if not isinstance(retained, dict):
                errors.append(f"retained run result must be an object: {relative}")
                continue
            if retained.get("run_id") != match.group(1):
                errors.append(
                    "retained run id/path mismatch: "
                    f"{relative} has {retained.get('run_id')!r}"
                )
            discovered[relative] = retained

    expected_paths: set[str] = set()
    for run in run_results:
        if not isinstance(run, dict):
            continue
        run_id = run.get("run_id")
        if (
            isinstance(run_id, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id)
        ):
            expected_paths.add(f"runs/{run_id}/run-result.json")
    for relative in sorted(set(discovered) - expected_paths):
        errors.append(f"retained run result omitted from supplied census: {relative}")
    for relative in sorted(expected_paths - set(discovered)):
        errors.append(f"supplied run result missing from retained census: {relative}")


def _audit_prompt_leaks(base_dir: Path, errors: list[str]) -> None:
    prompt_path = base_dir / "prompts" / "assess.alias_safety.fully_blind.md"
    if prompt_path.exists():
        text = prompt_path.read_text(encoding="utf-8").lower()
        for forbidden in FULLY_BLIND_PROMPT_FORBIDDEN_HINTS:
            if forbidden in text:
                errors.append(f"fully blind prompt leak: {prompt_path.relative_to(base_dir)} contains {forbidden!r}")

    candidates_path = base_dir / "prompts" / "assess.alias_safety.candidates.public.json"
    if candidates_path.exists():
        _audit_fully_blind_candidates(base_dir, candidates_path, errors)

    told_path = base_dir / "prompts" / "assess.alias_safety.told.md"
    if told_path.exists():
        text = told_path.read_text(encoding="utf-8").lower()
        if "told/control" not in text and "control variant" not in text:
            errors.append(f"told prompt unlabeled: {told_path.relative_to(base_dir)}")


def _audit_fully_blind_candidates(
    base_dir: Path,
    candidates_path: Path,
    errors: list[str],
) -> None:
    display = candidates_path.relative_to(base_dir).as_posix()
    try:
        payload = _json_load(candidates_path)
    except ValueError as exc:
        errors.append(str(exc))
        return
    if not isinstance(payload, dict):
        errors.append(f"fully blind candidate schema: {display} root must be an object")
        return
    root_keys = set(payload)
    if root_keys != {"candidates"}:
        errors.append(
            "fully blind candidate leak: "
            f"{display} root keys must be exactly ['candidates']; got {sorted(root_keys)}"
        )
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        errors.append(
            f"fully blind candidate schema: {display} candidates must be a non-empty array"
        )
        return
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(
                f"fully blind candidate schema: {display} candidate {index} must be an object"
            )
            continue
        keys = set(candidate)
        if keys != {"path"}:
            errors.append(
                "fully blind candidate leak: "
                f"{display} candidate {index} keys must be exactly ['path']; got {sorted(keys)}"
            )
            continue
        path = candidate["path"]
        if not isinstance(path, str):
            errors.append(
                f"fully blind candidate schema: {display} candidate {index} path must be a string"
            )
            continue
        if not _canonical_public_candidate_path(path):
            errors.append(
                f"fully blind candidate schema: {display} candidate {index} path is not canonical: {path!r}"
            )
        if path in seen:
            errors.append(
                f"fully blind candidate schema: {display} duplicate path: {path!r}"
            )
        seen.add(path)


def _canonical_public_candidate_path(path: str) -> bool:
    if not path.startswith("/") or path == "/" or path.endswith("/"):
        return False
    if "\\" in path or "?" in path or "#" in path or "//" in path:
        return False
    parts = path[1:].split("/")
    return bool(parts) and all(part not in {"", ".", ".."} for part in parts)


def _audit_public_claims(
    base_dir: Path,
    repository_root: Path,
    errors: list[str],
) -> None:
    """Apply bounded lexical tripwires; this is not semantic completeness."""
    for path, display in _circulated_markdown_surfaces(base_dir, repository_root):
        text = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_PUBLIC_CLAIMS:
            for match in re.finditer(re.escape(phrase), text):
                if not _claim_is_negated(text, match.start()):
                    errors.append(
                        f"deprecated public claim: {display} contains affirmative {phrase!r}"
                    )
        for pattern in BROAD_PUBLIC_CLAIM_PATTERNS:
            for match in pattern.finditer(text):
                if not _claim_is_negated(text, match.start()):
                    errors.append(
                        "broad public claim: "
                        f"{display} contains affirmative {match.group(0)!r}"
                    )


def _circulated_markdown_surfaces(
    base_dir: Path,
    repository_root: Path,
) -> list[tuple[Path, str]]:
    candidates: list[Path] = [
        base_dir / "README.md",
        base_dir / "PUBLISHING.md",
        base_dir / "experiments" / "alias-safety-SYNTHESIS.md",
        *sorted((base_dir / "public").glob("*.md")),
        *(repository_root / relative for relative in CIRCULATED_REPOSITORY_MARKDOWN),
    ]
    surfaces: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for path in candidates:
        if not path.exists():
            continue
        if path.is_symlink():
            # The package and clean-checkout audits reject the symlink too, but
            # keep this semantic gate independently fail closed.
            continue
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        try:
            display = resolved.relative_to(repository_root.resolve()).as_posix()
        except ValueError:
            try:
                display = resolved.relative_to(base_dir.resolve()).as_posix()
            except ValueError:
                display = resolved.as_posix()
        surfaces.append((resolved, display))
    return sorted(surfaces, key=lambda item: item[1])


def _claim_is_negated(text: str, start: int) -> bool:
    """Recognize direct caveats without exempting an affirmative claim nearby."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end < 0:
        line_end = len(text)
    prefix = text[line_start:start]
    # Direct sentence/table-cell negation.
    if re.search(
        r"(?:\bnot\b|\bnever\b|\bno\b|\bwithout\b|\bcannot\b|"
        r"\bcan't\b|\bdoes\s+not\b|\bdo\s+not\b|\bisn't\b|\baren't\b)"
        r"[^.!?;|]{0,120}$",
        prefix,
    ):
        return True
    if re.search(
        r"\bno\b[^.!?;|]{0,220}\bclaims?\s+such\s+as\s+[\"'`]?$",
        prefix,
    ):
        return True
    if re.search(
        r"\b(?:avoid|reject)\s+(?:claims?\s+(?:such\s+as|that)|"
        r"claiming|saying|asserting)\b[^.!?;|]{0,160}$",
        prefix,
    ):
        return True

    # A negative section heading governs its bullets until the next heading.
    heading_matches = list(re.finditer(r"(?m)^#{1,6}\s+(.+)$", text[:start]))
    if heading_matches:
        heading = heading_matches[-1].group(1)
        if re.search(
            r"\b(?:not\s+claiming|not\s+establish|limitations?|caveats?|"
            r"claim\s+boundar|claims?\s+to\s+avoid|unsupported\s+claims?|"
            r"forbidden\s+claims?|what\s+we\s+are\s+not)\b",
            heading,
        ):
            return True

    # Markdown comparison tables commonly put the negative operator in the
    # column header rather than repeating it in every row.
    previous_lines = text[max(0, line_start - 500):line_start]
    previous_lines = "\n".join(previous_lines.splitlines()[-3:])
    current_line = text[line_start:line_end]
    prior_claim_caveat = re.search(
        r"\b(?:no\s+deprecated\s+claims|forbidden\s+(?:public\s+)?claims|"
        r"claims?\s+to\s+avoid|and\s+no)\b",
        previous_lines,
    )
    continued_claim_examples = re.match(
        r"\s*claims?\s+such\s+as\s+[\"'`]",
        current_line,
    )
    if prior_claim_caveat and (
        current_line.lstrip().startswith(('"', "'", "`"))
        or continued_claim_examples
    ):
        return True
    if "|" in current_line and re.search(
        r"\b(?:does\s+not\s+establish|not\s+a\s+claim|not\s+evidence)\b",
        previous_lines,
    ):
        return True
    return False


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
        "| Run | Class | Task | Model | Substrate | Prompt | Success | Human rescues | Elapsed seconds | Tool calls | Metric source | Verification | Blast radius |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['run_id']} | {row['run_class']} | {row['task_id']} | {row['model']} | {row['substrate_id']} | {row['prompt_version']} | {row['task_success']} | {row['human_rescues']} | {row['elapsed_seconds']} | {row['tool_calls']} | {row['metrics_provenance']} | {row['verification_quality']} | {row['blast_radius']} |"
        )
    return lines


def _run_class(run: dict[str, Any]) -> str:
    """Classify what a row can safely be used for without trusting its name.

    Legacy run packets do not carry the full v1 measurement pins. They can be
    useful evidence, but must not silently enter a fixed-agent trend.
    """
    if _is_smoke_run(run):
        return "tooling_smoke"
    if run.get("schema_version") == "drupal_agent_readiness.run.v1":
        return str(run.get("lane", "measurement_v1"))
    return "legacy_unpinned"


def _is_smoke_run(run: dict[str, Any]) -> bool:
    agent = run.get("agent", {})
    return (
        "tooling-smoke" in run.get("run_id", "")
        or agent.get("name") == "Tooling smoke"
        or agent.get("model") == "none"
    )


def _contained_package_path(base_dir: Path, relative_value: Any) -> Path:
    base_dir = base_dir.resolve()
    if not isinstance(relative_value, (str, Path)):
        raise ValueError(f"unsafe package path: {relative_value!r}")
    raw = str(relative_value)
    relative = Path(raw)
    if (
        not raw
        or "\\" in raw
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ValueError(f"unsafe package path: {raw!r}")
    candidate = base_dir
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"unsafe package symlink path: {raw!r}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(f"unsafe package path: {raw!r}") from exc
    return resolved


def _package_repository_root(
    base_dir: Path,
    repository_root: Path | None,
) -> Path:
    """Locate repository-owned method inputs outside the public package.

    The checked package is always named ``agent_readiness`` and therefore uses
    its parent as the repository root. A non-canonical base path is supported
    only for self-contained test fixtures. Callers can override that fixture
    location explicitly without changing production autodetection.
    """
    base_dir = Path(base_dir)
    if repository_root is not None:
        return Path(repository_root).resolve()
    if base_dir.name == "agent_readiness":
        return base_dir.parent.resolve()
    resolved_base = base_dir.resolve()
    if resolved_base.name == "agent_readiness":
        return resolved_base.parent
    return resolved_base


def _contained_repository_dependency(
    repository_root: Path,
    relative_value: Any,
) -> Path:
    repository_root = repository_root.resolve()
    if not isinstance(relative_value, (str, Path)):
        raise ValueError(f"unsafe repository dependency path: {relative_value!r}")
    raw = str(relative_value)
    relative = Path(raw)
    if (
        not raw
        or "\\" in raw
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ValueError(f"unsafe repository dependency path: {raw!r}")
    candidate = repository_root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"unsafe repository dependency symlink path: {raw!r}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError(f"unsafe repository dependency path: {raw!r}") from exc
    return resolved


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
    if not isinstance(data, dict):
        errors.append("invalid manifest shape: root must be an object")
        return {}
    files = data.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        errors.append("invalid manifest shape: files must be an array of objects")
        return {}
    repository_dependencies = data.get("repository_dependencies")
    if not isinstance(repository_dependencies, list) or not all(
        isinstance(item, dict) for item in repository_dependencies
    ):
        errors.append(
            "invalid manifest shape: repository_dependencies must be an array of objects"
        )
        return {}
    return data


def _json_load(path: Path) -> Any:
    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path}: duplicate JSON object key {key!r}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> Any:
        raise ValueError(f"{path}: non-finite JSON number {value!r}")

    try:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_nonfinite,
        )
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    return data
