from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from media_catalog_builder.model import MediaType
from media_catalog_builder.wikidata import (
    WikidataSource,
    build_class_query,
    build_interval_query,
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


def _item_payload() -> dict[str, Any]:
    return {
        "results": {
            "bindings": [
                {
                    "item": {
                        "type": "uri",
                        "value": "http://www.wikidata.org/entity/Q42",
                    },
                    "releaseDate": {
                        "type": "literal",
                        "value": "2001-01-01T00:00:00Z",
                    },
                    "originals": {"type": "literal", "value": "Example"},
                    "enLabel": {"type": "literal", "value": "Example"},
                }
            ]
        }
    }


def test_class_query_isolated_from_item_lookup():
    query = build_class_query(MediaType.SERIES, limit=1000)

    assert "wd:Q5398426" in query
    assert "wd:Q1259759" in query
    assert "?class wdt:P279* ?root" in query
    assert "?item" not in query
    assert "LIMIT 1000" in query


def test_interval_query_uses_exact_cached_classes_and_relevance_fields():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 2, 1, tzinfo=UTC)

    query = build_interval_query(
        ("Q11424", "Q24869"),
        start,
        end,
        limit=250,
    )

    assert "VALUES ?class { wd:Q11424 wd:Q24869 }" in query
    assert "wdt:P31 ?class" in query
    assert "wdt:P31/wdt:P279*" not in query
    assert "wdt:P345" in query
    assert "wdt:P577" in query
    assert '2026-01-01T00:00:00Z' in query
    assert '2026-02-01T00:00:00Z' in query
    assert "GROUP_CONCAT" in query
    assert "LIMIT 250" in query


def test_fetch_interval_caches_classes_and_items(tmp_path: Path):
    class_payload = _class_payload("Q11424", "Q24869")
    item_payload = _item_payload()
    http = FakeHttp([class_payload, item_payload])
    source = WikidataSource(
        "https://query.wikidata.org/sparql",
        http,  # type: ignore[arg-type]
    )
    cache = tmp_path / "movie-2001-01.json"
    start = datetime(2001, 1, 1, tzinfo=UTC)
    end = datetime(2001, 2, 1, tzinfo=UTC)

    first = source.fetch_interval(MediaType.MOVIE, start, end, cache, limit=25)
    second = source.fetch_interval(MediaType.MOVIE, start, end, cache, limit=25)

    assert len(first) == 1
    assert second == first
    assert len(http.calls) == 2
    assert all(call[0] == "POST" for call in http.calls)
    assert "?class wdt:P279* ?root" in http.calls[0][2]["query"]
    assert "VALUES ?class { wd:Q11424 wd:Q24869 }" in http.calls[1][2]["query"]
    class_cache = tmp_path / "movie-classes.json"
    assert json.loads(class_cache.read_text(encoding="utf-8")) == class_payload
    assert json.loads(cache.read_text(encoding="utf-8")) == item_payload
    assert list(tmp_path.glob("*.tmp")) == []


def test_fetch_classes_reuses_completed_cache(tmp_path: Path):
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


def test_fetch_classes_rejects_saturated_limit(tmp_path: Path):
    qids = tuple(f"Q{number}" for number in range(1, 1001))
    source = WikidataSource(
        "https://query.wikidata.org/sparql",
        FakeHttp([_class_payload(*qids)]),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="class query reached its limit"):
        source.fetch_classes(MediaType.MOVIE, tmp_path / "movie-classes.json")
