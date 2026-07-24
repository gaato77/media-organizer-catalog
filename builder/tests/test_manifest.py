from __future__ import annotations

import json
from pathlib import Path

import pytest

from media_catalog_builder.manifest import (
    Asset,
    DeltaPath,
    ReleaseManifest,
    choose_update_path,
    load_manifest,
    write_manifest,
)


def _asset(name: str = "catalog-full-2026.07.24.sqlite.zip", size: int = 1000) -> Asset:
    return Asset(
        name=name,
        download_bytes=size,
        installed_bytes=size * 2,
        sha256="a" * 64,
    )


def _delta(from_version: str, to_version: str, size: int) -> DeltaPath:
    return DeltaPath(
        from_version=from_version,
        to_version=to_version,
        name=f"catalog-delta-{from_version}-to-{to_version}.sqlite.zip",
        download_bytes=size,
        installed_bytes=size * 2,
        sha256="b" * 64,
    )


def _manifest(*deltas: DeltaPath, full_size: int = 1000) -> ReleaseManifest:
    return ReleaseManifest(
        manifest_schema=1,
        catalog_schema=1,
        catalog_version="2026.07.24",
        published_at="2026-07-24T12:00:00Z",
        minimum_app_version="2.0.0-beta.10",
        full=_asset(size=full_size),
        deltas=tuple(deltas),
    )


def test_manifest_json_is_compact_sorted_and_round_trips(tmp_path: Path) -> None:
    manifest = _manifest(_delta("2026.07.17", "2026.07.24", 100))
    path = tmp_path / "manifest.json"

    write_manifest(path, manifest)
    text = path.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert "\n " not in text
    assert text.index('"catalog_schema"') < text.index('"catalog_version"')
    assert load_manifest(path) == manifest
    assert json.loads(text)["full"]["name"].startswith("catalog-full-")


def test_manifest_rejects_invalid_schema_and_sha256() -> None:
    with pytest.raises(ValueError, match="manifest schema"):
        ReleaseManifest(
            manifest_schema=2,
            catalog_schema=1,
            catalog_version="2026.07.24",
            published_at="2026-07-24T12:00:00Z",
            minimum_app_version="2.0.0",
            full=_asset(),
            deltas=(),
        )
    with pytest.raises(ValueError, match="SHA-256"):
        Asset("catalog.zip", 1, 1, "INVALID")


def test_manifest_rejects_more_than_eight_deltas() -> None:
    deltas = tuple(
        _delta(f"2026.05.{day:02d}", f"2026.05.{day + 1:02d}", 10)
        for day in range(1, 10)
    )

    with pytest.raises(ValueError, match="at most 8"):
        _manifest(*deltas)


def test_choose_update_path_selects_contiguous_delta_chain() -> None:
    manifest = _manifest(
        _delta("2026.07.03", "2026.07.10", 50),
        _delta("2026.07.10", "2026.07.17", 60),
        _delta("2026.07.17", "2026.07.24", 70),
    )

    selected = choose_update_path(manifest, "2026.07.10")

    assert [item.from_version for item in selected if isinstance(item, DeltaPath)] == [
        "2026.07.10",
        "2026.07.17",
    ]
    assert [item.to_version for item in selected if isinstance(item, DeltaPath)] == [
        "2026.07.17",
        "2026.07.24",
    ]


def test_choose_update_path_returns_empty_when_already_current() -> None:
    assert choose_update_path(_manifest(), "2026.07.24") == ()


def test_choose_update_path_falls_back_to_full_without_contiguous_chain() -> None:
    manifest = _manifest(_delta("2026.07.17", "2026.07.24", 100))

    assert choose_update_path(manifest, "2026.07.10") == (manifest.full,)


def test_choose_update_path_falls_back_when_deltas_reach_80_percent() -> None:
    manifest = _manifest(
        _delta("2026.07.10", "2026.07.17", 400),
        _delta("2026.07.17", "2026.07.24", 400),
        full_size=1000,
    )

    assert choose_update_path(manifest, "2026.07.10") == (manifest.full,)


def test_load_manifest_rejects_unknown_or_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = _manifest().to_dict()
    payload["unexpected"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="fields"):
        load_manifest(path)

    del payload["unexpected"]
    del payload["catalog_version"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="fields"):
        load_manifest(path)


def test_public_schema_and_examples_match_manifest_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "schema" / "manifest-schema-v1.json").read_text())
    example = load_manifest(root / "samples" / "manifest.example.json")
    lookup_cases = json.loads((root / "samples" / "lookup-cases.json").read_text())

    assert schema["additionalProperties"] is False
    assert schema["properties"]["deltas"]["maxItems"] == 8
    assert example.manifest_schema == 1
    assert example.catalog_schema == 1
    assert example.deltas == ()
    assert len(lookup_cases) >= 2
    assert {case["media_type"] for case in lookup_cases} == {"movie", "series"}
