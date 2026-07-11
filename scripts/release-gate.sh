#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QUICK="${1:-}"
PYTHON="${PYTHON:-python3}"
cd "$ROOT"
export PYTHONPYCACHEPREFIX="${TMPDIR:-/private/tmp}/packwright-pycache"

test "$(git remote | wc -l | tr -d ' ')" = 0
test "$(git tag --list | wc -l | tr -d ' ')" = 0
git diff --check
"$PYTHON" -m compileall -q src tests scripts
"$PYTHON" -m unittest discover -s tests
"$PYTHON" scripts/audit_zero_network.py
"$PYTHON" scripts/audit_public_tree.py

if [[ "$QUICK" == "--quick" ]]; then
  exit 0
fi

WORK="$(mktemp -d "${TMPDIR:-/private/tmp}/packwright-release.XXXXXX")"
cleanup() {
  rm -rf "$WORK" "$ROOT/build" "$ROOT/src/packwright.egg-info"
}
trap cleanup EXIT
"$PYTHON" -m build --outdir "$WORK/dist"
"$PYTHON" -m twine check "$WORK"/dist/*

SDIST="$(find "$WORK/dist" -name 'packwright-*.tar.gz' -print -quit)"
WHEEL="$(find "$WORK/dist" -name 'packwright-*.whl' -print -quit)"
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
"$PW" init --template creator -o "$WORK/work"
for adapter in codex claude-code cursor; do
  "$PW" build "$WORK/work" --adapter "$adapter" -o "$WORK/pack-$adapter"
  "$PW" install "$WORK/pack-$adapter" --adapter "$adapter" --target "$WORK/target-$adapter"
  "$PW" doctor "$WORK/target-$adapter"
  "$PW" score "$WORK/target-$adapter"
done
"$PW" migrate "$WORK/target-codex" --to cursor --target "$WORK/migrated-cursor" --dry-run
"$PW" migrate "$WORK/target-codex" --to cursor --target "$WORK/migrated-cursor" --yes
"$PW" doctor "$WORK/migrated-cursor"
"$PW" score "$WORK/migrated-cursor"

"$PYTHON" - "$WORK/dist" "$ROOT/release-artifacts.json" <<'PY'
import hashlib, json, pathlib, sys
dist = pathlib.Path(sys.argv[1])
items = []
for path in sorted(dist.iterdir()):
    items.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size})
pathlib.Path(sys.argv[2]).write_text(json.dumps({"version": "0.1.0rc1", "artifacts": items}, indent=2) + "\n", encoding="utf-8")
PY
