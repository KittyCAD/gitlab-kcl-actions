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
                        "export label = \"old\"",
                        "export enabled = false",
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
                        "export label = \"new\"",
                        "export enabled = true",
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

    def test_apply_parameters_requires_exported_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            params = Path(tmp) / "parameters.kcl"
            params.write_text("width = 20\n", encoding="utf-8")

            with self.assertRaises(kcl_artifacts.WorkflowError):
                kcl_artifacts.apply_parameters(params, json.dumps({"width": 42}))

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

    def test_project_info_lists_root_and_nested_assemblies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            (root / "part.kcl").write_text("", encoding="utf-8")
            nested = root / "assembly-2"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            (nested / "parameters.kcl").write_text("", encoding="utf-8")
            (nested / "part.kcl").write_text("", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(root, assemblies_out, snapshots_out)

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "root\tmain.kcl\tparameters.kcl",
                    "assembly-2\tassembly-2/main.kcl\tassembly-2/parameters.kcl",
                ],
            )
            self.assertEqual(
                snapshots_out.read_text(encoding="utf-8").splitlines(),
                [
                    "main.kcl",
                    "part.kcl",
                    "assembly-2/main.kcl",
                    "assembly-2/part.kcl",
                ],
            )

    def test_project_info_requires_parameters_next_to_each_main_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")

            with self.assertRaises(kcl_artifacts.WorkflowError):
                kcl_artifacts.write_project_info(
                    root,
                    root / "env",
                    root / "snapshots",
                )

    def test_project_info_can_filter_to_selected_main_kcl_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            (root / "part.kcl").write_text("", encoding="utf-8")
            nested = root / "assembly-2"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            (nested / "parameters.kcl").write_text("", encoding="utf-8")
            (nested / "part.kcl").write_text("", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                json.dumps(["assembly-2/main.kcl"]),
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                ["assembly-2\tassembly-2/main.kcl\tassembly-2/parameters.kcl"],
            )
            self.assertEqual(
                snapshots_out.read_text(encoding="utf-8").splitlines(),
                ["assembly-2/main.kcl", "assembly-2/part.kcl"],
            )

    def test_project_info_can_filter_to_one_bare_main_kcl_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "assembly-2"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            (nested / "parameters.kcl").write_text("", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                "assembly-2/main.kcl",
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                ["assembly-2\tassembly-2/main.kcl\tassembly-2/parameters.kcl"],
            )

    def test_project_info_rejects_missing_selected_main_kcl_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(kcl_artifacts.WorkflowError, "missing"):
                kcl_artifacts.write_project_info(
                    root,
                    root / "assemblies.tsv",
                    root / "snapshots.list",
                    json.dumps(["missing/main.kcl"]),
                )

    def test_project_parameters_update_each_matching_parameters_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root_params = root / "parameters.kcl"
            root_params.write_text(
                "export width = 20\nexport height = 12\n",
                encoding="utf-8",
            )
            nested = root / "nested"
            nested.mkdir()
            nested_params = nested / "parameters.kcl"
            nested_params.write_text(
                "export height = 10\nexport depth = 5\n",
                encoding="utf-8",
            )
            assemblies = root / "assemblies.tsv"
            assemblies.write_text(
                "\n".join(
                    [
                        "root\tmain.kcl\tparameters.kcl",
                        "nested\tnested/main.kcl\tnested/parameters.kcl",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            kcl_artifacts.apply_project_parameters(
                root,
                assemblies,
                json.dumps({"width": 24, "height": 99}),
            )

            self.assertEqual(
                root_params.read_text(encoding="utf-8"),
                "export width = 24\nexport height = 99\n",
            )
            self.assertEqual(
                nested_params.read_text(encoding="utf-8"),
                "export height = 99\nexport depth = 5\n",
            )

    def test_project_parameters_fail_when_key_is_missing_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "parameters.kcl").write_text("export width = 20\n", encoding="utf-8")
            assemblies = root / "assemblies.tsv"
            assemblies.write_text("root\tmain.kcl\tparameters.kcl\n", encoding="utf-8")

            with self.assertRaisesRegex(kcl_artifacts.WorkflowError, "not exported"):
                kcl_artifacts.apply_project_parameters(
                    root,
                    assemblies,
                    json.dumps({"depth": 5}),
                )

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

    def test_bounding_box_json_extracts_shape_from_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis.json"
            analysis.write_text(
                json.dumps(
                    {
                        "bounding_box": {
                            "center": {"x": 0, "y": 1, "z": 2},
                            "dimensions": {"x": 10, "y": 20, "z": 30},
                        }
                    }
                ),
                encoding="utf-8",
            )
            output = root / "bounding-box.json"

            kcl_artifacts.write_bounding_box_json(analysis, output, "mm")

            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                {
                    "center": {"x": 0, "y": 1, "z": 2},
                    "dimensions": {"x": 10, "y": 20, "z": 30},
                    "output_unit": "mm",
                },
            )


if __name__ == "__main__":
    unittest.main()
