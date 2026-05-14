#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_helper="${KCL_ARTIFACTS_PY:-${script_dir}/kcl_artifacts.py}"
repo_root="$(pwd)"
artifact_dir="${repo_root}/kcl-artifacts"
parameters_json="${KCL_PARAMETERS_JSON:-}"
if [[ -z "$parameters_json" ]]; then
  parameters_json="{}"
fi
main_kcl_paths="${KCL_MAIN_KCL_PATHS:-}"
if [[ -z "$main_kcl_paths" ]]; then
  main_kcl_paths="[]"
fi
entrypoint="${KCL_ENTRYPOINT:-main.kcl}"
parameters_filename="${KCL_PARAMETERS_FILENAME:-parameters.kcl}"
host="${KCL_ZOO_HOST:-}"
snapshot_angle="${KCL_SNAPSHOT_ANGLE:-four-ways}"
snapshot_views="${KCL_SNAPSHOT_VIEWS:-iso,front,top,right-side}"
if [[ -z "$snapshot_views" ]]; then
  snapshot_views="iso,front,top,right-side"
fi
camera_style="${KCL_CAMERA_STYLE:-ortho}"
camera_padding="${KCL_CAMERA_PADDING:-0.1}"
zoo_attempts="${KCL_ZOO_ATTEMPTS:-4}"
zoo_retry_delay="${KCL_ZOO_RETRY_DELAY:-10}"
zoo_parallelism="${KCL_ZOO_PARALLELISM:-4}"
if ! [[ "$zoo_attempts" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: KCL_ZOO_ATTEMPTS must be a positive integer, got ${zoo_attempts}" >&2
  exit 1
fi
if ! [[ "$zoo_retry_delay" =~ ^[0-9]+$ ]]; then
  echo "error: KCL_ZOO_RETRY_DELAY must be a non-negative integer, got ${zoo_retry_delay}" >&2
  exit 1
fi
if ! [[ "$zoo_parallelism" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: KCL_ZOO_PARALLELISM must be a positive integer, got ${zoo_parallelism}" >&2
  exit 1
fi

tmp_parent="$(mktemp -d)"
trap 'rm -rf "$tmp_parent"' EXIT
workspace="${tmp_parent}/repo"
state_dir="${tmp_parent}/state"
mkdir -p "$workspace" "$state_dir"
zoo_semaphore_fifo="$state_dir/zoo-semaphore"
mkfifo "$zoo_semaphore_fifo"
exec {zoo_semaphore_fd}<>"$zoo_semaphore_fifo"
rm -f "$zoo_semaphore_fifo"
for ((zoo_slot = 0; zoo_slot < zoo_parallelism; zoo_slot += 1)); do
  printf 'slot\n' >&"$zoo_semaphore_fd"
done

zero_sha() {
  [[ "$1" =~ ^0+$ ]]
}

git_commit_exists() {
  git -C "$repo_root" cat-file -e "${1}^{commit}" >/dev/null 2>&1
}

ensure_git_commit() {
  local commit="$1"
  if git_commit_exists "$commit"; then
    return 0
  fi
  git -C "$repo_root" fetch --no-tags --depth=100 origin "$commit" >/dev/null 2>&1 || true
  git_commit_exists "$commit"
}

write_changed_files() {
  local output="$1"
  : > "$output"

  if ! command -v git >/dev/null 2>&1; then
    echo "git is not available; no changed KCL assemblies can be selected" >&2
    return 0
  fi
  if ! git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "not in a git worktree; no changed KCL assemblies can be selected" >&2
    return 0
  fi

  local head="${CI_COMMIT_SHA:-HEAD}"
  local base=""
  if [[ -n "${CI_MERGE_REQUEST_DIFF_BASE_SHA:-}" ]] && ! zero_sha "$CI_MERGE_REQUEST_DIFF_BASE_SHA"; then
    base="$CI_MERGE_REQUEST_DIFF_BASE_SHA"
  elif [[ -n "${CI_COMMIT_BEFORE_SHA:-}" ]] && ! zero_sha "$CI_COMMIT_BEFORE_SHA"; then
    base="$CI_COMMIT_BEFORE_SHA"
  fi

  if [[ -n "$base" ]] && ensure_git_commit "$base"; then
    if git -C "$repo_root" diff --name-only --diff-filter=ACMRTD "$base" "$head" > "$output"; then
      return 0
    fi
  fi

  if git -C "$repo_root" rev-parse --verify -q "${head}^{commit}" >/dev/null && \
    git -C "$repo_root" rev-parse --verify -q "${head}^" >/dev/null; then
    git -C "$repo_root" diff-tree --no-commit-id --name-only -r "$head" > "$output"
    return 0
  fi

  git -C "$repo_root" diff --name-only --diff-filter=ACMRTD HEAD -- > "$output" || true
  git -C "$repo_root" diff --name-only --diff-filter=ACMRTD --cached >> "$output" || true
  sort -u -o "$output" "$output"
}

changed_files_args=()
if [[ "$main_kcl_paths" == "[]" ]]; then
  write_changed_files "$state_dir/changed-files.list"
  changed_files_args=(--changed-files-file "$state_dir/changed-files.list")
fi

tar \
  --exclude='./.git' \
  --exclude='./.gitlab-kcl-actions' \
  --exclude='./.kcl-tools' \
  --exclude='./kcl-artifacts' \
  -cf - . | tar -C "$workspace" -xf -
rm -rf "$artifact_dir"
mkdir -p "$artifact_dir/assemblies" "$artifact_dir/snapshots" "$artifact_dir/source"

cd "$workspace"

python3 "$python_helper" project-info \
  --repo-root "$workspace" \
  --assemblies-out "$state_dir/assemblies.tsv" \
  --snapshots-out "$state_dir/snapshots.list" \
  --main-kcl-paths "$main_kcl_paths" \
  --entrypoint "$entrypoint" \
  --parameters-filename "$parameters_filename" \
  "${changed_files_args[@]}"

if [[ ! -s "$state_dir/assemblies.tsv" ]]; then
  echo "No changed KCL assembly directories found; nothing to do."
  exit 0
fi

python3 "$python_helper" apply-project-parameters \
  --repo-root "$workspace" \
  --assemblies-file "$state_dir/assemblies.tsv" \
  --overrides-json "$parameters_json"

: "${ZOO_API_TOKEN:?ZOO_API_TOKEN is required for Zoo CLI artifact generation}"

zoo_cmd=(zoo)
if [[ -n "$host" ]]; then
  zoo_cmd+=(--host "$host")
fi

zoo_version="$(zoo version)"

with_zoo_slot() {
  local token
  local status=0

  if ! read -r -u "$zoo_semaphore_fd" token; then
    echo "error: failed to acquire Zoo command slot" >&2
    return 1
  fi

  set +e
  "$@"
  status="$?"
  set -e

  printf 'slot\n' >&"$zoo_semaphore_fd"
  return "$status"
}

run_zoo() {
  local attempt=1
  local status=0
  while true; do
    if with_zoo_slot "$@"; then
      return 0
    else
      status="$?"
    fi
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
  local tmp
  local attempt=1
  local status=0

  while true; do
    tmp="$(mktemp "${state_dir}/$(basename "$destination").XXXXXX.tmp")"
    if with_zoo_slot "$@" > "$tmp"; then
      mv "$tmp" "$destination"
      return 0
    else
      status="$?"
    fi
    rm -f "$tmp"
    if [ "$attempt" -ge "$zoo_attempts" ]; then
      return "$status"
    fi
    echo >&2 "Zoo command failed with status ${status}; retrying (${attempt}/${zoo_attempts})..."
    sleep "$zoo_retry_delay"
    attempt=$((attempt + 1))
  done
}

background_pids=()
background_names=()

finish_background_job() {
  local pid="${background_pids[0]}"
  local name="${background_names[0]}"
  local status=0
  local remaining_pid

  background_pids=("${background_pids[@]:1}")
  background_names=("${background_names[@]:1}")

  set +e
  wait "$pid"
  status="$?"
  set -e
  if [[ "$status" -eq 0 ]]; then
    return 0
  fi

  echo "error: background task failed with status ${status}: ${name}" >&2
  for remaining_pid in "${background_pids[@]}"; do
    kill "$remaining_pid" 2>/dev/null || true
  done
  for remaining_pid in "${background_pids[@]}"; do
    wait "$remaining_pid" 2>/dev/null || true
  done
  exit "$status"
}

run_background() {
  local name="$1"
  shift

  "$@" &
  background_pids+=("$!")
  background_names+=("$name")

  if [[ "${#background_pids[@]}" -ge "$zoo_parallelism" ]]; then
    finish_background_job
  fi
}

wait_for_background_jobs() {
  while [[ "${#background_pids[@]}" -gt 0 ]]; do
    finish_background_job
  done
}

snapshot_view_slug() {
  case "$1" in
    iso)
      printf '%s\n' "isometric"
      ;;
    right-side)
      printf '%s\n' "right"
      ;;
    four-ways)
      printf '%s\n' "four-ways"
      ;;
    *)
      printf '%s\n' "$1" | tr -cs 'A-Za-z0-9._-' '-' | sed 's/^-//;s/-$//'
      ;;
  esac
}

