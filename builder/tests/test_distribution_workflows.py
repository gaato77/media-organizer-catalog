import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECOVERY_WORKFLOW = ROOT / ".github" / "workflows" / "recover-1950-2015.yml"
SUPPLEMENT_WORKFLOW = ROOT / ".github" / "workflows" / "build-historical-range.yml"
CURRENT_YEAR_WORKFLOW = ROOT / ".github" / "workflows" / "current-year-catalog.yml"
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


def test_checkout_does_not_persist_write_credentials_and_push_auth_is_deferred() -> None:
    workflow = _workflow(RECOVERY_WORKFLOW)

    checkout = workflow[
        workflow.index("- uses: actions/checkout@v4") : workflow.index(
            "- uses: actions/setup-python@v5"
        )
    ]
    assert "persist-credentials: false" in checkout

    publication = workflow[workflow.index("Update base pointer and stable channel") :]
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in publication
    _assert_ordered(
        publication,
        'git commit -m "catalog: publish base 1950-2015"',
        "gh auth setup-git",
        "git push origin",
    )


def test_dry_run_build_job_is_read_only_and_write_permission_is_publish_gated() -> None:
    workflow = _workflow(RECOVERY_WORKFLOW)

    recover = workflow[workflow.index("  recover:") : workflow.index("\n  publish:")]
    publish = workflow[workflow.index("\n  publish:") :]

    assert "permissions:\n      actions: read\n      contents: read" in recover
    assert "contents: write" not in recover
    assert "needs: recover" in publish
    assert "if: inputs.publish == true" in publish
    assert "permissions:\n      actions: read\n      contents: write" in publish
    assert "Publish immutable base release" not in recover
    assert "Publish immutable base release" in publish
    assert "complete-1950-2015-catalog-recovered" in recover
    assert "complete-1950-2015-catalog-recovered" in publish
    assert workflow.count("- uses: actions/checkout@v4") == 2
    assert workflow.count("persist-credentials: false") == 2


def test_publication_diagnostics_are_uploaded_after_all_publication_stages() -> None:
    workflow = _workflow(RECOVERY_WORKFLOW)

    _assert_ordered(
        workflow,
        "Publish immutable base release",
        "Public release verification",
        "Update base pointer and stable channel",
        "Upload publication diagnostics",
        "Fail after preserving diagnostics",
    )
    diagnostics = workflow[
        workflow.index("Upload publication diagnostics") : workflow.index(
            "Fail after preserving diagnostics"
        )
    ]
    assert "if: always() && inputs.publish == true" in diagnostics
    assert "continue-on-error: true" in diagnostics
    for inventory in (
        "local-release-inventory.tsv",
        "existing-release-inventory.tsv",
        "public-release-inventory.tsv",
    ):
        assert inventory in diagnostics


def test_base_recovery_final_gate_covers_every_requested_stage() -> None:
    workflow = _workflow(RECOVERY_WORKFLOW)

    build_gate = workflow[
        workflow.index("Fail after preserving build diagnostics") : workflow.index("\n  publish:")
    ]
    for stage in ("preflight", "download", "assemble", "consolidate", "package"):
        assert f"steps.{stage}.outcome" in build_gate

    publication_gate = workflow[workflow.index("Fail after preserving diagnostics") :]
    for stage in ("publish_release", "verify_release", "update_pointers"):
        assert f"steps.{stage}.outcome" in publication_gate


def test_supplement_dispatch_is_validated_and_defaults_to_dry_run() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    inputs = workflow[workflow.index("    inputs:") : workflow.index("\npermissions:")]
    version = inputs[inputs.index("      version:") : inputs.index("      publish:")]
    publish = inputs[inputs.index("      publish:") :]
    assert "required: true" in version
    assert "type: string" in version
    assert "required: true" in publish
    assert "type: boolean" in publish
    assert "default: false" in publish
    assert "Version must match YYYY.MM.DD" in workflow
    assert "if: inputs.publish == true" in workflow


def test_supplement_shells_do_not_directly_interpolate_dispatch_version() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    assert 'echo "Version: ${{ inputs.version }}"' not in workflow
    assert '--title "Supplement catalog 2016-2025 - ${{ inputs.version }}"' not in workflow
    assert 'echo "Version: ${VERSION}"' in workflow
    assert '--title "Supplement catalog 2016-2025 - ${VERSION}"' in workflow


