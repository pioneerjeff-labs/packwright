#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
TEMP_ROOT="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
MODE=""
LOCAL_PREPUBLISH=false
OUTPUT_DIR=""
EMOTION_ENGINE_SOURCE="${PACKWRIGHT_RELEASE_EMOTION_ENGINE_SOURCE:-}"

set_mode() {
  if [[ -n "$MODE" ]]; then
    echo "release gate modes cannot be combined" >&2
    exit 2
  fi
  MODE="$1"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) set_mode quick ;;
    --unit) set_mode unit ;;
    --audit) set_mode audit ;;
    --package-only) set_mode package ;;
    --build-only) set_mode build ;;
    --local-prepublish) LOCAL_PREPUBLISH=true ;;
    --emotion-engine-source)
      shift
      [[ $# -gt 0 ]] || { echo "--emotion-engine-source requires a path" >&2; exit 2; }
      EMOTION_ENGINE_SOURCE="$1"
      ;;
    --output-dir)
      shift
      [[ $# -gt 0 ]] || { echo "--output-dir requires a path" >&2; exit 2; }
      OUTPUT_DIR="$1"
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

MODE="${MODE:-full}"

cd "$ROOT"
mkdir -p "$TEMP_ROOT"
export PYTHONPYCACHEPREFIX="$TEMP_ROOT/packwright-pycache"

if [[ "$LOCAL_PREPUBLISH" == true ]]; then
  test -z "$(git remote)"
  test -z "$(git tag --list)"
fi

run_unit_checks() {
  git diff --check
  "$PYTHON" -m compileall -q src tests scripts
  "$PYTHON" -m unittest discover -s tests
}

run_audits() {
  git diff --check
  "$PYTHON" scripts/audit_zero_network.py
  "$PYTHON" scripts/audit_public_tree.py
}

run_emotion_engine_smoke() {
  if [[ -z "$EMOTION_ENGINE_SOURCE" ]]; then
    echo "release-critical modes require --emotion-engine-source at the pinned checkout" >&2
    return 2
  fi
  if [[ ! -d "$EMOTION_ENGINE_SOURCE" ]]; then
    echo "Emotion Engine source is not a directory: $EMOTION_ENGINE_SOURCE" >&2
    return 2
  fi
  "$PYTHON" scripts/emotion_engine_release_smoke.py "$EMOTION_ENGINE_SOURCE"
}

case "$MODE" in
  unit)
    run_unit_checks
    exit 0
    ;;
  audit)
    run_audits
    exit 0
    ;;
  quick)
    run_unit_checks
    run_emotion_engine_smoke
    "$PYTHON" scripts/audit_zero_network.py
    "$PYTHON" scripts/audit_public_tree.py
    exit 0
    ;;
  full)
    run_unit_checks
    run_emotion_engine_smoke
    "$PYTHON" scripts/audit_zero_network.py
    "$PYTHON" scripts/audit_public_tree.py
    ;;
esac

if [[ "$MODE" != "full" && "$MODE" != "package" && "$MODE" != "build" ]]; then
  echo "unsupported release gate mode: $MODE" >&2
  exit 2
fi

if [[ "$MODE" == "package" || "$MODE" == "build" ]]; then
  run_emotion_engine_smoke
fi

WORK="$(mktemp -d "$TEMP_ROOT/packwright-release.XXXXXX")"
cleanup() {
  rm -rf "$WORK" "$ROOT/build" "$ROOT/src/packwright.egg-info"
}
trap cleanup EXIT

QUIET_INDEX=0
run_quiet() {
  local label="$1"
  local log
  shift
  QUIET_INDEX=$((QUIET_INDEX + 1))
  log="$WORK/command-$QUIET_INDEX.log"
  if "$@" >"$log" 2>&1; then
    echo "$label passed"
    return 0
  fi
  echo "$label failed" >&2
  cat "$log" >&2
  return 1
}

if [[ -n "$OUTPUT_DIR" ]]; then
  DIST="$(mkdir -p "$OUTPUT_DIR" && cd "$OUTPUT_DIR" && pwd)"
else
  DIST="$WORK/dist"
fi

write_receipt() {
  local packwright_commit emotion_engine_commit
  packwright_commit="$(git rev-parse HEAD)"
  emotion_engine_commit="$(git -C "$EMOTION_ENGINE_SOURCE" rev-parse HEAD)"
  "$PYTHON" - "$DIST" "$DIST/release-artifacts.json" "$packwright_commit" "$emotion_engine_commit" <<'PY'
import hashlib, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path.cwd() / "src"))
from packwright import __version__
dist = pathlib.Path(sys.argv[1])
items = []
for path in sorted(dist.iterdir()):
    if path.name == "release-artifacts.json" or not path.is_file():
        continue
    items.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size})
pathlib.Path(sys.argv[2]).write_text(json.dumps({
    "version": __version__,
    "packwright_commit": sys.argv[3],
    "emotion_engine_commit": sys.argv[4],
    "artifacts": items,
}, indent=2) + "\n", encoding="utf-8")
PY
}

run_quiet "distribution build" "$PYTHON" -m build --outdir "$DIST"
run_quiet "distribution metadata check" "$PYTHON" -m twine check "$DIST"/*

if [[ "$MODE" == "build" ]]; then
  write_receipt
  echo "release artifacts: $DIST"
  exit 0
fi

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
run_quiet "wheel version smoke" "$PW" --version
run_quiet "starter initialization smoke" "$PW" init --template code --name Nova -o "$WORK/work"
for adapter in codex claude-code cursor pi; do
  run_quiet "$adapter build smoke" "$PW" build "$WORK/work" --adapter "$adapter" -o "$WORK/pack-$adapter"
  run_quiet "$adapter install smoke" "$PW" install "$WORK/pack-$adapter" --adapter "$adapter" --target "$WORK/target-$adapter"
  run_quiet "$adapter doctor smoke" "$PW" doctor "$WORK/target-$adapter"
  run_quiet "$adapter score smoke" "$PW" score "$WORK/target-$adapter"
done
run_quiet "Cursor migration plan smoke" "$PW" migrate "$WORK/target-codex" --to cursor --target "$WORK/migrated-cursor" --dry-run
run_quiet "Cursor migration apply smoke" "$PW" migrate "$WORK/target-codex" --to cursor --target "$WORK/migrated-cursor" --yes --accept-degraded
run_quiet "Cursor migration doctor smoke" "$PW" doctor "$WORK/migrated-cursor"
run_quiet "Cursor migration score smoke" "$PW" score "$WORK/migrated-cursor"
run_quiet "Pi migration plan smoke" "$PW" migrate "$WORK/target-codex" --to pi --target "$WORK/migrated-pi" --dry-run
run_quiet "Pi migration apply smoke" "$PW" migrate "$WORK/target-codex" --to pi --target "$WORK/migrated-pi" --yes --accept-degraded
run_quiet "Pi migration doctor smoke" "$PW" doctor "$WORK/migrated-pi"
run_quiet "Pi migration score smoke" "$PW" score "$WORK/migrated-pi"

write_receipt
echo "release artifacts: $DIST"
