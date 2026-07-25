from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from media_catalog_builder.model import MediaType, SourceRecord
from media_catalog_builder.multi_year_probe import run_multi_year_probe, year_range


class FakeMultiYearSource:
    def __init__(self) -> None:
        self.calls: list[tuple[MediaType, int, int]] = []

    def fetch_interval(
        self,
        media_type: MediaType,
        start: datetime,
        end: datetime,
        cache_path: Path,
        *,
        limit: int,
    ) -> list[SourceRecord]:
        self.calls.append((media_type, start.year, start.month))
        qid = start.year if media_type is MediaType.MOVIE else 42
        title = f"Movie {start.year}" if media_type is MediaType.MOVIE else "Shared Series"
        binding = {
            "item": {
                "type": "uri",
                "value": f"http://www.wikidata.org/entity/Q{qid}",
            },
            "releaseDate": {
                "type": "literal",
                "value": f"{start.year:04d}-01-01T00:00:00Z",
            },
            "originals": {"type": "literal", "value": title},
            "enLabel": {"type": "literal", "value": title},
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"results": {"bindings": [binding]}}),
            encoding="utf-8",
        )
        return [
            SourceRecord(
                qid=qid,
                media_type=media_type,
                year=start.year,
                original_titles=(title,),
                english_label=title,
                spanish_label=None,
            )
        ][:limit]


def test_year_range_is_inclusive_and_validated() -> None:
    assert year_range(2016, 2025) == tuple(range(2016, 2026))
    with pytest.raises(ValueError, match="start year"):
        year_range(2025, 2016)


def test_multi_year_probe_deduplicates_years_and_reuses_completed_cache(
    tmp_path: Path,
) -> None:
    source = FakeMultiYearSource()

    first = run_multi_year_probe(source, tmp_path, 2024, 2025, limit=5000)
    calls_after_first = len(source.calls)
    second = run_multi_year_probe(source, tmp_path, 2024, 2025, limit=5000)

    assert first == second
    assert first["year_count"] == 2
    assert first["annual_source_rows"] == 4
    assert first["unique_source_records"] == 3
    assert first["duplicate_source_rows"] == 1
    assert [entry["year"] for entry in first["years"]] == [2024, 2025]  # type: ignore[index]
    assert calls_after_first == 48
    assert len(source.calls) == calls_after_first
    assert (tmp_path / "years" / "2024" / "summary.json").is_file()
    assert (tmp_path / "years" / "2025" / "summary.json").is_file()
    assert (tmp_path / "movie.json").is_file()
    assert (tmp_path / "series.json").is_file()
    assert list(tmp_path.rglob("*.tmp")) == []
