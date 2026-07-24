from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from media_catalog_builder.database import CatalogDatabase
from media_catalog_builder.model import MediaType, SourceRecord
from media_catalog_builder.release import build_database_from_sources


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "build" / "sample.sqlite"
SCHEMA = ROOT / "schema" / "catalog-schema-v1.sql"


def main() -> int:
    sources = [
        SourceRecord(
            1,
            MediaType.MOVIE,
            2001,
            ("Amélie",),
            "Amelie",
            "Amélie",
        ),
        SourceRecord(
            2,
            MediaType.SERIES,
            2020,
            ("Example Series",),
            "Example Series",
            "Serie de ejemplo",
        ),
    ]
    stats = build_database_from_sources(
        sources,
        OUTPUT,
        version="smoke",
        now=datetime(2026, 7, 24, tzinfo=UTC),
        schema_path=SCHEMA,
    )
    with CatalogDatabase.open(OUTPUT, readonly=True) as database:
        movie = database.lookup("Amelie", year=2001, media_type=MediaType.MOVIE)
        series = database.lookup(
            "Serie de ejemplo",
            year=2020,
            media_type=MediaType.SERIES,
        )
        integrity = database.integrity_check()

    if len(movie) != 1 or movie[0].canonical_title != "Amélie":
        raise RuntimeError("movie smoke lookup failed")
    if len(series) != 1 or series[0].canonical_title != "Example Series":
        raise RuntimeError("series smoke lookup failed")
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity failed: {integrity}")

    print(
        json.dumps(
            {
                "catalog_records": stats.catalog_records,
                "database_bytes": stats.database_bytes,
                "integrity": integrity,
                "movie": movie[0].canonical_title,
                "series": series[0].canonical_title,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
