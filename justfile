set shell := ["bash", "-euo", "pipefail", "-c"]

python_files := `git ls-files 'scripts/*.py' 'tests/*.py' | tr '\n' ' '`

default: check

sync:
    uv sync --all-groups

ci-sync:
    uv sync --all-groups --frozen

format:
    uv run ruff check --fix {{python_files}} pyproject.toml
    uv run ruff format {{python_files}}

lint:
    uv run ruff check {{python_files}} pyproject.toml
    uv run ruff format --check {{python_files}}
    uv run ty check {{python_files}}

unit-test:
    uv run python -m unittest tests.test_dataset_conversions tests.test_kcl_artifacts -v

test:
    uv run python -m unittest discover -s tests -v

shell:
    bash -n scripts/*.sh tests/*.sh

generated:
    uv run python scripts/render_component.py --check

check: lint unit-test shell generated

kcl-artifact-workflow:
    tests/test_kcl_artifact_workflow.sh
