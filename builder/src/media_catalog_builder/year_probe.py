from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from media_catalog_builder.model import MediaType
from media_catalog_builder.probe import IntervalSource, run_probe

_SEPARATOR = "\u001f"
type ProbeInterval = tuple[datetime, datetime, bool]


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _as_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _next_month_start(year: int, month: int) -> datetime:
    if month == 12:
        return datetime(year + 1, 1, 1, tzinfo=UTC)
    return datetime(year, month + 1, 1, tzinfo=UTC)


def _probe_intervals(
    year: int,
    through: datetime | None,
) -> tuple[tuple[ProbeInterval, ...], datetime]:
    if not 1 <= year <= 9998:
        raise ValueError("year must be between 1 and 9998")

    year_start = datetime(year, 1, 1, tzinfo=UTC)
    year_boundary = datetime(year + 1, 1, 1, tzinfo=UTC)
    through_utc = year_boundary if through is None else _as_utc(through, label="through")
    if not year_start < through_utc <= year_boundary:
        raise ValueError("through must fall within the selected year boundary")

    intervals: list[ProbeInterval] = []
    for month in range(1, 13):
        start = datetime(year, month, 1, tzinfo=UTC)
        if start >= through_utc:
            break
        natural_end = _next_month_start(year, month)
        end = min(natural_end, through_utc)
        intervals.append((start, end, end == natural_end))
    return tuple(intervals), through_utc


def month_intervals(year: int) -> tuple[tuple[datetime, datetime], ...]:
    intervals, _ = _probe_intervals(year, None)
    return tuple((start, end) for start, end, _complete in intervals)


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
    left_key = (left_value.casefold(), left_value)
    right_key = (right_value.casefold(), right_value)
    return left if left_key <= right_key else right


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


def _load_completed_summary(
    output_dir: Path,
    *,
    year: int,
    through: datetime,
    refresh_months: frozenset[int],
) -> dict[str, object] | None:
    if refresh_months:
        return None
    summary_path = output_dir / "summary.json"
    if not summary_path.is_file() or not all(
        (output_dir / f"{media_type.name.lower()}.json").is_file()
        for media_type in (MediaType.MOVIE, MediaType.SERIES)
    ):
        return None
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("probe_schema") != 1
        or payload.get("year") != year
        or payload.get("through") != _format_utc(through)
    ):
        return None
    return cast(dict[str, object], payload)


def _validated_refresh_months(
    requested: frozenset[int] | None,
    elapsed: frozenset[int],
) -> frozenset[int]:
    refresh_months = frozenset() if requested is None else requested
    for month in refresh_months:
        if isinstance(month, bool) or not 1 <= month <= 12:
            raise ValueError("refresh month must be between 1 and 12")
        if month not in elapsed:
            raise ValueError("refresh month is not elapsed")
    return refresh_months


def run_year_probe(
    source: IntervalSource,
    output_dir: Path,
    year: int,
    *,
    limit: int,
    through: datetime | None = None,
    refresh_months: frozenset[int] | None = None,
) -> dict[str, object]:
    if not 1 <= limit <= 50000:
        raise ValueError("limit must be between 1 and 50000")

    intervals, through_utc = _probe_intervals(year, through)
    elapsed_months = frozenset(start.month for start, _end, _complete in intervals)
    selected_refresh_months = _validated_refresh_months(refresh_months, elapsed_months)
    completed = _load_completed_summary(
        output_dir,
        year=year,
        through=through_utc,
        refresh_months=selected_refresh_months,
    )
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

    for start, end, complete in intervals:
        month_name = f"{start.year:04d}-{start.month:02d}"
        month_dir = output_dir / "months" / month_name
        if start.month in selected_refresh_months:
            shutil.rmtree(month_dir, ignore_errors=True)
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
                "window_start": _format_utc(start),
                "window_end": _format_utc(end),
                "complete": complete,
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
    active_partial_month = next(
        (str(month["month"]) for month in month_summaries if month["complete"] is False),
        None,
    )
    summary: dict[str, object] = {
        "probe_schema": 1,
        "year": year,
        "through": _format_utc(through_utc),
        "month_count": len(month_summaries),
        "complete_month_count": sum(1 for month in month_summaries if month["complete"] is True),
        "active_partial_month": active_partial_month,
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
