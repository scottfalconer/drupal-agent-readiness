import json
import os
import subprocess
from pathlib import Path
from typing import Any

from agent_readiness.evaluators.result import EvaluationResult


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "evaluators" / "alias_safety_collector.php"
DEFAULT_CANDIDATES = ROOT / "prompts" / "assess.alias_safety.candidates.json"


def evaluate(state: dict[str, Any], answer: dict[str, Any], verdict_only: bool = False) -> EvaluationResult:
    """Score an alias-safety answer against independently collected ground truth.

    Each candidate path is graded on two facts: the safe/unsafe verdict, and
    (when unsafe) the blocker kind. The ``latent_disabled_view`` blocker is the
    discriminating case: a path that is currently unrouted but is declared by a
    disabled view, which raw inspection ("does anything respond here?") misses.

    ``verdict_only=True`` grades only the safe/unsafe verdict and ignores
    blocker_kind. Use it for the knowledge-blind condition, where the agent is
    not told the blocker taxonomy (so naming the latent kind cannot be required);
    a latent claim counts as caught when the agent simply marked the path unsafe.
    """
    failures: list[str] = []
    assessments = answer.get("assessments") or {}
    latent_total = 0
    latent_correct = 0
    verdict_correct = 0

    for path, truth in state.items():
        truth_safe = bool(truth.get("safe"))
        truth_kind = truth.get("blocker_kind")
        is_latent = truth_kind == "latent_disabled_view"
        if is_latent:
            latent_total += 1

        answered = assessments.get(path)
        if not isinstance(answered, dict):
            failures.append(f"{path}.missing")
            continue

        answer_safe = bool(answered.get("safe"))
        answer_kind = answered.get("blocker_kind") or None

        if answer_safe == truth_safe:
            verdict_correct += 1
        else:
            failures.append(f"{path}.safe")

        if not verdict_only and not truth_safe and answer_kind != truth_kind:
            failures.append(f"{path}.blocker_kind")

        if is_latent and answer_safe is False:
            if verdict_only or answer_kind == "latent_disabled_view":
                latent_correct += 1

    details = {
        "candidates_total": len(state),
        "verdict_correct": verdict_correct,
        "latent_total": latent_total,
        "latent_correct": latent_correct,
    }
    return EvaluationResult(passed=not failures, failures=failures, details=details)


def collect_alias_safety_state(
    site_root: Path,
    candidates_file: Path = DEFAULT_CANDIDATES,
    php_ini_scan_dir: str | None = None,
) -> dict[str, Any]:
    """Collect ground truth from a live clone via the core-only collector."""
    drush = site_root / "vendor" / "bin" / "drush"
    if not drush.exists():
        raise RuntimeError(f"Cannot collect alias-safety state: {drush} does not exist")
    env = dict(os.environ)
    env["AR_ALIAS_CANDIDATES"] = str(candidates_file)
    if php_ini_scan_dir:
        env["PHP_INI_SCAN_DIR"] = php_ini_scan_dir
    completed = subprocess.run(
        [str(drush), "php:script", str(COLLECTOR)],
        cwd=site_root,
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    return json.loads(completed.stdout)
