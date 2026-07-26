from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_current_year_workflow_is_incremental_validated_and_publish_safe() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "current-year-catalog.yml"
    assert workflow_path.is_file()
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert workflow.count("cron:") == 2
    assert "refresh_mode:" in workflow
    assert "publish:" in workflow
    assert "Resolve current-year plan" in workflow
    assert "resolve_current_year_plan" in workflow
    assert "actions/cache/restore@5a3ec84eff668545956fd18022155c47e93e2684" in workflow
    assert "actions/cache/save@5a3ec84eff668545956fd18022155c47e93e2684" in workflow
    assert "probe_wikidata_year.py" in workflow
    assert "--through" in workflow
    assert "--refresh-month" in workflow
    assert "required_year=year" in workflow
    assert "if: always()" in workflow
    assert "current-year-catalog-diagnostics" in workflow
    assert "gh release create" in workflow
    assert "gh release download" in workflow
    assert "gh release upload" not in workflow
    assert "--clobber" not in workflow
    assert "write_latest_atomic" in workflow
    assert "steps.publish_release.outcome == 'success'" in workflow
    assert "contents: write" in workflow
    assert "actions: read" in workflow
    assert "1950-2015" not in workflow
    assert "probe-wikidata-1950-2015" not in workflow
