from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from media_catalog_builder.model import MediaType
from media_catalog_builder.probe import IntervalSource, run_probe

_SEPARATOR = "\u001f"


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def month_intervals(year: int) -> tuple[tuple[datetime, datetime], ...]:
    if not 1 <= year <= 9998:
        raise ValueError("year must be between 1 and 9998")
    starts = [datetime(year, month, 1, tzinfo=UTC) for month in range(1, 13)]
    starts.append(datetime(year + 1, 1, 1, tzinfo=UTC))
    return tuple(zip(starts, starts[1:], strict=True))


def _read_bindings(path: Path) -> list[dict[str, dict[str, str]]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid monthly cache: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"invalid monthly cache: {path}")
    results = payload.get("results")
    if not isinstance(results, Mapping):
        raise ValueError(f"invalid monthly cache: {path}")
    raw_bindings = results.get("bindings")
    if not isinstance(raw_bindings, list):
        raise ValueError(f"invalid monthly cache: {path}")

    bindings: list[dict[str, dict[str, str]]] = []
    for raw_binding in raw_bindings:
        if not isinstance(raw_binding, Mapping):
            raise ValueError(f"invalid monthly cache binding: {path}")
        binding: dict[str, dict[str, str]] = {}
        for key, raw_value in raw_binding.items():
            if not isinstance(key, str) or not isinstance(raw_value, Mapping):
                raise ValueError(f"invalid monthly cache binding: {path}")
            binding[key] = {str(value_key): str(value) for value_key, value in raw_value.items()}
        item = binding.get("item")
        if item is None or not item.get("value"):
            raise ValueError(f"monthly cache binding has no item: {path}")
        bindings.append(binding)
    return bindings


def _merge_multi_value(left: str, right: str) -> str:
    values = {value for value in (*left.split(_SEPARATOR), *right.split(_SEPARATOR)) if value}
    return _SEPARATOR.join(sorted(values, key=lambda value: (value.casefold(), value)))


def _merge_entry(
    key: str,
    left: dict[str, str],
    right: dict[str, str],
) -> dict[str, str]:
    left_value = left.get("value", "")
    right_value = right.get("value", "")
    if left_value == right_value:
        return left
    if key in {"originals", "aliases"}:
        merged = dict(left)
        merged["value"] = _merge_multi_value(left_value, right_value)
        return merged
    if key == "releaseDate":
        return left if left_value <= right_value else right
    if key == "modified":
        return left if left_value >= right_value else right
    return left if (left_value.casefold(), left_value) <= (right_value.casefold(), right_value) else right


def _merge_binding(
    left: dict[str, dict[str, str]],
    right: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    merged = {key: dict(value) for key, value in left.items()}
    for key, value in right.items():
        if key in merged:
            merged[key] = _merge_entry(key, merged[key], value)
        else:
            merged[key] = dict(value)
    return merged


def _item_sort_key(item_uri: str) -> tuple[int, str]:
    suffix = item_uri.rsplit("Q", 1)[-1]
    return (int(suffix), item_uri) if suffix.isdigit() else (2**63 - 1, item_uri)


def _consolidate_caches(paths: Sequence[Path], output_path: Path) -> tuple[int, int]:
    monthly_rows = 0
    by_item: dict[str, dict[str, dict[str, str]]] = {}
    for path in paths:
        for binding in _read_bindings(path):
            monthly_rows += 1
            item_uri = binding["item"]["value"]
            existing = by_item.get(item_uri)
            by_item[item_uri] = binding if existing is None else _merge_binding(existing, binding)

    bindings = [by_item[item] for item in sorted(by_item, key=_item_sort_key)]
    _write_json_atomic(output_path, {"results": {"bindings": bindings}})
    return monthly_rows, len(bindings)


def _load_completed_summary(output_dir: Path) -> dict[str, object] | None:
    summary_path = output_dir / "summary.json"
    if not summary_path.is_file() or not all(
        (output_dir / f"{media_type.name.lower()}.json").is_file()
        for media_type in (MediaType.MOVIE, MediaType.SERIES)
    ):
        return None
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("probe_schema") != 1:
        return None
    return cast(dict[str, object], payload)


def run_year_probe(
    source: IntervalSource,
    output_dir: Path,
    year: int,
    *,
    limit: int,
) -> dict[str, object]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    completed = _load_completed_summary(output_dir)
    if completed is not None:
        return completed

    output_dir.mkdir(parents=True, exist_ok=True)
    month_summaries: list[dict[str, object]] = []
    monthly_paths: dict[MediaType, list[Path]] = {
        MediaType.MOVIE: [],
        MediaType.SERIES: [],
    }
    monthly_cache_bytes = 0
    query_seconds = 0.0

    for start, end in month_intervals(year):
        month_name = f"{start.year:04d}-{start.month:02d}"
        month_dir = output_dir / "months" / month_name
        month_summary = run_probe(source, month_dir, start, end, limit=limit)
        results = month_summary.get("results")
        if not isinstance(results, list):
            raise ValueError(f"monthly probe summary is invalid: {month_name}")
        for result in results:
            if not isinstance(result, Mapping):
                raise ValueError(f"monthly probe result is invalid: {month_name}")
            records = result.get("records")
            if not isinstance(records, int):
                raise ValueError(f"monthly probe count is invalid: {month_name}")
            if records >= limit:
                raise ValueError(f"{month_name} reached the monthly limit of {limit}")
            elapsed = result.get("elapsed_seconds")
            if isinstance(elapsed, (int, float)):
                query_seconds += float(elapsed)
        cache_bytes = month_summary.get("total_cache_bytes")
        if not isinstance(cache_bytes, int):
            raise ValueError(f"monthly cache size is invalid: {month_name}")
        monthly_cache_bytes += cache_bytes
        month_summaries.append(
            {
                "month": month_name,
                "total_records": month_summary["total_records"],
                "cache_bytes": cache_bytes,
                "results": results,
            }
        )
        for media_type in (MediaType.MOVIE, MediaType.SERIES):
            monthly_paths[media_type].append(month_dir / f"{media_type.name.lower()}.json")

    monthly_source_rows = 0
    unique_source_records = 0
    for media_type in (MediaType.MOVIE, MediaType.SERIES):
        rows, unique = _consolidate_caches(
            monthly_paths[media_type],
            output_dir / f"{media_type.name.lower()}.json",
        )
        monthly_source_rows += rows
        unique_source_records += unique

    consolidated_cache_bytes = sum(
        (output_dir / f"{media_type.name.lower()}.json").stat().st_size
        for media_type in (MediaType.MOVIE, MediaType.SERIES)
    )
    summary: dict[str, object] = {
        "probe_schema": 1,
        "year": year,
        "month_count": len(month_summaries),
        "limit_per_type_per_month": limit,
        "months": month_summaries,
        "monthly_source_rows": monthly_source_rows,
        "unique_source_records": unique_source_records,
        "duplicate_source_rows": monthly_source_rows - unique_source_records,
        "monthly_cache_bytes": monthly_cache_bytes,
        "consolidated_cache_bytes": consolidated_cache_bytes,
        "query_seconds": round(query_seconds, 3),
    }
    _write_json_atomic(output_dir / "summary.json", summary)
    return summary
