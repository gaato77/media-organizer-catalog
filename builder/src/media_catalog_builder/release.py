from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from media_catalog_builder.database import CatalogDatabase
from media_catalog_builder.model import SourceRecord
from media_catalog_builder.names import to_catalog_record
from media_catalog_builder.normalize import normalize_lookup


@dataclass(frozen=True, slots=True)
class BuildStats:
    source_rows: int
    catalog_records: int
    skipped_records: int
    database_bytes: int


def _text_sort_key(value: str) -> tuple[str, str, str]:
    return (normalize_lookup(value), value.casefold(), value)


def _first_label(records: Sequence[SourceRecord], attribute: str) -> str | None:
    values = {
        value.strip()
        for record in records
        if (value := getattr(record, attribute)) is not None and value.strip()
    }
    return min(values, key=_text_sort_key) if values else None


def _merge_source_records(records: Sequence[SourceRecord]) -> SourceRecord:
    if not records:
        raise ValueError("source record group cannot be empty")
    originals = {
        title.strip() for record in records for title in record.original_titles if title.strip()
    }
    modified_values = [record.modified_at for record in records if record.modified_at]
    return SourceRecord(
        qid=records[0].qid,
        media_type=max((record.media_type for record in records), key=int),
        year=min(record.year for record in records),
        original_titles=tuple(sorted(originals, key=_text_sort_key)),
        english_label=_first_label(records, "english_label"),
        spanish_label=_first_label(records, "spanish_label"),
        modified_at=max(modified_values) if modified_values else None,
    )


def _published_at(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_database_from_sources(
    records: Iterable[SourceRecord],
    output: Path,
    *,
    version: str,
    now: datetime,
    schema_path: Path,
) -> BuildStats:
    source_rows = list(records)
    grouped: dict[int, list[SourceRecord]] = {}
    for record in source_rows:
        grouped.setdefault(record.qid, []).append(record)

    catalog_records = []
    skipped_records = 0
    for qid in sorted(grouped):
        merged = _merge_source_records(grouped[qid])
        catalog_record = to_catalog_record(merged)
        if catalog_record is None:
            skipped_records += 1
        else:
            catalog_records.append(catalog_record)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with CatalogDatabase.create(output, schema_path) as database:
        database.set_meta_many(
            {
                "catalog_schema": "1",
                "catalog_version": version,
                "published_at": _published_at(now),
                "source_rows": str(len(source_rows)),
                "work_count": str(len(catalog_records)),
            }
        )
        database.upsert_many(catalog_records)
        database.finalize()

    return BuildStats(
        source_rows=len(source_rows),
        catalog_records=len(catalog_records),
        skipped_records=skipped_records,
        database_bytes=output.stat().st_size,
    )
