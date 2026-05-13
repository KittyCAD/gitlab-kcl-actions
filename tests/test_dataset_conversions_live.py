from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from scripts import dataset_conversions


def live_token() -> str | None:
    return os.getenv("KITTYCAD_API_TOKEN") or os.getenv("ZOO_API_TOKEN")


class DatasetConversionsLiveTests(unittest.TestCase):
    def test_live_api_scrapes_successful_conversion_with_sdk(self) -> None:
        try:
            import kittycad  # noqa: F401
        except ImportError:
            self.fail("install the kittycad Python SDK to run the live scrape test")

        token = live_token()
        self.assertTrue(
            token,
            "set KITTYCAD_API_TOKEN or ZOO_API_TOKEN to run the live scrape test",
        )
        host = os.getenv("DATASET_CONVERSIONS_LIVE_HOST") or os.getenv("ZOO_HOST")
        filter_text = os.getenv("DATASET_CONVERSIONS_LIVE_FILTER", "status=success")
        limit = int(os.getenv("DATASET_CONVERSIONS_LIVE_LIMIT", "1"))

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "dataset-conversions"
            client = dataset_conversions.build_client(token=token, host=host)
            try:
                stats = dataset_conversions.scrape_datasets_conversions(
                    client,
                    dataset_id=None,
                    output_dir=output_dir,
                    filter_text=filter_text,
                    limit=limit,
                    sort_by=None,
                )
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    close()

            report = dataset_conversions.report_for_stats(
                stats,
                filter_text=filter_text,
            )
            report_path = output_dir / "dataset-conversions-report.json"
            dataset_conversions.write_report(report_path, report)

            self.assertGreater(
                dataset_conversions.total_count(stats, "seen"),
                0,
                "live dataset did not return any successful conversions",
            )
            self.assertGreater(
                dataset_conversions.total_count(stats, "fetched"),
                0,
                "live org datasets did not have any completed successful conversions",
            )
            self.assertGreater(
                dataset_conversions.total_count(stats, "outputs_written"),
                0,
                "live conversion details did not include converted KCL output",
            )
            self.assertTrue(report_path.is_file())
            self.assertTrue(list(output_dir.rglob("main.kcl")))


if __name__ == "__main__":
    unittest.main()
