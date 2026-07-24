from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from media_catalog_builder.model import MediaType, SourceRecord


class IntervalSource(Protocol):
    def fetch_interval(
        self,
        media_type: MediaType,
        start: datetime,
        end: datetime,
        cache_path: Path,
        *,
        limit: int,
    ) -> list[SourceRecord]: ...


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_probe(
    source: IntervalSource,
    output_dir: Path,
    start: datetime,
    end: datetime,
    *,
    limit: int,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    total_records = 0
    total_cache_bytes = 0

    for media_type in (MediaType.MOVIE, MediaType.SERIES):
        cache_path = output_dir / f"{media_type.name.lower()}.json"
        started = clock()
        records = source.fetch_interval(
            media_type,
            start,
            end,
            cache_path,
            limit=limit,
        )
        elapsed_seconds = max(0.0, clock() - started)
        cache_bytes = cache_path.stat().st_size
        total_records += len(records)
        total_cache_bytes += cache_bytes
        results.append(
            {
                "media_type": media_type.name.lower(),
                "records": len(records),
                "cache_bytes": cache_bytes,
                "elapsed_seconds": round(elapsed_seconds, 3),
            }
        )

    summary: dict[str, object] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit_per_type": limit,
        "results": results,
        "total_records": total_records,
        "total_cache_bytes": total_cache_bytes,
    }
    _write_json_atomic(output_dir / "summary.json", summary)
    return summary
