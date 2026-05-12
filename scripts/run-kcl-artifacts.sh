#!/usr/bin/env bash
set -Eeuo pipefail

: "${ZOO_API_TOKEN:?ZOO_API_TOKEN is required for Zoo CLI artifact generation}"

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
zoo_attempts="${KCL_ZOO_ATTEMPTS:-3}"
zoo_retry_delay="${KCL_ZOO_RETRY_DELAY:-5}"

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
mkdir -p "$artifact_dir/assemblies" "$artifact_dir/snapshots"

cd "$workspace"

python3 "$python_helper" project-info \
  --repo-root "$workspace" \
  --assemblies-out "$state_dir/assemblies.tsv" \
  --snapshots-out "$state_dir/snapshots.list"

while IFS=$'\t' read -r assembly_id main_kcl parameters_kcl; do
  [ -n "$assembly_id" ] || continue
  python3 "$python_helper" apply-parameters \
    --parameters-file "$parameters_kcl" \
    --overrides-json "$parameters_json"
done < "$state_dir/assemblies.tsv"

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

run_zoo() {
  local attempt=1
  while true; do
    if "$@"; then
      return 0
    fi
    local status="$?"
    if [ "$attempt" -ge "$zoo_attempts" ]; then
      return "$status"
    fi
    echo >&2 "Zoo command failed with status ${status}; retrying (${attempt}/${zoo_attempts})..."
    sleep "$zoo_retry_delay"
    attempt=$((attempt + 1))
  done
}

write_zoo_output() {
  local destination="$1"
  shift
  local tmp="${state_dir}/$(basename "$destination").tmp"
  local attempt=1

  while true; do
    rm -f "$tmp"
    if "$@" > "$tmp"; then
      mv "$tmp" "$destination"
      return 0
    fi
    local status="$?"
    rm -f "$tmp"
    if [ "$attempt" -ge "$zoo_attempts" ]; then
      return "$status"
    fi
    echo >&2 "Zoo command failed with status ${status}; retrying (${attempt}/${zoo_attempts})..."
    sleep "$zoo_retry_delay"
    attempt=$((attempt + 1))
  done
}

export_one() {
  local format="$1"
  local extension="$2"
  local main_kcl="$3"
  local export_dir="$4"
  local destination="$5"

  mkdir -p "$export_dir"
  run_zoo "${zoo_cmd[@]}" kcl export \
    --deterministic \
    --output-format "$format" \
    "$main_kcl" \
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

assembly_index=0
while IFS=$'\t' read -r assembly_id main_kcl parameters_kcl; do
  [ -n "$assembly_id" ] || continue
  assembly_index=$((assembly_index + 1))
  assembly_dir="$artifact_dir/assemblies/$assembly_id"
  mkdir -p "$assembly_dir"

  run_zoo "${zoo_cmd[@]}" kcl lint "$main_kcl"

  write_zoo_output "$assembly_dir/analysis.json" \
    "${zoo_cmd[@]}" kcl analyze \
    --format json \
    --material-density "$MATERIAL_DENSITY" \
    --material-density-unit "$MATERIAL_DENSITY_UNIT" \
    --mass-output-unit "$MASS_OUTPUT_UNIT" \
    --volume-output-unit "$VOLUME_OUTPUT_UNIT" \
    --density-output-unit "$DENSITY_OUTPUT_UNIT" \
    --surface-area-output-unit "$SURFACE_AREA_OUTPUT_UNIT" \
    --center-of-mass-output-unit "$CENTER_OF_MASS_OUTPUT_UNIT" \
    "$main_kcl"

  export_one step step "$main_kcl" "$state_dir/export-step-${assembly_index}" "$assembly_dir/model.step"
  export_one gltf gltf "$main_kcl" "$state_dir/export-gltf-${assembly_index}" "$assembly_dir/model.gltf"

  write_zoo_output "$assembly_dir/bounding-box.json" \
    "${zoo_cmd[@]}" kcl bounding-box \
    --format json \
    --output-unit "$BOUNDING_BOX_OUTPUT_UNIT" \
    "$main_kcl"

  run_zoo "${zoo_cmd[@]}" kcl snapshot \
    --output-format png \
    --angle "$snapshot_angle" \
    --camera-style "$camera_style" \
    --camera-padding "$camera_padding" \
    "$main_kcl" \
    "$assembly_dir/snapshot.png"
done < "$state_dir/assemblies.tsv"

while IFS= read -r snapshot_input; do
  [[ -n "$snapshot_input" ]] || continue
  snapshot_output="$artifact_dir/snapshots/${snapshot_input%.kcl}.png"
  mkdir -p "$(dirname "$snapshot_output")"
  run_zoo "${zoo_cmd[@]}" kcl snapshot \
    --output-format png \
    --angle "$snapshot_angle" \
    --camera-style "$camera_style" \
    --camera-padding "$camera_padding" \
    "$snapshot_input" \
    "$snapshot_output"
done < "$state_dir/snapshots.list"

python3 "$python_helper" write-manifest \
  --artifact-dir "$artifact_dir" \
  --assemblies-file "$state_dir/assemblies.tsv" \
  --zoo-version "$zoo_version" \
  --host "$host" \
  --parameters-json "$parameters_json"
