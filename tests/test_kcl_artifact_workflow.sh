#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_parent="$(mktemp -d)"
trap 'rm -rf "$tmp_parent"' EXIT

if [[ -z "${ZOO_API_TOKEN:-}" ]]; then
  echo "error: ZOO_API_TOKEN is required for the real Zoo flow test" >&2
  exit 1
fi

if ! command -v zoo >/dev/null 2>&1; then
  echo "error: zoo CLI is required on PATH" >&2
  exit 1
fi

project="$tmp_parent/project"
mkdir -p "$project"
cp -R "$repo_root/tests/fixtures/basic/." "$project/"

(
  cd "$project"
  KCL_PARAMETERS_JSON='{"width": 24, "depth": 6}' "$repo_root/scripts/run-kcl-artifacts.sh"
)

test -s "$project/kcl-artifacts/assembly/model.step"
test -s "$project/kcl-artifacts/assembly/model.gltf"
test -s "$project/kcl-artifacts/assembly/analysis.json"
test -s "$project/kcl-artifacts/assembly/bounding-box.json"
test -s "$project/kcl-artifacts/assembly/snapshot.png"
test -s "$project/kcl-artifacts/snapshots/main.png"
test -s "$project/kcl-artifacts/snapshots/part.png"
test -s "$project/kcl-artifacts/manifest.json"

grep -q 'width = 20' "$project/parameters.kcl"

python3 - "$project/kcl-artifacts/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert manifest["main_kcl"] == "main.kcl"
assert manifest["parameters_kcl"] == "parameters.kcl"
assert manifest["parameters_override_keys"] == ["depth", "width"]
artifacts = set(manifest["artifacts"])
expected = {
    "assembly/analysis.json",
    "assembly/bounding-box.json",
    "assembly/model.gltf",
    "assembly/model.step",
    "assembly/snapshot.png",
    "snapshots/main.png",
    "snapshots/part.png",
}
missing = expected - artifacts
if missing:
    raise SystemExit(f"manifest missing artifacts: {sorted(missing)}")
PY
