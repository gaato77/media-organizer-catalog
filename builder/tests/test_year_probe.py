from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from media_catalog_builder.model import MediaType, SourceRecord
from media_catalog_builder.year_probe import month_intervals, run_year_probe


def _binding(qid: int, year: int, title: str) -> dict[str, dict[str, str]]:
    return {
        "item": {
            "type": "uri",
            "value": f"http://www.wikidata.org/entity/Q{qid}",
        },
        "releaseDate": {
            "type": "literal",
            "value": f"{year}-01-01T00:00:00Z",
        },
        "originals": {"type": "literal", "value": title},
        "enLabel": {"type": "literal", "value": title},
    }


def _records(payload: dict[str, Any], media_type: MediaType, year: int) -> list[SourceRecord]:
    result: list[SourceRecord] = []
    for binding in payload["results"]["bindings"]:
        qid = int(binding["item"]["value"].rsplit("Q", 1)[1])
        title = binding["enLabel"]["value"]
        result.append(
            SourceRecord(
                qid=qid,
                media_type=media_type,
                year=year,
                original_titles=(title,),
                english_label=title,
                spanish_label=None,
            )
        )
    return result


class FakeYearSource:
    def __init__(self) -> None:
        self.downloads = 0

    def fetch_interval(
        self,
        media_type: MediaType,
        start: datetime,
        end: datetime,
        cache_path: Path,
        *,
        limit: int,
    ) -> list[SourceRecord]:
        del end, limit
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return _records(payload, media_type, start.year)

        self.downloads += 1
        qid = start.month * 100 + int(media_type)
        bindings = [_binding(qid, start.year, f"{media_type.name} {start.month}")]
        if media_type is MediaType.MOVIE and start.month in {1, 2}:
            bindings.append(_binding(999, start.year, "Shared Release"))
        payload = {"results": {"bindings": bindings}}
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        return _records(payload, media_type, start.year)


class SaturatedSource:
    def fetch_interval(
        self,
        media_type: MediaType,
        start: datetime,
        end: datetime,
        cache_path: Path,
        *,
        limit: int,
    ) -> list[SourceRecord]:
        del end
        records = [
            SourceRecord(
                qid=index + 1,
                media_type=media_type,
                year=start.year,
                original_titles=(f"Title {index}",),
                english_label=f"Title {index}",
                spanish_label=None,
            )
            for index in range(limit)
        ]
        cache_path.write_text('{"results":{"bindings":[]}}', encoding="utf-8")
        return records


def test_month_intervals_cover_exact_calendar_year() -> None:
    intervals = month_intervals(2025)

    assert len(intervals) == 12
    assert intervals[0] == (
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
    )
    assert intervals[-1] == (
        datetime(2025, 12, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert all(end == intervals[index + 1][0] for index, (_, end) in enumerate(intervals[:-1]))


def test_year_probe_deduplicates_months_and_reuses_completed_cache(tmp_path: Path) -> None:
    source = FakeYearSource()

    first = run_year_probe(source, tmp_path, 2025, limit=5000)
    second = run_year_probe(source, tmp_path, 2025, limit=5000)

    assert source.downloads == 24
    assert first == second
    assert first["month_count"] == 12
    assert first["complete_month_count"] == 12
    assert first["active_partial_month"] is None
    assert first["through"] == "2026-01-01T00:00:00Z"
    assert first["monthly_source_rows"] == 26
    assert first["unique_source_records"] == 25
    assert first["duplicate_source_rows"] == 1
    assert len(first["months"]) == 12  # type: ignore[arg-type]
    assert (tmp_path / "months" / "2025-01" / "movie.json").is_file()
    assert (tmp_path / "movie.json").is_file()
    assert (tmp_path / "series.json").is_file()
    saved = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert saved == first
    assert list(tmp_path.rglob("*.tmp")) == []


def test_partial_year_probe_queries_only_elapsed_months(tmp_path: Path) -> None:
    source = FakeYearSource()

    summary = run_year_probe(
        source,
        tmp_path,
        2026,
        limit=5000,
        through=datetime(2026, 3, 15, tzinfo=UTC),
    )

    assert source.downloads == 6
    assert summary["month_count"] == 3
    assert summary["complete_month_count"] == 2
    assert summary["through"] == "2026-03-15T00:00:00Z"
    assert summary["active_partial_month"] == "2026-03"
    assert [month["month"] for month in summary["months"]] == [
        "2026-01",
        "2026-02",
        "2026-03",
    ]


def test_partial_year_probe_rebuilds_only_selected_cached_months(tmp_path: Path) -> None:
    source = FakeYearSource()
    through = datetime(2026, 3, 15, tzinfo=UTC)

    run_year_probe(source, tmp_path, 2026, limit=5000, through=through)
    first_downloads = source.downloads

    run_year_probe(
        source,
        tmp_path,
        2026,
        limit=5000,
        through=through,
        refresh_months=frozenset({2, 3}),
    )

    assert source.downloads == first_downloads + 4
    assert (tmp_path / "months" / "2026-01" / "movie.json").is_file()
    assert (tmp_path / "months" / "2026-02" / "movie.json").is_file()
    assert (tmp_path / "months" / "2026-03" / "movie.json").is_file()


def test_partial_year_probe_rejects_future_refresh_month(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="refresh month is not elapsed"):
        run_year_probe(
            FakeYearSource(),
            tmp_path,
            2026,
            limit=5000,
            through=datetime(2026, 3, 15, tzinfo=UTC),
            refresh_months=frozenset({4}),
        )


def test_year_probe_rejects_saturated_month(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reached the monthly limit"):
        run_year_probe(SaturatedSource(), tmp_path, 2025, limit=3)
