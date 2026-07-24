from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from media_catalog_builder.model import MediaType, SourceRecord
from media_catalog_builder.probe import run_probe


class FakeSource:
    def fetch_interval(
        self,
        media_type: MediaType,
        start: datetime,
        end: datetime,
        cache_path: Path,
        *,
        limit: int,
    ) -> list[SourceRecord]:
        cache_path.write_text('{"cached":true}', encoding="utf-8")
        return [
            SourceRecord(
                qid=int(media_type),
                media_type=media_type,
                year=start.year,
                original_titles=(media_type.name,),
                english_label=media_type.name,
                spanish_label=None,
            )
        ][:limit]


def test_probe_writes_metrics_for_both_media_types(tmp_path: Path):
    ticks = iter((1.0, 1.25, 2.0, 2.5))
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 2, 1, tzinfo=UTC)

    summary = run_probe(
        FakeSource(),
        tmp_path,
        start,
        end,
        limit=25,
        clock=lambda: next(ticks),
    )

    assert summary["total_records"] == 2
    assert [result["media_type"] for result in summary["results"]] == [  # type: ignore[index]
        "movie",
        "series",
    ]
    saved = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert saved == summary
    assert list(tmp_path.glob("*.tmp")) == []
