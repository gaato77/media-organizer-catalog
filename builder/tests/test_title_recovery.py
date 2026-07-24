from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from media_catalog_builder.model import MediaType, SourceRecord
from media_catalog_builder.names import catalog_skip_reason, to_catalog_record
from media_catalog_builder.probe_release import build_skip_audit
from media_catalog_builder.wikidata import WikidataSource, build_alias_query


class FakeHttp:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post_json(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        self.calls.append((url, data))
        return self.payloads.pop(0)


def _detail_payload() -> dict[str, Any]:
    return {
        "results": {
            "bindings": [
                {
                    "item": {
                        "type": "uri",
                        "value": "http://www.wikidata.org/entity/Q10",
                    },
                    "releaseDate": {
                        "type": "literal",
                        "value": "2025-01-10T00:00:00Z",
                    },
                    "originals": {"type": "literal", "value": "映画"},
                }
            ]
        }
    }


def _alias_payload() -> dict[str, Any]:
    return {
        "results": {
            "bindings": [
                {
                    "item": {
                        "type": "uri",
                        "value": "http://www.wikidata.org/entity/Q10",
                    },
                    "aliases": {
                        "type": "literal",
                        "value": "Romanized Movie\u001fPelícula romanizada",
                    },
                }
            ]
        }
    }


def test_skip_reason_distinguishes_missing_and_non_latin_titles() -> None:
    missing = SourceRecord(1, MediaType.MOVIE, 2025, (), None, None)
    non_latin = SourceRecord(2, MediaType.MOVIE, 2025, ("映画",), None, None)

    assert catalog_skip_reason(missing) == "missing_titles"
    assert catalog_skip_reason(non_latin) == "non_latin_titles_only"


def test_latin_source_alias_is_last_canonical_fallback() -> None:
    source = SourceRecord(
        3,
        MediaType.MOVIE,
        2025,
        ("映画",),
        None,
        None,
        alternate_titles=("Romanized Movie",),
    )

    result = to_catalog_record(source)

    assert result is not None
    assert result.canonical_title == "Romanized Movie"
    assert result.names == ("romanized movie", "映画")


def test_alias_query_is_exact_and_language_limited() -> None:
    query = build_alias_query(("Q42", "Q123"))

    assert "VALUES ?item { wd:Q42 wd:Q123 }" in query
    assert "skos:altLabel" in query
    assert 'LANG(?alias) IN ("en", "es")' in query
    assert "P279*" not in query


def test_fetch_interval_recovers_and_persists_aliases_for_skipped_records(tmp_path: Path) -> None:
    cache_path = tmp_path / "movie.json"
    cache_path.write_text(json.dumps(_detail_payload()), encoding="utf-8")
    http = FakeHttp([_alias_payload()])
    source = WikidataSource(
        "https://query.wikidata.org/sparql",
        http,  # type: ignore[arg-type]
        detail_batch_size=50,
    )

    records = source.fetch_interval(
        MediaType.MOVIE,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        cache_path,
        limit=1000,
    )
    repeated = source.fetch_interval(
        MediaType.MOVIE,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        cache_path,
        limit=1000,
    )

    assert records[0].alternate_titles == ("Romanized Movie", "Película romanizada")
    assert to_catalog_record(records[0]) is not None
    assert repeated == records
    assert len(http.calls) == 1
    assert "skos:altLabel" in http.calls[0][1]["query"]
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    assert saved["results"]["bindings"][0]["aliases"]["value"].startswith("Romanized Movie")


def test_skip_audit_counts_recovered_and_remaining_records() -> None:
    records = [
        SourceRecord(1, MediaType.MOVIE, 2025, (), None, None),
        SourceRecord(2, MediaType.MOVIE, 2025, ("映画",), None, None),
        SourceRecord(
            3,
            MediaType.SERIES,
            2025,
            ("ドラマ",),
            None,
            None,
            alternate_titles=("Romanized Drama",),
        ),
        SourceRecord(4, MediaType.MOVIE, 2025, ("Already Latin",), None, None),
    ]

    report = build_skip_audit(records)

    assert report["baseline_skipped_records"] == 3
    assert report["recovered_records"] == 1
    assert report["remaining_skipped_records"] == 2
    assert report["by_remaining_reason"] == {
        "missing_titles": 1,
        "non_latin_titles_only": 1,
    }
    audited = report["records"]
    assert isinstance(audited, list)
    assert [entry["qid"] for entry in audited] == ["Q1", "Q2", "Q3"]
    assert audited[-1]["status"] == "recovered"
