from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, cast

from media_catalog_builder.classify import Binding, binding_to_source
from media_catalog_builder.model import MediaType, SourceRecord

_ROOTS: dict[MediaType, tuple[str, ...]] = {
    MediaType.MOVIE: ("Q11424",),
    MediaType.SERIES: ("Q5398426", "Q1259759"),
}


class JsonHttpClient(Protocol):
    def get_json(self, url: str, params: Mapping[str, str]) -> dict[str, Any]: ...


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("interval timestamps must be timezone-aware")
    utc_value = value.astimezone(timezone.utc).replace(microsecond=0)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _prefixes() -> str:
    return "\n".join(
        (
            "PREFIX wd: <http://www.wikidata.org/entity/>",
            "PREFIX wdt: <http://www.wikidata.org/prop/direct/>",
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>",
            "PREFIX schema: <http://schema.org/>",
            "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>",
        )
    )


def build_interval_query(
    media_type: MediaType,
    start: datetime,
    end: datetime,
    *,
    limit: int,
) -> str:
    start_text = _utc_timestamp(start)
    end_text = _utc_timestamp(end)
    if end <= start:
        raise ValueError("end must be after start")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")

    roots = " ".join(f"wd:{qid}" for qid in _ROOTS[media_type])
    lines = (
        _prefixes(),
        "SELECT ?item ?releaseDate",
        '  (GROUP_CONCAT(DISTINCT STR(?originalValue); separator="\\u001F") AS ?originals)',
        "  (SAMPLE(?enValue) AS ?enLabel)",
        "  (SAMPLE(?esValue) AS ?esLabel)",
        "  (MAX(?modifiedValue) AS ?modified)",
        "WHERE {",
        "  {",
        "    SELECT ?item (MIN(?releaseDateValue) AS ?releaseDate)",
        "    WHERE {",
        f"      VALUES ?root {{ {roots} }}",
        "      ?item wdt:P577 ?releaseDateValue ;",
        "            wdt:P345 ?imdbId ;",
        "            wdt:P31/wdt:P279* ?root .",
        "      FILTER(",
        f'        ?releaseDateValue >= "{start_text}"^^xsd:dateTime &&',
        f'        ?releaseDateValue < "{end_text}"^^xsd:dateTime',
        "      )",
        "    }",
        "    GROUP BY ?item",
        "    ORDER BY ?item",
        f"    LIMIT {limit}",
        "  }",
        "  OPTIONAL { ?item wdt:P1476 ?originalValue . }",
        '  OPTIONAL { ?item rdfs:label ?enValue . FILTER(LANG(?enValue) = "en") }',
        '  OPTIONAL { ?item rdfs:label ?esValue . FILTER(LANG(?esValue) = "es") }',
        "  OPTIONAL { ?item schema:dateModified ?modifiedValue . }",
        "}",
        "GROUP BY ?item ?releaseDate",
        "ORDER BY ?item",
    )
    return "\n".join(lines) + "\n"


def _read_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Wikidata cache must contain a JSON object")
    return cast(dict[str, Any], payload)


def _write_payload_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def _extract_bindings(payload: Mapping[str, Any]) -> list[Binding]:
    results = payload.get("results")
    if not isinstance(results, Mapping):
        raise ValueError("Wikidata response is missing results")
    raw_bindings = results.get("bindings")
    if not isinstance(raw_bindings, list):
        raise ValueError("Wikidata response is missing bindings")

    bindings: list[Binding] = []
    for raw_binding in raw_bindings:
        if not isinstance(raw_binding, Mapping):
            raise ValueError("Wikidata binding must be an object")
        converted: dict[str, Mapping[str, str]] = {}
        for key, raw_value in raw_binding.items():
            if not isinstance(key, str) or not isinstance(raw_value, Mapping):
                raise ValueError("Wikidata binding entry is invalid")
            converted[key] = {
                str(value_key): str(value) for value_key, value in raw_value.items()
            }
        bindings.append(converted)
    return bindings


class WikidataSource:
    def __init__(self, endpoint: str, http: JsonHttpClient) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("Wikidata endpoint must use HTTPS")
        self._endpoint = endpoint
        self._http = http

    def fetch_interval(
        self,
        media_type: MediaType,
        start: datetime,
        end: datetime,
        cache_path: Path,
        *,
        limit: int,
    ) -> list[SourceRecord]:
        if cache_path.exists():
            payload = _read_payload(cache_path)
        else:
            query = build_interval_query(media_type, start, end, limit=limit)
            payload = self._http.get_json(
                self._endpoint,
                {"query": query, "format": "json"},
            )
            _write_payload_atomic(cache_path, payload)

        records: list[SourceRecord] = []
        for binding in _extract_bindings(payload):
            record = binding_to_source(binding, media_type)
            if record is not None:
                records.append(record)
        return records
