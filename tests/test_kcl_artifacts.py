from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import kcl_artifacts


class KclArtifactsTests(unittest.TestCase):
    def test_apply_parameters_replaces_existing_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            params = Path(tmp) / "parameters.kcl"
            params.write_text(
                "\n".join(
                    [
                        "@settings(defaultLengthUnit = mm)",
                        "export width = 20 // keep this",
                        "label = \"old\"",
                        "enabled = false",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            kcl_artifacts.apply_parameters(
                params,
                json.dumps({"width": 42, "label": "new", "enabled": True}),
            )

            self.assertEqual(
                params.read_text(encoding="utf-8"),
                "\n".join(
                    [
                        "@settings(defaultLengthUnit = mm)",
                        "export width = 42 // keep this",
                        "label = \"new\"",
                        "enabled = true",
                    ]
                )
                + "\n",
            )

    def test_apply_parameters_can_override_one_of_many_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            params = Path(tmp) / "parameters.kcl"
            params.write_text(
                "\n".join(
                    [
                        "export width = 20",
                        "export height = 12",
                        "export depth = 8",
                        "export radius = 4",
                        "export count = 5",
                        "export label = \"old\"",
                        "export enabled = false",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            kcl_artifacts.apply_parameters(params, json.dumps({"height": 99}))

            self.assertEqual(
                params.read_text(encoding="utf-8"),
                "\n".join(
                    [
                        "export width = 20",
                        "export height = 99",
                        "export depth = 8",
                        "export radius = 4",
                        "export count = 5",
                        "export label = \"old\"",
                        "export enabled = false",
                    ]
                )
                + "\n",
            )

    def test_apply_parameters_fails_for_unknown_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            params = Path(tmp) / "parameters.kcl"
            params.write_text("export width = 20\n", encoding="utf-8")

            with self.assertRaises(kcl_artifacts.WorkflowError):
                kcl_artifacts.apply_parameters(params, '{"depth": 10}')

    def test_apply_parameters_requires_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            params = Path(tmp) / "parameters.kcl"
            params.write_text("export width = 20\n", encoding="utf-8")

            with self.assertRaises(kcl_artifacts.WorkflowError):
                kcl_artifacts.apply_parameters(params, '["nope"]')

    def test_project_info_requires_single_main_and_parameters_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            (root / "part.kcl").write_text("", encoding="utf-8")
            env_out = root / "project.env"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(root, env_out, snapshots_out)

            self.assertIn("MAIN_KCL=main.kcl", env_out.read_text(encoding="utf-8"))
            self.assertEqual(
                snapshots_out.read_text(encoding="utf-8").splitlines(),
                ["main.kcl", "part.kcl"],
            )

    def test_project_info_fails_for_multiple_main_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")

            with self.assertRaises(kcl_artifacts.WorkflowError):
                kcl_artifacts.write_project_info(root, root / "env", root / "snapshots")

    def test_metadata_validation_requires_all_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metadata = Path(tmp) / "metadata.json"
            metadata.write_text('{"material_density": 1}', encoding="utf-8")

            with self.assertRaises(kcl_artifacts.WorkflowError):
                kcl_artifacts.validate_metadata(metadata)

    def test_metadata_validation_accepts_required_shape(self) -> None:
        metadata = kcl_artifacts.validate_metadata(
            Path(__file__).parent / "fixtures" / "basic" / "metadata.json"
        )

        self.assertEqual(metadata["material_density"], 7850)

    def test_metadata_env_quotes_values_with_shell_metacharacters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "material_density": 1,
                        "material_density_unit": "kg:m3",
                        "mass_output_unit": "kg",
                        "volume_output_unit": "cm3",
                        "density_output_unit": "kg:m3",
                        "surface_area_output_unit": "cm2",
                        "center_of_mass_output_unit": "mm",
                        "bounding_box_output_unit": "millimeters please",
                    }
                ),
                encoding="utf-8",
            )
            env_out = root / "metadata.env"

            kcl_artifacts.write_metadata_env(metadata, env_out)

            self.assertIn("BOUNDING_BOX_OUTPUT_UNIT='millimeters please'", env_out.read_text())


if __name__ == "__main__":
    unittest.main()
