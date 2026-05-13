#!/usr/bin/env python3
"""Render the self-contained GitLab component from local scripts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
KCL_TARGET = ROOT / "templates" / "kcl-artifacts.yml"
INSTALL_TARGET = ROOT / "templates" / "install-zoo-cli.yml"
DATASET_CONVERSIONS_TARGET = ROOT / "templates" / "dataset-conversions.yml"
SCRIPT_FILES = {
    "install-zoo-cli.sh": ROOT / "scripts" / "install-zoo-cli.sh",
    "kcl_artifacts.py": ROOT / "scripts" / "kcl_artifacts.py",
    "run-kcl-artifacts.sh": ROOT / "scripts" / "run-kcl-artifacts.sh",
}
KCL_ARTIFACT_SCRIPT_FILES = {
    "kcl_artifacts.py": ROOT / "scripts" / "kcl_artifacts.py",
    "run-kcl-artifacts.sh": ROOT / "scripts" / "run-kcl-artifacts.sh",
}
DATASET_CONVERSIONS_SCRIPT_FILES = {
    "dataset_conversions.py": ROOT / "scripts" / "dataset_conversions.py",
}


def indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "".join(prefix + line if line.strip() else line for line in text.splitlines(True))


def heredoc_step(filename: str, content: str) -> str:
    marker = f"KCL_ARTIFACTS_{filename.upper().replace('.', '_').replace('-', '_')}"
    return (
        "    - |\n"
        f"      cat > .gitlab-kcl-actions/{filename} <<'{marker}'\n"
        f"{indent(content.rstrip() + chr(10), 6)}"
        f"      {marker}\n"
    )


def render_install() -> str:
    installer = (ROOT / "scripts" / "install-zoo-cli.sh").read_text(encoding="utf-8")
    body = """spec:
  inputs:
    stage:
      default: test
      description: "Pipeline stage for the Zoo CLI install job."
    job-name:
      default: install-zoo-cli
      description: "Job name to use after the component merges into the consuming pipeline."
    zoo_version:
      default: ""
      description: "Optional Zoo CLI release, like v0.2.165. Empty installs the latest release."
    image:
      default: debian:bookworm-slim
      description: "Container image for the Zoo CLI install job. Override with a Debian-compatible mirror if your runners cannot pull Docker Hub images."
