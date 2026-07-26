import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_1950_2015_recovery_reuses_existing_artifacts_and_keeps_diagnostics() -> None:
    workflow = (ROOT / ".github" / "workflows" / "recover-1950-2015.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "30157271026" in workflow
    assert "run-id: 30157271026" in workflow
    assert "github-token: ${{ secrets.GITHUB_TOKEN }}" in workflow
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in workflow
    assert "pattern: year-*" in workflow
    assert "probe_wikidata_year.py" not in workflow
    assert "consolidate_year_shards.py" in workflow
    assert "required_year_range=(1950, 2015)" in workflow
    assert "version=version" in workflow
    assert "2026.07.25-recovered" not in workflow
    assert "if: always()" in workflow
    assert "for directory in" in workflow
    assert "if: always() && steps.package.outcome == 'success'" in workflow
    assert "if: always() && steps.package.outcome != 'success'" in workflow
    assert "recovery-diagnostics-1950-2015" in workflow
    assert "complete-1950-2015-catalog-recovered" in workflow


def test_1950_2015_recovery_validates_and_propagates_immutable_release_version() -> None:
    workflow = (ROOT / ".github" / "workflows" / "recover-1950-2015.yml").read_text(
        encoding="utf-8"
    )

    assert 'version:\n        description: "Release version in YYYY.MM.DD format"' in workflow
    assert "VERSION: ${{ inputs.version || '2026.07.25' }}" in workflow
    assert 'datetime.strptime(version, "%Y.%m.%d")' in workflow
    assert "RELEASE_TAG: base-1950-2015-${{ inputs.version }}" in workflow
    assert '--title "Base catalog 1950-2015 — ${VERSION}"' in workflow
    assert '--published-at "${published_at}"' in workflow


@pytest.mark.parametrize("version", ["2026.7.26", "2026.07.2"])
def test_1950_2015_recovery_rejects_noncanonical_release_versions(version: str) -> None:
    workflow = (ROOT / ".github" / "workflows" / "recover-1950-2015.yml").read_text(
        encoding="utf-8"
    )
    preflight_python = workflow.split("python - <<'PY'", maxsplit=1)[1].split(
        "\n          PY", maxsplit=1
    )[0]
    code = "\n".join(line.removeprefix("          ") for line in preflight_python.splitlines())
    env = os.environ | {"VERSION": version, "SOURCE_RUN_ID": "30200783910"}

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert result.returncode != 0
    assert "Version must match YYYY.MM.DD" in result.stderr