export_one() {
  local format="$1"
  local extension="$2"
  local main_kcl="$3"
  local export_dir="$4"
  local destination="$5"
  local exported_count=0
  local exported_file=""
  local candidate

  mkdir -p "$export_dir"
  run_zoo "${zoo_cmd[@]}" kcl export \
    --deterministic \
    --output-format "$format" \
    "$main_kcl" \
    "$export_dir"

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

write_analysis() {
  local destination="$1"
  local main_kcl="$2"
  local center_of_mass_output_unit="$3"

  write_zoo_output "$destination" \
    "${zoo_cmd[@]}" kcl analyze \
    --format json \
    --material-density "$MATERIAL_DENSITY" \
    --material-density-unit "$MATERIAL_DENSITY_UNIT" \
    --mass-output-unit "$MASS_OUTPUT_UNIT" \
    --volume-output-unit "$VOLUME_OUTPUT_UNIT" \
    --density-output-unit "$DENSITY_OUTPUT_UNIT" \
    --surface-area-output-unit "$SURFACE_AREA_OUTPUT_UNIT" \
    --center-of-mass-output-unit "$center_of_mass_output_unit" \
    "$main_kcl"
}

process_assembly() {
  local assembly_index="$1"
  local assembly_id="$2"
  local main_kcl="$3"
  local metadata_json="$4"
  local assembly_dir="$artifact_dir/assemblies/$assembly_id"
  local metadata_env
  local analysis_file
  local bounding_box_analysis_file

  mkdir -p "$assembly_dir"

  metadata_env="${state_dir}/metadata-${assembly_index}.env"
  python3 "$python_helper" metadata-env \
    --metadata-file "$metadata_json" \
    --env-out "$metadata_env"

  # shellcheck disable=SC1090
  source "$metadata_env"

  run_zoo "${zoo_cmd[@]}" kcl lint "$main_kcl"

  analysis_file="$assembly_dir/analysis.json"
  write_analysis "$analysis_file" "$main_kcl" "$CENTER_OF_MASS_OUTPUT_UNIT"

  local step_pid
  local gltf_pid
  local step_status=0
  local gltf_status=0

  export_one \
    step \
    step \
    "$main_kcl" \
    "$state_dir/export-step-${assembly_index}" \
    "$assembly_dir/model.step" &
  step_pid="$!"

  export_one \
    gltf \
    gltf \
    "$main_kcl" \
    "$state_dir/export-gltf-${assembly_index}" \
    "$assembly_dir/model.gltf" &
  gltf_pid="$!"

  set +e
  wait "$step_pid"
  step_status="$?"
  wait "$gltf_pid"
  gltf_status="$?"
  set -e

  if [[ "$step_status" -ne 0 ]]; then
    echo "error: STEP export failed for ${main_kcl} with status ${step_status}" >&2
  fi
  if [[ "$gltf_status" -ne 0 ]]; then
    echo "error: glTF export failed for ${main_kcl} with status ${gltf_status}" >&2
  fi
  if [[ "$step_status" -ne 0 ]]; then
    return "$step_status"
  fi
  if [[ "$gltf_status" -ne 0 ]]; then
    return "$gltf_status"
  fi

  bounding_box_analysis_file="$analysis_file"
  if [[ "$BOUNDING_BOX_OUTPUT_UNIT" != "$CENTER_OF_MASS_OUTPUT_UNIT" ]]; then
    bounding_box_analysis_file="${state_dir}/bounding-box-analysis-${assembly_index}.json"
    write_analysis "$bounding_box_analysis_file" "$main_kcl" "$BOUNDING_BOX_OUTPUT_UNIT"
  fi
  python3 "$python_helper" bounding-box-json \
    --analysis-file "$bounding_box_analysis_file" \
    --output-file "$assembly_dir/bounding-box.json" \
    --output-unit "$BOUNDING_BOX_OUTPUT_UNIT"

  run_zoo "${zoo_cmd[@]}" kcl snapshot \
    --output-format png \
    --angle "$snapshot_angle" \
    --camera-style "$camera_style" \
    --camera-padding "$camera_padding" \
    "$main_kcl" \
    "$assembly_dir/snapshot.png"
}

assembly_index=0
while IFS=$'\t' read -r assembly_id main_kcl _parameters_kcl metadata_json; do
  [ -n "$assembly_id" ] || continue
  assembly_index=$((assembly_index + 1))
  run_background \
    "assembly ${assembly_id}" \
    process_assembly "$assembly_index" "$assembly_id" "$main_kcl" "$metadata_json"
done < "$state_dir/assemblies.tsv"
wait_for_background_jobs

write_snapshot_view() {
  local snapshot_input="$1"
  local snapshot_view_angle="$2"
  local snapshot_base="$artifact_dir/snapshots/${snapshot_input%.kcl}"
  local snapshot_slug
  local snapshot_output

  snapshot_slug="$(snapshot_view_slug "$snapshot_view_angle")"
  snapshot_output="${snapshot_base}.${snapshot_slug}.png"
  mkdir -p "$(dirname "$snapshot_output")"
  run_zoo "${zoo_cmd[@]}" kcl snapshot \
    --output-format png \
    --angle "$snapshot_view_angle" \
    --camera-style "$camera_style" \
    --camera-padding "$camera_padding" \
    "$snapshot_input" \
    "$snapshot_output"
}

IFS=',' read -r -a snapshot_view_angles <<< "$snapshot_views"
while IFS= read -r snapshot_input; do
  [[ -n "$snapshot_input" ]] || continue
  for snapshot_view_angle in "${snapshot_view_angles[@]}"; do
    snapshot_view_angle="${snapshot_view_angle//[[:space:]]/}"
    [[ -n "$snapshot_view_angle" ]] || continue
    run_background \
      "snapshot ${snapshot_input} ${snapshot_view_angle}" \
      write_snapshot_view "$snapshot_input" "$snapshot_view_angle"
  done
done < "$state_dir/snapshots.list"
wait_for_background_jobs

python3 "$python_helper" write-source-files \
  --repo-root "$workspace" \
  --snapshots-file "$state_dir/snapshots.list" \
  --assemblies-file "$state_dir/assemblies.tsv" \
  --output-dir "$artifact_dir/source"

python3 "$python_helper" write-manifest \
  --artifact-dir "$artifact_dir" \
  --assemblies-file "$state_dir/assemblies.tsv" \
  --zoo-version "$zoo_version" \
  --host "$host" \
  --parameters-json "$parameters_json"
