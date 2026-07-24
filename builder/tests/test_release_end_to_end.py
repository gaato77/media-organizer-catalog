from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from media_catalog_builder.config import CatalogConfig
from media_catalog_builder.database import CatalogDatabase
from media_catalog_builder.delta import create_delta
from media_catalog_builder.manifest import DeltaPath, choose_update_path
from media_catalog_builder.model import CatalogRecord, MediaType
from media_catalog_builder.release import (
    _retained_delta_chain,
    assemble_release,
    validate_release,
)


def _config() -> CatalogConfig:
    return CatalogConfig.load(Path(__file__).parents[1] / "config" / "catalog.toml")


def _record(number: int, *, changed: bool = False) -> CatalogRecord:
    title = f"Example {number}"
    if changed and number == 1:
        title = "Changed Example 1"
    return CatalogRecord(
        qid=number,
        media_type=MediaType.MOVIE if number % 2 else MediaType.SERIES,
        year=2000 + (number % 20),
        canonical_title=title,
        names=(title.casefold(),),
    )


def _catalog(
    path: Path,
    schema_path: Path,
    version: str,
    *,
    count: int,
    changed: bool = False,
) -> None:
    with CatalogDatabase.create(path, schema_path) as database:
        database.set_meta_many(
            {
                "catalog_schema": "1",
                "catalog_version": version,
                "published_at": f"{version.replace('.', '-')}T12:00:00Z",
                "source_rows": str(count),
                "work_count": str(count),
            }
        )
        database.upsert_many(_record(number, changed=changed) for number in range(1, count + 1))
        database.finalize()


def _lookup_cases(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "name": "Example 2",
                    "year": 2002,
                    "media_type": "series",
                    "canonical_title": "Example 2",
                },
                {
                    "name": "Example 3",
                    "year": 2003,
                    "media_type": "movie",
                    "canonical_title": "Example 3",
                },
            ]
        ),
        encoding="utf-8",
    )


