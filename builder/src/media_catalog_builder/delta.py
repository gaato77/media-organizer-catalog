from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from media_catalog_builder.database import sqlite_readonly_uri

_DELTA_SCHEMA = Path(__file__).resolve().parents[3] / "schema" / "delta-schema-v1.sql"
_REQUIRED_DELTA_META = frozenset(
    {
        "delta_schema",
        "catalog_schema",
        "from_version",
        "to_version",
        "source_sha256",
        "target_sha256",
        "target_header_fields",
    }
)
type WorkRow = tuple[int, int, int, str, tuple[tuple[str, int], ...]]
type StatRow = tuple[int, str, str | None, str]


@dataclass(frozen=True, slots=True)
class DeltaStats:
    added_works: int
    updated_works: int
    deleted_works: int
    unchanged_works: int
    delta_bytes: int


class _Connection:
    def __init__(self, path: Path, *, readonly: bool = False) -> None:
        if readonly:
            self.connection = sqlite3.connect(sqlite_readonly_uri(path), uri=True)
        else:
            self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row

    def __enter__(self) -> sqlite3.Connection:
        return self.connection

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.connection.close()


def _sqlite_header_fields(path: Path) -> str:
    header = path.read_bytes()[:100]
    if len(header) < 100 or header[:16] != b"SQLite format 3\x00":
        raise ValueError("invalid SQLite header")
    return (header[24:28] + header[40:44] + header[92:96]).hex()


def _patch_sqlite_header_fields(path: Path, fields_hex: str) -> None:
    try:
        fields = bytes.fromhex(fields_hex)
    except ValueError as exc:
        raise ValueError("invalid target SQLite header fields") from exc
    if len(fields) != 12:
        raise ValueError("invalid target SQLite header fields")
    with path.open("r+b") as handle:
        header = bytearray(handle.read(100))
        if len(header) < 100 or header[:16] != b"SQLite format 3\x00":
            raise ValueError("invalid updated SQLite header")
        header[24:28] = fields[0:4]
        header[40:44] = fields[4:8]
        header[92:96] = fields[8:12]
        handle.seek(0)
        handle.write(header)
        handle.flush()
        os.fsync(handle.fileno())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity(connection: sqlite3.Connection, label: str) -> None:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    if row is None or str(row[0]) != "ok":
        result = "missing" if row is None else str(row[0])
        raise ValueError(f"{label} integrity check failed: {result}")


def _meta(connection: sqlite3.Connection, table: str = "meta") -> dict[str, str]:
    if table not in {"meta", "target_meta"}:
        raise ValueError("invalid metadata table")
    rows = connection.execute(f"SELECT key, value FROM {table} ORDER BY key").fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def _catalog_rows(connection: sqlite3.Connection) -> dict[int, WorkRow]:
    works = connection.execute(
        "SELECT qid, media_type, release_year, canonical_title FROM works ORDER BY qid"
    ).fetchall()
    result: dict[int, WorkRow] = {}
    for work in works:
        qid = int(work["qid"])
        names = tuple(
            (str(row["normalized_name"]), int(row["name_rank"]))
            for row in connection.execute(
                "SELECT normalized_name, name_rank FROM names "
                "WHERE work_qid = ? ORDER BY name_rank",
                (qid,),
            )
        )
        result[qid] = (
            qid,
            int(work["media_type"]),
            int(work["release_year"]),
            str(work["canonical_title"]),
            names,
        )
    return result


def _catalog_snapshot(path: Path, label: str) -> tuple[dict[str, str], dict[int, WorkRow]]:
    try:
        with _Connection(path, readonly=True) as connection:
            _integrity(connection, label)
            metadata = _meta(connection)
            rows = _catalog_rows(connection)
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"invalid {label} catalog") from exc
    return metadata, rows


def _catalog_statistics(path: Path, label: str) -> tuple[StatRow, ...]:
    try:
        with _Connection(path, readonly=True) as connection:
            rows = connection.execute(
                "SELECT rowid, tbl, idx, stat FROM sqlite_stat1 ORDER BY rowid"
            ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"invalid {label} catalog statistics") from exc
    return tuple(
        (
            int(row["rowid"]),
            str(row["tbl"]),
            None if row["idx"] is None else str(row["idx"]),
            str(row["stat"]),
        )
        for row in rows
    )


def _create_delta_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(_DELTA_SCHEMA.read_text(encoding="utf-8"))
        connection.commit()
    except Exception:
        connection.close()
        path.unlink(missing_ok=True)
        raise
    return connection


def create_delta(
    old_catalog: Path,
    new_catalog: Path,
    delta_path: Path,
    *,
    from_version: str,
    to_version: str,
) -> DeltaStats:
    old_meta, old_rows = _catalog_snapshot(old_catalog, "source")
    new_meta, new_rows = _catalog_snapshot(new_catalog, "target")
    new_statistics = _catalog_statistics(new_catalog, "target")
    if old_meta.get("catalog_version") != from_version:
        raise ValueError("source catalog version does not match from_version")
    if new_meta.get("catalog_version") != to_version:
        raise ValueError("target catalog version does not match to_version")
    old_schema = old_meta.get("catalog_schema")
    new_schema = new_meta.get("catalog_schema")
    if old_schema is None or old_schema != new_schema:
        raise ValueError("catalog schema mismatch")

    old_qids = set(old_rows)
    new_qids = set(new_rows)
    added = new_qids - old_qids
    deleted = old_qids - new_qids
    updated = {qid for qid in old_qids & new_qids if old_rows[qid] != new_rows[qid]}
    unchanged = (old_qids & new_qids) - updated
    changed = added | updated

    connection = _create_delta_database(delta_path)
    try:
        with connection:
            connection.executemany(
                "INSERT INTO meta(key, value) VALUES(?, ?)",
                sorted(
                    {
                        "delta_schema": "1",
                        "catalog_schema": old_schema,
                        "from_version": from_version,
                        "to_version": to_version,
                        "source_sha256": _sha256(old_catalog),
                        "target_sha256": _sha256(new_catalog),
                        "target_header_fields": _sqlite_header_fields(new_catalog),
                    }.items()
                ),
            )
            connection.executemany(
                "INSERT INTO target_meta(key, value) VALUES(?, ?)",
                sorted(new_meta.items()),
            )
            connection.executemany(
                "INSERT INTO target_stat1(row_id, table_name, index_name, statistics) "
                "VALUES(?, ?, ?, ?)",
                new_statistics,
            )
            connection.executemany(
                "INSERT INTO delete_works(qid) VALUES(?)",
                ((qid,) for qid in sorted(deleted)),
            )
            for qid in sorted(changed):
                row = new_rows[qid]
                connection.execute(
                    "INSERT INTO upsert_works(qid, media_type, release_year, canonical_title) "
                    "VALUES(?, ?, ?, ?)",
                    row[:4],
                )
                connection.executemany(
                    "INSERT INTO upsert_names(normalized_name, work_qid, name_rank) "
                    "VALUES(?, ?, ?)",
                    ((name, qid, rank) for name, rank in row[4]),
                )
        connection.execute("ANALYZE")
        connection.execute("PRAGMA optimize")
        connection.commit()
        connection.execute("VACUUM")
        _integrity(connection, "delta")
    except Exception:
        connection.close()
        delta_path.unlink(missing_ok=True)
        raise
    finally:
        connection.close()

    return DeltaStats(
        added_works=len(added),
        updated_works=len(updated),
        deleted_works=len(deleted),
        unchanged_works=len(unchanged),
        delta_bytes=delta_path.stat().st_size,
    )


def _delta_metadata(path: Path) -> dict[str, str]:
    try:
        with _Connection(path, readonly=True) as connection:
            _integrity(connection, "delta")
            metadata = _meta(connection)
            if not _REQUIRED_DELTA_META.issubset(metadata):
                raise ValueError("delta metadata is incomplete")
            if metadata["delta_schema"] != "1":
                raise ValueError("unsupported delta schema")
            target_meta = _meta(connection, "target_meta")
            if target_meta.get("catalog_version") != metadata["to_version"]:
                raise ValueError("delta target metadata is inconsistent")
    except sqlite3.DatabaseError as exc:
        raise ValueError("invalid delta database") from exc
    return metadata


def _apply_delta_sql(temp_path: Path, delta_path: Path) -> None:
    connection = sqlite3.connect(temp_path)
    target_statistics: tuple[StatRow, ...] | None = None
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("ATTACH DATABASE ? AS delta_db", (str(delta_path),))
        try:
            has_target_statistics = connection.execute(
                "SELECT 1 FROM delta_db.sqlite_master "
                "WHERE type = 'table' AND name = 'target_stat1'"
            ).fetchone()
            if has_target_statistics is not None:
                target_statistics = tuple(
                    (
                        int(row[0]),
                        str(row[1]),
                        None if row[2] is None else str(row[2]),
                        str(row[3]),
                    )
                    for row in connection.execute(
                        "SELECT row_id, table_name, index_name, statistics "
                        "FROM delta_db.target_stat1 ORDER BY row_id"
                    )
                )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM works WHERE qid IN (SELECT qid FROM delta_db.delete_works)"
            )
            connection.execute(
                "DELETE FROM names WHERE work_qid IN (SELECT qid FROM delta_db.upsert_works)"
            )
            connection.execute(
                "INSERT OR REPLACE INTO works(qid, media_type, release_year, canonical_title) "
                "SELECT qid, media_type, release_year, canonical_title "
                "FROM delta_db.upsert_works ORDER BY qid"
            )
            connection.execute(
                "INSERT INTO names(normalized_name, work_qid, name_rank) "
                "SELECT normalized_name, work_qid, name_rank "
                "FROM delta_db.upsert_names ORDER BY work_qid, name_rank"
            )
            connection.execute("DELETE FROM meta")
            connection.execute(
                "INSERT INTO meta(key, value) "
                "SELECT key, value FROM delta_db.target_meta ORDER BY key"
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("DETACH DATABASE delta_db")

        connection.execute("ANALYZE")
        connection.execute("PRAGMA optimize")
        connection.commit()
        if target_statistics is not None:
            connection.execute("DELETE FROM sqlite_stat1")
            connection.executemany(
                "INSERT INTO sqlite_stat1(rowid, tbl, idx, stat) VALUES(?, ?, ?, ?)",
                target_statistics,
            )
            connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()


def _validate_output(path: Path) -> None:
    try:
        with _Connection(path, readonly=True) as connection:
            _integrity(connection, "updated catalog")
    except sqlite3.DatabaseError as exc:
        raise ValueError("updated catalog is invalid") from exc


def apply_delta(base_catalog: Path, delta_path: Path, output_catalog: Path) -> None:
    if base_catalog.resolve() == output_catalog.resolve():
        raise ValueError("output catalog must differ from base catalog")
    metadata = _delta_metadata(delta_path)
    base_meta, _ = _catalog_snapshot(base_catalog, "source")
    if base_meta.get("catalog_version") != metadata["from_version"]:
        raise ValueError("source version does not match delta")
    if base_meta.get("catalog_schema") != metadata["catalog_schema"]:
        raise ValueError("source catalog schema does not match delta")
    if _sha256(base_catalog) != metadata["source_sha256"]:
        raise ValueError("source catalog checksum does not match delta")

    output_catalog.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_catalog.with_name(f"{output_catalog.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        shutil.copyfile(base_catalog, temporary)
        _apply_delta_sql(temporary, delta_path)
        _patch_sqlite_header_fields(temporary, metadata["target_header_fields"])
        _validate_output(temporary)
        if _sha256(temporary) != metadata["target_sha256"]:
            raise ValueError("updated catalog checksum does not match target")
        os.replace(temporary, output_catalog)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
