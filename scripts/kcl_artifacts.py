#!/usr/bin/env python3
"""Helpers for the GitLab KCL artifact workflow."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Any


REQUIRED_METADATA = {
    "material_density": (int, float),
    "material_density_unit": str,
    "mass_output_unit": str,
    "volume_output_unit": str,
    "density_output_unit": str,
    "surface_area_output_unit": str,
    "center_of_mass_output_unit": str,
    "bounding_box_output_unit": str,
}

ENV_NAMES = {
    "material_density": "MATERIAL_DENSITY",
    "material_density_unit": "MATERIAL_DENSITY_UNIT",
    "mass_output_unit": "MASS_OUTPUT_UNIT",
    "volume_output_unit": "VOLUME_OUTPUT_UNIT",
    "density_output_unit": "DENSITY_OUTPUT_UNIT",
    "surface_area_output_unit": "SURFACE_AREA_OUTPUT_UNIT",
    "center_of_mass_output_unit": "CENTER_OF_MASS_OUTPUT_UNIT",
    "bounding_box_output_unit": "BOUNDING_BOX_OUTPUT_UNIT",
}

ASSIGNMENT_RE = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<equals>\s*=\s*)"
    r"(?P<value>.*?)(?P<comment>\s*(?://.*)?)$"
)
SKIPPED_DIRS = {
    ".git",
    ".gitlab-kcl-actions",
    ".kcl-tools",
    "kcl-artifacts",
    "node_modules",
    "target",
}


class WorkflowError(Exception):
    """A user-facing workflow error."""


def fail(message: str) -> None:
    raise WorkflowError(message)


def load_json_object(raw: str, description: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as err:
        fail(f"{description} is not valid JSON: {err}")
    if not isinstance(value, dict):
        fail(f"{description} must be a JSON object")
    return value


def kcl_literal(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            fail("JSON numbers must be finite")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(kcl_literal(item) for item in value) + "]"
    if isinstance(value, dict):
        fields: list[str] = []
        for key, item in value.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                fail(f"object key {key!r} is not a valid KCL identifier")
            fields.append(f"{key} = {kcl_literal(item)}")
        return "{ " + ", ".join(fields) + " }"
    fail(f"unsupported JSON value type: {type(value).__name__}")


def brace_delta(line: str) -> int:
    """Count braces outside strings and line comments for shallow KCL blocks."""
    delta = 0
    in_string = False
    escaped = False
    index = 0
    while index < len(line):
        char = line[index]
        next_char = line[index + 1] if index + 1 < len(line) else ""
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == "/" and next_char == "/":
            break
        elif char == '"':
            in_string = True
        elif char == "{":
            delta += 1
        elif char == "}":
            delta -= 1
        index += 1
    return delta


def apply_parameters(parameters_file: Path, overrides_json: str) -> None:
    if not parameters_file.is_file():
        fail(f"required parameters.kcl file does not exist: {parameters_file}")

    overrides = load_json_object(overrides_json, "parameters_json")
    if not overrides:
        return

    lines = parameters_file.read_text(encoding="utf-8").splitlines(keepends=True)
    replacement_names = set(overrides)
    seen: set[str] = set()
    output: list[str] = []
    brace_depth = 0

    for line in lines:
        newline = ""
        body = line
        if body.endswith("\n"):
            newline = "\n"
            body = body[:-1]

        match = ASSIGNMENT_RE.match(body) if brace_depth == 0 else None
        if not match:
            output.append(line)
            brace_depth += brace_delta(body)
            if brace_depth < 0:
                brace_depth = 0
            continue

        name = match.group("name")
        if name not in overrides:
            output.append(line)
            brace_depth += brace_delta(body)
            if brace_depth < 0:
                brace_depth = 0
            continue
        if name in seen:
            fail(f"parameters.kcl defines {name!r} more than once")

        seen.add(name)
        output.append(
            f"{match.group('prefix')}{name}{match.group('equals')}"
            f"{kcl_literal(overrides[name])}{match.group('comment')}{newline}"
        )
        brace_depth += brace_delta(body)
        if brace_depth < 0:
            brace_depth = 0

    missing = sorted(replacement_names - seen)
    if missing:
        fail(
            "parameters_json referenced parameter(s) not defined in parameters.kcl: "
            + ", ".join(missing)
        )

    parameters_file.write_text("".join(output), encoding="utf-8")


def walk_kcl_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for root, dirs, filenames in os.walk(repo_root):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
        for filename in sorted(filenames):
            if filename.endswith(".kcl"):
                files.append(Path(root, filename))
    return files


def relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def find_single_named_file(repo_root: Path, filename: str) -> Path:
    matches = [path for path in walk_kcl_files(repo_root) if path.name == filename]
    if not matches:
        fail(f"required {filename} file was not found")
    if len(matches) > 1:
        formatted = ", ".join(relative_posix(path, repo_root) for path in matches)
        fail(f"expected exactly one {filename}, found {len(matches)}: {formatted}")
    return matches[0]


def write_project_info(repo_root: Path, env_out: Path, snapshots_out: Path) -> None:
    repo_root = repo_root.resolve()
    main_kcl = find_single_named_file(repo_root, "main.kcl")
    parameters_kcl = find_single_named_file(repo_root, "parameters.kcl")

    snapshot_files = [
        path for path in walk_kcl_files(repo_root) if path.resolve() != parameters_kcl.resolve()
    ]

    env_out.write_text(
        "\n".join(
            [
                f"MAIN_KCL={shlex.quote(relative_posix(main_kcl, repo_root))}",
                f"PARAMETERS_KCL={shlex.quote(relative_posix(parameters_kcl, repo_root))}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    snapshots_out.write_text(
        "".join(relative_posix(path, repo_root) + "\n" for path in snapshot_files),
        encoding="utf-8",
    )


def validate_metadata(metadata_file: Path) -> dict[str, Any]:
    if not metadata_file.is_file():
        fail("required metadata.json file was not found at the repo root")
    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        fail(f"metadata.json is not valid JSON: {err}")
    if not isinstance(metadata, dict):
        fail("metadata.json must be a JSON object")

    for field, expected_type in REQUIRED_METADATA.items():
        if field not in metadata:
            fail(f"metadata.json is missing required field: {field}")
        value = metadata[field]
        if value is None:
            fail(f"metadata.json field {field} must not be null")
        if field == "material_density":
            if isinstance(value, bool) or not isinstance(value, expected_type):
                fail("metadata.json field material_density must be a number")
            if not math.isfinite(float(value)):
                fail("metadata.json field material_density must be finite")
        elif not isinstance(value, expected_type):
            fail(f"metadata.json field {field} must be a string")
        if isinstance(value, str) and value == "":
            fail(f"metadata.json field {field} must not be empty")
    return metadata


def write_metadata_env(metadata_file: Path, env_out: Path) -> None:
    metadata = validate_metadata(metadata_file)
    env_out.write_text(
        "".join(
            f"{env_name}={shlex.quote(str(metadata[field]))}\n"
            for field, env_name in ENV_NAMES.items()
        ),
        encoding="utf-8",
    )


def write_manifest(
    artifact_dir: Path,
    main_kcl: str,
    parameters_kcl: str,
    zoo_version: str,
    host: str,
    parameters_json: str,
) -> None:
    artifact_dir = artifact_dir.resolve()
    files = sorted(
        path.relative_to(artifact_dir).as_posix()
        for path in artifact_dir.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "main_kcl": main_kcl,
        "parameters_kcl": parameters_kcl,
        "zoo_version": zoo_version,
        "host": host or None,
        "parameters_override_keys": sorted(load_json_object(parameters_json, "parameters_json")),
        "artifacts": files,
    }
    (artifact_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    apply_parser = subparsers.add_parser("apply-parameters")
    apply_parser.add_argument("--parameters-file", required=True, type=Path)
    apply_parser.add_argument("--overrides-json", required=True)

    info_parser = subparsers.add_parser("project-info")
    info_parser.add_argument("--repo-root", required=True, type=Path)
    info_parser.add_argument("--env-out", required=True, type=Path)
    info_parser.add_argument("--snapshots-out", required=True, type=Path)

    metadata_parser = subparsers.add_parser("metadata-env")
    metadata_parser.add_argument("--metadata-file", required=True, type=Path)
    metadata_parser.add_argument("--env-out", required=True, type=Path)

    manifest_parser = subparsers.add_parser("write-manifest")
    manifest_parser.add_argument("--artifact-dir", required=True, type=Path)
    manifest_parser.add_argument("--main-kcl", required=True)
    manifest_parser.add_argument("--parameters-kcl", required=True)
    manifest_parser.add_argument("--zoo-version", required=True)
    manifest_parser.add_argument("--host", default="")
    manifest_parser.add_argument("--parameters-json", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "apply-parameters":
            apply_parameters(args.parameters_file, args.overrides_json)
        elif args.command == "project-info":
            write_project_info(args.repo_root, args.env_out, args.snapshots_out)
        elif args.command == "metadata-env":
            write_metadata_env(args.metadata_file, args.env_out)
        elif args.command == "write-manifest":
            write_manifest(
                args.artifact_dir,
                args.main_kcl,
                args.parameters_kcl,
                args.zoo_version,
                args.host,
                args.parameters_json,
            )
        else:
            parser.error(f"unknown command: {args.command}")
    except WorkflowError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
