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


def test_production_probe_covers_complete_reference_month() -> None:
    workflow = (ROOT / ".github" / "workflows" / "probe-wikidata.yml").read_text(encoding="utf-8")
    assert "timeout-minutes: 30" in workflow
    assert "--start 2025-01-01T00:00:00Z" in workflow
    assert "--end 2025-02-01T00:00:00Z" in workflow
    assert "--limit 1000" in workflow


def test_production_probe_builds_and_uploads_validated_release() -> None:
    workflow = (ROOT / ".github" / "workflows" / "probe-wikidata.yml").read_text(encoding="utf-8")
    assert "from media_catalog_builder.probe_release import build_probe_release" in workflow
    assert "probe-release-summary.json" in workflow
    assert "probe-release" in workflow
    assert "PACKAGE_EXIT_CODE" in workflow


def test_annual_probe_is_resumable_and_packages_complete_2025() -> None:
    workflow = (ROOT / ".github" / "workflows" / "probe-wikidata-year.yml").read_text(
        encoding="utf-8"
    )
    assert "timeout-minutes: 120" in workflow
    assert "actions/cache/restore@v4" in workflow
    assert "actions/cache/save@v4" in workflow
    assert "if: always()" in workflow
    assert "--year 2025" in workflow
    assert "--limit 5000" in workflow
    assert 'version="2026.07.24"' in workflow
    assert "year-2025" not in workflow
    assert "build_probe_release" in workflow
    assert "probe-results/year-2025.json" in workflow
    assert "annual-skip-audit.json" in workflow


def test_annual_probe_uses_full_configured_retry_budget() -> None:
    script = (BUILDER / "scripts" / "probe_wikidata_year.py").read_text(encoding="utf-8")
    assert "request_retries=config.request_retries" in script
    assert "request_retries=min(config.request_retries, 2)" not in script


def test_codeql_scans_python_on_pull_requests_and_weekly() -> None:
    workflow = (ROOT / ".github" / "workflows" / "codeql.yml").read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "schedule:" in workflow
    assert "security-events: write" in workflow
    assert "github/codeql-action/init@v4" in workflow
    assert "github/codeql-action/analyze@v4" in workflow
    assert "languages: python" in workflow
