from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import TracebackType

from media_catalog_builder.model import CatalogRecord, MediaType
from media_catalog_builder.normalize import normalize_lookup


class CatalogDatabase:
    def __init__(
        self,
        path: Path,
        connection: sqlite3.Connection,
        *,
        readonly: bool,
    ) -> None:
        self.path = path
        self._connection = connection
        self._readonly = readonly
        self._closed = False

    @classmethod
    def create(cls, path: Path, schema_path: Path) -> CatalogDatabase:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(path)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            connection.commit()
        except Exception:
            connection.close()
            path.unlink(missing_ok=True)
            raise
        return cls(path, connection, readonly=False)

    @classmethod
    def open(cls, path: Path, *, readonly: bool = False) -> CatalogDatabase:
        if readonly:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return cls(path, connection, readonly=readonly)

    def __enter__(self) -> CatalogDatabase:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def _require_writable(self) -> None:
        if self._readonly:
            raise PermissionError("catalog database is read-only")

    def _upsert_uncommitted(self, record: CatalogRecord) -> None:
        self._connection.execute(
            "INSERT INTO works(qid, media_type, release_year, canonical_title) "
            "VALUES(?, ?, ?, ?) "
            "ON CONFLICT(qid) DO UPDATE SET "
            "media_type=excluded.media_type, "
            "release_year=excluded.release_year, "
            "canonical_title=excluded.canonical_title",
            (
                record.qid,
                int(record.media_type),
                record.year,
                record.canonical_title,
            ),
        )
        self._connection.execute("DELETE FROM names WHERE work_qid = ?", (record.qid,))
        self._connection.executemany(
            "INSERT INTO names(normalized_name, work_qid, name_rank) VALUES(?, ?, ?)",
            ((name, record.qid, rank) for rank, name in enumerate(record.names)),
        )

    def upsert(self, record: CatalogRecord) -> None:
        self._require_writable()
        with self._connection:
            self._upsert_uncommitted(record)

    def upsert_many(self, records: Iterable[CatalogRecord]) -> None:
        self._require_writable()
        with self._connection:
            for record in records:
                self._upsert_uncommitted(record)

    def delete(self, qid: int) -> None:
        self._require_writable()
        with self._connection:
            self._connection.execute("DELETE FROM works WHERE qid = ?", (qid,))

    def set_meta(self, key: str, value: str) -> None:
        self._require_writable()
        with self._connection:
            self._connection.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def set_meta_many(self, values: Mapping[str, str]) -> None:
        self._require_writable()
        with self._connection:
            self._connection.executemany(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                sorted(values.items()),
            )

    def get_meta(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM meta WHERE key = ?",
            (key,),
        ).fetchone()
        return None if row is None else str(row["value"])

    def _load_record(self, qid: int) -> CatalogRecord:
        work = self._connection.execute(
            "SELECT qid, media_type, release_year, canonical_title FROM works WHERE qid = ?",
            (qid,),
        ).fetchone()
        if work is None:
            raise KeyError(qid)
        names = tuple(
            str(row["normalized_name"])
            for row in self._connection.execute(
                "SELECT normalized_name FROM names WHERE work_qid = ? ORDER BY name_rank",
                (qid,),
            )
        )
        return CatalogRecord(
            qid=int(work["qid"]),
            media_type=MediaType(int(work["media_type"])),
            year=int(work["release_year"]),
            canonical_title=str(work["canonical_title"]),
            names=names,
        )

    def lookup(
        self,
        name: str,
        *,
        year: int | None = None,
        media_type: MediaType | None = None,
    ) -> tuple[CatalogRecord, ...]:
        normalized_name = normalize_lookup(name)
        if not normalized_name:
            return ()

        clauses = ["n.normalized_name = ?"]
        parameters: list[object] = [normalized_name]
        if year is not None:
            clauses.append("w.release_year = ?")
            parameters.append(year)
        if media_type is not None:
            clauses.append("w.media_type = ?")
            parameters.append(int(media_type))

        rows = self._connection.execute(
            "SELECT w.qid FROM names AS n "
            "JOIN works AS w ON w.qid = n.work_qid "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY w.release_year, w.media_type, w.qid",
            parameters,
        ).fetchall()
        return tuple(self._load_record(int(row["qid"])) for row in rows)

    def integrity_check(self) -> str:
        row = self._connection.execute("PRAGMA integrity_check").fetchone()
        if row is None:
            raise RuntimeError("SQLite integrity check returned no result")
        return str(row[0])

    def finalize(self) -> str:
        self._require_writable()
        self._connection.commit()
        self._connection.execute("ANALYZE")
        self._connection.execute("PRAGMA optimize")
        self._connection.commit()
        self._connection.execute("VACUUM")
        result = self.integrity_check()
        if result != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {result}")
        return result
