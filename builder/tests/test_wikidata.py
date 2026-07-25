from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from media_catalog_builder.model import MediaType
from media_catalog_builder.wikidata import (
    WikidataSource,
    build_candidate_query,
    build_class_query,
    build_detail_query,
)


class FakeHttp:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def post_json(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        self.calls.append(("POST", url, data))
        return self.payloads.pop(0)


def _class_payload(*qids: str) -> dict[str, Any]:
    return {
        "results": {
            "bindings": [
                {
                    "class": {
                        "type": "uri",
                        "value": f"http://www.wikidata.org/entity/{qid}",
                    }
                }
                for qid in qids
            ]
        }
    }


def _candidate_payload(*rows: tuple[str, str]) -> dict[str, Any]:
    return {
        "results": {
            "bindings": [
                {
                    "item": {
                        "type": "uri",
                        "value": f"http://www.wikidata.org/entity/{qid}",
                    },
                    "classes": {
                        "type": "literal",
                        "value": "\u001f".join(classes.split(",")),
                    },
                }
                for qid, classes in rows
            ]
        }
    }


def _detail_payload(*rows: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "results": {
            "bindings": [
                {
                    "item": {
                        "type": "uri",
                        "value": f"http://www.wikidata.org/entity/{qid}",
                    },
                    "releaseDate": {
                        "type": "literal",
                        "value": release_date,
                    },
                    "originals": {"type": "literal", "value": title},
                    "enLabel": {"type": "literal", "value": title},
                }
                for qid, release_date, title in rows
            ]
        }
    }


def test_class_query_isolated_from_item_lookup() -> None:
    query = build_class_query(MediaType.SERIES, limit=1000)

    assert "wd:Q5398426" in query
    assert "wd:Q1259759" in query
    assert "?class wdt:P279* ?root" in query
    assert "?item" not in query
    assert "LIMIT 1000" in query


def test_candidate_query_is_date_first_and_has_no_media_class_values() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 2, 1, tzinfo=UTC)

    query = build_candidate_query(start, end, page_size=1000)

    assert "wdt:P345" in query
    assert "wdt:P577" in query
    assert "wdt:P31 ?class" in query
    assert "GROUP_CONCAT" in query
    assert "VALUES ?class" not in query
    assert "P279*" not in query
    assert "2026-01-01T00:00:00Z" in query
    assert "2026-02-01T00:00:00Z" in query
    assert "LIMIT 1000" in query


def test_candidate_query_uses_cursor_for_resumable_pages() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 2, 1, tzinfo=UTC)

    query = build_candidate_query(start, end, page_size=500, after_qid="Q42")

    assert 'FILTER(STR(?item) > "http://www.wikidata.org/entity/Q42")' in query
    assert "LIMIT 500" in query


def test_detail_query_uses_only_exact_item_ids() -> None:
    query = build_detail_query(("Q42", "Q123"))

    assert "VALUES ?item { wd:Q42 wd:Q123 }" in query
    assert "MIN(?releaseDateValue)" in query
    assert "GROUP_CONCAT" in query
    assert "P279*" not in query
    assert "xsd:dateTime" not in query
    assert "VALUES ?class" not in query


def test_fetch_interval_uses_shared_candidate_pages_and_local_classification(
    tmp_path: Path,
) -> None:
    movie_classes = _class_payload("Q11424", "Q24869")
    series_classes = _class_payload("Q5398426", "Q1259759")
    candidates = _candidate_payload(
        ("Q10", "http://www.wikidata.org/entity/Q11424"),
        ("Q20", "http://www.wikidata.org/entity/Q5398426"),
        (
            "Q30",
            "http://www.wikidata.org/entity/Q11424,http://www.wikidata.org/entity/Q5398426",
        ),
    )
    empty_candidates = _candidate_payload()
    movie_details = _detail_payload(("Q10", "2001-01-01T00:00:00Z", "Movie"))
    series_details = _detail_payload(
        ("Q20", "2002-01-01T00:00:00Z", "Series"),
        ("Q30", "2003-01-01T00:00:00Z", "Overlap"),
    )
    http = FakeHttp(
        [
            movie_classes,
            series_classes,
            candidates,
            empty_candidates,
            movie_details,
            series_details,
        ]
    )
    source = WikidataSource(
        "https://query.wikidata.org/sparql",
        http,  # type: ignore[arg-type]
        candidate_page_size=3,
        detail_batch_size=2,
    )
    start = datetime(2001, 1, 1, tzinfo=UTC)
    end = datetime(2001, 2, 1, tzinfo=UTC)

    movies = source.fetch_interval(
        MediaType.MOVIE,
        start,
        end,
        tmp_path / "movie.json",
        limit=25,
    )
    series = source.fetch_interval(
        MediaType.SERIES,
        start,
        end,
        tmp_path / "series.json",
        limit=25,
    )

    assert [record.qid for record in movies] == [10]
    assert [record.qid for record in series] == [20, 30]
    assert len(http.calls) == 6
    candidate_calls = [
        call for call in http.calls if "GROUP_CONCAT(DISTINCT STR(?class)" in call[2]["query"]
    ]
    assert len(candidate_calls) == 2
    assert "Q30" in candidate_calls[1][2]["query"]
    assert "VALUES ?item { wd:Q10 }" in http.calls[4][2]["query"]
    assert "VALUES ?item { wd:Q20 wd:Q30 }" in http.calls[5][2]["query"]
    assert (tmp_path / "source-candidates-20010101T000000Z-20010201T000000Z").is_dir()
    assert list(tmp_path.rglob("*.tmp")) == []


