from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECOVERY_WORKFLOW = ROOT / ".github" / "workflows" / "recover-1950-2015.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _workflow(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_ordered(workflow: str, *needles: str) -> None:
    positions = [workflow.index(needle) for needle in needles]
    assert positions == sorted(positions), dict(zip(needles, positions, strict=True))


def test_base_recovery_defaults_to_dry_run_and_uses_shared_publication_lock() -> None:
    workflow = _workflow(RECOVERY_WORKFLOW)

    assert "publish:" in workflow
    assert "type: boolean" in workflow
    assert "default: false" in workflow
    assert "source_run_id:" in workflow
    assert "type: string" in workflow
    assert 'default: "30157271026"' in workflow
    assert "group: stable-catalog-publication" in workflow
    assert "cancel-in-progress: false" in workflow


def test_base_recovery_preflights_every_required_source_artifact_before_download() -> None:
    workflow = _workflow(RECOVERY_WORKFLOW)

    _assert_ordered(
        workflow,
        "Preflight source workflow artifacts",
        "Download the 66 completed yearly artifacts",
        "Assemble the annual shard tree",
        "Build and validate the recovered package",
    )
    assert "actions/runs/${SOURCE_RUN_ID}" in workflow
    assert "range(1950, 2016)" in workflow
    assert "missing" in workflow
    assert "expired" in workflow
    assert "duplicates" in workflow
    assert "completed successfully" in workflow
    assert "steps.preflight.outputs.source_run_id" in workflow


def test_base_release_is_immutable_idempotent_and_publicly_verified() -> None:
    workflow = _workflow(RECOVERY_WORKFLOW)

    assert "base-1950-2015-2026.07.25" in workflow
    assert "gh release create" in workflow
    assert "gh release download" in workflow
    assert "sha256sum" in workflow
    assert "local-release-inventory.tsv" in workflow
    assert "existing-release-inventory.tsv" in workflow
    assert "--clobber" not in workflow
    assert "gh release upload" not in workflow
    assert "api.github.com/repos/${GITHUB_REPOSITORY}/releases/tags/${RELEASE_TAG}" in workflow
    assert "Public release verification" in workflow
    assert "public-release-inventory.tsv" in workflow
    public_verification = workflow[
        workflow.index("Public release verification") : workflow.index(
            "Update base pointer and stable channel"
        )
    ]
    assert "Authorization:" not in public_verification
    _assert_ordered(
        workflow,
        "Build and validate the recovered package",
        "Publish immutable base release",
        "Public release verification",
        "Update base pointer and stable channel",
    )


def test_base_pointer_commit_is_release_gated_and_confined_to_generated_files() -> None:
    workflow = _workflow(RECOVERY_WORKFLOW)

    pointer_condition = "steps.verify_release.outcome == 'success'"
    assert pointer_condition in workflow
    assert "write_component_pointer.py" in workflow
    assert "catalog/components/base.json" in workflow
    assert "assemble_stable_channel.py" in workflow
    assert 'if [ -f "${pointer}" ]' in workflow
    assert "catalog/channel/stable.json" in workflow
    assert "git pull --rebase" in workflow
    assert "git diff --cached --name-only" in workflow
    assert "git diff --name-only" in workflow
    assert "Unrelated tracked change" in workflow
    assert "non-fast-forward" in workflow
    assert "--force" not in workflow
    _assert_ordered(
        workflow,
        "Public release verification",
        "git pull --rebase",
        "write_component_pointer.py",
        "assemble_stable_channel.py",
        "git add catalog/components/base.json catalog/channel/stable.json",
        'git commit -m "catalog: publish base 1950-2015"',
        "git push origin",
    )


def test_base_recovery_final_gate_covers_every_requested_stage() -> None:
    workflow = _workflow(RECOVERY_WORKFLOW)

    final_gate = workflow[workflow.index("Fail after preserving diagnostics") :]
    for stage in (
        "preflight",
        "download",
        "assemble",
        "consolidate",
        "package",
        "publish_release",
        "verify_release",
        "update_pointers",
    ):
        assert f"steps.{stage}.outcome" in final_gate


def test_ci_runs_checksum_pinned_official_actionlint_for_every_workflow() -> None:
    workflow = _workflow(CI_WORKFLOW)

    assert "ACTIONLINT_VERSION: 1.7.12" in workflow
    assert "rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${archive}" in workflow
    assert "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8" in workflow
    assert 'find .github/workflows -type f -name "*.yml"' in workflow
    assert "actionlint -color" in workflow
    assert "latest" not in workflow[workflow.index("Install actionlint") :]
