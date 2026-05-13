from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tempfile
import unittest

from scripts import dataset_conversions


@dataclass
class FakeDataset:
    id: str
    name: str


@dataclass
class FakeSummary:
    id: str
    file_path: str
    phase: str = "completed"
    status: str = "success"


@dataclass
class FakeImage:
    data_base64: bytes
    mime_type: str = "image/png"


@dataclass
class FakeDetails:
    output: str | None = None
    salon_kcl_snapshot_images: list[FakeImage] = field(default_factory=list)


class FakeOrgs:
    def __init__(self) -> None:
        self.list_kwargs: dict[str, object] | None = None
        self.detail_calls: list[tuple[str, str]] = []

    def get_org_dataset(self, dataset_id: str) -> FakeDataset:
        self.dataset_id = dataset_id
        return FakeDataset(dataset_id, "Demo Dataset!*")

    def list_org_datasets(self) -> list[FakeDataset]:
        return [
            FakeDataset("dataset-1", "Demo Dataset!*"),
            FakeDataset("dataset-2", "Other Dataset"),
        ]

    def list_org_dataset_conversions(
        self,
        dataset_id: str,
        **kwargs: object,
    ) -> list[FakeSummary]:
        self.list_dataset_id = dataset_id
        self.list_kwargs = kwargs
        return [
            FakeSummary("conversion-1", "folder/model.step"),
            FakeSummary("conversion-2", "folder/skipped.step", phase="queued"),
        ]

    def get_org_dataset_conversion(
        self,
        dataset_id: str,
        conversion_id: str,
    ) -> FakeDetails:
        self.detail_calls.append((dataset_id, conversion_id))
        return FakeDetails(
            output="main",
            salon_kcl_snapshot_images=[FakeImage(b"salon-image")],
        )


class FakeClient:
    def __init__(self) -> None:
        self.orgs = FakeOrgs()


class DatasetConversionsTests(unittest.TestCase):
    def test_safe_relative_path_rejects_traversal(self) -> None:
        with self.assertRaisesRegex(SystemExit, "cannot traverse"):
            dataset_conversions.safe_relative_path("../nope.step")

    def test_scrape_uses_sdk_org_surface_and_writes_conversion_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "dataset-conversions"
            client = FakeClient()

            stats = dataset_conversions.scrape_dataset_conversions(
                client,
                dataset_id="dataset-1",
                output_dir=output_dir,
            )

            self.assertEqual(client.orgs.dataset_id, "dataset-1")
            self.assertEqual(client.orgs.list_dataset_id, "dataset-1")
            self.assertEqual(
                client.orgs.list_kwargs,
                {
                    "filter": "status=success",
                },
            )
            self.assertEqual(client.orgs.detail_calls, [("dataset-1", "conversion-1")])
            self.assertEqual(stats.seen, 2)
            self.assertEqual(stats.completed, 1)
            self.assertEqual(stats.skipped_phase, 1)
            self.assertEqual(stats.outputs_written, 1)
            self.assertEqual(stats.snapshots_written, 1)

            conversion_dir = (
                output_dir / "Demo Dataset" / "output" / "folder" / "model.step"
            )
            self.assertEqual((conversion_dir / "main.kcl").read_text(), "main")
            self.assertEqual((conversion_dir / "0.png").read_bytes(), b"salon-image")

    def test_scrape_without_dataset_id_lists_all_org_datasets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "dataset-conversions"
            client = FakeClient()

            stats = dataset_conversions.scrape_datasets_conversions(
                client,
                dataset_id=None,
                output_dir=output_dir,
            )

            self.assertEqual([item.dataset_id for item in stats], ["dataset-1", "dataset-2"])
            self.assertEqual(dataset_conversions.total_count(stats, "fetched"), 2)
            self.assertEqual(dataset_conversions.total_count(stats, "outputs_written"), 2)

    def test_non_png_snapshot_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            summary = FakeSummary("conversion-1", "model.step")
            details = FakeDetails(
                output="main",
                salon_kcl_snapshot_images=[FakeImage(b"data", mime_type="image/jpeg")],
            )

            with self.assertRaisesRegex(SystemExit, "unsupported mime type"):
                dataset_conversions.write_conversion_artifacts(
                    output_dir,
                    "dataset",
                    summary,
                    details,
                )


if __name__ == "__main__":
    unittest.main()
