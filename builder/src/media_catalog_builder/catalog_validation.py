from __future__ import annotations

import sqlite3
from pathlib import Path

from media_catalog_builder.database import sqlite_readonly_uri


def validate_catalog_year(catalog_path: Path, required_year: int) -> None:
    if not 1 <= required_year <= 9999:
        raise ValueError("required year must be between 1 and 9999")
    try:
        connection = sqlite3.connect(sqlite_readonly_uri(catalog_path), uri=True)
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM works WHERE release_year <> ?",
                (required_year,),
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError("invalid catalog database") from exc
    if row is None or int(row[0]) != 0:
        raise ValueError("catalog contains records outside required year")
