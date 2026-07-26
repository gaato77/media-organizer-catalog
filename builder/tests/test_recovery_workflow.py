from pathlib import Path

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
    assert 'version="2026.07.25"' in workflow
    assert "2026.07.25-recovered" not in workflow
    assert "if: always()" in workflow
    assert "for directory in" in workflow
    assert "if: always() && steps.package.outcome == 'success'" in workflow
    assert "if: always() && steps.package.outcome != 'success'" in workflow
    assert "recovery-diagnostics-1950-2015" in workflow
    assert "complete-1950-2015-catalog-recovered" in workflow
