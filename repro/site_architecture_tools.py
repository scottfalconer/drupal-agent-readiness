import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_MODULE_SOURCE = Path(__file__).resolve().parents[1] / "agent_readiness" / "fixtures" / "site_architecture_module"


def build_install_plan(
    *,
    site_root: Path,
    module_source: Path = DEFAULT_MODULE_SOURCE,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    site_root = site_root.resolve()
    module_source = module_source.resolve()
    output_dir = output_dir.resolve() if output_dir else None
    artifact_dir = output_dir or site_root.parent
    drush = site_root / "vendor" / "drush" / "drush" / "drush.php"
    return {
        "site_root": site_root,
        "drush": drush,
        "drupal_root": site_root / "web",
        "module_source": module_source,
        "module_target": site_root / "web" / "modules" / "custom" / "site_architecture",
        "surfaces_json": artifact_dir / "site-architecture-surfaces.json",
        "brief_md": artifact_dir / "site-architecture-brief.md",
    }


def install_site_architecture(
    *,
    site_root: Path,
    module_source: Path = DEFAULT_MODULE_SOURCE,
    output_dir: Path | None = None,
) -> dict[str, str]:
    plan = build_install_plan(site_root=site_root, module_source=module_source, output_dir=output_dir)
    _validate_plan(plan)
    plan["module_target"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(plan["module_source"], plan["module_target"])

    _run_drush(plan, ["pm:install", "site_architecture", "--yes"])
    surfaces = _run_drush(plan, ["site-architecture:surfaces", "--format=json"])
    brief = _run_drush(plan, ["site-architecture:brief"])
    plan["surfaces_json"].write_text(surfaces, encoding="utf-8")
    plan["brief_md"].write_text(brief, encoding="utf-8")

    return {
        "module_target": str(plan["module_target"]),
        "surfaces_json": str(plan["surfaces_json"]),
        "brief_md": str(plan["brief_md"]),
    }


def plan_to_jsonable(plan: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in plan.items()}


def _validate_plan(plan: dict[str, Any]) -> None:
    if not plan["site_root"].exists():
        raise FileNotFoundError(f"Site root does not exist: {plan['site_root']}")
    if not plan["drush"].exists():
        raise FileNotFoundError(f"Drush does not exist: {plan['drush']}")
    if not plan["module_source"].exists():
        raise FileNotFoundError(f"Module source does not exist: {plan['module_source']}")
    if plan["module_target"].exists():
        raise FileExistsError(f"Module target already exists: {plan['module_target']}")


def _run_drush(plan: dict[str, Any], args: list[str]) -> str:
    command = [
        "php",
        "-d",
        "memory_limit=1024M",
        str(plan["drush"]),
        "--root=" + str(plan["drupal_root"]),
        *args,
    ]
    completed = subprocess.run(
        command,
        cwd=plan["site_root"],
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout
