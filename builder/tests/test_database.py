from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from media_catalog_builder.database import CatalogDatabase
from media_catalog_builder.model import CatalogRecord, MediaType


def _record(
    qid: int,
    year: int,
    title: str,
    names: tuple[str, ...],
    media_type: MediaType = MediaType.MOVIE,
) -> CatalogRecord:
    return CatalogRecord(qid, media_type, year, title, names)


def test_upsert_replaces_stale_names(tmp_path: Path, schema_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    with CatalogDatabase.create(path, schema_path) as database:
        database.upsert(_record(1, 2000, "Old title", ("old title", "old alias")))
        database.upsert(_record(1, 2000, "New title", ("new title",)))

        assert database.lookup("old alias") == ()
        result = database.lookup("new title")

    assert len(result) == 1
    assert result[0].canonical_title == "New title"
    assert result[0].names == ("new title",)


def test_identical_name_can_map_to_different_years(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    with CatalogDatabase.create(tmp_path / "catalog.sqlite", schema_path) as database:
        database.upsert(_record(1, 1990, "Example", ("example",)))
        database.upsert(_record(2, 2020, "Example", ("example",)))

        assert [record.year for record in database.lookup("Example")] == [1990, 2020]
        assert [record.qid for record in database.lookup("Example", year=2020)] == [2]


def test_lookup_filters_by_year_and_media_type(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    with CatalogDatabase.create(tmp_path / "catalog.sqlite", schema_path) as database:
        database.upsert(_record(1, 2020, "Shared", ("shared",), MediaType.MOVIE))
        database.upsert(_record(2, 2020, "Shared", ("shared",), MediaType.SERIES))

        movies = database.lookup("SHARED!", year=2020, media_type=MediaType.MOVIE)
        series = database.lookup("shared", year=2020, media_type=MediaType.SERIES)

    assert [record.qid for record in movies] == [1]
    assert [record.qid for record in series] == [2]
    assert movies[0].canonical_title == "Shared"


def test_delete_removes_work_and_names(tmp_path: Path, schema_path: Path) -> None:
    with CatalogDatabase.create(tmp_path / "catalog.sqlite", schema_path) as database:
        database.upsert(_record(1, 2000, "Example", ("example", "alias")))
        database.delete(1)

        assert database.lookup("example") == ()
        assert database.lookup("alias") == ()


def test_schema_cannot_store_more_than_four_ranked_names(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite"
    with CatalogDatabase.create(path, schema_path):
        pass

    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO works(qid, media_type, release_year, canonical_title) "
            "VALUES(1, 1, 2000, 'Example')"
        )
        for rank in range(4):
            connection.execute(
                "INSERT INTO names(normalized_name, work_qid, name_rank) VALUES(?, 1, ?)",
                (f"name-{rank}", rank),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO names(normalized_name, work_qid, name_rank) "
                "VALUES('fifth', 1, 3)"
            )
    finally:
        connection.close()


def test_finalize_returns_ok_integrity(tmp_path: Path, schema_path: Path) -> None:
    with CatalogDatabase.create(tmp_path / "catalog.sqlite", schema_path) as database:
        database.upsert(_record(1, 2000, "Example", ("example",)))
        assert database.finalize() == "ok"
