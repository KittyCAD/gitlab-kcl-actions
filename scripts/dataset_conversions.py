#!/usr/bin/env python3
"""Download successful org dataset conversion outputs with the KittyCAD Python SDK."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any


LOG_PREFIX = "[dataset-conversions]"
SAFE_PATH_PART_RE = re.compile(r"[^A-Za-z0-9._ -]+")
SAFE_PATH_SEPARATORS_RE = re.compile(r"_+")
DEFAULT_FILTER = "status=success"
SORT_MODES = {
    "created_at_ascending",
    "created_at_descending",
    "status_ascending",
    "status_descending",
    "updated_at_ascending",
    "updated_at_descending",
}


@dataclass
class ScrapeStats:
    dataset_id: str
    dataset_name: str
    output_dir: Path
    seen: int = 0
    completed: int = 0
    skipped_phase: int = 0
    fetched: int = 0
    outputs_written: int = 0
    snapshots_written: int = 0
    conversions: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.conversions is None:
            self.conversions = []


def log(message: str) -> None:
    print(f"{LOG_PREFIX} {message}", file=sys.stderr, flush=True)


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def safe_path_part(value: str, *, fallback: str) -> str:
    part = SAFE_PATH_PART_RE.sub("_", value.strip())
    part = SAFE_PATH_SEPARATORS_RE.sub("_", part)
    return part.strip(" ._-") or fallback


def safe_relative_path(value: str) -> Path:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        fail(f"conversion file path must be relative, got: {value!r}")

    parts: list[str] = []
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            fail(f"conversion file path cannot traverse directories, got: {value!r}")
        parts.append(safe_path_part(part, fallback="unnamed"))

    if not parts:
        fail("conversion file path cannot be empty")
    return Path(*parts)


def ensure_png_bytes(image: Any, *, conversion_id: str, group: str, index: int) -> bytes:
    mime_type = getattr(image, "mime_type", None)
    if mime_type != "image/png":
        fail(
            f"conversion {conversion_id} {group} snapshot {index} has unsupported "
            f"mime type {mime_type!r}; expected image/png"
        )

    data = getattr(image, "data_base64", None)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        fail(
            f"conversion {conversion_id} {group} snapshot {index} did not contain "
            "SDK-decoded bytes"
        )
    return bytes(data)


def write_text_artifact(path: Path, value: str | None) -> bool:
    if value is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return True


def write_salon_snapshots(
    conversion_dir: Path,
    conversion_id: str,
    images: list[Any],
) -> int:
    written = 0
    for index, image in enumerate(images):
        data = ensure_png_bytes(
            image,
            conversion_id=conversion_id,
            group="salon-kcl",
            index=index,
        )
        path = conversion_dir / f"{index}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written += 1
    return written


def write_conversion_artifacts(
    output_dir: Path,
    dataset_dir_name: str,
    summary: Any,
    details: Any,
) -> dict[str, Any]:
    conversion_id = str(getattr(summary, "id"))
    file_path = str(getattr(summary, "file_path"))
    conversion_dir = output_dir / dataset_dir_name / "output" / safe_relative_path(
        file_path
    )

    output_paths: list[str] = []
    path = conversion_dir / "main.kcl"
    if write_text_artifact(path, getattr(details, "output", None)):
        output_paths.append(path.relative_to(output_dir).as_posix())

    snapshot_count = write_salon_snapshots(
        conversion_dir,
        conversion_id,
        list(getattr(details, "salon_kcl_snapshot_images", []) or []),
    )

    return {
        "id": conversion_id,
        "file_path": file_path,
        "phase": enum_value(getattr(summary, "phase", "")),
        "status": enum_value(getattr(summary, "status", "")),
        "output_paths": output_paths,
        "snapshot_count": snapshot_count,
        "artifact_dir": conversion_dir.relative_to(output_dir).as_posix(),
    }


def scrape_dataset_conversions(
    client: Any,
    *,
    dataset_id: str,
    output_dir: Path,
    filter_text: str | None,
    limit: int | None,
    sort_by: Any,
    dataset: Any | None = None,
) -> ScrapeStats:
    if dataset is None:
        dataset = client.orgs.get_org_dataset(dataset_id)
    dataset_name = str(getattr(dataset, "name"))
    dataset_dir_name = safe_path_part(dataset_name, fallback=dataset_id)
    stats = ScrapeStats(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        output_dir=output_dir,
    )
    log(
        "scraping dataset conversions: "
        f"dataset_id={dataset_id} dataset_name={dataset_name!r} "
        f"filter={filter_text!r} limit={limit!r} sort_by={sort_by!r} "
        f"output_dir={output_dir}"
    )

    conversions = client.orgs.list_org_dataset_conversions(
        dataset_id,
        filter=filter_text,
        limit=limit,
        sort_by=sort_by,
    )
    for summary in conversions:
        stats.seen += 1
        conversion_id = str(getattr(summary, "id"))
        phase = enum_value(getattr(summary, "phase", ""))
        status = enum_value(getattr(summary, "status", ""))
        file_path = str(getattr(summary, "file_path"))
        log(
            "conversion summary: "
            f"id={conversion_id} phase={phase} status={status} file_path={file_path!r}"
        )
        if phase != "completed":
            stats.skipped_phase += 1
            log(f"skipping conversion {conversion_id}: phase={phase}")
            continue

        stats.completed += 1
        details = client.orgs.get_org_dataset_conversion(dataset_id, conversion_id)
        stats.fetched += 1
        record = write_conversion_artifacts(
            output_dir,
            dataset_dir_name,
            summary,
            details,
        )
        stats.outputs_written += len(record["output_paths"])
        stats.snapshots_written += int(record["snapshot_count"])
        stats.conversions.append(record)
        log(
            "conversion written: "
            f"id={conversion_id} outputs={len(record['output_paths'])} "
            f"snapshots={record['snapshot_count']} dir={record['artifact_dir']}"
        )

    return stats


def selected_datasets(client: Any, dataset_id: str | None) -> list[Any]:
    if dataset_id:
        return [client.orgs.get_org_dataset(dataset_id)]
    return list(client.orgs.list_org_datasets())


def scrape_datasets_conversions(
    client: Any,
    *,
    dataset_id: str | None,
    output_dir: Path,
    filter_text: str | None,
    limit: int | None,
    sort_by: Any,
) -> list[ScrapeStats]:
    datasets = selected_datasets(client, dataset_id)
    log(f"selected {len(datasets)} dataset(s)")
    stats: list[ScrapeStats] = []
    for dataset in datasets:
        current_dataset_id = str(getattr(dataset, "id"))
        stats.append(
            scrape_dataset_conversions(
                client,
                dataset_id=current_dataset_id,
                output_dir=output_dir,
                filter_text=filter_text,
                limit=limit,
                sort_by=sort_by,
                dataset=dataset,
            )
        )
    return stats


def total_count(stats: list[ScrapeStats], attr: str) -> int:
    return sum(int(getattr(item, attr)) for item in stats)


def report_for_stats(stats: list[ScrapeStats], *, filter_text: str | None) -> dict[str, Any]:
    conversions: list[dict[str, Any]] = []
    for item in stats:
        for conversion in item.conversions or []:
            conversions.append(
                {
                    **conversion,
                    "dataset_id": item.dataset_id,
                    "dataset_name": item.dataset_name,
                }
            )

    return {
        "output_dir": str(stats[0].output_dir) if stats else "",
        "filter": filter_text,
        "counts": {
            "datasets": len(stats),
            "seen": total_count(stats, "seen"),
            "completed": total_count(stats, "completed"),
            "skipped_phase": total_count(stats, "skipped_phase"),
            "fetched": total_count(stats, "fetched"),
            "outputs_written": total_count(stats, "outputs_written"),
            "snapshots_written": total_count(stats, "snapshots_written"),
        },
        "datasets": [
            {
                "id": item.dataset_id,
                "name": item.dataset_name,
                "counts": {
                    "seen": item.seen,
                    "completed": item.completed,
                    "skipped_phase": item.skipped_phase,
                    "fetched": item.fetched,
                    "outputs_written": item.outputs_written,
                    "snapshots_written": item.snapshots_written,
                },
            }
            for item in stats
        ],
        "conversions": conversions,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_client(*, token: str | None, host: str | None) -> Any:
    try:
        from kittycad import KittyCAD
    except ImportError:
        fail("install the kittycad Python SDK before running this script")

    kwargs: dict[str, Any] = {}
    if host:
        kwargs["base_url"] = host
    if token:
        return KittyCAD(token=token, **kwargs)
    return KittyCAD(**kwargs)


def sdk_sort_mode(value: str | None) -> Any:
    if value is None:
        return None
    try:
        from kittycad import ConversionSortMode
    except ImportError:
        fail("install the kittycad Python SDK before running this script")

    try:
        return ConversionSortMode(value)
    except ValueError:
        fail(f"unsupported sort mode {value!r}; expected one of {sorted(SORT_MODES)}")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-id",
        default=env_first("DATASET_ID", "ORG_DATASET_ID"),
        help=(
            "Optional org dataset UUID to narrow the scrape. If omitted, every org "
            "dataset is scraped. Defaults to DATASET_ID, then ORG_DATASET_ID."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(env_first("DATASET_CONVERSIONS_OUTPUT_DIR") or "dataset-conversions"),
        help="Directory where conversion outputs should be written.",
    )
    parser.add_argument(
        "--filter",
        default=os.getenv("DATASET_CONVERSIONS_FILTER", DEFAULT_FILTER),
        help=f"Dataset conversion filter passed to the SDK. Defaults to {DEFAULT_FILTER!r}.",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=(
            positive_int(value)
            if (value := os.getenv("DATASET_CONVERSIONS_LIMIT"))
            else None
        ),
        help="Optional per-page limit passed to the SDK iterator.",
    )
    parser.add_argument(
        "--sort-by",
        choices=sorted(SORT_MODES),
        default=env_first("DATASET_CONVERSIONS_SORT_BY"),
        help="Optional conversion sort mode passed to the SDK iterator.",
    )
    parser.add_argument(
        "--host",
        help=(
            "Optional API host. If unset, the KittyCAD SDK uses its default host "
            "or the standard ZOO_HOST environment variable."
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Report JSON path. Defaults to <output-dir>/dataset-conversions-report.json.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    token = env_first("KITTYCAD_API_TOKEN", "ZOO_API_TOKEN")
    client = build_client(token=token, host=args.host)
    try:
        stats = scrape_datasets_conversions(
            client,
            dataset_id=args.dataset_id or None,
            output_dir=args.output_dir,
            filter_text=args.filter or None,
            limit=args.limit,
            sort_by=sdk_sort_mode(args.sort_by),
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    report = report_for_stats(stats, filter_text=args.filter or None)
    report_path = args.report or args.output_dir / "dataset-conversions-report.json"
    write_report(report_path, report)
    print(
        "downloaded "
        f"{total_count(stats, 'fetched')} completed conversion(s) "
        f"from {len(stats)} dataset(s), "
        f"wrote {total_count(stats, 'outputs_written')} KCL output file(s) and "
        f"{total_count(stats, 'snapshots_written')} snapshot(s)"
    )
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
