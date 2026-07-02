#!/usr/bin/env python3
import argparse
import csv
import json
import re
import subprocess
from pathlib import Path
from typing import Any


SEO_CONFIG_RE = re.compile(r"^field\.(storage|field)\.node\.field_seo_")
BASE_EXCLUDED_OWNERS = {"drupal_cms_seo_tools", "drupal_cms_seo_basic"}
E3_EXCLUDED_OWNERS = {"drupal_cms_accessibility_tools"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the registered non-target intent catalog to a baseline site.")
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--mode", choices=["apply", "clear-all"], default="apply")
    parser.add_argument("--variant", choices=["main", "a11y"], default="main")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    report = clear_all(args.site) if args.mode == "clear-all" else apply_catalog(args.site, args.catalog, args.variant)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(_summary(report), indent=2))
    return 0 if report.get("errors", 0) == 0 else 1


def apply_catalog(site: Path, catalog: Path, variant: str) -> dict[str, Any]:
    rows = list(csv.DictReader(catalog.open(newline="", encoding="utf-8")))
    records: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        config_name = (row.get("config_name") or "").strip().lstrip("?")
        if not _is_candidate(row, config_name):
            continue
        reason = _exclusion_reason(row, config_name, variant)
        if reason:
            exclusions.append({
                "config_name": config_name,
                "intent_id": row.get("intent_id", ""),
                "source_owner": row.get("source_owner", ""),
                "reason": reason,
            })
            continue
        if config_name in seen:
            exclusions.append({
                "config_name": config_name,
                "intent_id": row.get("intent_id", ""),
                "source_owner": row.get("source_owner", ""),
                "reason": "duplicate_config_name",
            })
            continue
        seen.add(config_name)
        result = _dr(site, "intent:set", config_name, "--value", row["intent_value"], "--format=json")
        status = "ok" if result.returncode == 0 else "error"
        parsed = _parse_json(result.stdout)
        if isinstance(parsed, dict) and "No config entity found" in str(parsed.get("error", "")):
            status = "missing_config"
        records.append({
            "config_name": config_name,
            "intent_id": row.get("intent_id"),
            "source_owner": row.get("source_owner"),
            "status": status,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        })

    counts: dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    return {
        "mode": "apply",
        "variant": variant,
        "catalog": str(catalog),
        "site": str(site),
        "applied_count": counts.get("ok", 0),
        "candidate_count": len(records) + len(exclusions),
        "exclusion_count": len(exclusions),
        "counts": counts,
        "records": records,
        "exclusions": exclusions,
        "errors": counts.get("error", 0),
    }


def clear_all(site: Path) -> dict[str, Any]:
    listed = _dr(site, "intent:list", "--format=json")
    parsed = _parse_json(listed.stdout)
    items = parsed.get("items", []) if isinstance(parsed, dict) else []
    records = []
    for item in items:
        config_name = item.get("config") or item.get("config_name")
        if not config_name:
            continue
        result = _dr(site, "intent:delete", config_name, "--format=json")
        records.append({
            "config_name": config_name,
            "status": "ok" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        })
    return {
        "mode": "clear-all",
        "site": str(site),
        "cleared_count": sum(1 for record in records if record["status"] == "ok"),
        "records": records,
        "errors": sum(1 for record in records if record["status"] != "ok"),
    }


def _is_candidate(row: dict[str, str], config_name: str) -> bool:
    return (
        bool(config_name)
        and row.get("v0_attachable") == "yes"
        and row.get("coverage_status") == "intent_covered"
        and bool((row.get("intent_value") or "").strip())
    )


def _exclusion_reason(row: dict[str, str], config_name: str, variant: str) -> str | None:
    owner = row.get("source_owner") or ""
    if config_name == "core.entity_form_display.node.page.default":
        return "target_form_display"
    if SEO_CONFIG_RE.match(config_name):
        return "target_seo_field_config"
    if owner in BASE_EXCLUDED_OWNERS:
        return "seo_recipe_owner"
    if variant == "a11y" and owner in E3_EXCLUDED_OWNERS:
        return "a11y_recipe_owner"
    if variant == "a11y" and config_name == "views.view.a11y_tools_editoria11y_results":
        return "e3_target_view"
    return None


def _dr(site: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(site / "vendor/bin/dr"), *args], cwd=site, text=True, capture_output=True)


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: report[key]
        for key in ["mode", "variant", "applied_count", "candidate_count", "exclusion_count", "cleared_count", "errors"]
        if key in report
    }


if __name__ == "__main__":
    raise SystemExit(main())