def test_assemble_and_validate_full_release(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    catalog = tmp_path / "catalog.sqlite"
    release_dir = tmp_path / "release-2026.07.24"
    lookups = tmp_path / "lookups.json"
    _catalog(catalog, schema_path, "2026.07.24", count=40)
    _lookup_cases(lookups)

    manifest = assemble_release(
        catalog,
        release_dir,
        version="2026.07.24",
        published_at=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
        minimum_app_version="2.0.0-beta.10",
        config=_config(),
        lookup_cases_path=lookups,
    )
    validated = validate_release(
        release_dir,
        config=_config(),
        lookup_cases_path=lookups,
    )

    assert validated == manifest
    assert manifest.deltas == ()
    assert set(path.name for path in release_dir.iterdir()) == {
        manifest.full.name,
        "manifest.json",
        "checksums.sha256",
    }
    checksums = (release_dir / "checksums.sha256").read_text(encoding="utf-8")
    assert manifest.full.name in checksums
    assert "manifest.json" in checksums
    assert not list(tmp_path.glob("*.staging"))


def test_release_retains_contiguous_efficient_delta_chain(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    config = _config()
    lookups = tmp_path / "lookups.json"
    _lookup_cases(lookups)
    v1 = tmp_path / "v1.sqlite"
    v2 = tmp_path / "v2.sqlite"
    v3 = tmp_path / "v3.sqlite"
    d12 = tmp_path / "d12.sqlite"
    d23 = tmp_path / "d23.sqlite"
    _catalog(v1, schema_path, "2026.07.10", count=500)
    _catalog(v2, schema_path, "2026.07.17", count=500, changed=True)
    _catalog(v3, schema_path, "2026.07.24", count=501, changed=True)
    create_delta(v1, v2, d12, from_version="2026.07.10", to_version="2026.07.17")
    create_delta(v2, v3, d23, from_version="2026.07.17", to_version="2026.07.24")

    previous_release = tmp_path / "release-2026.07.17"
    assemble_release(
        v2,
        previous_release,
        version="2026.07.17",
        published_at=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        minimum_app_version="2.0.0-beta.10",
        config=config,
        lookup_cases_path=lookups,
        delta_path=d12,
        delta_from_version="2026.07.10",
    )
    current_release = tmp_path / "release-2026.07.24"
    manifest = assemble_release(
        v3,
        current_release,
        version="2026.07.24",
        published_at=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
        minimum_app_version="2.0.0-beta.10",
        config=config,
        lookup_cases_path=lookups,
        previous_release_dir=previous_release,
        delta_path=d23,
        delta_from_version="2026.07.17",
    )

    assert len(manifest.deltas) == 2
    selected = choose_update_path(manifest, "2026.07.10")
    assert [item.name for item in selected] == [delta.name for delta in manifest.deltas]
    validate_release(current_release, config=config, lookup_cases_path=lookups)


def test_inefficient_delta_is_omitted(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    lookups = tmp_path / "lookups.json"
    _lookup_cases(lookups)
    old = tmp_path / "old.sqlite"
    new = tmp_path / "new.sqlite"
    delta = tmp_path / "delta.sqlite"
    _catalog(old, schema_path, "2026.07.17", count=3)
    _catalog(new, schema_path, "2026.07.24", count=3, changed=True)
    create_delta(old, new, delta, from_version="2026.07.17", to_version="2026.07.24")

    manifest = assemble_release(
        new,
        tmp_path / "release",
        version="2026.07.24",
        published_at=datetime(2026, 7, 24, tzinfo=UTC),
        minimum_app_version="2.0.0-beta.10",
        config=_config(),
        lookup_cases_path=lookups,
        delta_path=delta,
        delta_from_version="2026.07.17",
    )

    assert manifest.deltas == ()


def test_validate_release_rejects_tampered_asset(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    catalog = tmp_path / "catalog.sqlite"
    lookups = tmp_path / "lookups.json"
    release_dir = tmp_path / "release"
    _catalog(catalog, schema_path, "2026.07.24", count=20)
    _lookup_cases(lookups)
    manifest = assemble_release(
        catalog,
        release_dir,
        version="2026.07.24",
        published_at=datetime(2026, 7, 24, tzinfo=UTC),
        minimum_app_version="2.0.0-beta.10",
        config=_config(),
        lookup_cases_path=lookups,
    )
    with (release_dir / manifest.full.name).open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(ValueError, match="checksum|size"):
        validate_release(release_dir, config=_config(), lookup_cases_path=lookups)


def test_assembly_failure_never_activates_staging_directory(
    tmp_path: Path,
    schema_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import media_catalog_builder.release as release_module

    catalog = tmp_path / "catalog.sqlite"
    lookups = tmp_path / "lookups.json"
    output = tmp_path / "release"
    _catalog(catalog, schema_path, "2026.07.24", count=20)
    _lookup_cases(lookups)

    def fail_validation(*args: object, **kwargs: object) -> object:
        raise RuntimeError("simulated release validation failure")

    monkeypatch.setattr(release_module, "validate_release", fail_validation)

    with pytest.raises(RuntimeError, match="simulated release validation failure"):
        assemble_release(
            catalog,
            output,
            version="2026.07.24",
            published_at=datetime(2026, 7, 24, tzinfo=UTC),
            minimum_app_version="2.0.0-beta.10",
            config=_config(),
            lookup_cases_path=lookups,
        )

    assert not output.exists()
    assert not list(tmp_path.glob("*.staging"))


def test_retained_chain_keeps_only_last_seven_previous_edges() -> None:
    deltas = tuple(
        DeltaPath(
            from_version=f"2026.06.{day:02d}",
            to_version=f"2026.06.{day + 1:02d}",
            name=f"delta-{day}.zip",
            download_bytes=10,
            installed_bytes=20,
            sha256=f"{day:064x}",
        )
        for day in range(1, 9)
    )

    retained = _retained_delta_chain(deltas, "2026.06.09", limit=7)

    assert len(retained) == 7
    assert retained[0].from_version == "2026.06.02"
    assert retained[-1].to_version == "2026.06.09"
