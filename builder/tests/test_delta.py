from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from media_catalog_builder.database import CatalogDatabase
from media_catalog_builder.delta import apply_delta, create_delta
from media_catalog_builder.model import CatalogRecord, MediaType


def _record(
    qid: int,
    title: str,
    names: tuple[str, ...],
    *,
    year: int = 2020,
    media_type: MediaType = MediaType.MOVIE,
) -> CatalogRecord:
    return CatalogRecord(qid, media_type, year, title, names)


def _catalog(
    path: Path,
    schema_path: Path,
    version: str,
    records: tuple[CatalogRecord, ...],
) -> None:
    with CatalogDatabase.create(path, schema_path) as database:
        database.set_meta_many(
            {
                "catalog_schema": "1",
                "catalog_version": version,
                "published_at": f"{version}T00:00:00Z",
                "source_rows": str(len(records)),
                "work_count": str(len(records)),
            }
        )
        database.upsert_many(sorted(records, key=lambda record: record.qid))
        database.finalize()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _logical_rows(path: Path) -> tuple[tuple[object, ...], ...]:
    import sqlite3

    connection = sqlite3.connect(path)
    try:
        works = connection.execute(
            "SELECT qid, media_type, release_year, canonical_title FROM works ORDER BY qid"
        ).fetchall()
        names = connection.execute(
            "SELECT normalized_name, work_qid, name_rank FROM names ORDER BY work_qid, name_rank"
        ).fetchall()
        meta = connection.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
    finally:
        connection.close()
    return tuple(works + names + meta)


def test_delta_round_trip_adds_updates_and_deletes(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    old = tmp_path / "old.sqlite"
    new = tmp_path / "new.sqlite"
    delta = tmp_path / "update.sqlite"
    output = tmp_path / "updated.sqlite"
    _catalog(
        old,
        schema_path,
        "2026.07.17",
        (
            _record(1, "Old title", ("old title", "old alias")),
            _record(2, "Delete me", ("delete me",)),
            _record(4, "Unchanged", ("unchanged",)),
        ),
    )
    _catalog(
        new,
        schema_path,
        "2026.07.24",
        (
            _record(1, "New title", ("new title", "new alias"), year=2021),
            _record(3, "Added series", ("added series",), media_type=MediaType.SERIES),
            _record(4, "Unchanged", ("unchanged",)),
        ),
    )
    original_base_sha = _sha256(old)

    stats = create_delta(
        old,
        new,
        delta,
        from_version="2026.07.17",
        to_version="2026.07.24",
    )
    apply_delta(old, delta, output)

    assert stats.added_works == 1
    assert stats.updated_works == 1
    assert stats.deleted_works == 1
    assert stats.unchanged_works == 1
    assert _sha256(old) == original_base_sha
    assert _logical_rows(output) == _logical_rows(new)
    assert _sha256(output) == _sha256(new)


def test_unchanged_delta_updates_metadata_and_matches_target(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    old = tmp_path / "old.sqlite"
    new = tmp_path / "new.sqlite"
    delta = tmp_path / "update.sqlite"
    output = tmp_path / "updated.sqlite"
    records = (_record(1, "Example", ("example",)),)
    _catalog(old, schema_path, "2026.07.17", records)
    _catalog(new, schema_path, "2026.07.24", records)

    stats = create_delta(
        old,
        new,
        delta,
        from_version="2026.07.17",
        to_version="2026.07.24",
    )
    apply_delta(old, delta, output)

    assert stats.added_works == 0
    assert stats.updated_works == 0
    assert stats.deleted_works == 0
    assert stats.unchanged_works == 1
    assert _sha256(output) == _sha256(new)


def test_apply_rejects_wrong_source_version_without_creating_output(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    old = tmp_path / "old.sqlite"
    wrong = tmp_path / "wrong.sqlite"
    new = tmp_path / "new.sqlite"
    delta = tmp_path / "update.sqlite"
    output = tmp_path / "updated.sqlite"
    records = (_record(1, "Example", ("example",)),)
    _catalog(old, schema_path, "2026.07.17", records)
    _catalog(wrong, schema_path, "2026.07.10", records)
    _catalog(new, schema_path, "2026.07.24", records)
    create_delta(
        old,
        new,
        delta,
        from_version="2026.07.17",
        to_version="2026.07.24",
    )

    with pytest.raises(ValueError, match="source version"):
        apply_delta(wrong, delta, output)

    assert not output.exists()


def test_corrupt_delta_preserves_existing_output(
    tmp_path: Path,
    schema_path: Path,
) -> None:
    base = tmp_path / "base.sqlite"
    delta = tmp_path / "corrupt.sqlite"
    output = tmp_path / "active.sqlite"
    _catalog(base, schema_path, "2026.07.17", (_record(1, "Example", ("example",)),))
    delta.write_bytes(b"not a sqlite database")
    output.write_bytes(b"existing active catalog")
    existing = output.read_bytes()

    with pytest.raises(ValueError, match="delta"):
        apply_delta(base, delta, output)

    assert output.read_bytes() == existing
    assert list(tmp_path.glob("*.tmp")) == []


def test_interrupted_apply_preserves_base_and_existing_output(
    tmp_path: Path,
    schema_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import media_catalog_builder.delta as delta_module

    old = tmp_path / "old.sqlite"
    new = tmp_path / "new.sqlite"
    delta = tmp_path / "update.sqlite"
    output = tmp_path / "active.sqlite"
    _catalog(old, schema_path, "2026.07.17", (_record(1, "Old", ("old",)),))
    _catalog(new, schema_path, "2026.07.24", (_record(1, "New", ("new",)),))
    create_delta(
        old,
        new,
        delta,
        from_version="2026.07.17",
        to_version="2026.07.24",
    )
    output.write_bytes(b"existing active catalog")
    old_sha = _sha256(old)
    active_bytes = output.read_bytes()

    def fail_before_activation(path: Path) -> None:
        raise RuntimeError(f"simulated interruption for {path.name}")

    monkeypatch.setattr(delta_module, "_validate_output", fail_before_activation)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        apply_delta(old, delta, output)

    assert _sha256(old) == old_sha
    assert output.read_bytes() == active_bytes
    assert list(tmp_path.glob("*.tmp")) == []
