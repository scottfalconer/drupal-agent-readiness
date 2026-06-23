import json
import shutil
from pathlib import Path
from typing import Any

from agent_readiness.site_architecture_tools import install_site_architecture


DEFAULT_SUBSTRATE = Path("<workspace>/haven-clean-install")
DEFAULT_COPY_ROOT = Path("<workspace>/tmp/agent-readiness")
PROMPT_PATH = Path("agent_readiness/prompts/inventory.read_only.md")


def build_inventory_packet(
    *,
    run_id: str,
    copy_root: Path = DEFAULT_COPY_ROOT,
    variant: str = "stock",
    substrate: Path = DEFAULT_SUBSTRATE,
) -> dict[str, Any]:
    if variant not in {"stock", "enhanced"}:
        raise ValueError(f"Unsupported inventory run variant: {variant}")
    run_dir = copy_root / run_id
    site_root = run_dir / "site"
    enhanced_artifacts = {}
    if variant == "enhanced":
        enhanced_artifacts = {
            "surfaces_json": run_dir / "site-architecture-surfaces.json",
            "brief_md": run_dir / "site-architecture-brief.md",
        }
    packet = {
        "run_id": run_id,
        "task_id": "inventory.read_only",
        "variant": variant,
        "prompt_version": "v0.1",
        "substrate": substrate,
        "run_dir": run_dir,
        "site_root": site_root,
        "answer_json": run_dir / "answer.json",
        "transcript": run_dir / "transcript.md",
        "prompt": run_dir / "agent-prompt.md",
        "enhanced_artifacts": enhanced_artifacts,
    }
    packet["prompt_text"] = render_inventory_prompt(packet)
    return packet


def prepare_inventory_packet(
    *,
    run_id: str,
    copy_root: Path = DEFAULT_COPY_ROOT,
    variant: str = "stock",
    substrate: Path = DEFAULT_SUBSTRATE,
) -> dict[str, Any]:
    packet = build_inventory_packet(
        run_id=run_id,
        copy_root=copy_root,
        variant=variant,
        substrate=substrate,
    )
    if packet["run_dir"].exists():
        raise FileExistsError(f"Run directory already exists: {packet['run_dir']}")
    packet["run_dir"].mkdir(parents=True)
    shutil.copytree(packet["substrate"], packet["site_root"], symlinks=True)
    if variant == "enhanced":
        install_site_architecture(site_root=packet["site_root"], output_dir=packet["run_dir"])
    packet["prompt"].write_text(packet["prompt_text"], encoding="utf-8")
    (packet["run_dir"] / "run-packet.json").write_text(
        json.dumps(packet_to_jsonable(packet), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return packet


def render_inventory_prompt(packet: dict[str, Any]) -> str:
    lines = [
        "# Independent Inventory Run Packet",
        "",
        "Use the fixed prompt at `agent_readiness/prompts/inventory.read_only.md`.",
        "",
        "## Run Context",
        "",
        f"- Run ID: `{packet['run_id']}`",
        f"- Variant: `{packet['variant']}`",
        f"- Drupal site root: `{packet['site_root']}`",
        f"- Write answer JSON to: `{packet['answer_json']}`",
        f"- Write transcript or command log to: `{packet['transcript']}`",
        "",
        "## Rules",
        "",
        "- Do not mutate the baseline substrate.",
        "- Keep the task read-only.",
        "- Do not use generated smoke-run answers.",
        "- Produce only this run's `answer.json` and transcript/log.",
    ]
    if packet["variant"] == "enhanced":
        lines.extend([
            "",
            "## Live Inventory Aids",
            "",
            f"- Site architecture brief: `{packet['enhanced_artifacts']['brief_md']}`",
            f"- Site architecture surfaces JSON: `{packet['enhanced_artifacts']['surfaces_json']}`",
            "- You may use `site-architecture:path-owner`, `site-architecture:surfaces`, and `site-architecture:brief` from the cloned site.",
        ])
    lines.extend([
        "",
        "After the run, package it with:",
        "",
        "```bash",
        "python3 agent_readiness/scripts/capture_run.py \\",
        f"  --run-id {packet['run_id']} \\",
        "  --task-id inventory.read_only \\",
        f"  --site-root {packet['site_root']} \\",
        f"  --answer-json {packet['answer_json']} \\",
        f"  --transcript {packet['transcript']} \\",
        '  --agent-name "<agent name>" \\',
        '  --agent-model "<model>" \\',
        '  --agent-harness "<harness>" \\',
        "  --elapsed-seconds <seconds> \\",
        "  --tool-calls <count> \\",
        "  --human-rescues <count>",
        "```",
    ])
    return "\n".join(lines) + "\n"


def packet_to_jsonable(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _jsonable(value)
        for key, value in packet.items()
        if key != "prompt_text"
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(child) for key, child in value.items()}
    return value
