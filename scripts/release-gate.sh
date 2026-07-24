#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
TEMP_ROOT="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
QUICK=false
LOCAL_PREPUBLISH=false
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) QUICK=true ;;
    --local-prepublish) LOCAL_PREPUBLISH=true ;;
    --output-dir)
      shift
      [[ $# -gt 0 ]] || { echo "--output-dir requires a path" >&2; exit 2; }
      OUTPUT_DIR="$1"
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

cd "$ROOT"
mkdir -p "$TEMP_ROOT"
export PYTHONPYCACHEPREFIX="$TEMP_ROOT/packwright-pycache"

if [[ "$LOCAL_PREPUBLISH" == true ]]; then
  test -z "$(git remote)"
  test -z "$(git tag --list)"
fi

git diff --check
"$PYTHON" -m compileall -q src tests scripts
"$PYTHON" -m unittest discover -s tests
"$PYTHON" scripts/audit_zero_network.py
"$PYTHON" scripts/audit_public_tree.py

if [[ "$QUICK" == true ]]; then
  exit 0
fi

WORK="$(mktemp -d "$TEMP_ROOT/packwright-release.XXXXXX")"
cleanup() {
  rm -rf "$WORK" "$ROOT/build" "$ROOT/src/packwright.egg-info"
}
trap cleanup EXIT

if [[ -n "$OUTPUT_DIR" ]]; then
  DIST="$(mkdir -p "$OUTPUT_DIR" && cd "$OUTPUT_DIR" && pwd)"
else
  DIST="$WORK/dist"
fi

"$PYTHON" -m build --outdir "$DIST"
"$PYTHON" -m twine check "$DIST"/*

SDIST="$(find "$DIST" -name 'packwright-*.tar.gz' -print -quit)"
WHEEL="$(find "$DIST" -name 'packwright-*.whl' -print -quit)"
mkdir "$WORK/sdist"
tar -xzf "$SDIST" -C "$WORK/sdist"
SDIR="$(find "$WORK/sdist" -mindepth 1 -maxdepth 1 -type d -print -quit)"
"$PYTHON" -m venv "$WORK/sdist-venv"
"$WORK/sdist-venv/bin/python" -m pip install -q "$SDIR[test]"
(cd "$SDIR" && "$WORK/sdist-venv/bin/python" -m unittest discover -s tests)

"$PYTHON" -m venv "$WORK/wheel-venv"
"$WORK/wheel-venv/bin/python" -m pip install -q "$WHEEL"
PW="$WORK/wheel-venv/bin/packwright"
"$PW" --version
"$PW" init --template code --name Nova -o "$WORK/work"
for adapter in codex claude-code cursor pi; do
  "$PW" build "$WORK/work" --adapter "$adapter" -o "$WORK/pack-$adapter"
  "$PW" install "$WORK/pack-$adapter" --adapter "$adapter" --target "$WORK/target-$adapter"
  "$PW" doctor "$WORK/target-$adapter"
  "$PW" score "$WORK/target-$adapter"
done
"$PW" migrate "$WORK/target-codex" --to cursor --target "$WORK/migrated-cursor" --dry-run
"$PW" migrate "$WORK/target-codex" --to cursor --target "$WORK/migrated-cursor" --yes
"$PW" doctor "$WORK/migrated-cursor"
"$PW" score "$WORK/migrated-cursor"
"$PW" migrate "$WORK/target-codex" --to pi --target "$WORK/migrated-pi" --dry-run
"$PW" migrate "$WORK/target-codex" --to pi --target "$WORK/migrated-pi" --yes --accept-degraded
"$PW" doctor "$WORK/migrated-pi"
"$PW" score "$WORK/migrated-pi"

"$PYTHON" - "$DIST" "$DIST/release-artifacts.json" <<'PY'
import hashlib, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path.cwd() / "src"))
from packwright import __version__
dist = pathlib.Path(sys.argv[1])
items = []
for path in sorted(dist.iterdir()):
    if path.name == "release-artifacts.json" or not path.is_file():
        continue
    items.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size})
pathlib.Path(sys.argv[2]).write_text(json.dumps({"version": __version__, "artifacts": items}, indent=2) + "\n", encoding="utf-8")
PY
echo "release artifacts: $DIST"
