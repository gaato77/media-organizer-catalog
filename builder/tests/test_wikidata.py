from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from media_catalog_builder.model import MediaType
from media_catalog_builder.wikidata import WikidataSource, build_interval_query


class FakeHttp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        self.calls.append((url, params))
        return self.payload


def test_interval_query_is_narrow_and_requires_relevance_fields():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 2, 1, tzinfo=timezone.utc)

    query = build_interval_query(MediaType.MOVIE, start, end, limit=250)

    assert "wd:Q11424" in query
    assert "wdt:P345" in query
    assert "wdt:P577" in query
    assert '2026-01-01T00:00:00Z' in query
    assert '2026-02-01T00:00:00Z' in query
    assert "GROUP_CONCAT" in query
    assert "LIMIT 250" in query


def test_series_query_uses_approved_roots():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 2, 1, tzinfo=timezone.utc)

    query = build_interval_query(MediaType.SERIES, start, end, limit=10)

    assert "wd:Q5398426" in query
    assert "wd:Q1259759" in query


def test_fetch_interval_writes_atomic_cache_and_reuses_it(tmp_path: Path):
    payload = {
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
    http = FakeHttp(payload)
    source = WikidataSource(
        "https://query.wikidata.org/sparql", http  # type: ignore[arg-type]
    )
    cache = tmp_path / "probe.json"
    start = datetime(2001, 1, 1, tzinfo=timezone.utc)
    end = datetime(2001, 2, 1, tzinfo=timezone.utc)

    first = source.fetch_interval(MediaType.MOVIE, start, end, cache, limit=25)
    second = source.fetch_interval(MediaType.MOVIE, start, end, cache, limit=25)

    assert len(first) == 1
    assert second == first
    assert len(http.calls) == 1
    assert json.loads(cache.read_text(encoding="utf-8")) == payload
    assert list(tmp_path.glob("*.tmp")) == []
