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
  # empty.kcl has no exportable geometry. Including it proves that a file which
  # cannot produce artifacts only warns and is skipped, without failing the job.
  KCL_MAIN_KCL_PATHS='["main.kcl","part.kcl","assembly-2/main.kcl","assembly-2/part.kcl","empty.kcl"]' \
    KCL_PARAMETERS_JSON='{"width": 24, "depth": 6}' \
    "$repo_root/scripts/run-kcl-artifacts.sh"
)

# Every .kcl file is its own assembly and gets a STEP, glTF, snapshot, and
# physics artifacts, regardless of which folder it lives in.
for assembly in main part assembly-2/main assembly-2/part; do
  test -s "$project/kcl-artifacts/assemblies/${assembly}.step"
  test -s "$project/kcl-artifacts/assemblies/${assembly}.gltf"
  test -s "$project/kcl-artifacts/assemblies/${assembly}-analysis.json"
  test -s "$project/kcl-artifacts/assemblies/${assembly}-bounding-box.json"
  test -s "$project/kcl-artifacts/assemblies/${assembly}-snapshot.png"
done

for source in main part assembly-2/main assembly-2/part; do
  for view in isometric front top right; do
    test -s "$project/kcl-artifacts/snapshots/${source}.${view}.png"
  done
done

# empty.kcl could not be exported, so its assembly artifacts must be absent even
# though the job succeeded.
for empty_artifact in \
  "assemblies/empty.step" \
  "assemblies/empty.gltf" \
  "assemblies/empty-analysis.json" \
  "assemblies/empty-bounding-box.json" \
  "assemblies/empty-snapshot.png"; do
  if [[ -e "$project/kcl-artifacts/${empty_artifact}" ]]; then
    echo "error: empty.kcl should not have produced ${empty_artifact}" >&2
    exit 1
  fi
done

# Its source is still copied so reviewers can see the skipped input.
test -s "$project/kcl-artifacts/source/empty.kcl"

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
        "id": "main",
        "main_kcl": "main.kcl",
        "metadata_json": "metadata.json",
        "parameters_kcl": "parameters.kcl",
    },
    {
        "id": "part",
        "main_kcl": "part.kcl",
        "metadata_json": "metadata.json",
        "parameters_kcl": "parameters.kcl",
    },
    {
        "id": "assembly-2/main",
        "main_kcl": "assembly-2/main.kcl",
        "metadata_json": "assembly-2/metadata.json",
        "parameters_kcl": "assembly-2/parameters.kcl",
    },
    {
        "id": "assembly-2/part",
        "main_kcl": "assembly-2/part.kcl",
        "metadata_json": "assembly-2/metadata.json",
        "parameters_kcl": "assembly-2/parameters.kcl",
    },
    {
        "id": "empty",
        "main_kcl": "empty.kcl",
        "metadata_json": "metadata.json",
        "parameters_kcl": "parameters.kcl",
    },
]
artifacts = set(manifest["artifacts"])
expected = {"parameters.json"}
for assembly in ("main", "part", "assembly-2/main", "assembly-2/part"):
    expected.update(
        {
            f"assemblies/{assembly}-analysis.json",
            f"assemblies/{assembly}-bounding-box.json",
            f"assemblies/{assembly}.gltf",
            f"assemblies/{assembly}.step",
            f"assemblies/{assembly}-snapshot.png",
        }
    )
for source in ("main", "part", "assembly-2/main", "assembly-2/part"):
    for view in ("isometric", "front", "top", "right"):
        expected.add(f"snapshots/{source}.{view}.png")
for source in (
    "main.kcl",
    "metadata.json",
    "part.kcl",
    "parameters.kcl",
    "empty.kcl",
    "assembly-2/main.kcl",
    "assembly-2/metadata.json",
    "assembly-2/part.kcl",
    "assembly-2/parameters.kcl",
):
    expected.add(f"source/{source}")
missing = expected - artifacts
if missing:
    raise SystemExit(f"manifest missing artifacts: {sorted(missing)}")

# empty.kcl yields no exportable geometry, so it must not contribute any
# assembly artifacts even though it is listed as an assembly.
forbidden = {
    "assemblies/empty.step",
    "assemblies/empty.gltf",
    "assemblies/empty-analysis.json",
    "assemblies/empty-bounding-box.json",
    "assemblies/empty-snapshot.png",
}
present = forbidden & artifacts
if present:
    raise SystemExit(f"manifest unexpectedly lists skipped artifacts: {sorted(present)}")

for assembly, bounding_box_unit in (
    ("main", "mm"),
    ("part", "mm"),
    ("assembly-2/main", "cm"),
    ("assembly-2/part", "cm"),
):
    analysis = json.loads(
        (artifact_root / "assemblies" / f"{assembly}-analysis.json").read_text(
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
        (artifact_root / "assemblies" / f"{assembly}-bounding-box.json").read_text(
            encoding="utf-8"
        )
    )
    assert bounding_box["output_unit"] == bounding_box_unit
    assert sorted(bounding_box) == ["center", "dimensions", "output_unit"]
    assert sorted(bounding_box["center"]) == ["x", "y", "z"]
    assert sorted(bounding_box["dimensions"]) == ["x", "y", "z"]
PY
