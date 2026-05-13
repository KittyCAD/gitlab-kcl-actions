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
  KCL_MAIN_KCL_PATHS='["main.kcl","assembly-2/main.kcl"]' \
    KCL_PARAMETERS_JSON='{"width": 24, "depth": 6}' \
    "$repo_root/scripts/run-kcl-artifacts.sh"
)

test -s "$project/kcl-artifacts/assemblies/root/model.step"
test -s "$project/kcl-artifacts/assemblies/root/model.gltf"
test -s "$project/kcl-artifacts/assemblies/root/analysis.json"
test -s "$project/kcl-artifacts/assemblies/root/bounding-box.json"
test -s "$project/kcl-artifacts/assemblies/root/snapshot.png"
test -s "$project/kcl-artifacts/assemblies/assembly-2/model.step"
test -s "$project/kcl-artifacts/assemblies/assembly-2/model.gltf"
test -s "$project/kcl-artifacts/assemblies/assembly-2/analysis.json"
test -s "$project/kcl-artifacts/assemblies/assembly-2/bounding-box.json"
test -s "$project/kcl-artifacts/assemblies/assembly-2/snapshot.png"
for view in isometric front top right; do
  test -s "$project/kcl-artifacts/snapshots/main.${view}.png"
  test -s "$project/kcl-artifacts/snapshots/part.${view}.png"
  test -s "$project/kcl-artifacts/snapshots/assembly-2/main.${view}.png"
  test -s "$project/kcl-artifacts/snapshots/assembly-2/part.${view}.png"
done
test -s "$project/kcl-artifacts/source/main.kcl"
test -s "$project/kcl-artifacts/source/metadata.json"
test -s "$project/kcl-artifacts/source/part.kcl"
test -s "$project/kcl-artifacts/source/parameters.kcl"
test -s "$project/kcl-artifacts/source/assembly-2/main.kcl"
test -s "$project/kcl-artifacts/source/assembly-2/metadata.json"
test -s "$project/kcl-artifacts/source/assembly-2/part.kcl"
test -s "$project/kcl-artifacts/source/assembly-2/parameters.kcl"
test -s "$project/kcl-artifacts/manifest.json"

grep -q 'export width = 20' "$project/parameters.kcl"

python3 - "$project/kcl-artifacts/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

artifact_root = Path(sys.argv[1]).parent
manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert manifest["parameters_override_keys"] == ["depth", "width"]
assert manifest["assemblies"] == [
    {
        "id": "root",
        "main_kcl": "main.kcl",
        "parameters_kcl": "parameters.kcl",
    },
    {
        "id": "assembly-2",
        "main_kcl": "assembly-2/main.kcl",
        "parameters_kcl": "assembly-2/parameters.kcl",
    },
]
artifacts = set(manifest["artifacts"])
expected = {
    "assemblies/root/analysis.json",
    "assemblies/root/bounding-box.json",
    "assemblies/root/model.gltf",
    "assemblies/root/model.step",
    "assemblies/root/snapshot.png",
    "assemblies/assembly-2/analysis.json",
    "assemblies/assembly-2/bounding-box.json",
    "assemblies/assembly-2/model.gltf",
    "assemblies/assembly-2/model.step",
    "assemblies/assembly-2/snapshot.png",
    "source/main.kcl",
    "source/metadata.json",
    "source/part.kcl",
    "source/parameters.kcl",
    "source/assembly-2/main.kcl",
    "source/assembly-2/metadata.json",
    "source/assembly-2/part.kcl",
    "source/assembly-2/parameters.kcl",
}
for source in ("main", "part", "assembly-2/main", "assembly-2/part"):
    for view in ("isometric", "front", "top", "right"):
        expected.add(f"snapshots/{source}.{view}.png")
missing = expected - artifacts
if missing:
    raise SystemExit(f"manifest missing artifacts: {sorted(missing)}")

for assembly, bounding_box_unit in (("root", "mm"), ("assembly-2", "cm")):
    analysis = json.loads(
        (artifact_root / "assemblies" / assembly / "analysis.json").read_text(
            encoding="utf-8"
        )
    )
    assert analysis["mass"]["output_unit"] == "kg"
    assert analysis["volume"]["output_unit"] == "cm3"
    assert analysis["density"]["output_unit"] == "kg:m3"
    assert analysis["surface_area"]["output_unit"] == "cm2"
    assert analysis["center_of_mass"]["output_unit"] == "mm"
    assert sorted(analysis["bounding_box"]) == ["center", "dimensions"]

    bounding_box = json.loads(
        (artifact_root / "assemblies" / assembly / "bounding-box.json").read_text(
            encoding="utf-8"
        )
    )
    assert bounding_box["output_unit"] == bounding_box_unit
    assert sorted(bounding_box) == ["center", "dimensions", "output_unit"]
    assert sorted(bounding_box["center"]) == ["x", "y", "z"]
    assert sorted(bounding_box["dimensions"]) == ["x", "y", "z"]
PY
