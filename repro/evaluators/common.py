import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from agent_readiness.evaluators.result import EvaluationResult


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "evaluators" / "drupal_state_collector.php"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def get_path(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def add_equal_failure(
    failures: list[str],
    state: dict[str, Any],
    answer: dict[str, Any],
    path: str,
) -> None:
    if get_path(state, path) != get_path(answer, path):
        failures.append(path)


def add_contains_failures(
    failures: list[str],
    expected: list[Any],
    actual: list[Any],
    path: str,
) -> None:
    missing = [item for item in expected if item not in actual]
    if missing:
        failures.append(path)


def add_unexpected_failures(
    failures: list[str],
    expected: list[Any],
    actual: list[Any],
    path: str,
) -> None:
    """Flag items the answer reported that are absent from live state.

    Pairs with ``add_contains_failures`` (which flags missing items) so a list
    field is graded as a set: over-claiming a surface that does not exist is an
    error, not a harmless extra.
    """
    unexpected = [item for item in actual if item not in expected]
    if unexpected:
        failures.append(f"{path}.unexpected")


def command_runner_from_state(state: dict[str, Any]) -> str:
    runner = state.get("command_runner", {})
    if runner.get("ddev") and runner.get("drush"):
        return "ddev drush"
    if runner.get("drush"):
        return "vendor/bin/drush"
    if runner.get("dr"):
        return "vendor/bin/dr"
    return ""


def collect_live_state(site_root: Path) -> dict[str, Any]:
    drush = site_root / "vendor" / "bin" / "drush"
    if not drush.exists():
        raise RuntimeError(f"Cannot collect live state: {drush} does not exist")

    status = subprocess.run(
        [str(drush), "status", "--format=json"],
        cwd=site_root,
        text=True,
        capture_output=True,
        check=True,
    )
    drupal_state = subprocess.run(
        [str(drush), "php:script", str(COLLECTOR)],
        cwd=site_root,
        text=True,
        capture_output=True,
        check=True,
    )

    state = json.loads(drupal_state.stdout)
    status_data = json.loads(status.stdout)
    sync_dir = Path(status_data.get("config-sync") or status_data.get("config") or "")
    sync_files = []
    if sync_dir.exists():
        sync_files = [
            item
            for item in sync_dir.iterdir()
            if item.is_file() and item.suffix in {".yml", ".yaml"}
        ]

    state["command_runner"] = {
        "drush": drush.exists(),
        "dr": (site_root / "vendor" / "bin" / "dr").exists(),
        "ddev": (site_root / ".ddev").exists(),
    }
    state.setdefault("provenance", {})
    state["provenance"]["config_sync_status"] = "populated" if sync_files else "empty"
    state["provenance"]["active_config_source"] = "database"
    return state


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    state = parser.add_mutually_exclusive_group(required=True)
    state.add_argument("--state-json", type=Path, help="Pre-collected live state JSON")
    state.add_argument("--site-root", type=Path, help="Drupal project root to inspect with vendor/bin/drush")
    parser.add_argument("--answer-json", type=Path, required=True, help="Agent answer.json to evaluate")
    return parser


def load_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_json(args.state_json) if args.state_json else collect_live_state(args.site_root)
    answer = load_json(args.answer_json)
    return state, answer


def print_result(result: EvaluationResult) -> None:
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
