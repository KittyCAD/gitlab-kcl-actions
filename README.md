# gitlab-kcl-actions

Reusable GitLab CI/CD components for KCL and Zoo workflows. The templates are
self-contained because GitLab components only release YAML to consumers, so each
component writes the helper scripts it needs into the job workspace before
running.

The components currently cover installing the Zoo CLI, generating KCL artifacts
with the Zoo CLI, and downloading org dataset conversion outputs with the
KittyCAD Python SDK.

## Components

All components accept `stage` and `job-name`. Single-job components use `image`
for their container. Components with separate installer and artifact jobs use
`install_image` and `artifacts_image`.

### `install-zoo-cli`

Use this when a GitLab pipeline only needs the Zoo CLI installed:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/install-zoo-cli@1.0.0
```

The component installs the latest Zoo CLI by default, using the same Linux
release asset and SHA256 check as
[`KittyCAD/action-install-cli`](https://github.com/KittyCAD/action-install-cli).
It publishes `.kcl-tools/bin/zoo` as a job artifact so later jobs can consume it.

Pin a version if needed:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/install-zoo-cli@1.0.0
    inputs:
      zoo_version: "v0.2.165"
```

Use a mirrored image when your runners cannot pull Docker Hub directly:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/install-zoo-cli@1.0.0
    inputs:
      image: registry.example.com/mirrors/debian:bookworm-slim
```

The install job still expects a Debian-compatible image because it installs
`ca-certificates`, `curl`, and `coreutils` with `apt-get`.

Use the installed binary in a later job:

```yaml
use-zoo:
  stage: test
  needs:
    - job: install-zoo-cli
      artifacts: true
  script:
    - export PATH="$CI_PROJECT_DIR/.kcl-tools/bin:$PATH"
    - zoo version
```

### `kcl-artifacts`

This component installs Zoo itself. You do not need to include
`install-zoo-cli` separately for the artifact workflow. It always creates both
jobs: `$[[ inputs.job-name ]]-install-zoo-cli` installs the CLI and
`$[[ inputs.job-name ]]` generates artifacts with a `needs` dependency on that
install job.

Include the component from GitLab:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
```

Pass parameter overrides as JSON:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      parameters_json: '{"width": 24, "depth": 6}'
```

By default the workflow discovers **every** `.kcl` file in the repository and
produces a STEP, glTF, snapshot, and physics artifacts for each one. Folders are
not treated as projects: each `.kcl` file is its own assembly, identified by its
repo-relative path without the `.kcl` extension (for example `cube`,
`assembly-1/part1`, `chair/leg`).

Limit the workflow to one or more specific `.kcl` files:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      main_kcl_paths: "assembly-2/part.kcl"
      parameters_json: '{"width": 24}'
```

`main_kcl_paths` accepts a bare relative path, a JSON string, or a JSON array of
relative paths to `.kcl` files. If it is empty, the workflow detects changed
files with Git and processes only the affected `.kcl` files (see Changed-file
selection below). If nothing relevant changed, the job exits successfully
without producing artifacts.

Use `parameters_filename` when a repo's shared parameter file uses a name other
than `parameters.kcl`:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      parameters_filename: inputs.kcl
```

`parameters_filename` defaults to `parameters.kcl` and must be a bare `.kcl`
filename. A file with that name is treated as a shared parameters file rather
than an assembly: it is excluded from STEP/glTF output, and it applies to every
other `.kcl` file in the same folder.

Use `metadata_path` when the metadata file is not the default sibling
`metadata.json`:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      metadata_path: config/kcl-metadata.json
```

`metadata_path` defaults to `metadata.json`. A bare filename is looked up next to
each `.kcl` file and shared by every `.kcl` file in that folder. A repo-relative
path (containing `/`) makes every selected `.kcl` file use that one shared
metadata JSON file.

GitLab evaluates `spec:inputs` when the pipeline is created. Per GitLab's
input limits, the string inside an interpolation block must stay under 1 KB, so
keep `parameters_json` to small sweep-style overrides.

