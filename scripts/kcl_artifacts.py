#!/usr/bin/env python3
"""Helpers for the GitLab KCL artifact workflow."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

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

DEFAULT_PARAMETERS_FILENAME = "parameters.kcl"
DEFAULT_METADATA_PATH = "metadata.json"
MISSING_ASSEMBLY_FIELD = "-"

ASSIGNMENT_RE = re.compile(
    r"^(?P<prefix>export\s+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<equals>\s*=\s*)"
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


@dataclass(frozen=True)
class Assembly:
    id: str
    main_kcl: str
    parameters_kcl: str | None
    metadata_json: str | None


def fail(message: str) -> NoReturn:
    raise WorkflowError(message)


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def assembly_file_field(path: str | None) -> str:
    return path if path is not None else MISSING_ASSEMBLY_FIELD


def optional_assembly_file_field(raw_path: str) -> str | None:
    if raw_path in {"", MISSING_ASSEMBLY_FIELD}:
        return None
    return raw_path


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


def load_entrypoint_paths(raw: str, description: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        values = [text]
    else:
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            values = value
        else:
            fail(
                f"{description} must be a relative .kcl file path, JSON string, "
                "or JSON array of strings"
            )

    output: list[str] = []
    seen: set[str] = set()
    for item in values:
        path = normalize_entrypoint_path(item, "main_kcl_paths")
        if path in seen:
            fail(f"{description} contains duplicate path: {path}")
        seen.add(path)
        output.append(path)
    return output


def normalize_entrypoint_path(raw_path: str, description: str) -> str:
    path = PurePosixPath(raw_path)
    if raw_path == "" or path.is_absolute():
        fail(f"{description} path must be relative: {raw_path!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        fail(f"{description} path must not contain empty, '.', or '..' parts: {raw_path!r}")
    if path.suffix != ".kcl":
        fail(f"{description} path must point to a .kcl file: {raw_path!r}")
    return path.as_posix()


def normalize_parameters_filename(raw_filename: str) -> str:
    path = PurePosixPath(raw_filename)
    if raw_filename == "" or path.is_absolute() or len(path.parts) != 1:
        fail(f"parameters_filename must be a relative .kcl filename: {raw_filename!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        fail(f"parameters_filename must not contain empty, '.', or '..' parts: {raw_filename!r}")
    if path.suffix != ".kcl":
        fail(f"parameters_filename must point to a .kcl file: {raw_filename!r}")
    return path.as_posix()


def normalize_metadata_path(raw_path: str) -> str:
    path = PurePosixPath(raw_path)
    if raw_path == "" or path.is_absolute():
        fail(f"metadata_path must be relative: {raw_path!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        fail(f"metadata_path must not contain empty, '.', or '..' parts: {raw_path!r}")
    if path.suffix != ".json":
        fail(f"metadata_path must point to a .json file: {raw_path!r}")
    return path.as_posix()


def unique_paths(paths: list[Path]) -> list[Path]:
    output: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        output.append(path)
    return output


def parameters_file_for_assembly(
    repo_root: Path,
    kcl_file: Path,
    parameters_filename: str,
    warn_if_missing: bool,
) -> Path | None:
    candidate = kcl_file.parent / parameters_filename
    if candidate.is_file():
        return candidate
    if warn_if_missing:
        warn(
            f"parameters file was not found for "
            f"{relative_posix(kcl_file, repo_root)}; tried "
            f"{relative_posix(candidate, repo_root)}; "
            "parameter overrides will be skipped for this file"
        )
    return None


def metadata_file_for_assembly(
    repo_root: Path,
    kcl_file: Path,
    metadata_path: str,
) -> Path | None:
    path = PurePosixPath(metadata_path)
    if len(path.parts) > 1:
        metadata_file = repo_root / path.as_posix()
        if metadata_file.is_file():
            return metadata_file
        warn(f"metadata file {metadata_path!r} was not found; physics artifacts will be skipped")
        return None

    candidate = kcl_file.parent / metadata_path
    if candidate.is_file():
        return candidate
    warn(
        f"metadata file was not found for "
        f"{relative_posix(kcl_file, repo_root)}; tried "
        f"{relative_posix(candidate, repo_root)}; "
        "physics artifacts will be skipped for this file"
    )
    return None


def normalize_repo_path(raw_path: str, description: str) -> str:
    path = PurePosixPath(raw_path)
    if raw_path == "" or path.is_absolute():
        fail(f"{description} path must be relative: {raw_path!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        fail(f"{description} path must not contain empty, '.', or '..' parts: {raw_path!r}")
    return path.as_posix()


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


def apply_parameter_values(parameters_file: Path, overrides: dict[str, Any]) -> None:
    if not parameters_file.is_file():
        fail(f"required parameters file does not exist: {parameters_file}")

    if not overrides:
        return

    lines = parameters_file.read_text(encoding="utf-8").splitlines(keepends=True)
    replacement_names = set(overrides)
    seen: set[str] = set()
    output: list[str] = []

    for line in lines:
        newline = ""
        body = line
        if body.endswith("\n"):
            newline = "\n"
            body = body[:-1]

        match = ASSIGNMENT_RE.match(body)
        if not match:
            output.append(line)
            continue

        name = match.group("name")
        if name not in overrides:
            output.append(line)
            continue
        if name in seen:
            fail(f"parameters file defines {name!r} more than once")

        seen.add(name)
        output.append(
            f"{match.group('prefix')}{name}{match.group('equals')}"
            f"{kcl_literal(overrides[name])}{match.group('comment')}{newline}"
        )

    missing = sorted(replacement_names - seen)
    if missing:
        fail(
            "parameters_json referenced parameter(s) not exported in parameters file: "
            + ", ".join(missing)
        )

    parameters_file.write_text("".join(output), encoding="utf-8")


def apply_parameters(parameters_file: Path, overrides_json: str) -> None:
    overrides = load_json_object(overrides_json, "parameters_json")
    apply_parameter_values(parameters_file, overrides)


def exported_parameter_names(parameters_file: Path) -> set[str]:
    if not parameters_file.is_file():
        fail(f"required parameters file does not exist: {parameters_file}")

    names: set[str] = set()
    lines = parameters_file.read_text(encoding="utf-8").splitlines()
    for line in lines:
        match = ASSIGNMENT_RE.match(line)
        if match:
            names.add(match.group("name"))
    return names


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


def discover_assembly_files(repo_root: Path, parameters_filename: str) -> list[Path]:
    return [path for path in walk_kcl_files(repo_root) if path.name != parameters_filename]


def assembly_id_for_file(kcl_file: Path, repo_root: Path) -> str:
    relative = PurePosixPath(relative_posix(kcl_file, repo_root))
    return relative.with_suffix("").as_posix()


def load_changed_paths(changed_files_file: Path | None) -> list[str]:
    if changed_files_file is None:
        return []
    if not changed_files_file.is_file():
        fail(f"changed files list does not exist: {changed_files_file}")

    output: list[str] = []
    seen: set[str] = set()
    for line in changed_files_file.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        path = normalize_repo_path(line, "changed file")
        if PurePosixPath(path).parts[0] in SKIPPED_DIRS:
            continue
        if path not in seen:
            seen.add(path)
            output.append(path)
    return output


def assemblies_for_changed_paths(
    repo_root: Path,
    all_assembly_files: list[Path],
    changed_paths: list[str],
    parameters_filename: str,
    metadata_path: str,
) -> list[Path]:
    metadata_pure = PurePosixPath(metadata_path)
    metadata_is_shared = len(metadata_pure.parts) > 1
    metadata_sibling_name = None if metadata_is_shared else metadata_path

    assembly_by_relpath = {
        relative_posix(assembly, repo_root): assembly for assembly in all_assembly_files
    }
    folder_assemblies: dict[Path, list[Path]] = {}
    for assembly in all_assembly_files:
        folder_assemblies.setdefault(assembly.parent, []).append(assembly)

    selected: set[Path] = set()
    for relative_path in changed_paths:
        if metadata_is_shared and relative_path == metadata_path:
            return list(all_assembly_files)
        name = PurePosixPath(relative_path).name
        if name == parameters_filename or (
            metadata_sibling_name is not None and name == metadata_sibling_name
        ):
            folder = (repo_root / relative_path).parent
            selected.update(folder_assemblies.get(folder, []))
            continue
        assembly = assembly_by_relpath.get(relative_path)
        if assembly is not None:
            selected.add(assembly)
    return [assembly for assembly in all_assembly_files if assembly in selected]


def write_project_info(
    repo_root: Path,
    assemblies_out: Path,
    snapshots_out: Path,
    main_kcl_paths_json: str = "[]",
    changed_files_file: Path | None = None,
    parameters_filename: str = DEFAULT_PARAMETERS_FILENAME,
    metadata_path: str = DEFAULT_METADATA_PATH,
    parameters_json: str = "{}",
) -> None:
    repo_root = repo_root.resolve()
    parameters_filename = normalize_parameters_filename(parameters_filename)
    metadata_path = normalize_metadata_path(metadata_path)
    parameters_overrides = load_json_object(parameters_json, "parameters_json")
    selected_paths = load_entrypoint_paths(main_kcl_paths_json, "main_kcl_paths")

    all_assembly_files = discover_assembly_files(repo_root, parameters_filename)

    if selected_paths:
        assembly_files: list[Path] = []
        for path in selected_paths:
            assembly_file = repo_root / path
            if not assembly_file.is_file():
                fail(f"main_kcl_paths referenced missing .kcl file: {path}")
            if PurePosixPath(path).name == parameters_filename:
                fail(f"main_kcl_paths referenced the parameters file: {path}")
            assembly_files.append(assembly_file)
        assembly_files = unique_paths(assembly_files)
    elif changed_files_file is not None:
        changed_paths = load_changed_paths(changed_files_file)
        assembly_files = assemblies_for_changed_paths(
            repo_root,
            all_assembly_files,
            changed_paths,
            parameters_filename,
            metadata_path,
        )
    else:
        if not all_assembly_files:
            fail("no .kcl files were found")
        assembly_files = all_assembly_files

    assemblies: list[Assembly] = []
    assembly_ids: set[str] = set()
    for kcl_file in assembly_files:
        parameters_kcl = parameters_file_for_assembly(
            repo_root,
            kcl_file,
            parameters_filename,
            warn_if_missing=bool(parameters_overrides),
        )
        metadata_json = metadata_file_for_assembly(repo_root, kcl_file, metadata_path)
        if metadata_json is not None:
            validate_metadata(metadata_json)

        assembly_id = assembly_id_for_file(kcl_file, repo_root)
        if assembly_id in assembly_ids:
            fail(f"assembly id {assembly_id!r} is not unique")
        assembly_ids.add(assembly_id)
        assemblies.append(
            Assembly(
                assembly_id,
                relative_posix(kcl_file, repo_root),
                relative_posix(parameters_kcl, repo_root) if parameters_kcl is not None else None,
                relative_posix(metadata_json, repo_root) if metadata_json is not None else None,
            )
        )

    assemblies_out.write_text(
        "".join(
            "\t".join(
                [
                    assembly.id,
                    assembly.main_kcl,
                    assembly_file_field(assembly.parameters_kcl),
                    assembly_file_field(assembly.metadata_json),
                ]
            )
            + "\n"
            for assembly in assemblies
        ),
        encoding="utf-8",
    )
    snapshots_out.write_text(
        "".join(
            relative_posix(assembly_file, repo_root) + "\n" for assembly_file in assembly_files
        ),
        encoding="utf-8",
    )


def load_assemblies(assemblies_file: Path) -> list[Assembly]:
    assemblies: list[Assembly] = []
    for line in assemblies_file.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 4:
            fail(f"invalid assemblies file row: {line!r}")
        assemblies.append(
            Assembly(
                fields[0],
                fields[1],
                optional_assembly_file_field(fields[2]),
                optional_assembly_file_field(fields[3]),
            )
        )
    if not assemblies:
        fail("assemblies file did not contain any assembly entries")
    return assemblies


def apply_project_parameters(
    repo_root: Path,
    assemblies_file: Path,
    overrides_json: str,
) -> None:
    overrides = load_json_object(overrides_json, "parameters_json")
    if not overrides:
        return

    repo_root = repo_root.resolve()
    assemblies = load_assemblies(assemblies_file)
    names_by_file: dict[Path, set[str]] = {}
    seen: set[str] = set()
    for assembly in assemblies:
        if assembly.parameters_kcl is None:
            warn(
                f"assembly {assembly.id} has no parameters file; "
                "skipping parameter overrides for it"
            )
            continue
        parameters_file = repo_root / assembly.parameters_kcl
        names = exported_parameter_names(parameters_file)
        names_by_file[parameters_file] = names
        seen.update(name for name in overrides if name in names)

    missing = sorted(set(overrides) - seen)
    if missing:
        fail(
            "parameters_json referenced parameter(s) not exported in any "
            "parameters file: " + ", ".join(missing)
        )

    for parameters_file, names in names_by_file.items():
        selected = {name: value for name, value in overrides.items() if name in names}
        apply_parameter_values(parameters_file, selected)


def validate_metadata(metadata_file: Path) -> dict[str, Any]:
    if not metadata_file.is_file():
        fail(f"required metadata.json file was not found: {metadata_file}")
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


def write_bounding_box_json(
    analysis_file: Path,
    output_file: Path,
    output_unit: str,
) -> None:
    try:
        analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        fail(f"{analysis_file} is not valid JSON: {err}")
    if not isinstance(analysis, dict):
        fail(f"{analysis_file} must contain a JSON object")

    bounding_box = analysis.get("bounding_box")
    if not isinstance(bounding_box, dict):
        fail(f"{analysis_file} is missing object field: bounding_box")
    for field in ("center", "dimensions"):
        value = bounding_box.get(field)
        if not isinstance(value, dict):
            fail(f"{analysis_file} bounding_box.{field} must be an object")
        for axis in ("x", "y", "z"):
            coordinate = value.get(axis)
            if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
                fail(f"{analysis_file} bounding_box.{field}.{axis} must be a number")

    output = {
        "center": bounding_box["center"],
        "dimensions": bounding_box["dimensions"],
        "output_unit": output_unit,
    }
    output_file.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_source_files(
    repo_root: Path,
    snapshots_file: Path,
    assemblies_file: Path,
    output_dir: Path,
) -> None:
    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    relative_paths: set[str] = set()
    for line in snapshots_file.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        relative_path = normalize_repo_path(line, "source file")
        if not relative_path.endswith(".kcl"):
            continue
        relative_paths.add(relative_path)

    for assembly in load_assemblies(assemblies_file):
        if assembly.parameters_kcl is not None:
            relative_paths.add(normalize_repo_path(assembly.parameters_kcl, "source file"))
        if assembly.metadata_json is not None:
            relative_paths.add(normalize_repo_path(assembly.metadata_json, "source file"))

    for relative_path in sorted(relative_paths):
        source = repo_root / relative_path
        if not source.is_file():
            fail(f"source file does not exist: {relative_path}")
        destination = output_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def parameters_json_name_for_assemblies(assemblies: list[Assembly]) -> str:
    names = set()
    for assembly in assemblies:
        if assembly.parameters_kcl is None:
            continue
        path = PurePosixPath(assembly.parameters_kcl)
        if path.suffix != ".kcl":
            fail(f"assembly parameters_kcl must point to a .kcl file: {assembly.parameters_kcl!r}")
        names.add(path.with_suffix(".json").name)
    if not names:
        fail("parameters_json was supplied, but no selected assembly has a parameters file")
    if len(names) == 1:
        return names.pop()
    return DEFAULT_PARAMETERS_FILENAME.replace(".kcl", ".json")


def write_manifest(
    artifact_dir: Path,
    assemblies_file: Path,
    zoo_version: str,
    host: str,
    parameters_json: str,
) -> None:
    artifact_dir = artifact_dir.resolve()
    loaded_assemblies = load_assemblies(assemblies_file)
    parameters_overrides = load_json_object(parameters_json, "parameters_json")
    parameters_json_name = (
        parameters_json_name_for_assemblies(loaded_assemblies) if parameters_overrides else None
    )
    if parameters_overrides:
        parameters_json_path = artifact_dir / str(parameters_json_name)
        parameters_json_path.write_text(
            json.dumps(parameters_overrides, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    assemblies = [
        {
            "id": assembly.id,
            "main_kcl": assembly.main_kcl,
            "metadata_json": assembly.metadata_json,
            "parameters_kcl": assembly.parameters_kcl,
        }
        for assembly in loaded_assemblies
    ]
    files = sorted(
        path.relative_to(artifact_dir).as_posix()
        for path in artifact_dir.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "assemblies": assemblies,
        "zoo_version": zoo_version,
        "host": host or None,
        "parameters_json": parameters_json_name if parameters_overrides else None,
        "parameters_override_keys": sorted(parameters_overrides),
        "parameters_overrides": parameters_overrides,
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

    apply_project_parser = subparsers.add_parser("apply-project-parameters")
    apply_project_parser.add_argument("--repo-root", required=True, type=Path)
    apply_project_parser.add_argument("--assemblies-file", required=True, type=Path)
    apply_project_parser.add_argument("--overrides-json", required=True)

    info_parser = subparsers.add_parser("project-info")
    info_parser.add_argument("--repo-root", required=True, type=Path)
    info_parser.add_argument("--assemblies-out", required=True, type=Path)
    info_parser.add_argument("--snapshots-out", required=True, type=Path)
    info_parser.add_argument("--main-kcl-paths", default="[]")
    info_parser.add_argument("--changed-files-file", type=Path)
    info_parser.add_argument("--parameters-filename", default=DEFAULT_PARAMETERS_FILENAME)
    info_parser.add_argument("--metadata-path", default=DEFAULT_METADATA_PATH)
    info_parser.add_argument("--parameters-json", default="{}")

    metadata_parser = subparsers.add_parser("metadata-env")
    metadata_parser.add_argument("--metadata-file", required=True, type=Path)
    metadata_parser.add_argument("--env-out", required=True, type=Path)

    bounding_box_parser = subparsers.add_parser("bounding-box-json")
    bounding_box_parser.add_argument("--analysis-file", required=True, type=Path)
    bounding_box_parser.add_argument("--output-file", required=True, type=Path)
    bounding_box_parser.add_argument("--output-unit", required=True)

    source_parser = subparsers.add_parser("write-source-files")
    source_parser.add_argument("--repo-root", required=True, type=Path)
    source_parser.add_argument("--snapshots-file", required=True, type=Path)
    source_parser.add_argument("--assemblies-file", required=True, type=Path)
    source_parser.add_argument("--output-dir", required=True, type=Path)

    manifest_parser = subparsers.add_parser("write-manifest")
    manifest_parser.add_argument("--artifact-dir", required=True, type=Path)
    manifest_parser.add_argument("--assemblies-file", required=True, type=Path)
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
        elif args.command == "apply-project-parameters":
            apply_project_parameters(
                args.repo_root,
                args.assemblies_file,
                args.overrides_json,
            )
        elif args.command == "project-info":
            write_project_info(
                args.repo_root,
                args.assemblies_out,
                args.snapshots_out,
                args.main_kcl_paths,
                args.changed_files_file,
                args.parameters_filename,
                args.metadata_path,
                args.parameters_json,
            )
        elif args.command == "metadata-env":
            write_metadata_env(args.metadata_file, args.env_out)
        elif args.command == "bounding-box-json":
            write_bounding_box_json(
                args.analysis_file,
                args.output_file,
                args.output_unit,
            )
        elif args.command == "write-source-files":
            write_source_files(
                args.repo_root,
                args.snapshots_file,
                args.assemblies_file,
                args.output_dir,
            )
        elif args.command == "write-manifest":
            write_manifest(
                args.artifact_dir,
                args.assemblies_file,
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
