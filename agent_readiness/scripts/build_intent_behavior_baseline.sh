#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-$REPO/method/intent-behavior}"
SOURCE_SITE="${SOURCE_SITE:-/Users/scott/dev/drupal-contrib/cms-clean-install}"
MODULE_DIR="${MODULE_DIR:-/Users/scott/dev/drupal-contrib/intent}"
CATALOG="${CATALOG:-$MODULE_DIR/catalog/drupal-cms-config-coverage.csv}"
BASE_ROOT="${BASE_ROOT:-$ARTIFACT_ROOT/sites}"
BASELINE_MAIN="$BASE_ROOT/baseline-main"
BASELINE_STALE="$BASE_ROOT/baseline-stale"
BASELINE_A11Y="$BASE_ROOT/baseline-a11y"
BASELINE_MANIFEST="$ARTIFACT_ROOT/baseline-manifest.json"
FORCE="${FORCE:-0}"
REUSE_EXISTING="${REUSE_EXISTING:-0}"
BUILD_A11Y="${BUILD_A11Y:-0}"
SKIP_COMPOSER_UPDATE="${SKIP_COMPOSER_UPDATE:-0}"
HASH_ONLY="${HASH_ONLY:-0}"

drush() {
  local site="$1"
  shift
  (cd "$site" && php -d memory_limit=-1 vendor/bin/drush.php "$@")
}

dr() {
  local site="$1"
  shift
  (cd "$site" && php -d memory_limit=-1 vendor/bin/dr "$@")
}

patch_dr_proxy_if_needed() {
  local site="$1"
  if [ ! -f "$site/vendor/bin/dr" ]; then
    return
  fi
  python3 - "$site/vendor/bin/dr" <<'PY'
from pathlib import Path
import re
import sys
path = Path(sys.argv[1])
text = path.read_text()
text = re.sub(
    r'include\("phpvfscomposer://" \. __DIR__ \. ([^)]+)\);\s*exit\(0\);',
    r'return include("phpvfscomposer://" . __DIR__ . \1);',
    text,
    flags=re.S,
)
text = re.sub(
    r'\ninclude __DIR__ \. ([^;]+);',
    r'\nreturn include __DIR__ . \1;',
    text,
)
path.write_text(text)
PY
}

fix_sqlite_path() {
  local site="$1"
  local settings="$site/web/sites/default/settings.php"
  local sqlite="$site/web/sites/default/files/.sqlite"
  chmod u+w "$settings" 2>/dev/null || true
  python3 - "$settings" "$sqlite" <<'PY'
from pathlib import Path
import re
import sys
settings = Path(sys.argv[1])
sqlite = Path(sys.argv[2])
text = settings.read_text()
text = re.sub(
    r"'database'\s*=>\s*'[^']*\.sqlite'",
    "'database' => '" + str(sqlite).replace("'", "\\'") + "'",
    text,
    count=1,
)
settings.write_text(text)
PY
  chmod 0444 "$settings" 2>/dev/null || true
}

copy_site() {
  local source="$1"
  local target="$2"
  if [ -e "$target" ]; then
    if [ "$REUSE_EXISTING" = "1" ]; then
      patch_dr_proxy_if_needed "$target"
      fix_sqlite_path "$target"
      return
    fi
    if [ "$FORCE" != "1" ]; then
      echo "Refusing to overwrite existing $target. Re-run with FORCE=1." >&2
      exit 2
    fi
    chmod -R u+w "$target" 2>/dev/null || true
    rm -rf "$target"
  fi
  mkdir -p "$(dirname "$target")"
  cp -cR "$source" "$target" 2>/dev/null || rsync -a --delete "$source/" "$target/"
  patch_dr_proxy_if_needed "$target"
  fix_sqlite_path "$target"
}

copy_intent_module() {
  local site="$1"
  mkdir -p "$site/web/modules/custom"
  rm -rf "$site/web/modules/custom/intent"
  rsync -a --delete --exclude .git --exclude vendor "$MODULE_DIR/" "$site/web/modules/custom/intent/"
}

