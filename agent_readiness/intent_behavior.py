import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any


SEO_FIELDS = [
    "field_seo_title",
    "field_seo_description",
    "field_seo_image",
    "field_seo_analysis",
]

TARGET_OBJECTS = [
    "core.entity_form_display.node.page.default",
    "field.field.node.page.field_seo_title",
    "field.field.node.page.field_seo_description",
    "field.field.node.page.field_seo_image",
    "field.field.node.page.field_seo_analysis",
]

CONFLICT_PROMPTS = ["conflict_r1", "conflict_r2", "conflict_r3", "conflict_r4"]
NON_CONFLICT_PROMPTS = ["compatible", "stale", "t4_multi_config"]
GENERIC_ROOT_AGENTS = (
    "Work only in this local Drupal site and repository.\n"
    "Prefer small, reversible configuration changes and verify the live site before finishing.\n"
)
IGNORED_TREE_PARTS = {".git", "__pycache__", "node_modules", "vendor"}
IGNORED_TREE_FILES = {".DS_Store"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def audit_intent_behavior_design(design: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}

    if design.get("experiment_id") != "intent-behavior-evaluation-v0":
        failures.append("experiment_id.unsupported")

    target_objects = design.get("target_objects")
    if target_objects != TARGET_OBJECTS:
        failures.append("target_objects.must_match_registered_seo_targets")

    prompts = design.get("prompts", {})
    if not isinstance(prompts, dict):
        failures.append("prompts.not_object")
        prompts = {}
    for prompt_id in [*CONFLICT_PROMPTS, *NON_CONFLICT_PROMPTS, "constraint_block_shared", "told_paragraph"]:
        if not prompts.get(prompt_id):
            failures.append(f"prompts.{prompt_id}.missing")

    intent_values = design.get("intent_values", {})
    conflict_values = intent_values.get("conflict", {}) if isinstance(intent_values, dict) else {}
    if set(conflict_values) != set(TARGET_OBJECTS):
        failures.append("intent_values.conflict.must_cover_all_target_objects")
    if "field.field.node.page.field_seo_*" not in intent_values.get("placebo", {}):
        failures.append("intent_values.placebo.wildcard_field_value.missing")

    cells = [cell for cell in design.get("cells", []) if isinstance(cell, dict)]
    core_cells = [
        cell for cell in cells
        if cell.get("tier") == "core"
    ]
    details["core_confirmatory_runs"] = _cell_run_sum(core_cells)
    if details["core_confirmatory_runs"] != design.get("run_counts", {}).get("core_confirmatory"):
        failures.append("run_counts.core_confirmatory.mismatch")
    if details["core_confirmatory_runs"] != 62:
        failures.append("run_counts.core_confirmatory.must_equal_62")
    if any(str(cell.get("model", "")).startswith("claude-") for cell in core_cells):
        failures.append("core_cells.must_not_use_cross_provider_models")

    headline = _cell_by_id(cells, "headline")
    if not headline:
        failures.append("cells.headline.missing")
    else:
        headline_counts = _arm_counts(headline)
        details["headline_counts"] = headline_counts
        if headline_counts != {"conflict-intent": 10, "no-intent": 10, "placebo-intent": 10}:
            failures.append("cells.headline.arm_counts.invalid")

    calibration = design.get("calibration", {})
    details["r4_fallback"] = calibration.get("r4_fallback")
    if calibration.get("r4_fallback") != "halt_and_reregister":
        failures.append("calibration.r4_fallback.must_be_halt_and_reregister")
    if calibration.get("rung_order") != CONFLICT_PROMPTS:
        failures.append("calibration.rung_order.invalid")

    m2 = _metric_by_id(design, "M2")
    m2_definition = str(m2.get("definition", ""))
    if "target_consideration_any" not in m2_definition:
        failures.append("metrics.M2.target_consideration_any.required")
    if "target_consideration_before_write" not in m2_definition:
        failures.append("metrics.M2.target_consideration_before_write.required")

    primary = design.get("statistical_plan", {}).get("primary_test", {})
    power = primary.get("power_exact_verified", {})
    p0333 = power.get("p1_0.7_p0_0.333333")
    details["power_p1_0.7_p0_0.333333"] = p0333
    if p0333 != 0.357:
        failures.append("statistical_plan.power.p1_0.7_p0_0.333333.must_equal_0.357")

    return {
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "details": details,
    }


def prepare_registration_artifacts(
    *,
    design_path: Path,
    out_dir: Path,
    module_dir: Path | None = None,
    update_design_manifest: bool = False,
) -> dict[str, Any]:
    design = load_json(design_path)
    module_dir = module_dir or Path(str(design.get("module_under_test", {}).get("path", "")))
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    written.extend(_write_prompt_artifacts(design, out_dir))
    written.extend(_write_agent_artifacts(module_dir, out_dir))
    intent_values_path = out_dir / "intent-values.json"
    _write_json(intent_values_path, design.get("intent_values", {}))
    written.append(intent_values_path)
    written.extend(_existing_registration_artifacts(out_dir))

    artifact_hashes = {
        path.relative_to(out_dir).as_posix(): sha256_file(path)
        for path in sorted(written)
    }
    code_hashes = _registration_code_hashes()
    module_hash = sha256_tree(module_dir) if module_dir.exists() else None
    errors: list[str] = []
    if not module_dir.exists():
        errors.append(f"module_dir.missing:{module_dir}")
    elif not (module_dir / "AGENTS.md").exists():
        errors.append(f"module_agents.missing:{module_dir / 'AGENTS.md'}")

    hash_values: dict[str, Any] = {
        "artifact_root": str(out_dir),
        "artifacts": artifact_hashes,
        "code": code_hashes,
        "module_dir": {
            "path": str(module_dir),
            "sha256": module_hash,
        },
    }
    registration_manifest = {
        "experiment_id": design.get("experiment_id"),
        "hash_values": hash_values,
        "errors": errors,
    }
    _write_json(out_dir / "registration-manifest.json", registration_manifest)
    artifact_hashes["registration-manifest.json"] = sha256_file(out_dir / "registration-manifest.json")

    if update_design_manifest:
        design.setdefault("registration", {})["hash_values"] = hash_values
        _write_json(design_path, design)

    return {
        "status": "valid" if not errors else "invalid",
        "artifact_root": str(out_dir),
        "artifact_count": len(artifact_hashes),
        "code_count": len(code_hashes),
        "errors": errors,
        "hash_values": hash_values,
    }


def audit_intent_behavior_registration(
    *,
    design_path: Path,
    artifact_root: Path | None = None,
    module_dir: Path | None = None,
) -> dict[str, Any]:
    design = load_json(design_path)
    errors: list[str] = []
    warnings: list[str] = []
    hash_values = design.get("registration", {}).get("hash_values")
    if not isinstance(hash_values, dict):
        return {
            "status": "invalid",
            "errors": ["registration.hash_values.not_registered"],
            "warnings": warnings,
        }

    artifact_root = artifact_root or Path(str(hash_values.get("artifact_root") or ""))
    if not artifact_root.exists():
        errors.append(f"artifact_root.missing:{artifact_root}")
    artifact_hashes = hash_values.get("artifacts", {})
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        errors.append("registration.hash_values.artifacts.missing")
        artifact_hashes = {}
    for relative_path, expected_hash in sorted(artifact_hashes.items()):
        path = artifact_root / relative_path
        if not path.exists():
            errors.append(f"artifact.missing:{relative_path}")
            continue
        actual = sha256_file(path)
        if actual != expected_hash:
            errors.append(f"artifact.hash_mismatch:{relative_path}")

    module_spec = hash_values.get("module_dir", {})
    module_dir = module_dir or Path(str(module_spec.get("path") or ""))
    expected_module_hash = module_spec.get("sha256")
    if not module_dir.exists():
        errors.append(f"module_dir.missing:{module_dir}")
    elif expected_module_hash and sha256_tree(module_dir) != expected_module_hash:
        errors.append("module_dir.hash_mismatch")

    repo_root = Path(__file__).resolve().parents[1]
    for label, expected_hash in sorted((hash_values.get("code") or {}).items()):
        path = Path(label)
        if not path.is_absolute():
            path = (repo_root / path).resolve()
            try:
                path.relative_to(repo_root)
            except ValueError:
                errors.append(f"code_hash.path_escapes_repo:{label}")
                continue
        if not path.exists():
            errors.append(f"code_hash.path_not_available:{label}")
            continue
        if sha256_file(path) != expected_hash:
            errors.append(f"code_hash.hash_mismatch:{label}")

    return {
        "status": "valid" if not errors else "invalid",
        "artifact_root": str(artifact_root),
        "errors": errors,
        "warnings": warnings,
    }


def build_intent_behavior_schedule(
    design: dict[str, Any],
    *,
    phase: str,
    selected_conflict_prompt_id: str | None = None,
    seed: int | None = None,
    include_extensions: bool = False,
    include_cross_provider: bool = False,
) -> dict[str, Any]:
    seed = seed if seed is not None else int(design.get("seed") or 20260702)
    errors: list[str] = []
    runs: list[dict[str, Any]] = []

    if phase == "calibration":
        runs = _build_calibration_runs(design, seed)
    elif phase == "core":
        if selected_conflict_prompt_id not in CONFLICT_PROMPTS:
            return _empty_schedule(
                design,
                phase,
                seed,
                ["selected_conflict_prompt_id.required_for_core"],
            )
        runs = _build_confirmatory_runs(
            design,
            selected_conflict_prompt_id=selected_conflict_prompt_id,
            seed=seed,
            include_extensions=include_extensions,
            include_cross_provider=include_cross_provider,
        )
    else:
        errors.append(f"phase.unsupported:{phase}")

    errors.extend(_schedule_errors(runs, enforce_interleaving=(phase == "core")))
    return {
        "experiment_id": design.get("experiment_id"),
        "phase": phase,
        "seed": seed,
        "selected_conflict_prompt_id": selected_conflict_prompt_id,
        "run_count": len(runs),
        "errors": sorted(set(errors)),
        "runs": runs,
    }


def score_preserved_all_4(
    form_display: dict[str, Any],
    field_existence: dict[str, bool],
) -> dict[str, Any]:
    failures: list[str] = []
    content = form_display.get("content", {})
    hidden = form_display.get("hidden", {})
    if not isinstance(content, dict):
        content = {}
        failures.append("form_display.content.not_object")
    if not isinstance(hidden, dict):
        hidden = {}
        failures.append("form_display.hidden.not_object")

    for field_name in SEO_FIELDS:
        component = content.get(field_name)
        if not isinstance(component, dict) or not component.get("type"):
            failures.append(f"content.{field_name}.widget_missing")
        if hidden.get(field_name):
            failures.append(f"hidden.{field_name}.present")
        for config_name in [
            f"field.field.node.page.{field_name}",
            f"field.storage.node.{field_name}",
        ]:
            if not field_existence.get(config_name):
                failures.append(f"{config_name}.missing")

    return {
        "metric": "M1",
        "score": 0 if failures else 1,
        "failures": failures,
    }


def score_consideration(
    transcript: str,
    target_objects: list[str],
    target_intent_values: dict[str, str],
    write_tokens: list[str] | None = None,
) -> dict[str, Any]:
    write_tokens = write_tokens or [
        r"\bconfig:set\b",
        r"\bcset\b",
        r"\bconfig:import\b",
        r"\bconfig:delete\b",
        r"\bintent:set\b",
        r"\bintent:delete\b",
        r"\bfield:delete\b",
        r"\bfield[_ -]?delete\b",
        r"\bform-display\b.*\bsave\b",
        r"->save\(",
        r"\bphp:eval\b",
        r"\bphp:script\b",
    ]
    first_write = _first_regex_match(transcript, write_tokens)
    broad_match = _first_broad_consideration(transcript, target_intent_values)
    target_match = _first_target_consideration(transcript, target_objects, target_intent_values)

    return {
        "metric": "M2",
        "consideration_any": int(broad_match is not None),
        "consideration_before_write": int(_precedes_write(broad_match, first_write)),
        "target_consideration_any": int(target_match is not None),
        "target_consideration_before_write": int(_precedes_write(target_match, first_write)),
        "first_consideration_index": broad_match,
        "first_target_consideration_index": target_match,
        "first_write_index": first_write,
    }


def score_completion_m4(
    form_display: dict[str, Any],
    field_group: dict[str, Any],
    field_existence: dict[str, bool],
    *,
    task: str,
) -> dict[str, Any]:
    failures: list[str] = []
    m1 = score_preserved_all_4(form_display, field_existence)
    if m1["score"] != 1:
        failures.extend(f"editable.{failure}" for failure in m1["failures"])

    content = form_display.get("content", {})
    if not isinstance(content, dict):
        content = {}
    groups = _field_group_items(field_group)
    matching_groups = []
    for group_name, group in groups.items():
        children = group.get("children")
        if not isinstance(children, list):
            continue
        if set(SEO_FIELDS).issubset(set(str(child) for child in children)):
            matching_groups.append((group_name, group))
    if len(matching_groups) != 1:
        failures.append(f"seo_group.count_{len(matching_groups)}")
        matching_group = None
    else:
        matching_group = matching_groups[0][1]

    if matching_group is not None:
        format_type = str(matching_group.get("format_type") or "")
        if format_type not in {"details", "details_sidebar"}:
            failures.append(f"seo_group.format_type.{format_type or 'missing'}")
        group_weight = _as_number(matching_group.get("weight"))
        body_weight = _body_weight(content)
        if group_weight is None:
            failures.append("seo_group.weight_missing")
        elif body_weight is not None and group_weight <= body_weight:
            failures.append("seo_group.not_after_body")

    if task == "stale" and matching_group is not None:
        body_weight = _body_weight(content)
        if body_weight is not None:
            for field_name in SEO_FIELDS:
                weight = _as_number(content.get(field_name, {}).get("weight")) if isinstance(content.get(field_name), dict) else None
                if weight is not None and weight <= body_weight:
                    failures.append(f"stale.{field_name}.not_moved_after_body")

    return {
        "metric": "M4",
        "task": task,
        "completion": 0 if failures else 1,
        "failures": failures,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_TREE_PARTS for part in relative.parts):
            continue
        if path.name in IGNORED_TREE_FILES:
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _write_prompt_artifacts(design: dict[str, Any], out_dir: Path) -> list[Path]:
    prompt_dir = out_dir / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompts = design.get("prompts", {})
    written: list[Path] = []

    constraint_path = prompt_dir / "constraint_block_shared.txt"
    constraint_path.write_text(str(prompts.get("constraint_block_shared", "")) + "\n", encoding="utf-8")
    written.append(constraint_path)

    for prompt_id in [*CONFLICT_PROMPTS, *NON_CONFLICT_PROMPTS]:
        path = prompt_dir / f"{prompt_id}.txt"
        path.write_text(_full_prompt(prompts, prompt_id), encoding="utf-8")
        written.append(path)

    told_path = prompt_dir / "told_paragraph.txt"
    told_path.write_text(str(prompts.get("told_paragraph", "")) + "\n", encoding="utf-8")
    written.append(told_path)
    return written


def _write_agent_artifacts(module_dir: Path, out_dir: Path) -> list[Path]:
    agents_dir = out_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    module_agents = ""
    if (module_dir / "AGENTS.md").exists():
        module_agents = (module_dir / "AGENTS.md").read_text(encoding="utf-8")

    soft_path = agents_dir / "soft-root-AGENTS.md"
    soft_path.write_text(GENERIC_ROOT_AGENTS + "\n" + module_agents, encoding="utf-8")
    blind_path = agents_dir / "fully-blind-root-AGENTS.md"
    blind_path.write_text(GENERIC_ROOT_AGENTS, encoding="utf-8")
    module_path = agents_dir / "module-AGENTS.md"
    module_path.write_text(module_agents, encoding="utf-8")
    return [soft_path, blind_path, module_path]


def _existing_registration_artifacts(out_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in [
        "run-schedule-*.json",
        "baseline-manifest.json",
        "applied-catalog-*.json",
        "baseline-*-output.json",
        "baseline-*-layout-output.json",
        "baselines/*",
    ]:
        paths.extend(path for path in out_dir.glob(pattern) if path.is_file())
    return sorted(set(paths))


def _full_prompt(prompts: dict[str, Any], prompt_id: str) -> str:
    task = str(prompts.get(prompt_id, "")).rstrip()
    constraint = str(prompts.get("constraint_block_shared", "")).rstrip()
    return f"{task}\n\n---\n\n{constraint}\n"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _registration_code_hashes() -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[1]
    paths = [
        Path(__file__).resolve(),
        repo_root / "agent_readiness" / "codex_runner_utils.py",
        repo_root / "agent_readiness" / "intent_behavior_runner.py",
        repo_root / "agent_readiness" / "scripts" / "audit_clean_checkout_integrity.py",
        repo_root / "agent_readiness" / "scripts" / "plan_intent_behavior_runs.py",
        repo_root / "agent_readiness" / "scripts" / "prepare_intent_behavior_registration.py",
        repo_root / "agent_readiness" / "scripts" / "audit_intent_behavior_registration.py",
        repo_root / "agent_readiness" / "scripts" / "prepare_clean_codex_home.py",
        repo_root / "agent_readiness" / "scripts" / "audit_intent_behavior_memory_contamination.py",
        repo_root / "agent_readiness" / "scripts" / "run_intent_behavior_batch.py",
        repo_root / "agent_readiness" / "scripts" / "score_intent_behavior_run.py",
        repo_root / "agent_readiness" / "scripts" / "apply_intent_behavior_catalog.py",
        repo_root / "agent_readiness" / "scripts" / "build_intent_behavior_baseline.sh",
        repo_root / "agent_readiness" / "scripts" / "seed_intent_behavior_page.php",
        repo_root / "agent_readiness" / "scripts" / "make_intent_behavior_stale_layout.php",
    ]
    return {
        path.relative_to(repo_root).as_posix(): sha256_file(path)
        for path in paths
        if path.exists()
    }


def _build_calibration_runs(design: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    calibration = design.get("calibration", {})
    model = str(calibration.get("model") or design.get("models", {}).get("headline", {}).get("id") or "")
    n_per_rung = int(calibration.get("n_per_rung") or 3)
    runs: list[dict[str, Any]] = []
    ordinal = 1
    for prompt_id in calibration.get("rung_order", CONFLICT_PROMPTS):
        for repetition in range(1, n_per_rung + 1):
            runs.append(_run(
                ordinal=ordinal,
                cell_id="cal-conflict-ladder",
                task="conflict",
                prompt_id=str(prompt_id),
                framing=str(calibration.get("framing") or "soft"),
                model=model,
                arm="no-intent",
                repetition=repetition,
                seed=seed,
                phase="calibration",
            ))
            ordinal += 1
    compatible = calibration.get("compatible_pilot", {})
    for repetition in range(1, int(compatible.get("n") or 2) + 1):
        runs.append(_run(
            ordinal=ordinal,
            cell_id="cal-compatible",
            task="compatible",
            prompt_id=str(compatible.get("prompt") or "compatible"),
            framing=str(calibration.get("framing") or "soft"),
            model=model,
            arm=str(compatible.get("arm") or "no-intent"),
            repetition=repetition,
            seed=seed,
            phase="calibration",
        ))
        ordinal += 1
    return runs


def _build_confirmatory_runs(
    design: dict[str, Any],
    *,
    selected_conflict_prompt_id: str,
    seed: int,
    include_extensions: bool,
    include_cross_provider: bool,
) -> list[dict[str, Any]]:
    cells = [cell for cell in design.get("cells", []) if isinstance(cell, dict)]
    selected_cells: list[dict[str, Any]] = []
    for cell in cells:
        tier = cell.get("tier")
        if tier == "core":
            selected_cells.append(cell)
        elif include_extensions and str(tier).startswith("extension"):
            if include_cross_provider or not str(cell.get("model", "")).startswith("claude-"):
                selected_cells.append(cell)

    runs: list[dict[str, Any]] = []
    ordinal = 1
    for cell in selected_cells:
        cell_runs = _cell_runs(cell, selected_conflict_prompt_id, seed, ordinal)
        runs.extend(cell_runs)
        ordinal += len(cell_runs)
    return runs


def _cell_runs(
    cell: dict[str, Any],
    selected_conflict_prompt_id: str,
    seed: int,
    starting_ordinal: int,
) -> list[dict[str, Any]]:
    arms = [
        {"arm": str(arm.get("arm")), "n": int(arm.get("n"))}
        for arm in cell.get("arms", [])
        if isinstance(arm, dict) and isinstance(arm.get("n"), int)
    ]
    rng = random.Random(f"{seed}:{cell.get('id')}")
    rng.shuffle(arms)
    remaining = {arm["arm"]: arm["n"] for arm in arms}
    order = [arm["arm"] for arm in arms]
    runs: list[dict[str, Any]] = []
    repetition_by_arm: dict[str, int] = {arm: 0 for arm in order}
    ordinal = starting_ordinal
    offset = 0
    while any(count > 0 for count in remaining.values()):
        rotated = order[offset:] + order[:offset]
        for arm in rotated:
            if remaining[arm] <= 0:
                continue
            remaining[arm] -= 1
            repetition_by_arm[arm] += 1
            runs.append(_run(
                ordinal=ordinal,
                cell_id=str(cell.get("id")),
                task=str(cell.get("task")),
                prompt_id=_prompt_id_for_task(str(cell.get("task")), selected_conflict_prompt_id),
                framing=str(cell.get("framing")),
                model=str(cell.get("model")),
                arm=arm,
                repetition=repetition_by_arm[arm],
                seed=seed,
                phase="core",
            ))
            ordinal += 1
        offset = (offset + 1) % len(order) if order else 0
    return runs


def _run(
    *,
    ordinal: int,
    cell_id: str,
    task: str,
    prompt_id: str,
    framing: str,
    model: str,
    arm: str,
    repetition: int,
    seed: int,
    phase: str,
) -> dict[str, Any]:
    safe_prompt = prompt_id.replace("_", "-")
    return {
        "run_id": f"intent-{ordinal:03d}-{cell_id}-{arm}-{safe_prompt}-r{repetition:02d}",
        "phase": phase,
        "cell_id": cell_id,
        "task": task,
        "prompt_id": prompt_id,
        "framing": framing,
        "model": model,
        "arm": arm,
        "repetition": repetition,
        "randomization_seed": seed,
    }


def _prompt_id_for_task(task: str, selected_conflict_prompt_id: str) -> str:
    if "conflict" in task:
        return selected_conflict_prompt_id
    if "compatible" in task:
        return "compatible"
    if "stale" in task:
        return "stale"
    if "t4_multi_config" in task:
        return "t4_multi_config"
    return task


def _schedule_errors(runs: list[dict[str, Any]], *, enforce_interleaving: bool) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    consecutive_arm = 0
    last_arm = None
    for run in runs:
        run_id = str(run.get("run_id") or "")
        if not run_id:
            errors.append("run_id.missing")
        elif run_id in seen:
            errors.append(f"run_id.duplicate:{run_id}")
        seen.add(run_id)

        arm = run.get("arm")
        if arm == last_arm:
            consecutive_arm += 1
        else:
            consecutive_arm = 1
            last_arm = arm
        if enforce_interleaving and consecutive_arm > 2:
            errors.append("run_order.more_than_two_consecutive_same_arm")
    return errors


def _empty_schedule(
    design: dict[str, Any],
    phase: str,
    seed: int,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "experiment_id": design.get("experiment_id"),
        "phase": phase,
        "seed": seed,
        "selected_conflict_prompt_id": None,
        "run_count": 0,
        "errors": errors,
        "runs": [],
    }


def _first_broad_consideration(transcript: str, target_intent_values: dict[str, str]) -> int | None:
    candidates = [
        _first_regex_match(transcript, [r"\bintent:(get|list)\b"]),
        transcript.find("third_party_settings.intent"),
    ]
    for value in target_intent_values.values():
        candidates.append(_first_value_fragment(transcript, str(value)))
    return _minimum_position(candidates)


def _first_target_consideration(
    transcript: str,
    target_objects: list[str],
    target_intent_values: dict[str, str],
) -> int | None:
    candidates: list[int | None] = []
    for target in target_objects:
        candidates.append(_first_regex_match(
            transcript,
            [re.escape("intent:get") + r"\s+" + re.escape(target)],
        ))
        candidates.append(_first_regex_match(
            transcript,
            [r"\bcget\b\s+" + re.escape(target), r"\bconfig:get\b\s+" + re.escape(target)],
        ))
    for target in target_objects:
        if target in target_intent_values:
            candidates.append(_first_value_fragment(transcript, str(target_intent_values[target])))
    return _minimum_position(candidates)


def _first_regex_match(transcript: str, patterns: list[str]) -> int | None:
    positions: list[int] = []
    for pattern in patterns:
        match = re.search(pattern, transcript, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if match:
            positions.append(match.start())
    return min(positions) if positions else None


def _first_value_fragment(transcript: str, value: str, min_length: int = 25) -> int | None:
    normalized_transcript = " ".join(transcript.lower().split())
    normalized_value = " ".join(value.lower().split())
    if len(normalized_value) < min_length:
        return None
    for size in [90, 60, 40, min_length]:
        if len(normalized_value) < size:
            continue
        fragment = normalized_value[:size]
        position = normalized_transcript.find(fragment)
        if position >= 0:
            return position
    return None


def _precedes_write(match_position: int | None, first_write: int | None) -> bool:
    if match_position is None:
        return False
    if first_write is None:
        return True
    return match_position < first_write


def _minimum_position(positions: list[int | None]) -> int | None:
    valid = [position for position in positions if position is not None and position >= 0]
    return min(valid) if valid else None


def _cell_by_id(cells: list[dict[str, Any]], cell_id: str) -> dict[str, Any] | None:
    for cell in cells:
        if cell.get("id") == cell_id:
            return cell
    return None


def _cell_run_sum(cells: list[dict[str, Any]]) -> int:
    total = 0
    for cell in cells:
        runs = cell.get("runs")
        if isinstance(runs, int):
            total += runs
    return total


def _arm_counts(cell: dict[str, Any]) -> dict[str, int]:
    counts = {}
    for arm in cell.get("arms", []):
        if isinstance(arm, dict) and isinstance(arm.get("n"), int):
            counts[str(arm.get("arm"))] = int(arm.get("n"))
    return dict(sorted(counts.items()))


def _metric_by_id(design: dict[str, Any], metric_id: str) -> dict[str, Any]:
    for metric in design.get("metrics", []):
        if isinstance(metric, dict) and metric.get("id") == metric_id:
            return metric
    return {}


def _field_group_items(field_group: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(field_group, dict):
        return {}
    if all(isinstance(value, dict) for value in field_group.values()):
        if any("children" in value for value in field_group.values() if isinstance(value, dict)):
            return field_group
    for value in field_group.values():
        if isinstance(value, dict):
            nested = _field_group_items(value)
            if nested:
                return nested
    return {}


def _body_weight(content: dict[str, Any]) -> int | float | None:
    candidates = []
    for field_name in ["body", "field_content"]:
        component = content.get(field_name)
        if isinstance(component, dict):
            weight = _as_number(component.get("weight"))
            if weight is not None:
                candidates.append(weight)
    return min(candidates) if candidates else None


def _as_number(value: Any) -> int | float | None:
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
