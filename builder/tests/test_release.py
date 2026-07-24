from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from media_catalog_builder.database import CatalogDatabase
from media_catalog_builder.model import MediaType, SourceRecord
from media_catalog_builder.release import build_database_from_sources


def _source(
    qid: int,
    media_type: MediaType,
    year: int,
    originals: tuple[str, ...],
    english: str | None,
    spanish: str | None,
) -> SourceRecord:
    return SourceRecord(qid, media_type, year, originals, english, spanish)


def test_full_build_is_byte_deterministic_for_shuffled_sources(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    sources = [
        _source(2, MediaType.SERIES, 2020, ("Series",), "Series", "Serie"),
        _source(1, MediaType.MOVIE, 2001, ("Amélie",), "Amelie", "Amélie"),
        _source(2, MediaType.SERIES, 2019, ("Series original",), "Series", None),
    ]
    now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    first = tmp_path / "first.sqlite"
    second = tmp_path / "second.sqlite"

    first_stats = build_database_from_sources(
        sources,
        first,
        version="2026.07.24",
        now=now,
        schema_path=schema_path,
    )
    second_stats = build_database_from_sources(
        reversed(sources),
        second,
        version="2026.07.24",
        now=now,
        schema_path=schema_path,
    )

    assert first.read_bytes() == second.read_bytes()
    assert first_stats == second_stats
    assert first_stats.source_rows == 3
    assert first_stats.catalog_records == 2
    assert first_stats.skipped_records == 0


def test_full_build_merges_earliest_year_and_series_priority(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    output = tmp_path / "catalog.sqlite"
    sources = [
        _source(7, MediaType.MOVIE, 2021, ("Hybrid",), "Hybrid", None),
        _source(7, MediaType.SERIES, 2018, ("Hybrid Series",), "Hybrid", "Híbrido"),
    ]

    build_database_from_sources(
        sources,
        output,
        version="2026.07.24",
        now=datetime(2026, 7, 24, tzinfo=UTC),
        schema_path=schema_path,
    )

    with CatalogDatabase.open(output, readonly=True) as database:
        result = database.lookup("hybrid", year=2018, media_type=MediaType.SERIES)
        assert database.get_meta("catalog_version") == "2026.07.24"
        assert database.get_meta("catalog_schema") == "1"

    assert len(result) == 1
    assert result[0].qid == 7
    assert result[0].year == 2018
    assert result[0].media_type is MediaType.SERIES


def test_full_build_skips_records_without_usable_latin_title(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    output = tmp_path / "catalog.sqlite"
    stats = build_database_from_sources(
        [_source(9, MediaType.MOVIE, 2020, ("千と千尋",), None, None)],
        output,
        version="2026.07.24",
        now=datetime(2026, 7, 24, tzinfo=UTC),
        schema_path=schema_path,
    )

    assert stats.catalog_records == 0
    assert stats.skipped_records == 1
    with CatalogDatabase.open(output, readonly=True) as database:
        assert database.lookup("千と千尋") == ()