def test_fetch_interval_reuses_completed_detail_batches_after_interruption(
    tmp_path: Path,
) -> None:
    movie_classes = _class_payload("Q11424")
    series_classes = _class_payload("Q5398426")
    candidates = _candidate_payload(
        ("Q1", "http://www.wikidata.org/entity/Q11424"),
        ("Q2", "http://www.wikidata.org/entity/Q11424"),
        ("Q3", "http://www.wikidata.org/entity/Q11424"),
    )
    first_batch = _detail_payload(
        ("Q1", "2001-01-01T00:00:00Z", "One"),
        ("Q2", "2001-01-01T00:00:00Z", "Two"),
    )
    second_batch = _detail_payload(("Q3", "2001-01-01T00:00:00Z", "Three"))
    page_dir = tmp_path / "source-candidates-20010101T000000Z-20010201T000000Z"
    page_dir.mkdir()
    (page_dir / "page-000001.json").write_text(json.dumps(candidates), encoding="utf-8")
    (page_dir / "page-000002.json").write_text(json.dumps(_candidate_payload()), encoding="utf-8")
    (tmp_path / "movie-classes.json").write_text(json.dumps(movie_classes), encoding="utf-8")
    (tmp_path / "series-classes.json").write_text(json.dumps(series_classes), encoding="utf-8")
    batch_dir = tmp_path / "movie-details"
    batch_dir.mkdir()
    (batch_dir / "batch-000001.json").write_text(json.dumps(first_batch), encoding="utf-8")
    http = FakeHttp([second_batch])
    source = WikidataSource(
        "https://query.wikidata.org/sparql",
        http,  # type: ignore[arg-type]
        candidate_page_size=3,
        detail_batch_size=2,
    )

    records = source.fetch_interval(
        MediaType.MOVIE,
        datetime(2001, 1, 1, tzinfo=UTC),
        datetime(2001, 2, 1, tzinfo=UTC),
        tmp_path / "movie.json",
        limit=25,
    )

    assert [record.qid for record in records] == [1, 2, 3]
    assert len(http.calls) == 1
    assert "VALUES ?item { wd:Q3 }" in http.calls[0][2]["query"]
    assert (batch_dir / "batch-000001.json").exists()
    assert (batch_dir / "batch-000002.json").exists()
    assert (tmp_path / "movie.json").exists()


def test_fetch_interval_accepts_annual_safety_limit(tmp_path: Path) -> None:
    cache = tmp_path / "movie.json"
    cache.write_text(json.dumps(_detail_payload()), encoding="utf-8")
    source = WikidataSource(
        "https://query.wikidata.org/sparql",
        FakeHttp([]),  # type: ignore[arg-type]
    )

    assert (
        source.fetch_interval(
            MediaType.MOVIE,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 2, 1, tzinfo=UTC),
            cache,
            limit=5000,
        )
        == []
    )
    with pytest.raises(ValueError, match="between 1 and 5000"):
        source.fetch_interval(
            MediaType.MOVIE,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 2, 1, tzinfo=UTC),
            cache,
            limit=5001,
        )


def test_fetch_classes_reuses_completed_cache(tmp_path: Path) -> None:
    class_payload = _class_payload("Q5398426", "Q1259759")
    http = FakeHttp([class_payload])
    source = WikidataSource(
        "https://query.wikidata.org/sparql",
        http,  # type: ignore[arg-type]
    )
    cache = tmp_path / "series-classes.json"

    first = source.fetch_classes(MediaType.SERIES, cache)
    second = source.fetch_classes(MediaType.SERIES, cache)

    assert first == ("Q1259759", "Q5398426")
    assert second == first
    assert len(http.calls) == 1


def test_fetch_classes_rejects_saturated_limit(tmp_path: Path) -> None:
    qids = tuple(f"Q{number}" for number in range(1, 1001))
    source = WikidataSource(
        "https://query.wikidata.org/sparql",
        FakeHttp([_class_payload(*qids)]),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="class query reached its limit"):
        source.fetch_classes(MediaType.MOVIE, tmp_path / "movie-classes.json")