Expose that JSON as a pipeline input if you want to trigger parameter sweeps
with `curl`:

```yaml
spec:
  inputs:
    kcl_parameters_json:
      type: string
      default: "{}"
      description: "JSON overrides for exported values in sibling parameters.kcl files."
    kcl_main_kcl_paths:
      type: string
      default: "[]"
      description: "Optional JSON string or array of .kcl file paths to process. Empty auto-selects changed .kcl files."
    kcl_parameters_filename:
      type: string
      default: parameters.kcl
      description: "Shared KCL parameters filename applied to every .kcl file in the same folder."
    kcl_metadata_path:
      type: string
      default: metadata.json
      description: "Metadata JSON filename next to each .kcl file, or one repo-relative metadata JSON path."
---

include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      main_kcl_paths: '$[[ inputs.kcl_main_kcl_paths ]]'
      parameters_filename: '$[[ inputs.kcl_parameters_filename ]]'
      metadata_path: '$[[ inputs.kcl_metadata_path ]]'
      parameters_json: '$[[ inputs.kcl_parameters_json ]]'
```

Then trigger the pipeline with GitLab's pipeline trigger API:

```sh
curl --fail --request POST \
  --form "token=$GITLAB_TRIGGER_TOKEN" \
  --form "ref=main" \
  --form 'inputs[kcl_main_kcl_paths]=["assembly-2/main.kcl"]' \
  --form 'inputs[kcl_parameters_json]={"width":24,"depth":6}' \
  "https://gitlab.example.com/api/v4/projects/123456/trigger/pipeline"
```

Use your GitLab host and project ID, and create `GITLAB_TRIGGER_TOKEN` from the
project's pipeline trigger settings. GitLab validates the input before the
pipeline is created.

Use a non-default Zoo API host:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      host: "https://api.example.com"
```

If `host` is empty, the workflow does not pass `--host` and the Zoo CLI uses
its default host/configuration. If `host` is set, every `zoo kcl ...` command
receives that host.

Use mirrored images when your runners cannot pull Docker Hub directly:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      install_image: registry.example.com/mirrors/debian:bookworm-slim
      artifacts_image: registry.example.com/mirrors/python:3.12-slim
```

`install_image` must be Debian-compatible. `artifacts_image` must provide
Python 3.12 and be Debian-compatible because the artifact job also installs
small system packages with `apt-get`.

The job expects `ZOO_API_TOKEN` to be available in CI/CD variables when changed
assemblies are selected and artifacts need to be generated. If the default
changed-file detection finds no matching assembly, the job exits before using
the token.

#### Repository Contract

Consuming repositories must contain:

- one or more `.kcl` files anywhere in the tree. Every `.kcl` file is treated as
  its own assembly and gets its own STEP, glTF, snapshot, and physics artifacts.
- optionally, a shared parameters file named `parameters.kcl` (override the name
  with `parameters_filename`). A file with that name is not turned into an
  assembly; instead it provides parameter overrides for every `.kcl` file in the
  same folder.
- optionally, a metadata JSON file. By default this is sibling `metadata.json`,
  shared by every `.kcl` file in the same folder. `metadata_path` can point at
  another bare filename or one shared repo-relative `.json` path.

An empty repository (no `.kcl` files) is a hard failure when no selection or
changed-file list is supplied. Missing parameters files are ignored when
`parameters_json` is empty or `{}`. When overrides are supplied, missing
parameters files produce warnings, and the workflow fails if an override key is
not exported by any selected parameters file. Missing metadata files are
warnings; the workflow still writes STEP, glTF, and snapshot artifacts but skips
physics analysis and bounding-box JSON for that file. Invalid metadata JSON is
still a hard failure when the file exists.

#### Changed-file selection

When `main_kcl_paths` is empty, the workflow uses Git to find changed files and
selects:

- each changed `.kcl` file (its own assembly),
- every `.kcl` file in a folder whose `parameters.kcl` or sibling `metadata.json`
  changed, and
