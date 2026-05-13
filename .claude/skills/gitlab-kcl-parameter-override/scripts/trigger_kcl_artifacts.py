#!/usr/bin/env python3
"""Trigger a GitLab kcl-artifacts pipeline with parameters.kcl overrides."""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, NoReturn
from uuid import uuid4


def fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def normalize_gitlab_host(raw_host: str) -> str:
    host = raw_host.strip()
    if not host:
        fail("GitLab host cannot be empty")
    if "://" not in host:
        host = f"https://{host}"
    return host.rstrip("/")


def normalize_main_kcl_path(raw_path: str) -> str:
    value = raw_path.strip().replace("\\", "/")
    if not value:
        fail("part path cannot be empty")
    if value.startswith("/"):
        fail(f"part path must be repo-relative, got {raw_path!r}")

    trailing_slash = value.endswith("/")
    path = PurePosixPath(value)
    normalized = posixpath.normpath(path.as_posix())
    if normalized in (".", ""):
        fail("part path cannot point at the repository root")
    if normalized == ".." or normalized.startswith("../") or "/../" in f"/{normalized}/":
        fail(f"part path cannot traverse directories, got {raw_path!r}")

    if trailing_slash:
        return f"{normalized.rstrip('/')}/main.kcl"
    if normalized.endswith("/main.kcl"):
        return normalized
    if normalized.endswith("/parameters.kcl"):
        return f"{normalized.removesuffix('/parameters.kcl')}/main.kcl"

    fail(f"part path must be a directory, main.kcl, or parameters.kcl; got {raw_path!r}")


def parse_parameter_value(raw_value: str) -> Any:
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value


def parse_parameter_assignment(raw_assignment: str) -> tuple[str, Any]:
    name, separator, value = raw_assignment.partition("=")
    if separator != "=":
        fail(f"parameter must be name=value, got {raw_assignment!r}")
    name = name.strip()
    if not name:
        fail(f"parameter name cannot be empty in {raw_assignment!r}")
    return name, parse_parameter_value(value.strip())


def load_parameters_json(raw_json: str | None) -> dict[str, Any]:
    if not raw_json:
        return {}
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError as error:
        fail(f"parameters JSON is invalid: {error}")
    if not isinstance(value, dict):
        fail("parameters JSON must be an object")
    if not all(isinstance(key, str) and key for key in value):
        fail("parameters JSON keys must be non-empty strings")
    return dict(value)


def build_parameters(raw_json: str | None, assignments: list[str]) -> str:
    parameters = load_parameters_json(raw_json)
    for assignment in assignments:
        name, value = parse_parameter_assignment(assignment)
        parameters[name] = value
    return json.dumps(parameters, separators=(",", ":"), sort_keys=True)


def encode_multipart_form(fields: Mapping[str, str]) -> tuple[bytes, str]:
    boundary = f"----gitlab-kcl-artifacts-{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def trigger_pipeline(
    *,
    gitlab_host: str,
    project: str,
    ref: str,
    token: str,
    main_kcl_path: str,
    parameters_json: str,
) -> dict[str, Any]:
    project_path = urllib.parse.quote(project, safe="")
    url = f"{gitlab_host}/api/v4/projects/{project_path}/trigger/pipeline"
    fields = {
        "token": token,
        "ref": ref,
        "inputs[kcl_main_kcl_paths]": json.dumps([main_kcl_path], separators=(",", ":")),
        "inputs[kcl_parameters_json]": parameters_json,
    }
    body, content_type = encode_multipart_form(fields)
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_body = response.read().decode()
    except urllib.error.HTTPError as error:
        error_body = error.read().decode(errors="replace")
        fail(f"GitLab returned HTTP {error.code}: {error_body}")
    except urllib.error.URLError as error:
        fail(f"failed to reach GitLab: {error.reason}")

    try:
        value = json.loads(response_body)
    except json.JSONDecodeError:
        fail(f"GitLab returned non-JSON response: {response_body}")
    if not isinstance(value, dict):
        fail(f"GitLab returned unexpected response: {response_body}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gitlab-host",
        default=os.getenv("GITLAB_HOST", "https://gitlab.com"),
        help="GitLab host URL. Defaults to GITLAB_HOST, then https://gitlab.com.",
    )
    parser.add_argument(
        "--project",
        required=True,
        help="GitLab project ID or path, for example 123456 or my-group/my-repo.",
    )
    parser.add_argument(
        "--ref",
        default="main",
        help="Branch or tag to trigger. Defaults to main.",
    )
    parser.add_argument(
        "--part-path",
        required=True,
        help="Repo-relative directory, main.kcl, or parameters.kcl path.",
    )
    parser.add_argument(
        "--parameters-json",
        help="JSON object of exported parameters.kcl values to override.",
    )
    parser.add_argument(
        "--parameter",
        action="append",
        default=[],
        help="Override in name=value form. May be repeated. Values are parsed as JSON when possible.",
    )
    parser.add_argument(
        "--token-env",
        default="GITLAB_TRIGGER_TOKEN",
        help="Environment variable containing the GitLab trigger token.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually trigger the pipeline. Without this flag, print the normalized dry run.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    gitlab_host = normalize_gitlab_host(args.gitlab_host)
    main_kcl_path = normalize_main_kcl_path(args.part_path)
    parameters_json = build_parameters(args.parameters_json, args.parameter)
    inputs = {
        "kcl_main_kcl_paths": json.dumps([main_kcl_path], separators=(",", ":")),
        "kcl_parameters_json": parameters_json,
    }

    if not args.execute:
        print(f"gitlab_host={gitlab_host}")
        print(f"project={args.project}")
        print(f"ref={args.ref}")
        print(json.dumps({"inputs": inputs}, indent=2, sort_keys=True))
        print("dry run only; add --execute to trigger the pipeline", file=sys.stderr)
        return 0

    token = os.getenv(args.token_env)
    if not token:
        fail(f"{args.token_env} is not set")

    pipeline = trigger_pipeline(
        gitlab_host=gitlab_host,
        project=args.project,
        ref=args.ref,
        token=token,
        main_kcl_path=main_kcl_path,
        parameters_json=parameters_json,
    )
    web_url = pipeline.get("web_url")
    if isinstance(web_url, str) and web_url:
        print(web_url)
    else:
        print(json.dumps(pipeline, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130) from None