apply_recipe() {
  local site="$1"
  local recipe="$2"
  if [[ "$recipe" != /* ]]; then
    recipe="$site/$recipe"
  fi
  dr "$site" recipe "$recipe"
}

ensure_main_baseline() {
  copy_site "$SOURCE_SITE" "$BASELINE_MAIN"
  chmod -R u+w "$BASELINE_MAIN/web/sites/default" 2>/dev/null || true
  if [ "$SKIP_COMPOSER_UPDATE" != "1" ]; then
    (
      cd "$BASELINE_MAIN"
      composer update drupal/core drupal/core-recommended drupal/core-composer-scaffold drupal/core-project-message --with-all-dependencies --no-interaction
    )
  fi
  if [ ! -f "$BASELINE_MAIN/web/autoload_runtime.php" ]; then
    (cd "$BASELINE_MAIN" && composer drupal:scaffold --no-interaction)
  fi
  patch_dr_proxy_if_needed "$BASELINE_MAIN"
  fix_sqlite_path "$BASELINE_MAIN"
  drush "$BASELINE_MAIN" updatedb -y
  apply_recipe "$BASELINE_MAIN" recipes/drupal_cms_seo_tools
  copy_intent_module "$BASELINE_MAIN"
  drush "$BASELINE_MAIN" pm:install intent -y
  drush "$BASELINE_MAIN" php:script "$REPO/agent_readiness/scripts/seed_intent_behavior_page.php" \
    > "$ARTIFACT_ROOT/baseline-seed-output.json"
  python3 "$REPO/agent_readiness/scripts/apply_intent_behavior_catalog.py" \
    --site "$BASELINE_MAIN" \
    --catalog "$CATALOG" \
    --variant main \
    --report "$ARTIFACT_ROOT/applied-catalog-main.json"
  dr "$BASELINE_MAIN" cache:rebuild
}

ensure_stale_baseline() {
  copy_site "$BASELINE_MAIN" "$BASELINE_STALE"
  drush "$BASELINE_STALE" php:script "$REPO/agent_readiness/scripts/make_intent_behavior_stale_layout.php" \
    > "$ARTIFACT_ROOT/baseline-stale-layout-output.json"
  dr "$BASELINE_STALE" cache:rebuild
}

ensure_a11y_baseline() {
  if [ "$BUILD_A11Y" != "1" ]; then
    return
  fi
  copy_site "$BASELINE_MAIN" "$BASELINE_A11Y"
  apply_recipe "$BASELINE_A11Y" recipes/drupal_cms_accessibility_tools
  python3 "$REPO/agent_readiness/scripts/apply_intent_behavior_catalog.py" \
    --site "$BASELINE_A11Y" \
    --catalog "$CATALOG" \
    --variant a11y \
    --report "$ARTIFACT_ROOT/applied-catalog-a11y.json"
  dr "$BASELINE_A11Y" cache:rebuild
}

write_hash_artifacts() {
  mkdir -p "$ARTIFACT_ROOT/baselines"
  rm -f "$ARTIFACT_ROOT/baselines/baseline-main.sql.gz" "$ARTIFACT_ROOT/baselines/baseline-main.sql.gz.gz"
  rm -f "$ARTIFACT_ROOT/baselines/baseline-stale.sql.gz" "$ARTIFACT_ROOT/baselines/baseline-stale.sql.gz.gz"
  drush "$BASELINE_MAIN" sql:dump --gzip --result-file="$ARTIFACT_ROOT/baselines/baseline-main.sql" >/dev/null
  drush "$BASELINE_STALE" sql:dump --gzip --result-file="$ARTIFACT_ROOT/baselines/baseline-stale.sql" >/dev/null
  local config_export_dir="$ARTIFACT_ROOT/baselines/config-export-main"
  rm -rf "$config_export_dir"
  mkdir -p "$config_export_dir"
  drush "$BASELINE_MAIN" config:export --destination="$config_export_dir" -y >/dev/null
  tar -czf "$ARTIFACT_ROOT/baselines/config-export-main.tar.gz" -C "$config_export_dir" .
  rm -rf "$config_export_dir"
  tar -czf "$ARTIFACT_ROOT/baselines/module-dir-intent.tar.gz" -C "$BASELINE_MAIN/web/modules/custom" intent
  python3 - "$ARTIFACT_ROOT" "$BASELINE_MAIN" "$BASELINE_STALE" "$BASELINE_A11Y" "$BUILD_A11Y" "$BASELINE_MANIFEST" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

artifact_root = Path(sys.argv[1])
main = Path(sys.argv[2])
stale = Path(sys.argv[3])
a11y = Path(sys.argv[4])
build_a11y = sys.argv[5] == "1"
manifest = Path(sys.argv[6])

def sha_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def sha_tree(root):
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in {".git", "__pycache__", "vendor", "node_modules"} for part in rel.parts):
            continue
        h.update(rel.as_posix().encode())
        h.update(b"\0")
        h.update(sha_file(path).encode())
        h.update(b"\n")
    return h.hexdigest()

files = {}
for path in sorted((artifact_root / "baselines").glob("*")):
    if path.is_file():
        files[path.relative_to(artifact_root).as_posix()] = sha_file(path)

data = {
    "baseline_main": str(main),
    "baseline_stale": str(stale),
    "baseline_a11y": str(a11y) if build_a11y else None,
    "site_hashes": {
        "baseline-main": sha_tree(main),
        "baseline-stale": sha_tree(stale),
        **({"baseline-a11y": sha_tree(a11y)} if build_a11y else {}),
    },
    "file_hashes": files,
}
manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
PY
}

mkdir -p "$ARTIFACT_ROOT"
if [ "$HASH_ONLY" = "1" ]; then
  write_hash_artifacts
  echo "$BASELINE_MANIFEST"
  exit 0
fi
ensure_main_baseline
ensure_stale_baseline
ensure_a11y_baseline
write_hash_artifacts
echo "$BASELINE_MANIFEST"