- every `.kcl` file when a shared repo-relative `metadata_path` changed.

Importing another file does not pull it in automatically; only the changed file
itself is rebuilt. List paths in `main_kcl_paths` to force a specific set.

#### Parameters file

The `parameters_json` input replaces existing exported top-level assignments in
each discovered `parameters.kcl` file. If `parameters_json` is empty or `{}`,
parameters files are optional and missing files are ignored. When overrides are
supplied, `.kcl` files without a folder parameters file are left alone unless
that leaves an override key with no matching export anywhere. It does not add new
parameters and it does not replace non-exported local values. The default
filename is `parameters.kcl`; override it with `parameters_filename`.

Example `parameters.kcl`:

```kcl
@settings(defaultLengthUnit = mm)

export width = 20
export height = 12
export depth = 8
```

Example consuming KCL:

```kcl
import * from "parameters.kcl"

assembly = startSketchOn(XY)
  |> rectangle(width = width, height = height, center = [0, 0])
  |> extrude(length = depth)
```

With:

```json
{"width": 24, "depth": 6}
```

the temporary workspace gets:

```kcl
export width = 24
export height = 12
export depth = 6
```

The repository checkout is not edited. Replacement values are JSON literals
rendered as KCL literals: numbers, strings, booleans, null as `none`, arrays,
and objects with identifier-shaped keys.

When overrides are supplied, the artifact bundle also includes an override JSON
file named after the resolved parameters file, for example
`kcl-artifacts/parameters.json`, `kcl-artifacts/inputs.json`, or
`kcl-artifacts/assembly-parameters.json`. That path is recorded in
`manifest.json` so downstream upload jobs can tag the snapshot with labels like
`width=24`.

When there are multiple assemblies, one JSON object is applied across all
selected parameters files. If `main_kcl_paths` is empty, all assemblies are
selected. If a key is exported by more than one selected assembly, all matching
files get the new value. If a key is not exported by any selected assembly, the
workflow fails.

This matches the multi-file KCL sample style, where `parameters.kcl` exports
top-level parameters and model files use `import * from "parameters.kcl"`.

#### Metadata JSON

The metadata JSON provides the physics arguments for each `.kcl` file's
`zoo kcl analyze` and derived bounding-box artifact. If no metadata file exists
for a file, the job warns and skips those physics artifacts for that file. By
default, `metadata.json` lives next to each `.kcl` file and is shared by every
`.kcl` file in that folder: files under `assembly-2/` use
`assembly-2/metadata.json`. Set `metadata_path` to a bare filename to use that
exact sibling filename, or to a repo-relative path to make every selected file
use one shared metadata file.

```json
{
  "material_density": 7850,
  "material_density_unit": "kg:m3",
  "mass_output_unit": "kg",
  "volume_output_unit": "cm3",
  "density_output_unit": "kg:m3",
  "surface_area_output_unit": "cm2",
  "center_of_mass_output_unit": "mm",
  "bounding_box_output_unit": "mm"
}
```

When the metadata file exists, all fields are required. `material_density` must
be a finite number. The unit fields must be non-empty strings. The workflow does
not guess density, units, or material data.

#### Physics JSON

Each `.kcl` file gets `<id>-analysis.json` from `zoo kcl analyze --format json`,
where `<id>` is the file's repo-relative path without `.kcl`. The numeric values
depend on the model and the units in that file's `metadata.json`; the shape
looks like:

```json
{
  "bounding_box": {
    "center": { "x": 0.0, "y": 0.0, "z": 4.0 },
    "dimensions": { "x": 20.0, "y": 12.0, "z": 8.0 }
  },
  "center_of_mass": {
    "center_of_mass": { "x": 0.0, "y": 4.0, "z": 0.0 },
    "output_unit": "mm"
  },
  "density": { "density": 7850.0, "output_unit": "kg:m3" },
  "mass": { "mass": 0.015072000949582314, "output_unit": "kg" },
  "surface_area": { "surface_area": 9.920000156853348, "output_unit": "cm2" },
  "volume": { "volume": 1.9200001209659, "output_unit": "cm3" }
}
```

