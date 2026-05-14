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

Limit the workflow to one or more assembly entrypoints when the repo has
multiple KCL entrypoint files:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      main_kcl_paths: "assembly-2/main.kcl"
      parameters_json: '{"width": 24}'
```

`main_kcl_paths` accepts a bare relative path, a JSON string, or a JSON array of
relative paths to `.kcl` entrypoint files. If it is empty, the workflow detects
changed files with Git and processes only the assembly directories that contain
or own those changes. If no changed file belongs to a directory with a matching
entrypoint, the job exits successfully without producing artifacts.

Use `entrypoint` when a repo's KCL project uses a filename other than
`main.kcl`:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      entrypoint: assembly.kcl
```

`entrypoint` defaults to `main.kcl`. A bare filename discovers every matching
file in the repo; a repo-relative path targets that one entrypoint when
`main_kcl_paths` is empty.

Use `parameters_filename` when each entrypoint's sibling parameter file uses a
name other than `parameters.kcl`:

```yaml
include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      entrypoint: assembly.kcl
      parameters_filename: inputs.kcl
```

`parameters_filename` defaults to `parameters.kcl`. It must be a bare `.kcl`
filename and is resolved next to every selected entrypoint.

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
      description: "Optional JSON string or array of KCL entrypoint paths to process. Empty auto-selects changed assemblies."
    kcl_parameters_filename:
      type: string
      default: parameters.kcl
      description: "Sibling KCL parameters filename next to each selected entrypoint."
---

include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      main_kcl_paths: '$[[ inputs.kcl_main_kcl_paths ]]'
      parameters_filename: '$[[ inputs.kcl_parameters_filename ]]'
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

- one or more KCL entrypoint files. By default these are named `main.kcl`, but
  the `entrypoint` input can point at a different filename or path.
- a sibling parameters file next to every entrypoint file. By default this is
  named `parameters.kcl`, but `parameters_filename` can point at another bare
  `.kcl` filename.
- a sibling `metadata.json` next to every entrypoint file.

Missing entrypoint files, missing sibling parameters files, duplicate assembly
IDs, and missing or invalid sibling `metadata.json` files are hard failures.

#### Parameters file

The `parameters_json` input replaces existing exported top-level assignments in
each discovered sibling parameters file. It does not add new parameters and it
does not replace non-exported local values. The default filename is
`parameters.kcl`.

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

When overrides are supplied, the artifact bundle also includes
`kcl-artifacts/parameters.json` and records those values in `manifest.json` so
downstream upload jobs can tag the snapshot with labels like `width=24`.

When there are multiple assemblies, one JSON object is applied across all
selected parameters files. If `main_kcl_paths` is empty, all assemblies are
selected. If a key is exported by more than one selected assembly, all matching
files get the new value. If a key is not exported by any selected assembly, the
workflow fails.

This matches the multi-file KCL sample style, where `parameters.kcl` exports
top-level parameters and model files use `import * from "parameters.kcl"`.

#### `metadata.json`

`metadata.json` lives next to each entrypoint file and provides the physics arguments
for that entrypoint's `zoo kcl analyze` and derived bounding-box artifact. A
root `main.kcl` uses the root `metadata.json`; `assembly-2/main.kcl` uses
`assembly-2/metadata.json`. The workflow does not fall back from a nested
assembly to the root metadata file.

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

All fields are required. `material_density` must be a finite number. The unit
fields must be non-empty strings. The workflow does not guess density, units,
or material data.

#### Physics JSON

Each assembly gets `analysis.json` from `zoo kcl analyze --format json`. The
numeric values depend on the model and the units in that assembly's sibling
`metadata.json`; the shape looks like:

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

The workflow also writes `bounding-box.json` as a smaller machine-friendly
artifact:

```json
{
  "center": { "x": 0.0, "y": 0.0, "z": 4.0 },
  "dimensions": { "x": 20.0, "y": 12.0, "z": 8.0 },
  "output_unit": "mm"
}
```

`analysis.json` is the raw Zoo CLI analysis JSON. `bounding-box.json` is
extracted from Zoo analysis JSON so consumers do not have to parse the CLI's
human table output from `zoo kcl bounding-box`.

#### Artifacts

The workflow always writes to `kcl-artifacts/`:

```text
kcl-artifacts/
  assemblies/
    root/
      model.step
      model.gltf
      analysis.json
      bounding-box.json
      snapshot.png
    assembly-2/
      model.step
      model.gltf
      analysis.json
      bounding-box.json
      snapshot.png
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

Each entrypoint file gets STEP, glTF, physics analysis, bounding box, and a
four-ways assembly snapshot preview under
`kcl-artifacts/assemblies/<assembly-id>/`. The root entrypoint uses `root` as
its assembly ID. Nested entrypoints use their directory path relative to the
repo, so `assembly-2/main.kcl` writes under `assemblies/assembly-2/`.

Per-file snapshots are generated for every `.kcl` file except the configured
parameters filename, preserving the source path under `kcl-artifacts/snapshots/`
and adding a view suffix. The default scheme is
`<source-without-.kcl>.<view>.png`, with `isometric`, `front`, `top`, and
`right` views. The source `.kcl` files used for those snapshots are copied under
`kcl-artifacts/source/` with the same relative paths. Each selected assembly's
sibling parameters file and `metadata.json` are copied there too. Assembly
artifacts, source copies, and per-file snapshots are limited to the selected
assembly directories, whether they were selected by `main_kcl_paths` or by
changed-file detection.

Override `snapshot_views` with a comma-separated Zoo snapshot angle list to
change the per-file views. The built-in default maps `iso` to `isometric` and
`right-side` to `right` in filenames.

The artifact job runs assembly generation and per-file snapshot generation with
bounded concurrency. Override `parallelism` to tune the maximum number of
concurrent Zoo CLI artifact commands. The default is `4`; set it to `1` to force
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