def test_supplement_publication_requires_default_branch_dispatch() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    publish_start = workflow.index("\n  publish:")
    publish_header = workflow[publish_start : workflow.index("    runs-on:", publish_start)]
    assert "inputs.publish == true" in publish_header
    assert "github.ref_type == 'branch'" in publish_header
    assert "github.ref_name == github.event.repository.default_branch" in publish_header


def test_supplement_probes_exact_year_matrix_and_uploads_complete_shards() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    assert "year: [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]" in workflow
    assert "probe_wikidata_year.py" in workflow
    assert '--year "${YEAR}"' in workflow
    assert "name: year-${{ matrix.year }}" in workflow
    assert "annual-probe-output/summary.json" in workflow
    assert "annual-probe-output/movie.json" in workflow
    assert "annual-probe-output/series.json" in workflow


def test_supplement_build_waits_for_all_shards_and_validates_exact_range() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    build = workflow[workflow.index("  build:") : workflow.index("\n  publish:")]
    assert "needs: probe" in build
    assert "pattern: year-*" in build
    assert "for year in $(seq 2016 2025)" in build
    assert "consolidate_year_shards.py" in build
    assert "--start-year 2016" in build
    assert "--end-year 2025" in build
    assert "build_probe_release" in build
    assert "mode=ro" in build
    assert "PRAGMA integrity_check" in build
    assert "MIN(release_year), MAX(release_year), COUNT(DISTINCT release_year)" in build
    assert "(2016, 2025, 10)" in build
    _assert_ordered(
        build,
        "Download all ten yearly artifacts",
        "Assemble the annual shard tree",
        "Consolidate annual shards",
        "Build and validate supplement package",
        "Verify final SQLite year range",
    )


def test_supplement_diagnostics_and_package_artifacts_are_retained_for_14_days() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    assert workflow.count("retention-days: 14") >= 4
    assert "supplement-probe-diagnostics-${{ matrix.year }}" in workflow
    assert "supplement-build-diagnostics-${{ inputs.version }}" in workflow
    assert "supplement-2016-2025-${{ inputs.version }}" in workflow
    assert "supplement-publication-diagnostics-${{ github.run_id }}" in workflow
    assert "Fail after preserving probe diagnostics" in workflow
    assert "Fail after preserving build diagnostics" in workflow
    assert "Fail after preserving publication diagnostics" in workflow


def test_supplement_write_permission_is_confined_to_gated_publication() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    probe = workflow[workflow.index("  probe:") : workflow.index("\n  build:")]
    build = workflow[workflow.index("  build:") : workflow.index("\n  publish:")]
    publish = workflow[workflow.index("\n  publish:") :]
    assert "permissions:\n      contents: read" in probe
    assert "permissions:\n      actions: read\n      contents: read" in build
    assert "contents: write" not in probe
    assert "contents: write" not in build
    assert "needs: build" in publish
    assert "if: inputs.publish == true" in publish
    assert "permissions:\n      actions: read\n      contents: write" in publish
    assert "group: stable-catalog-publication" in workflow
    assert "cancel-in-progress: false" in workflow


def test_supplement_publication_lock_is_scoped_to_write_job() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    workflow_header = workflow[: workflow.index("jobs:")]
    probe = workflow[workflow.index("  probe:") : workflow.index("\n  build:")]
    build = workflow[workflow.index("  build:") : workflow.index("\n  publish:")]
    publish_start = workflow.index("\n  publish:")
    publish_header = workflow[publish_start : workflow.index("    steps:", publish_start)]
    assert "concurrency:" not in workflow_header
    assert "stable-catalog-publication" not in probe
    assert "stable-catalog-publication" not in build
    assert "concurrency:\n      group: stable-catalog-publication" in publish_header
    assert "cancel-in-progress: false" in publish_header


def test_supplement_write_job_actions_are_pinned_to_reviewed_commits() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    publish = workflow[workflow.index("\n  publish:") :]
    actions = re.findall(r"^\s+(?:- )?uses: ([^@\s]+)@([^\s]+)", publish, flags=re.MULTILINE)
    assert actions == [
        ("actions/checkout", "11bd71901bbe5b1630ceea73d27597364c9af683"),
        ("actions/setup-python", "a26af69be951a213d495a4c3e4e4022e16d87065"),
        ("actions/download-artifact", "d3f86a106a0bac45b974a628896c90dbdf5c8093"),
        ("actions/upload-artifact", "ea165f8d65b6e75b540449e92b4886f43607fa02"),
    ]


