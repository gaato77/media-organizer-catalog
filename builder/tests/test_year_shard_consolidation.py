from __future__ import annotations

import json
from pathlib import Path

import pytest

from media_catalog_builder.multi_year_probe import consolidate_year_shards


def _binding(qid: int, year: int, title: str) -> dict[str, dict[str, str]]:
    return {
        "item": {"type": "uri", "value": f"http://www.wikidata.org/entity/Q{qid}"},
        "releaseDate": {"type": "literal", "value": f"{year}-01-01T00:00:00Z"},
        "originals": {"type": "literal", "value": title},
        "enLabel": {"type": "literal", "value": title},
    }


def _write_year(root: Path, year: int) -> None:
    target = root / "years" / str(year)
    target.mkdir(parents=True)
    movie = {"results": {"bindings": [_binding(year, year, f"Movie {year}")]}}
    series = {"results": {"bindings": [_binding(42, year, "Shared Series")]}}
    (target / "movie.json").write_text(json.dumps(movie), encoding="utf-8")
    (target / "series.json").write_text(json.dumps(series), encoding="utf-8")
    cache_bytes = sum((target / name).stat().st_size for name in ("movie.json", "series.json"))
    summary = {
        "probe_schema": 1,
        "year": year,
        "limit_per_type_per_month": 50000,
        "monthly_source_rows": 2,
        "unique_source_records": 2,
        "duplicate_source_rows": 0,
        "consolidated_cache_bytes": cache_bytes,
        "query_seconds": 0.0,
    }
    (target / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def test_consolidation_deduplicates_completed_year_shards(tmp_path: Path) -> None:
    _write_year(tmp_path, 2024)
    _write_year(tmp_path, 2025)

    summary = consolidate_year_shards(tmp_path, 2024, 2025)

    assert summary["year_count"] == 2
    assert summary["annual_source_rows"] == 4
    assert summary["unique_source_records"] == 3
    assert summary["duplicate_source_rows"] == 1
    assert summary["limit_per_type_per_month"] == 50000
    assert (tmp_path / "movie.json").is_file()
    assert (tmp_path / "series.json").is_file()


def test_consolidation_rejects_a_missing_year_shard(tmp_path: Path) -> None:
    _write_year(tmp_path, 2024)

    with pytest.raises(ValueError, match="missing completed annual shard: 2025"):
        consolidate_year_shards(tmp_path, 2024, 2025)
