from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from media_catalog_builder.config import CatalogConfig
from media_catalog_builder.probe_release import build_probe_release
from media_catalog_builder.release import validate_release

ROOT = Path(__file__).resolve().parents[2]


def _binding(qid: int, release_date: str, title: str) -> dict[str, object]:
    return {
        "item": {
            "type": "uri",
            "value": f"http://www.wikidata.org/entity/Q{qid}",
        },
        "releaseDate": {"type": "literal", "value": release_date},
        "originals": {"type": "literal", "value": title},
        "enLabel": {"type": "literal", "value": title},
    }


def _payload(*bindings: dict[str, object]) -> dict[str, object]:
    return {"results": {"bindings": list(bindings)}}


def test_probe_release_builds_and_validates_complete_package(tmp_path: Path) -> None:
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    (probe_dir / "movie.json").write_text(
        json.dumps(_payload(_binding(10, "2025-01-10T00:00:00Z", "January Movie"))),
        encoding="utf-8",
    )
    (probe_dir / "series.json").write_text(
        json.dumps(_payload(_binding(20, "2025-01-20T00:00:00Z", "January Series"))),
        encoding="utf-8",
    )
    config = CatalogConfig.load(ROOT / "builder" / "config" / "catalog.toml")
    release_dir = tmp_path / "release"

    summary = build_probe_release(
        probe_dir,
        tmp_path / "work",
        release_dir,
        config=config,
        schema_path=ROOT / "schema" / "catalog-schema-v1.sql",
        version="2026.07.24",
        published_at=datetime(2026, 7, 24, 22, 45, tzinfo=UTC),
        minimum_app_version="0.1.0",
    )

    assert summary["source_records"] == 2
    assert summary["catalog_records"] == 2
    assert summary["skipped_records"] == 0
    assert summary["release_files"] == [
        "catalog-full-2026.07.24.sqlite.zip",
        "checksums.sha256",
        "manifest.json",
    ]
    manifest = validate_release(
        release_dir,
        config=config,
        lookup_cases_path=tmp_path / "work" / "lookup-cases.json",
    )
    assert manifest.catalog_version == "2026.07.24"
    assert manifest.full.installed_bytes == summary["database_bytes"]


def test_probe_release_uses_post_merge_canonical_title_for_lookup_case(
    tmp_path: Path,
) -> None:
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    (probe_dir / "movie.json").write_text(
        json.dumps(_payload(_binding(10, "2009-01-10T00:00:00Z", "We Live in Public"))),
        encoding="utf-8",
    )
    (probe_dir / "series.json").write_text(
        json.dumps(
            _payload(
                _binding(
                    5415,
                    "2011-01-01T00:00:00Z",
                    "My Little Pony: Friendship is Magic",
                ),
                _binding(
                    5415,
                    "2011-01-01T00:00:00Z",
                    "My Little Pony: Friendship Is Magic",
                ),
            )
        ),
        encoding="utf-8",
    )
    config = CatalogConfig.load(ROOT / "builder" / "config" / "catalog.toml")
    work_dir = tmp_path / "work"

    build_probe_release(
        probe_dir,
        work_dir,
        tmp_path / "release",
        config=config,
        schema_path=ROOT / "schema" / "catalog-schema-v1.sql",
        version="2026.07.25",
        published_at=datetime(2026, 7, 25, 17, 30, tzinfo=UTC),
        minimum_app_version="0.1.0",
    )

    cases = json.loads((work_dir / "lookup-cases.json").read_text(encoding="utf-8"))
    series_case = next(case for case in cases if case["media_type"] == "series")
    assert series_case == {
        "name": "My Little Pony: Friendship Is Magic",
        "year": 2011,
        "media_type": "series",
        "canonical_title": "My Little Pony: Friendship Is Magic",
    }


def test_probe_release_filters_records_outside_required_year(tmp_path: Path) -> None:
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    (probe_dir / "movie.json").write_text(
        json.dumps(
            _payload(
                _binding(10, "2026-01-10T00:00:00Z", "Current Movie"),
                _binding(11, "2025-12-31T00:00:00Z", "Previous Movie"),
            )
        ),
        encoding="utf-8",
    )
    (probe_dir / "series.json").write_text(
        json.dumps(_payload(_binding(20, "2026-02-01T00:00:00Z", "Current Series"))),
        encoding="utf-8",
    )
    config = CatalogConfig.load(ROOT / "builder" / "config" / "catalog.toml")
    work_dir = tmp_path / "work"

    summary = build_probe_release(
        probe_dir,
        work_dir,
        tmp_path / "release",
        config=config,
        schema_path=ROOT / "schema" / "catalog-schema-v1.sql",
        version="2026.07.25",
        published_at=datetime(2026, 7, 25, 17, 30, tzinfo=UTC),
        minimum_app_version="0.1.0",
        required_year=2026,
    )

    assert summary["source_records"] == 3
    assert summary["excluded_other_year_records"] == 1
    assert summary["catalog_records"] == 2
    with sqlite3.connect(work_dir / "catalog.sqlite") as connection:
        years = connection.execute(
            "SELECT DISTINCT release_year FROM works ORDER BY release_year"
        ).fetchall()
    assert years == [(2026,)]
