#!/usr/bin/env python3
"""Render the self-contained GitLab component from local scripts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
KCL_TARGET = ROOT / "templates" / "kcl-artifacts.yml"
INSTALL_TARGET = ROOT / "templates" / "install-zoo-cli.yml"
SCRIPT_FILES = {
    "install-zoo-cli.sh": ROOT / "scripts" / "install-zoo-cli.sh",
    "kcl_artifacts.py": ROOT / "scripts" / "kcl_artifacts.py",
    "run-kcl-artifacts.sh": ROOT / "scripts" / "run-kcl-artifacts.sh",
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
---
"$[[ inputs.job-name ]]":
  stage: $[[ inputs.stage ]]
  image: debian:bookworm-slim
  before_script:
    - apt-get update
    - apt-get install -y --no-install-recommends ca-certificates curl python3 coreutils
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
    scripts = {name: path.read_text(encoding="utf-8") for name, path in SCRIPT_FILES.items()}
    body = """spec:
  inputs:
    stage:
      default: test
      description: "Pipeline stage for the KCL artifact job."
    job-name:
      default: kcl-artifacts
      description: "Job name to use after the component merges into the consuming pipeline."
    parameters_json:
      default: "{}"
      description: "JSON object of values to replace in sibling parameters.kcl files before running Zoo."
    main_kcl_paths:
      default: "[]"
      description: "Optional bare path, JSON string, or JSON array of main.kcl paths. Empty processes every main.kcl."
    host:
      default: ""
      description: "Optional Zoo API host. Empty means do not pass --host to the Zoo CLI."
    zoo_version:
      default: ""
      description: "Optional Zoo CLI release, like v0.2.165. Empty installs the latest release."
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
"$[[ inputs.job-name ]]":
  stage: $[[ inputs.stage ]]
  image: python:3.12-slim
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
    - apt-get install -y --no-install-recommends ca-certificates curl tar coreutils findutils
    - rm -rf /var/lib/apt/lists/*
    - mkdir -p .gitlab-kcl-actions .kcl-tools/bin
"""
    for filename, content in scripts.items():
        body += heredoc_step(filename, content)
    body += """    - chmod +x .gitlab-kcl-actions/install-zoo-cli.sh .gitlab-kcl-actions/run-kcl-artifacts.sh
    - export PATH="$CI_PROJECT_DIR/.kcl-tools/bin:$PATH"
    - .gitlab-kcl-actions/install-zoo-cli.sh '$[[ inputs.zoo_version ]]' "$CI_PROJECT_DIR/.kcl-tools/bin"
  script:
    - export PATH="$CI_PROJECT_DIR/.kcl-tools/bin:$PATH"
    - KCL_ARTIFACTS_PY="$CI_PROJECT_DIR/.gitlab-kcl-actions/kcl_artifacts.py" .gitlab-kcl-actions/run-kcl-artifacts.sh
  artifacts:
    when: always
    paths:
      - kcl-artifacts/
"""
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the template is stale")
    args = parser.parse_args(argv)

    rendered = {
        INSTALL_TARGET: render_install(),
        KCL_TARGET: render_kcl_artifacts(),
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
