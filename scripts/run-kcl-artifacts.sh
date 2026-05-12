#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_helper="${KCL_ARTIFACTS_PY:-${script_dir}/kcl_artifacts.py}"
repo_root="$(pwd)"
artifact_dir="${repo_root}/kcl-artifacts"
parameters_json="${KCL_PARAMETERS_JSON:-}"
if [[ -z "$parameters_json" ]]; then
  parameters_json="{}"
fi
host="${KCL_ZOO_HOST:-}"
snapshot_angle="${KCL_SNAPSHOT_ANGLE:-iso}"
camera_style="${KCL_CAMERA_STYLE:-ortho}"
camera_padding="${KCL_CAMERA_PADDING:-0.1}"

tmp_parent="$(mktemp -d)"
trap 'rm -rf "$tmp_parent"' EXIT
workspace="${tmp_parent}/repo"
state_dir="${tmp_parent}/state"
mkdir -p "$workspace" "$state_dir"

tar \
  --exclude='./.git' \
  --exclude='./.gitlab-kcl-actions' \
  --exclude='./.kcl-tools' \
  --exclude='./kcl-artifacts' \
  -cf - . | tar -C "$workspace" -xf -
rm -rf "$artifact_dir"
mkdir -p "$artifact_dir/assembly" "$artifact_dir/snapshots"

cd "$workspace"

python3 "$python_helper" project-info \
  --repo-root "$workspace" \
  --env-out "$state_dir/project.env" \
  --snapshots-out "$state_dir/snapshots.list"

# shellcheck disable=SC1091
source "$state_dir/project.env"

python3 "$python_helper" apply-parameters \
  --parameters-file "$PARAMETERS_KCL" \
  --overrides-json "$parameters_json"

python3 "$python_helper" metadata-env \
  --metadata-file "$workspace/metadata.json" \
  --env-out "$state_dir/metadata.env"

# shellcheck disable=SC1091
source "$state_dir/metadata.env"

zoo_cmd=(zoo)
if [[ -n "$host" ]]; then
  zoo_cmd+=(--host "$host")
fi

zoo_version="$(zoo version)"

"${zoo_cmd[@]}" kcl lint "$MAIN_KCL"

"${zoo_cmd[@]}" kcl analyze \
  --format json \
  --material-density "$MATERIAL_DENSITY" \
  --material-density-unit "$MATERIAL_DENSITY_UNIT" \
  --mass-output-unit "$MASS_OUTPUT_UNIT" \
  --volume-output-unit "$VOLUME_OUTPUT_UNIT" \
  --density-output-unit "$DENSITY_OUTPUT_UNIT" \
  --surface-area-output-unit "$SURFACE_AREA_OUTPUT_UNIT" \
  --center-of-mass-output-unit "$CENTER_OF_MASS_OUTPUT_UNIT" \
  "$MAIN_KCL" > "$artifact_dir/assembly/analysis.json"

export_one() {
  local format="$1"
  local extension="$2"
  local destination="$3"
  local export_dir="${state_dir}/export-${format}"

  mkdir -p "$export_dir"
  "${zoo_cmd[@]}" kcl export \
    --deterministic \
    --output-format "$format" \
    "$MAIN_KCL" \
    "$export_dir"

  exported_count=0
  exported_file=""
  while IFS= read -r candidate; do
    exported_count=$((exported_count + 1))
    exported_file="$candidate"
  done < <(find "$export_dir" -type f -name "*.${extension}" | sort)
  if [[ "$exported_count" -ne 1 ]]; then
    echo "error: expected one ${extension} export, found ${exported_count}" >&2
    exit 1
  fi
  mv "$exported_file" "$destination"
}

export_one step step "$artifact_dir/assembly/model.step"
export_one gltf gltf "$artifact_dir/assembly/model.gltf"

"${zoo_cmd[@]}" kcl bounding-box \
  --format json \
  --output-unit "$BOUNDING_BOX_OUTPUT_UNIT" \
  "$MAIN_KCL" > "$artifact_dir/assembly/bounding-box.json"

"${zoo_cmd[@]}" kcl snapshot \
  --output-format png \
  --angle "$snapshot_angle" \
  --camera-style "$camera_style" \
  --camera-padding "$camera_padding" \
  "$MAIN_KCL" \
  "$artifact_dir/assembly/snapshot.png"

while IFS= read -r snapshot_input; do
  [[ -n "$snapshot_input" ]] || continue
  snapshot_output="$artifact_dir/snapshots/${snapshot_input%.kcl}.png"
  mkdir -p "$(dirname "$snapshot_output")"
  "${zoo_cmd[@]}" kcl snapshot \
    --output-format png \
    --angle "$snapshot_angle" \
    --camera-style "$camera_style" \
    --camera-padding "$camera_padding" \
    "$snapshot_input" \
    "$snapshot_output"
done < "$state_dir/snapshots.list"

python3 "$python_helper" write-manifest \
  --artifact-dir "$artifact_dir" \
  --main-kcl "$MAIN_KCL" \
  --parameters-kcl "$PARAMETERS_KCL" \
  --zoo-version "$zoo_version" \
  --host "$host" \
  --parameters-json "$parameters_json"
