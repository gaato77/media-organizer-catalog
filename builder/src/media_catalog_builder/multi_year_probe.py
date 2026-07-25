from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from media_catalog_builder.model import MediaType
from media_catalog_builder.probe import IntervalSource
from media_catalog_builder.year_probe import (
    _consolidate_caches,
    _write_json_atomic,
    run_year_probe,
)


def year_range(start_year: int, end_year: int) -> tuple[int, ...]:
    if not 1 <= start_year <= 9998 or not 1 <= end_year <= 9998:
        raise ValueError("years must be between 1 and 9998")
    if start_year > end_year:
        raise ValueError("start year must not be after end year")
    return tuple(range(start_year, end_year + 1))


def _load_completed_summary(
    output_dir: Path,
    start_year: int,
    end_year: int,
) -> dict[str, object] | None:
    summary_path = output_dir / "summary.json"
    if not summary_path.is_file() or not all(
        (output_dir / f"{media_type.name.lower()}.json").is_file()
        for media_type in (MediaType.MOVIE, MediaType.SERIES)
    ):
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("probe_schema") != 2
        or payload.get("start_year") != start_year
        or payload.get("end_year") != end_year
    ):
        return None
    return cast(dict[str, object], payload)


def _required_integer(summary: Mapping[str, object], key: str, year: int) -> int:
    value = summary.get(key)
    if not isinstance(value, int):
        raise ValueError(f"annual summary {year} has invalid {key}")
    return value


def _required_number(summary: Mapping[str, object], key: str, year: int) -> float:
    value = summary.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"annual summary {year} has invalid {key}")
    return float(value)


def _load_annual_summary(year_dir: Path, year: int) -> dict[str, object]:
    required = (
        year_dir / "summary.json",
        year_dir / "movie.json",
        year_dir / "series.json",
    )
    if not all(path.is_file() for path in required):
        raise ValueError(f"missing completed annual shard: {year}")
    try:
        payload = json.loads(required[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid completed annual shard: {year}") from exc
    if not isinstance(payload, dict) or payload.get("year") != year:
        raise ValueError(f"invalid completed annual shard: {year}")
    return cast(dict[str, object], payload)


def consolidate_year_shards(
    output_dir: Path,
    start_year: int,
    end_year: int,
) -> dict[str, object]:
    years = year_range(start_year, end_year)
    completed = _load_completed_summary(output_dir, start_year, end_year)
    if completed is not None:
        return completed

    annual_paths: dict[MediaType, list[Path]] = {
        MediaType.MOVIE: [],
        MediaType.SERIES: [],
    }
    year_summaries: list[dict[str, object]] = []
    annual_cache_bytes = 0
    query_seconds = 0.0
    limits: set[int] = set()

    for year in years:
        year_dir = output_dir / "years" / str(year)
        year_summary = _load_annual_summary(year_dir, year)
        unique_records = _required_integer(year_summary, "unique_source_records", year)
        monthly_rows = _required_integer(year_summary, "monthly_source_rows", year)
        duplicate_rows = _required_integer(year_summary, "duplicate_source_rows", year)
        cache_bytes = _required_integer(year_summary, "consolidated_cache_bytes", year)
        elapsed = _required_number(year_summary, "query_seconds", year)
        limit = year_summary.get("limit_per_type_per_month")
        if isinstance(limit, int):
            limits.add(limit)

        annual_cache_bytes += cache_bytes
        query_seconds += elapsed
        year_summaries.append(
            {
                "year": year,
                "monthly_source_rows": monthly_rows,
                "unique_source_records": unique_records,
                "duplicate_source_rows": duplicate_rows,
                "consolidated_cache_bytes": cache_bytes,
                "query_seconds": round(elapsed, 3),
            }
        )
        for media_type in (MediaType.MOVIE, MediaType.SERIES):
            annual_paths[media_type].append(year_dir / f"{media_type.name.lower()}.json")

    if len(limits) > 1:
        raise ValueError("annual shards use inconsistent limits")

    output_dir.mkdir(parents=True, exist_ok=True)
    annual_source_rows = 0
    unique_source_records = 0
    for media_type in (MediaType.MOVIE, MediaType.SERIES):
        rows, unique = _consolidate_caches(
            annual_paths[media_type],
            output_dir / f"{media_type.name.lower()}.json",
        )
        annual_source_rows += rows
        unique_source_records += unique

    consolidated_cache_bytes = sum(
        (output_dir / f"{media_type.name.lower()}.json").stat().st_size
        for media_type in (MediaType.MOVIE, MediaType.SERIES)
    )
    summary: dict[str, object] = {
        "probe_schema": 2,
        "start_year": start_year,
        "end_year": end_year,
        "year_count": len(years),
        "limit_per_type_per_month": next(iter(limits)) if limits else 0,
        "years": year_summaries,
        "annual_source_rows": annual_source_rows,
        "unique_source_records": unique_source_records,
        "duplicate_source_rows": annual_source_rows - unique_source_records,
        "annual_cache_bytes": annual_cache_bytes,
        "consolidated_cache_bytes": consolidated_cache_bytes,
        "query_seconds": round(query_seconds, 3),
    }
    _write_json_atomic(output_dir / "summary.json", summary)
    return summary


def run_multi_year_probe(
    source: IntervalSource,
    output_dir: Path,
    start_year: int,
    end_year: int,
    *,
    limit: int,
) -> dict[str, object]:
    years = year_range(start_year, end_year)
    if not 1 <= limit <= 50000:
        raise ValueError("limit must be between 1 and 50000")
    completed = _load_completed_summary(output_dir, start_year, end_year)
    if completed is not None:
        return completed

    output_dir.mkdir(parents=True, exist_ok=True)
    for year in years:
        run_year_probe(source, output_dir / "years" / str(year), year, limit=limit)
    return consolidate_year_shards(output_dir, start_year, end_year)