def test_supplement_release_is_immutable_idempotent_and_publicly_verified() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    assert "RELEASE_TAG: supplement-2016-2025-${{ inputs.version }}" in workflow
    assert "gh release create" in workflow
    assert "gh release download" in workflow
    assert "sha256sum" in workflow
    assert "local-release-inventory.tsv" in workflow
    assert "existing-release-inventory.tsv" in workflow
    assert "--clobber" not in workflow
    assert "gh release upload" not in workflow
    assert "Public release verification" in workflow
    assert "public-release-inventory.tsv" in workflow
    public_verification = workflow[
        workflow.index("Public release verification") : workflow.index(
            "Update supplement pointer and stable channel"
        )
    ]
    assert "Authorization:" not in public_verification
    _assert_ordered(
        workflow,
        "Verify final SQLite year range",
        "Publish immutable supplement release",
        "Public release verification",
        "Update supplement pointer and stable channel",
    )


def test_supplement_pointer_is_public_release_gated_and_generated_safely() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    assert "steps.verify_release.outcome == 'success'" in workflow
    assert "write_component_pointer.py" in workflow
    assert "--component-type supplement" in workflow
    assert "--from-year 2016" in workflow
    assert "--to-year 2025" in workflow
    assert "--priority 200" in workflow
    assert "catalog/components/supplement-2016-2025.json" in workflow
    assert 'if [ -f "${pointer}" ]' in workflow
    assert "assemble_stable_channel.py" in workflow
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
        "git add catalog/components/supplement-2016-2025.json catalog/channel/stable.json",
        'git commit -m "catalog: publish supplement 2016-2025"',
        "git push origin",
    )


def test_supplement_final_gates_cover_every_fallible_stage() -> None:
    workflow = _workflow(SUPPLEMENT_WORKFLOW)

    probe_gate = workflow[
        workflow.index("Fail after preserving probe diagnostics") : workflow.index("\n  build:")
    ]
    for stage in ("validate", "probe"):
        assert f"steps.{stage}.outcome" in probe_gate

    build_gate = workflow[
        workflow.index("Fail after preserving build diagnostics") : workflow.index("\n  publish:")
    ]
    for stage in ("download", "assemble", "consolidate", "package", "verify_database"):
        assert f"steps.{stage}.outcome" in build_gate

    publication_gate = workflow[workflow.index("Fail after preserving publication diagnostics") :]
    for stage in ("publish_release", "verify_release", "update_pointers"):
        assert f"steps.{stage}.outcome" in publication_gate


def test_current_year_build_is_read_only_and_publication_is_default_branch_gated() -> None:
    workflow = _workflow(CURRENT_YEAR_WORKFLOW)

    build = workflow[workflow.index("  build:") : workflow.index("\n  publish:")]
    publish_start = workflow.index("\n  publish:")
    publish = workflow[publish_start:]
    publish_header = workflow[publish_start : workflow.index("    runs-on:", publish_start)]
    assert "permissions:\n      actions: read\n      contents: read" in build
    assert "contents: write" not in build
    assert "needs: build" in publish_header
    assert "needs.build.outputs.publish == 'true'" in publish_header
    assert "github.ref_type == 'branch'" in publish_header
    assert "github.ref_name == github.event.repository.default_branch" in publish_header
    assert "permissions:\n      actions: read\n      contents: write" in publish_header
    assert "Publish validated current-year release" not in build
    assert "Publish validated current-year release" in publish


def test_current_year_publication_lock_is_scoped_and_actions_are_pinned() -> None:
    workflow = _workflow(CURRENT_YEAR_WORKFLOW)

    workflow_header = workflow[: workflow.index("jobs:")]
    build = workflow[workflow.index("  build:") : workflow.index("\n  publish:")]
    publish_start = workflow.index("\n  publish:")
    publish_header = workflow[publish_start : workflow.index("    steps:", publish_start)]
    publish = workflow[publish_start:]
    assert "concurrency:" not in workflow_header
    assert "stable-catalog-publication" not in build
    assert "concurrency:\n      group: stable-catalog-publication" in publish_header
    assert "cancel-in-progress: false" in publish_header
    actions = re.findall(r"^\s+(?:- )?uses: ([^@\s]+)@([^\s]+)", publish, flags=re.MULTILINE)
    assert actions == [
        ("actions/checkout", "11bd71901bbe5b1630ceea73d27597364c9af683"),
        ("actions/setup-python", "a26af69be951a213d495a4c3e4e4022e16d87065"),
        ("actions/download-artifact", "d3f86a106a0bac45b974a628896c90dbdf5c8093"),
        ("actions/upload-artifact", "ea165f8d65b6e75b540449e92b4886f43607fa02"),
    ]


