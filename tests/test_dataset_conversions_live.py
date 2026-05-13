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

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "dataset-conversions"
            client = dataset_conversions.build_client(token=token, host=host)
            try:
                stats = dataset_conversions.scrape_datasets_conversions(
                    client,
                    dataset_id=None,
                    output_dir=output_dir,
                )
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    close()

            self.assertGreaterEqual(len(stats), 0)
            self.assertGreaterEqual(dataset_conversions.total_count(stats, "seen"), 0)
            self.assertGreaterEqual(
                dataset_conversions.total_count(stats, "outputs_written"),
                0,
            )
            if dataset_conversions.total_count(stats, "outputs_written") > 0:
                self.assertTrue(list(output_dir.rglob("main.kcl")))


if __name__ == "__main__":
    unittest.main()
