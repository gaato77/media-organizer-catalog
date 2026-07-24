import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "builder"


def test_pyproject_configures_ruff_and_mypy() -> None:
    with (BUILDER / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)

    test_dependencies = config["project"]["optional-dependencies"]["test"]
    assert any(dependency.startswith("ruff") for dependency in test_dependencies)
    assert any(dependency.startswith("mypy") for dependency in test_dependencies)
    assert any(dependency.startswith("types-requests") for dependency in test_dependencies)

    assert config["tool"]["ruff"]["target-version"] == "py312"
    assert config["tool"]["ruff"]["lint"]["select"] == ["E", "F", "I", "UP", "B", "SIM"]
    assert config["tool"]["mypy"]["python_version"] == "3.12"
    assert config["tool"]["mypy"]["strict"] is True


def test_ci_runs_tests_lint_format_and_types() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python -m pytest builder/tests -q" in workflow
    assert "python -m ruff check builder" in workflow
    assert "python -m ruff format --check builder" in workflow
    assert "python -m mypy builder/src/media_catalog_builder" in workflow


def test_codeql_scans_python_on_pull_requests_and_weekly() -> None:
    workflow = (ROOT / ".github" / "workflows" / "codeql.yml").read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "schedule:" in workflow
    assert "security-events: write" in workflow
    assert "github/codeql-action/init@v4" in workflow
    assert "github/codeql-action/analyze@v4" in workflow
    assert "languages: python" in workflow
