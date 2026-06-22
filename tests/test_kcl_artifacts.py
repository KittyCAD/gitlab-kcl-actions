from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import kcl_artifacts

REQUIRED_METADATA = {
    "material_density": 7850,
    "material_density_unit": "kg:m3",
    "mass_output_unit": "kg",
    "volume_output_unit": "cm3",
    "density_output_unit": "kg:m3",
    "surface_area_output_unit": "cm2",
    "center_of_mass_output_unit": "mm",
    "bounding_box_output_unit": "mm",
}


def write_metadata(path: Path, **overrides: object) -> None:
    metadata = REQUIRED_METADATA | overrides
    path.write_text(json.dumps(metadata), encoding="utf-8")


class KclArtifactsTests(unittest.TestCase):
    def test_apply_parameters_replaces_existing_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            params = Path(tmp) / "parameters.kcl"
            params.write_text(
                "\n".join(
                    [
                        "@settings(defaultLengthUnit = mm)",
                        "export width = 20 // keep this",
                        'export label = "old"',
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
                        'export label = "new"',
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
                        'export label = "old"',
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
                        'export label = "old"',
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

    def test_project_info_lists_every_kcl_file_as_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "part.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")
            nested = root / "assembly-2"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            (nested / "part.kcl").write_text("", encoding="utf-8")
            (nested / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(nested / "metadata.json")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(root, assemblies_out, snapshots_out)

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "main\tmain.kcl\tparameters.kcl\tmetadata.json",
                    "part\tpart.kcl\tparameters.kcl\tmetadata.json",
                    "assembly-2/main\tassembly-2/main.kcl\tassembly-2/parameters.kcl\tassembly-2/metadata.json",
                    "assembly-2/part\tassembly-2/part.kcl\tassembly-2/parameters.kcl\tassembly-2/metadata.json",
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

    def test_project_info_uses_file_stem_path_as_assembly_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cube.kcl").write_text("", encoding="utf-8")
            chair = root / "chair"
            chair.mkdir()
            (chair / "leg.kcl").write_text("", encoding="utf-8")
            (chair / "seat.kcl").write_text("", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                kcl_artifacts.write_project_info(root, assemblies_out, snapshots_out)

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "cube\tcube.kcl\t-\t-",
                    "chair/leg\tchair/leg.kcl\t-\t-",
                    "chair/seat\tchair/seat.kcl\t-\t-",
                ],
            )
            self.assertEqual(
                snapshots_out.read_text(encoding="utf-8").splitlines(),
                ["cube.kcl", "chair/leg.kcl", "chair/seat.kcl"],
            )

    def test_project_info_shares_folder_parameters_across_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.kcl").write_text("", encoding="utf-8")
            (root / "b.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(root, assemblies_out, snapshots_out)

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "a\ta.kcl\tparameters.kcl\tmetadata.json",
                    "b\tb.kcl\tparameters.kcl\tmetadata.json",
                ],
            )

    def test_project_info_fails_when_no_kcl_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(kcl_artifacts.WorkflowError, "no .kcl files"):
                kcl_artifacts.write_project_info(
                    root,
                    root / "assemblies.tsv",
                    root / "snapshots.list",
                )

    def test_project_info_can_use_custom_parameters_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "inputs.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                parameters_filename="inputs.kcl",
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                ["main\tmain.kcl\tinputs.kcl\tmetadata.json"],
            )
            self.assertEqual(
                snapshots_out.read_text(encoding="utf-8").splitlines(),
                ["main.kcl"],
            )

    def test_project_info_warns_for_missing_parameters_when_overrides_are_supplied(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                kcl_artifacts.write_project_info(
                    root,
                    assemblies_out,
                    snapshots_out,
                    parameters_json=json.dumps({"width": 24}),
                )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8"),
                "main\tmain.kcl\t-\tmetadata.json\n",
            )
            self.assertIn("parameters file was not found", stderr.getvalue())

    def test_project_info_can_use_custom_metadata_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "mass-properties.json")
            nested = root / "assembly-2"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            (nested / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(nested / "mass-properties.json")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                metadata_path="mass-properties.json",
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "main\tmain.kcl\tparameters.kcl\tmass-properties.json",
                    "assembly-2/main\tassembly-2/main.kcl\tassembly-2/parameters.kcl\tassembly-2/mass-properties.json",
                ],
            )

    def test_project_info_can_use_shared_metadata_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config"
            config.mkdir()
            write_metadata(config / "kcl-metadata.json")
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
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
                metadata_path="config/kcl-metadata.json",
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "main\tmain.kcl\tparameters.kcl\tconfig/kcl-metadata.json",
                    "assembly-2/main\tassembly-2/main.kcl\tassembly-2/parameters.kcl\tconfig/kcl-metadata.json",
                ],
            )

    def test_project_info_allows_missing_parameters_without_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")
            nested = root / "nested"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            write_metadata(nested / "metadata.json")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                kcl_artifacts.write_project_info(
                    root,
                    assemblies_out,
                    snapshots_out,
                )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "main\tmain.kcl\tparameters.kcl\tmetadata.json",
                    "nested/main\tnested/main.kcl\t-\tnested/metadata.json",
                ],
            )
            self.assertEqual(stderr.getvalue(), "")

    def test_project_info_allows_missing_metadata_next_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")
            nested = root / "nested"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            (nested / "parameters.kcl").write_text("", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "main\tmain.kcl\tparameters.kcl\tmetadata.json",
                    "nested/main\tnested/main.kcl\tnested/parameters.kcl\t-",
                ],
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
            write_metadata(nested / "metadata.json")
            (nested / "part.kcl").write_text("", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                json.dumps(["assembly-2/main.kcl", "assembly-2/part.kcl"]),
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "assembly-2/main\tassembly-2/main.kcl\tassembly-2/parameters.kcl\tassembly-2/metadata.json",
                    "assembly-2/part\tassembly-2/part.kcl\tassembly-2/parameters.kcl\tassembly-2/metadata.json",
                ],
            )
            self.assertEqual(
                snapshots_out.read_text(encoding="utf-8").splitlines(),
                ["assembly-2/main.kcl", "assembly-2/part.kcl"],
            )

    def test_project_info_rejects_selecting_parameters_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(kcl_artifacts.WorkflowError, "parameters file"):
                kcl_artifacts.write_project_info(
                    root,
                    root / "assemblies.tsv",
                    root / "snapshots.list",
                    json.dumps(["parameters.kcl"]),
                )

    def test_project_info_changed_file_selects_only_that_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "part.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")
            changed_files = root / "changed-files.list"
            changed_files.write_text("part.kcl\n", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                changed_files_file=changed_files,
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                ["part\tpart.kcl\tparameters.kcl\tmetadata.json"],
            )
            self.assertEqual(
                snapshots_out.read_text(encoding="utf-8").splitlines(),
                ["part.kcl"],
            )

    def test_project_info_changed_parameters_file_selects_folder_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "part.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")
            nested = root / "assembly-2"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            (nested / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(nested / "metadata.json")
            changed_files = root / "changed-files.list"
            changed_files.write_text("parameters.kcl\n", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                changed_files_file=changed_files,
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "main\tmain.kcl\tparameters.kcl\tmetadata.json",
                    "part\tpart.kcl\tparameters.kcl\tmetadata.json",
                ],
            )

    def test_project_info_changed_sibling_metadata_selects_folder_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "part.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")
            changed_files = root / "changed-files.list"
            changed_files.write_text("metadata.json\n", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                changed_files_file=changed_files,
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "main\tmain.kcl\tparameters.kcl\tmetadata.json",
                    "part\tpart.kcl\tparameters.kcl\tmetadata.json",
                ],
            )

    def test_project_info_allows_no_changed_kcl_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "readme.md").write_text("", encoding="utf-8")
            nested = root / "assembly-2"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            (nested / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(nested / "metadata.json")
            changed_files = root / "changed-files.list"
            changed_files.write_text("docs/readme.md\n", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                changed_files_file=changed_files,
            )

            self.assertEqual(assemblies_out.read_text(encoding="utf-8"), "")
            self.assertEqual(snapshots_out.read_text(encoding="utf-8"), "")

    def test_project_info_allows_no_kcl_files_when_selecting_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed_files = root / "changed-files.list"
            changed_files.write_text("README.md\n", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                changed_files_file=changed_files,
            )

            self.assertEqual(assemblies_out.read_text(encoding="utf-8"), "")
            self.assertEqual(snapshots_out.read_text(encoding="utf-8"), "")

    def test_project_info_can_filter_to_one_bare_main_kcl_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "assembly-2"
            nested.mkdir()
            (nested / "design.kcl").write_text("", encoding="utf-8")
            (nested / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(nested / "metadata.json")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                "assembly-2/design.kcl",
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "assembly-2/design\tassembly-2/design.kcl\tassembly-2/parameters.kcl\tassembly-2/metadata.json"
                ],
            )

    def test_project_info_selects_all_assemblies_when_shared_metadata_path_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config"
            config.mkdir()
            write_metadata(config / "kcl-metadata.json")
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            nested = root / "assembly-2"
            nested.mkdir()
            (nested / "main.kcl").write_text("", encoding="utf-8")
            (nested / "parameters.kcl").write_text("", encoding="utf-8")
            changed_files = root / "changed-files.list"
            changed_files.write_text("config/kcl-metadata.json\n", encoding="utf-8")
            assemblies_out = root / "assemblies.tsv"
            snapshots_out = root / "snapshots.list"

            kcl_artifacts.write_project_info(
                root,
                assemblies_out,
                snapshots_out,
                changed_files_file=changed_files,
                metadata_path="config/kcl-metadata.json",
            )

            self.assertEqual(
                assemblies_out.read_text(encoding="utf-8").splitlines(),
                [
                    "main\tmain.kcl\tparameters.kcl\tconfig/kcl-metadata.json",
                    "assembly-2/main\tassembly-2/main.kcl\tassembly-2/parameters.kcl\tconfig/kcl-metadata.json",
                ],
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

    def test_project_info_rejects_nested_parameters_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")

            with self.assertRaisesRegex(kcl_artifacts.WorkflowError, "parameters_filename"):
                kcl_artifacts.write_project_info(
                    root,
                    root / "assemblies.tsv",
                    root / "snapshots.list",
                    parameters_filename="config/parameters.kcl",
                )

    def test_project_info_rejects_non_json_metadata_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            (root / "parameters.kcl").write_text("", encoding="utf-8")
            write_metadata(root / "metadata.json")

            with self.assertRaisesRegex(kcl_artifacts.WorkflowError, "metadata_path"):
                kcl_artifacts.write_project_info(
                    root,
                    root / "assemblies.tsv",
                    root / "snapshots.list",
                    metadata_path="config/metadata.kcl",
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
                        "root\tmain.kcl\tparameters.kcl\tmetadata.json",
                        "nested\tnested/main.kcl\tnested/parameters.kcl\tnested/metadata.json",
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

    def test_project_parameters_skip_assemblies_without_parameters_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            nested_params = nested / "parameters.kcl"
            nested_params.write_text("export height = 10\n", encoding="utf-8")
            assemblies = root / "assemblies.tsv"
            assemblies.write_text(
                "\n".join(
                    [
                        "root\tmain.kcl\t-\tmetadata.json",
                        "nested\tnested/main.kcl\tnested/parameters.kcl\tnested/metadata.json",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            kcl_artifacts.apply_project_parameters(
                root,
                assemblies,
                json.dumps({"height": 99}),
            )

            self.assertEqual(nested_params.read_text(encoding="utf-8"), "export height = 99\n")

    def test_project_parameters_fail_when_key_is_missing_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "parameters.kcl").write_text("export width = 20\n", encoding="utf-8")
            assemblies = root / "assemblies.tsv"
            assemblies.write_text(
                "root\tmain.kcl\tparameters.kcl\tmetadata.json\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(kcl_artifacts.WorkflowError, "not exported"):
                kcl_artifacts.apply_project_parameters(
                    root,
                    assemblies,
                    json.dumps({"depth": 5}),
                )

    def test_project_parameters_fail_when_no_selected_assembly_has_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assemblies = root / "assemblies.tsv"
            assemblies.write_text(
                "root\tmain.kcl\t-\tmetadata.json\n",
                encoding="utf-8",
            )

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

    def test_source_copy_skips_missing_optional_support_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.kcl").write_text("", encoding="utf-8")
            assemblies = root / "assemblies.tsv"
            assemblies.write_text("root\tmain.kcl\t-\t-\n", encoding="utf-8")
            snapshots = root / "snapshots.list"
            snapshots.write_text("main.kcl\n", encoding="utf-8")
            output = root / "source"

            kcl_artifacts.write_source_files(root, snapshots, assemblies, output)

            self.assertTrue((output / "main.kcl").is_file())
            self.assertEqual(list(output.rglob("*")), [output / "main.kcl"])

    def test_manifest_saves_parameter_overrides_for_upload_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "kcl-artifacts"
            artifact_dir.mkdir()
            assemblies = root / "assemblies.tsv"
            assemblies.write_text(
                "root\tmain.kcl\tparameters.kcl\tmetadata.json\n",
                encoding="utf-8",
            )
            (artifact_dir / "source").mkdir()
            (artifact_dir / "source" / "parameters.kcl").write_text(
                "export thing = 2\n",
                encoding="utf-8",
            )

            kcl_artifacts.write_manifest(
                artifact_dir,
                assemblies,
                "v1",
                "",
                json.dumps({"thing": 2, "label": "hello world"}),
            )

            self.assertEqual(
                json.loads((artifact_dir / "parameters.json").read_text(encoding="utf-8")),
                {"label": "hello world", "thing": 2},
            )
            manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["assemblies"],
                [
                    {
                        "id": "root",
                        "main_kcl": "main.kcl",
                        "metadata_json": "metadata.json",
                        "parameters_kcl": "parameters.kcl",
                    }
                ],
            )
            self.assertEqual(manifest["parameters_json"], "parameters.json")
            self.assertEqual(manifest["parameters_override_keys"], ["label", "thing"])
            self.assertEqual(
                manifest["parameters_overrides"],
                {"label": "hello world", "thing": 2},
            )
            self.assertIn("parameters.json", manifest["artifacts"])

    def test_manifest_records_missing_optional_support_files_as_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "kcl-artifacts"
            artifact_dir.mkdir()
            assemblies = root / "assemblies.tsv"
            assemblies.write_text(
                "root\tmain.kcl\t-\t-\n",
                encoding="utf-8",
            )

            kcl_artifacts.write_manifest(artifact_dir, assemblies, "v1", "", "{}")

            manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["assemblies"],
                [
                    {
                        "id": "root",
                        "main_kcl": "main.kcl",
                        "metadata_json": None,
                        "parameters_kcl": None,
                    }
                ],
            )
            self.assertIsNone(manifest["parameters_json"])

    def test_manifest_fails_parameter_overrides_without_parameters_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "kcl-artifacts"
            artifact_dir.mkdir()
            assemblies = root / "assemblies.tsv"
            assemblies.write_text(
                "root\tmain.kcl\t-\tmetadata.json\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(kcl_artifacts.WorkflowError, "parameters file"):
                kcl_artifacts.write_manifest(
                    artifact_dir,
                    assemblies,
                    "v1",
                    "",
                    json.dumps({"thing": 2}),
                )

    def test_manifest_names_parameter_overrides_after_stemmed_parameters_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "kcl-artifacts"
            artifact_dir.mkdir()
            assemblies = root / "assemblies.tsv"
            assemblies.write_text(
                "root\tassembly.kcl\tassembly-parameters.kcl\tassembly-metadata.json\n",
                encoding="utf-8",
            )

            kcl_artifacts.write_manifest(
                artifact_dir,
                assemblies,
                "v1",
                "",
                json.dumps({"thing": 2}),
            )

            self.assertEqual(
                json.loads((artifact_dir / "assembly-parameters.json").read_text()),
                {"thing": 2},
            )
            self.assertFalse((artifact_dir / "parameters.json").exists())
            manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["parameters_json"], "assembly-parameters.json")
            self.assertIn("assembly-parameters.json", manifest["artifacts"])

    def test_manifest_names_parameter_overrides_after_custom_parameters_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "kcl-artifacts"
            artifact_dir.mkdir()
            assemblies = root / "assemblies.tsv"
            assemblies.write_text(
                "root\tassembly.kcl\tinputs.kcl\tmetadata.json\n",
                encoding="utf-8",
            )

            kcl_artifacts.write_manifest(
                artifact_dir,
                assemblies,
                "v1",
                "",
                json.dumps({"thing": 2}),
            )

            self.assertEqual(
                json.loads((artifact_dir / "inputs.json").read_text()),
                {"thing": 2},
            )
            manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["parameters_json"], "inputs.json")
            self.assertIn("inputs.json", manifest["artifacts"])

    def test_manifest_uses_default_parameter_override_name_for_mixed_parameter_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "kcl-artifacts"
            artifact_dir.mkdir()
            assemblies = root / "assemblies.tsv"
            assemblies.write_text(
                "\n".join(
                    [
                        "root\tassembly.kcl\tassembly-parameters.kcl\tmetadata.json",
                        "other\tother/assembly.kcl\tother/assembly_parameters.kcl\tother/metadata.json",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            kcl_artifacts.write_manifest(
                artifact_dir,
                assemblies,
                "v1",
                "",
                json.dumps({"thing": 2}),
            )

            manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["parameters_json"], "parameters.json")
            self.assertIn("parameters.json", manifest["artifacts"])


if __name__ == "__main__":
    unittest.main()