---
"$[[ inputs.job-name ]]":
  stage: $[[ inputs.stage ]]
  image: $[[ inputs.image ]]
  before_script:
    - apt-get update
    - apt-get install -y --no-install-recommends ca-certificates curl coreutils
    - rm -rf /var/lib/apt/lists/*
    - mkdir -p .gitlab-kcl-actions .kcl-tools/bin
"""
    body += heredoc_step("install-zoo-cli.sh", installer)
    body += """    - chmod +x .gitlab-kcl-actions/install-zoo-cli.sh
  script:
    - .gitlab-kcl-actions/install-zoo-cli.sh '$[[ inputs.zoo_version ]]' "$CI_PROJECT_DIR/.kcl-tools/bin"
  artifacts:
    paths:
      - .kcl-tools/bin/zoo
"""
    return body


def render_kcl_artifacts() -> str:
    installer = (ROOT / "scripts" / "install-zoo-cli.sh").read_text(encoding="utf-8")
    scripts = {
        name: path.read_text(encoding="utf-8")
        for name, path in KCL_ARTIFACT_SCRIPT_FILES.items()
    }
    body = """spec:
  inputs:
    stage:
      default: test
      description: "Pipeline stage for both KCL artifact jobs."
    job-name:
      default: kcl-artifacts
      description: "Job name to use after the component merges into the consuming pipeline."
    parameters_json:
      default: "{}"
      description: "JSON object of values to replace in sibling parameters.kcl files before running Zoo."
    main_kcl_paths:
      default: "[]"
      description: "Optional bare path, JSON string, or JSON array of main.kcl paths. Empty processes changed assemblies only."
    host:
      default: ""
      description: "Optional Zoo API host. Empty means do not pass --host to the Zoo CLI."
    zoo_version:
      default: ""
      description: "Optional Zoo CLI release, like v0.2.165. Empty installs the latest release."
    install_image:
      default: debian:bookworm-slim
      description: "Container image for the Zoo CLI install job. Override with a Debian-compatible mirror if your runners cannot pull Docker Hub images."
    artifacts_image:
      default: python:3.12-slim
      description: "Container image for the KCL artifact job. Override with a Python 3.12 Debian-compatible mirror if your runners cannot pull Docker Hub images."
    snapshot_angle:
      default: iso
      options:
        - front
        - top
        - right-side
        - four-ways
        - iso
      description: "Camera angle used for assembly and per-file snapshots."
    camera_style:
      default: ortho
      options:
        - ortho
        - perspective
      description: "Camera style used for snapshots."
    camera_padding:
      default: "0.1"
      description: "Camera padding passed to zoo kcl snapshot."
---
"$[[ inputs.job-name ]]-install-zoo-cli":
  stage: $[[ inputs.stage ]]
  image: $[[ inputs.install_image ]]
  before_script:
    - apt-get update
    - apt-get install -y --no-install-recommends ca-certificates curl coreutils
    - rm -rf /var/lib/apt/lists/*
    - mkdir -p .gitlab-kcl-actions .kcl-tools/bin
"""
    body += heredoc_step("install-zoo-cli.sh", installer)
    body += """    - chmod +x .gitlab-kcl-actions/install-zoo-cli.sh
  script:
    - .gitlab-kcl-actions/install-zoo-cli.sh '$[[ inputs.zoo_version ]]' "$CI_PROJECT_DIR/.kcl-tools/bin"
  artifacts:
    paths:
      - .kcl-tools/bin/zoo

"$[[ inputs.job-name ]]":
  stage: $[[ inputs.stage ]]
  image: $[[ inputs.artifacts_image ]]
  needs:
    - job: "$[[ inputs.job-name ]]-install-zoo-cli"
      artifacts: true
  variables:
    KCL_PARAMETERS_JSON: |-
      $[[ inputs.parameters_json ]]
    KCL_MAIN_KCL_PATHS: |-
      $[[ inputs.main_kcl_paths ]]
    KCL_ZOO_HOST: '$[[ inputs.host ]]'
    KCL_SNAPSHOT_ANGLE: '$[[ inputs.snapshot_angle ]]'
    KCL_CAMERA_STYLE: '$[[ inputs.camera_style ]]'
    KCL_CAMERA_PADDING: '$[[ inputs.camera_padding ]]'
  before_script:
    - apt-get update
    - apt-get install -y --no-install-recommends ca-certificates tar coreutils findutils git
    - rm -rf /var/lib/apt/lists/*
    - mkdir -p .gitlab-kcl-actions .kcl-tools/bin
"""
    for filename, content in scripts.items():
        body += heredoc_step(filename, content)
    body += """    - chmod +x .gitlab-kcl-actions/run-kcl-artifacts.sh
    - export PATH="$CI_PROJECT_DIR/.kcl-tools/bin:$PATH"
  script:
    - export PATH="$CI_PROJECT_DIR/.kcl-tools/bin:$PATH"
    - KCL_ARTIFACTS_PY="$CI_PROJECT_DIR/.gitlab-kcl-actions/kcl_artifacts.py" .gitlab-kcl-actions/run-kcl-artifacts.sh
  artifacts:
    when: always
    paths:
      - kcl-artifacts/
"""
    return body


def render_dataset_conversions() -> str:
    scripts = {
        name: path.read_text(encoding="utf-8")
        for name, path in DATASET_CONVERSIONS_SCRIPT_FILES.items()
    }
    body = """spec:
  inputs:
    stage:
      default: test
      description: "Pipeline stage for the dataset conversion scrape job."
    job-name:
      default: dataset-conversions
      description: "Job name to use after the component merges into the consuming pipeline."
    dataset_id:
      default: ""
      description: "Optional org dataset UUID to scrape. Empty scrapes every org dataset."
    output_dir:
      default: dataset-conversions
      description: "Artifact directory where conversion outputs and the report are written."
    host:
      default: ""
      description: "Optional Zoo API host. Empty means use the SDK default or existing ZOO_HOST."
    filter:
      default: "status=success"
      description: "Dataset conversion filter passed to the KittyCAD Python SDK."
    limit:
      default: ""
      description: "Optional per-page limit passed to the SDK iterator. Empty leaves it unset."
    sort_by:
      default: ""
      options:
        - ""
        - created_at_ascending
        - created_at_descending
        - status_ascending
        - status_descending
        - updated_at_ascending
        - updated_at_descending
      description: "Optional conversion sort mode passed to the SDK iterator."
    image:
      default: python:3.12-slim
      description: "Container image for the scrape job."
    kittycad_package:
      default: kittycad
      description: "Python package requirement to install for the KittyCAD SDK, for example kittycad==1.3.8."
---
"$[[ inputs.job-name ]]":
  stage: $[[ inputs.stage ]]
  image: $[[ inputs.image ]]
  variables:
    DATASET_ID: '$[[ inputs.dataset_id ]]'
    DATASET_CONVERSIONS_OUTPUT_DIR: '$[[ inputs.output_dir ]]'
    DATASET_CONVERSIONS_FILTER: '$[[ inputs.filter ]]'
    DATASET_CONVERSIONS_LIMIT: '$[[ inputs.limit ]]'
    DATASET_CONVERSIONS_SORT_BY: '$[[ inputs.sort_by ]]'
    DATASET_CONVERSIONS_HOST: '$[[ inputs.host ]]'
    DATASET_CONVERSIONS_KITTYCAD_PACKAGE: '$[[ inputs.kittycad_package ]]'
  before_script:
    - mkdir -p .gitlab-kcl-actions
"""
    for filename, content in scripts.items():
        body += heredoc_step(filename, content)
    body += """  script:
    - python -m pip install --no-cache-dir "$DATASET_CONVERSIONS_KITTYCAD_PACKAGE"
    - |
      if [ -n "$DATASET_CONVERSIONS_HOST" ]; then
        export ZOO_HOST="$DATASET_CONVERSIONS_HOST"
      fi
      set -- \
        --output-dir "$DATASET_CONVERSIONS_OUTPUT_DIR" \
        --filter "$DATASET_CONVERSIONS_FILTER"
      if [ -n "$DATASET_ID" ]; then
        set -- "$@" --dataset-id "$DATASET_ID"
      fi
      if [ -n "$DATASET_CONVERSIONS_LIMIT" ]; then
        set -- "$@" --limit "$DATASET_CONVERSIONS_LIMIT"
      fi
      if [ -n "$DATASET_CONVERSIONS_SORT_BY" ]; then
        set -- "$@" --sort-by "$DATASET_CONVERSIONS_SORT_BY"
      fi
      python .gitlab-kcl-actions/dataset_conversions.py "$@"
  artifacts:
    when: always
    paths:
      - $[[ inputs.output_dir ]]/
"""
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the template is stale")
    args = parser.parse_args(argv)

    rendered = {
        INSTALL_TARGET: render_install(),
        KCL_TARGET: render_kcl_artifacts(),
        DATASET_CONVERSIONS_TARGET: render_dataset_conversions(),
    }
    if args.check:
        for target, content in rendered.items():
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                print(
                    f"error: {target} is not up to date; run scripts/render_component.py",
                    file=sys.stderr,
                )
                return 1
        return 0

    for target, content in rendered.items():
        target.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
