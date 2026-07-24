from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from media_catalog_builder.classify import binding_to_source
from media_catalog_builder.config import CatalogConfig
from media_catalog_builder.model import MediaType, SourceRecord
from media_catalog_builder.names import to_catalog_record
from media_catalog_builder.release import (
    assemble_release,
    build_database_from_sources,
    validate_release,
)


def _load_cached_records(path: Path, media_type: MediaType) -> list[SourceRecord]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid probe cache: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid probe cache: {path.name}")
    results = payload.get("results")
    if not isinstance(results, Mapping):
        raise ValueError(f"invalid probe cache: {path.name}")
    raw_bindings = results.get("bindings")
    if not isinstance(raw_bindings, list):
        raise ValueError(f"invalid probe cache: {path.name}")

    records: list[SourceRecord] = []
    for raw_binding in raw_bindings:
        if not isinstance(raw_binding, Mapping):
            raise ValueError(f"invalid probe cache binding: {path.name}")
        converted: dict[str, Mapping[str, str]] = {}
        for key, raw_value in raw_binding.items():
            if not isinstance(key, str) or not isinstance(raw_value, Mapping):
                raise ValueError(f"invalid probe cache binding: {path.name}")
            converted[key] = {
                str(value_key): str(value) for value_key, value in raw_value.items()
            }
        record = binding_to_source(converted, media_type)
        if record is not None:
            records.append(record)
    return sorted(records, key=lambda record: record.qid)


def _write_lookup_cases(records: Sequence[SourceRecord], path: Path) -> None:
    cases: list[dict[str, object]] = []
    selected_types: set[MediaType] = set()
    for source in sorted(records, key=lambda record: (int(record.media_type), record.qid)):
        if source.media_type in selected_types:
            continue
        catalog_record = to_catalog_record(source)
        if catalog_record is None:
            continue
        cases.append(
            {
                "name": catalog_record.canonical_title,
                "year": catalog_record.year,
                "media_type": catalog_record.media_type.name.lower(),
                "canonical_title": catalog_record.canonical_title,
            }
        )
        selected_types.add(source.media_type)
    if not cases:
        raise ValueError("probe records contain no representative lookup case")
    path.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_probe_release(
    probe_dir: Path,
    work_dir: Path,
    release_dir: Path,
    *,
    config: CatalogConfig,
    schema_path: Path,
    version: str,
    published_at: datetime,
    minimum_app_version: str,
) -> dict[str, object]:
    records = [
        *_load_cached_records(probe_dir / "movie.json", MediaType.MOVIE),
        *_load_cached_records(probe_dir / "series.json", MediaType.SERIES),
    ]
    work_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = work_dir / "catalog.sqlite"
    lookup_cases_path = work_dir / "lookup-cases.json"
    _write_lookup_cases(records, lookup_cases_path)

    stats = build_database_from_sources(
        records,
        catalog_path,
        version=version,
        now=published_at,
        schema_path=schema_path,
    )
    manifest = assemble_release(
        catalog_path,
        release_dir,
        version=version,
        published_at=published_at,
        minimum_app_version=minimum_app_version,
        config=config,
        lookup_cases_path=lookup_cases_path,
    )
    validate_release(
        release_dir,
        config=config,
        lookup_cases_path=lookup_cases_path,
    )

    release_files = sorted(path.name for path in release_dir.iterdir() if path.is_file())
    return {
        "source_records": len(records),
        "catalog_records": stats.catalog_records,
        "skipped_records": stats.skipped_records,
        "database_bytes": stats.database_bytes,
        "compressed_bytes": manifest.full.download_bytes,
        "release_files": release_files,
    }