def test_current_year_release_is_immutable_idempotent_and_verified_from_public_bytes() -> None:
    workflow = _workflow(CURRENT_YEAR_WORKFLOW)

    assert "gh release create" in workflow
    assert "gh release download" in workflow
    assert "existing-release-inventory.tsv" in workflow
    assert "local-release-inventory.tsv" in workflow
    assert "sha256sum" in workflow
    assert "--clobber" not in workflow
    assert "gh release upload" not in workflow
    assert "Existing immutable current-year release" in workflow
    assert "No release or pointer was changed" in workflow
    assert "Public release verification" in workflow
    assert "public-release-inventory.tsv" in workflow
    verification = workflow[
        workflow.index("Public release verification") : workflow.index(
            "Update current-year pointers and stable channel"
        )
    ]
    assert "Authorization:" not in verification
    _assert_ordered(
        workflow,
        "Build and validate current-year package",
        "Publish validated current-year release",
        "Public release verification",
        "Update current-year pointers and stable channel",
    )


def test_current_year_pointers_are_dynamic_and_derived_from_verified_release() -> None:
    workflow = _workflow(CURRENT_YEAR_WORKFLOW)

    pointer_start = workflow.index("Update current-year pointers and stable channel")
    pointer = workflow[pointer_start:]
    assert "steps.verify_release.outcome == 'success'" in pointer
    assert "YEAR: ${{ needs.build.outputs.year }}" in pointer
    assert "2026" not in pointer
    assert 'Path("public-release-assets/manifest.json")' in pointer
    assert "public-release-work/catalog.sqlite" in pointer
    assert 'write_latest_atomic(Path("catalog/current/latest.json"), latest)' in pointer
    assert "write_component_pointer.py" in pointer
    assert '--component-id "current-${YEAR}"' in pointer
    assert "--component-type current-year" in pointer
    assert '--from-year "${YEAR}"' in pointer
    assert '--to-year "${YEAR}"' in pointer
    assert "--priority 400" in pointer
    assert "catalog/components/current-year.json" in pointer
    assert 'if [ -f "${pointer}" ]' in pointer
    assert "assemble_stable_channel.py" in pointer
    assert "catalog/channel/stable.json" in pointer


def test_current_year_generated_commit_is_atomic_confined_and_non_forced() -> None:
    workflow = _workflow(CURRENT_YEAR_WORKFLOW)

    assert "git diff --cached --name-only" in workflow
    assert "git diff --name-only" in workflow
    assert "Unrelated tracked change" in workflow
    assert "non-fast-forward" in workflow
    assert "--force" not in workflow
    _assert_ordered(
        workflow,
        "Public release verification",
        "git pull --rebase",
        "write_latest_atomic",
        "write_component_pointer.py",
        "assemble_stable_channel.py",
        (
            "git add catalog/current/latest.json catalog/components/current-year.json "
            "catalog/channel/stable.json"
        ),
        'git commit -m "catalog: publish current-year ${VERSION}"',
        "gh auth setup-git",
        "git push origin",
    )


def test_current_year_final_gates_cover_build_and_publication_stages() -> None:
    workflow = _workflow(CURRENT_YEAR_WORKFLOW)

    build_gate = workflow[
        workflow.index("Fail after preserving build diagnostics") : workflow.index("\n  publish:")
    ]
    for stage in ("probe", "package"):
        assert f"steps.{stage}.outcome" in build_gate

    publication_gate = workflow[workflow.index("Fail after preserving publication diagnostics") :]
    for stage in ("publish_release", "verify_release", "update_pointers"):
        assert f"steps.{stage}.outcome" in publication_gate


def test_ci_runs_checksum_pinned_official_actionlint_for_every_workflow() -> None:
    workflow = _workflow(CI_WORKFLOW)

    assert "ACTIONLINT_VERSION: 1.7.12" in workflow
    assert "rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${archive}" in workflow
    assert "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8" in workflow
    assert 'find .github/workflows -type f -name "*.yml"' in workflow
    assert "actionlint -color" in workflow
    assert "latest" not in workflow[workflow.index("Install actionlint") :]