The workflow also writes `<id>-bounding-box.json` as a smaller
machine-friendly artifact:

```json
{
  "center": { "x": 0.0, "y": 0.0, "z": 4.0 },
  "dimensions": { "x": 20.0, "y": 12.0, "z": 8.0 },
  "output_unit": "mm"
}
```

`<id>-analysis.json` is the raw Zoo CLI analysis JSON.
`<id>-bounding-box.json` is extracted from Zoo analysis JSON so
consumers do not have to parse the CLI's human table output from
`zoo kcl bounding-box`.

#### Artifacts

The workflow always writes to `kcl-artifacts/`:

```text
kcl-artifacts/
  assemblies/
    main.step
    main.gltf
    main-analysis.json
    main-bounding-box.json
    main-snapshot.png
    part.step
    part.gltf
    part-analysis.json
    part-bounding-box.json
    part-snapshot.png
    assembly-2/
      main.step
      main.gltf
      main-analysis.json
      main-bounding-box.json
      main-snapshot.png
      part.step
      part.gltf
      part-analysis.json
      part-bounding-box.json
      part-snapshot.png
  snapshots/
    main.isometric.png
    main.front.png
    main.top.png
    main.right.png
    part.isometric.png
    part.front.png
    part.top.png
    part.right.png
    assembly-2/
      main.isometric.png
      main.front.png
      main.top.png
      main.right.png
      part.isometric.png
      part.front.png
      part.top.png
      part.right.png
  source/
    main.kcl
    metadata.json
    part.kcl
    parameters.kcl
    assembly-2/
      main.kcl
      metadata.json
      part.kcl
      parameters.kcl
  manifest.json
```

Every `.kcl` file gets a STEP, glTF, and a four-ways assembly snapshot preview
under `kcl-artifacts/assemblies/`, named by the file's repo-relative path with
its extension swapped: `assembly-1/part1.kcl` writes
`assemblies/assembly-1/part1.step`, `assemblies/assembly-1/part1.gltf`,
`assemblies/assembly-1/part1-analysis.json`,
`assemblies/assembly-1/part1-bounding-box.json`, and
`assemblies/assembly-1/part1-snapshot.png`; a root file `cube.kcl` writes
`assemblies/cube.step`, and so on. The analysis and bounding-box files are only
present when metadata JSON was available for that file.

Per-file view snapshots are generated for every selected `.kcl` file (the
configured parameters filename is excluded), preserving the source path under
`kcl-artifacts/snapshots/` and adding a view suffix. The default scheme is
`<source-without-.kcl>.<view>.png`, with `isometric`, `front`, `top`, and
`right` views. The source `.kcl` files are copied under `kcl-artifacts/source/`
with the same relative paths, along with each selected file's folder parameters
file and metadata JSON when present.
Assembly artifacts, source copies, and per-file snapshots are limited to the
selected `.kcl` files, whether they were selected by `main_kcl_paths` or by
changed-file detection.

Override `snapshot_views` with a comma-separated Zoo snapshot angle list to
change the per-file views. The built-in default maps `iso` to `isometric` and
`right-side` to `right` in filenames.

The artifact job runs assembly generation and per-file snapshot generation with
bounded concurrency. Override `parallelism` to tune the maximum number of
concurrent Zoo CLI artifact commands. The default is `6`; set it to `1` to force
the old sequential behavior. Each Zoo CLI artifact command retries on failure;
override `zoo_attempts` and `zoo_retry_delay` to tune the retry count and delay.
The defaults are `4` attempts with a `10` second delay.

The workflow stops after producing artifacts. Uploading those artifacts is out
of scope and should happen in a later GitLab job.

### `dataset-conversions`

Use this to download successful converted KCL outputs and salon snapshot PNGs
from every org dataset using the KittyCAD Python SDK:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/dataset-conversions@1.0.0
```

By default, the job lists every dataset in the authenticated org and downloads
successful completed conversions into the current directory:

```text
Dataset Name/
  output/
    path/from/dataset.step/
      main.kcl
      0.png
      1.png
      README.md
```

Set `output_dir` if you want those files under a specific artifact directory:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/dataset-conversions@1.0.0
    inputs:
      output_dir: dataset-conversions
```

Narrow to one dataset if needed:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/dataset-conversions@1.0.0
    inputs:
      dataset_id: "00000000-0000-0000-0000-000000000000"
```

Override the API host the same way as the other components:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/dataset-conversions@1.0.0
    inputs:
      host: "https://api.example.com"
```

The component sets `ZOO_HOST` from that input. If `host` is empty, the SDK uses
its default host or an existing `ZOO_HOST` from the job environment.

Use a mirrored image when your runners cannot pull Docker Hub directly:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/dataset-conversions@1.0.0
    inputs:
      image: registry.example.com/mirrors/python:3.12-slim
```

`image` must provide Python 3.12.

Run it from a GitLab pipeline schedule by making a schedule-only pipeline config.
This example writes conversion outputs at the repository root and commits
top-level dataset `output/` directories back to the default branch:

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
    - when: never

stages:
  - scrape
  - commit

include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/dataset-conversions@1.0.0
    inputs:
      stage: scrape
      job-name: scrape-dataset-conversions
      host: "https://api.zoo.dev"
      output_dir: "."

commit-dataset-conversions:
  stage: commit
  image: alpine:3
  needs:
    - job: scrape-dataset-conversions
      artifacts: true
  resource_group: dataset-conversions-commit
  variables:
    GIT_DEPTH: "0"
  before_script:
    - apk add --no-cache git
  script:
    - git config --global --add safe.directory "$CI_PROJECT_DIR"
    - git config user.name "Dataset Conversions Bot"
    - git config user.email "dataset-conversions-bot@example.com"
    - git remote set-url origin "$CI_REPOSITORY_URL"
    - rm -rf .gitlab-kcl-actions
    - find . -mindepth 2 -maxdepth 2 -type d -name output -print0 > /tmp/dataset-output-dirs
    - |
      if [ ! -s /tmp/dataset-output-dirs ]; then
        echo "No dataset conversion output directories found"
        exit 0
      fi
    - xargs -0 git add -A -- < /tmp/dataset-output-dirs
    - |
      if git diff --cached --quiet; then
        echo "No dataset conversion changes to commit"
        exit 0
      fi
    - |
      git commit -m "chore: update dataset conversions [skip ci]"
    - git pull --rebase origin "$CI_DEFAULT_BRANCH"
    - git push -o ci.skip origin "HEAD:$CI_DEFAULT_BRANCH"
```

Create the schedule in GitLab's pipeline schedules UI with whatever cron cadence
you want, and set `ZOO_API_TOKEN` as a protected/masked CI/CD variable. The job
fails if the token is not present. To let the commit job push with
`CI_REPOSITORY_URL`, enable job-token repository pushes in the project CI/CD
settings, and make sure the schedule owner can push to the default branch. If
you use a different commit-job image, make sure it includes `git` or install it
with that image's package manager before running the `git` commands.

## Local Development

Use `uv` and `just` for local development:

```sh
just sync
just lint
just unit-test
just generated
```

`just check` runs lint, unit tests, shell syntax, and generated-template checks.
`just test` runs the full Python test discovery, including live API tests.
`just format` runs Ruff's auto-fixes and formatter.

Render the self-contained GitLab component after editing scripts:

```sh
uv run python scripts/render_component.py
```

The real flow tests require `ZOO_API_TOKEN`. The KCL artifact workflow test also
requires a `zoo` binary on `PATH`. GitHub CI installs the latest Zoo CLI and
runs `just kcl-artifact-workflow` on every push and pull request. If the secret
is missing, CI fails.
