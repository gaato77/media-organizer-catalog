from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from media_catalog_builder.classify import Binding, binding_to_source, parse_qid
from media_catalog_builder.model import MediaType, SourceRecord

_ROOTS: dict[MediaType, tuple[str, ...]] = {
    MediaType.MOVIE: ("Q11424",),
    MediaType.SERIES: ("Q5398426", "Q1259759"),
}
_CLASS_QUERY_LIMIT = 1000
_DEFAULT_CANDIDATE_PAGE_SIZE = 1000
_DEFAULT_DETAIL_BATCH_SIZE = 100
_QID = re.compile(r"^Q[1-9][0-9]*$")
_ITEM_URI = "http://www.wikidata.org/entity/"
_SEPARATOR = "\u001f"


class JsonHttpClient(Protocol):
    def post_json(self, url: str, data: Mapping[str, str]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _Candidate:
    qid: str
    class_qids: frozenset[str]


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("interval timestamps must be timezone-aware")
    utc_value = value.astimezone(UTC).replace(microsecond=0)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _validated_qids(values: Sequence[str]) -> tuple[str, ...]:
    qids = tuple(sorted(set(values), key=lambda value: int(value[1:])))
    if not qids:
        raise ValueError("at least one Wikidata QID is required")
    if any(_QID.fullmatch(qid) is None for qid in qids):
        raise ValueError("invalid Wikidata QID")
    return qids


def build_class_query(media_type: MediaType, *, limit: int = _CLASS_QUERY_LIMIT) -> str:
    if not 1 <= limit <= _CLASS_QUERY_LIMIT:
        raise ValueError("class limit must be between 1 and 1000")
    roots = " ".join(f"wd:{qid}" for qid in _ROOTS[media_type])
    return f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT DISTINCT ?class WHERE {{
  VALUES ?root {{ {roots} }}
  ?class wdt:P279* ?root .
}}
ORDER BY ?class
LIMIT {limit}
"""


def build_candidate_query(
    start: datetime,
    end: datetime,
    *,
    page_size: int,
    after_qid: str | None = None,
) -> str:
    if end <= start:
        raise ValueError("end must be after start")
    if not 1 <= page_size <= 5000:
        raise ValueError("candidate page size must be between 1 and 5000")
    if after_qid is not None and _QID.fullmatch(after_qid) is None:
        raise ValueError("invalid candidate cursor QID")

    start_text = _utc_timestamp(start)
    end_text = _utc_timestamp(end)
    cursor_filter = ""
    if after_qid is not None:
        cursor_filter = f'  FILTER(STR(?item) > "{_ITEM_URI}{after_qid}")\n'

    return f"""PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT
  ?item
  (GROUP_CONCAT(DISTINCT STR(?class); separator="\\u001F") AS ?classes)
WHERE {{
  ?item wdt:P31 ?class ;
        wdt:P345 ?imdbId ;
        wdt:P577 ?releaseDateValue .
  FILTER(
    ?releaseDateValue >= "{start_text}"^^xsd:dateTime &&
    ?releaseDateValue < "{end_text}"^^xsd:dateTime
  )
{cursor_filter}}}
GROUP BY ?item
ORDER BY STR(?item)
LIMIT {page_size}
"""


def build_detail_query(item_qids: Sequence[str]) -> str:
    items = " ".join(f"wd:{qid}" for qid in _validated_qids(item_qids))
    return f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>

SELECT
  ?item
  (MIN(?releaseDateValue) AS ?releaseDate)
  (GROUP_CONCAT(DISTINCT STR(?originalValue); separator="\\u001F") AS ?originals)
  (SAMPLE(?enValue) AS ?enLabel)
  (SAMPLE(?esValue) AS ?esLabel)
  (MAX(?modifiedValue) AS ?modified)
WHERE {{
  VALUES ?item {{ {items} }}
  ?item wdt:P577 ?releaseDateValue .
  OPTIONAL {{ ?item wdt:P1476 ?originalValue . }}
  OPTIONAL {{ ?item rdfs:label ?enValue . FILTER(LANG(?enValue) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?esValue . FILTER(LANG(?esValue) = "es") }}
  OPTIONAL {{ ?item schema:dateModified ?modifiedValue . }}
}}
GROUP BY ?item
ORDER BY ?item
"""


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


def _extract_class_qids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    bindings = _extract_bindings(payload)
    if len(bindings) >= _CLASS_QUERY_LIMIT:
        raise ValueError("class query reached its limit")

    qids: list[str] = []
    for binding in bindings:
        entry = binding.get("class")
        value = entry.get("value") if entry is not None else None
        qid = parse_qid(value) if value is not None else None
        if qid is not None:
            qids.append(f"Q{qid}")
    return _validated_qids(qids)


def _candidate_from_binding(binding: Binding) -> _Candidate | None:
    item = binding.get("item")
    item_value = item.get("value") if item is not None else None
    numeric_qid = parse_qid(item_value) if item_value is not None else None
    classes = binding.get("classes")
    classes_value = classes.get("value") if classes is not None else None
    if numeric_qid is None or not classes_value:
        return None

    class_qids: set[str] = set()
    for class_uri in classes_value.split(_SEPARATOR):
        numeric_class_qid = parse_qid(class_uri)
        if numeric_class_qid is not None:
            class_qids.add(f"Q{numeric_class_qid}")
    if not class_qids:
        return None
    return _Candidate(f"Q{numeric_qid}", frozenset(class_qids))


def _candidate_media_type(
    candidate: _Candidate,
    movie_classes: frozenset[str],
    series_classes: frozenset[str],
) -> MediaType | None:
    # Series wins overlap to avoid emitting the same work as both movie and series.
    if candidate.class_qids & series_classes:
        return MediaType.SERIES
    if candidate.class_qids & movie_classes:
        return MediaType.MOVIE
    return None


def _interval_cache_key(start: datetime, end: datetime) -> str:
    start_text = _utc_timestamp(start).replace("-", "").replace(":", "")
    end_text = _utc_timestamp(end).replace("-", "").replace(":", "")
    return f"source-candidates-{start_text}-{end_text}"


def _payload_for_bindings(bindings: Iterable[Binding]) -> dict[str, Any]:
    return {"results": {"bindings": list(bindings)}}


def _binding_qids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    qids: list[str] = []
    for binding in _extract_bindings(payload):
        item = binding.get("item")
        value = item.get("value") if item is not None else None
        numeric_qid = parse_qid(value) if value is not None else None
        if numeric_qid is not None:
            qids.append(f"Q{numeric_qid}")
    return tuple(sorted(set(qids), key=lambda value: int(value[1:])))


class WikidataSource:
    def __init__(
        self,
        endpoint: str,
        http: JsonHttpClient,
        *,
        candidate_page_size: int = _DEFAULT_CANDIDATE_PAGE_SIZE,
        detail_batch_size: int = _DEFAULT_DETAIL_BATCH_SIZE,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("Wikidata endpoint must use HTTPS")
        if not 1 <= candidate_page_size <= 5000:
            raise ValueError("candidate page size must be between 1 and 5000")
        if not 1 <= detail_batch_size <= 500:
            raise ValueError("detail batch size must be between 1 and 500")
        self._endpoint = endpoint
        self._http = http
        self._candidate_page_size = candidate_page_size
        self._detail_batch_size = detail_batch_size

    def fetch_classes(self, media_type: MediaType, cache_path: Path) -> tuple[str, ...]:
        if cache_path.exists():
            payload = _read_payload(cache_path)
        else:
            payload = self._http.post_json(
                self._endpoint,
                {
                    "query": build_class_query(media_type),
                    "format": "json",
                },
            )
            _extract_class_qids(payload)
            _write_payload_atomic(cache_path, payload)
        return _extract_class_qids(payload)

    def _fetch_candidates(
        self,
        start: datetime,
        end: datetime,
        cache_root: Path,
    ) -> tuple[_Candidate, ...]:
        page_directory = cache_root / _interval_cache_key(start, end)
        page_directory.mkdir(parents=True, exist_ok=True)
        candidates: dict[str, _Candidate] = {}
        after_qid: str | None = None
        page_number = 1

        while True:
            page_path = page_directory / f"page-{page_number:06d}.json"
            if page_path.exists():
                payload = _read_payload(page_path)
            else:
                payload = self._http.post_json(
                    self._endpoint,
                    {
                        "query": build_candidate_query(
                            start,
                            end,
                            page_size=self._candidate_page_size,
                            after_qid=after_qid,
                        ),
                        "format": "json",
                    },
                )
                _write_payload_atomic(page_path, payload)

            bindings = _extract_bindings(payload)
            page_candidates = tuple(
                candidate
                for binding in bindings
                if (candidate := _candidate_from_binding(binding)) is not None
            )
            for candidate in page_candidates:
                candidates[candidate.qid] = candidate

            if len(bindings) < self._candidate_page_size:
                break
            if not page_candidates:
                raise ValueError("candidate page is full but contains no valid items")
            new_after_qid = page_candidates[-1].qid
            if new_after_qid == after_qid:
                raise ValueError("candidate pagination cursor did not advance")
            after_qid = new_after_qid
            page_number += 1

        return tuple(
            candidates[qid]
            for qid in sorted(candidates, key=lambda value: int(value[1:]))
        )

    def _fetch_details(
        self,
        item_qids: Sequence[str],
        cache_path: Path,
    ) -> dict[str, Any]:
        if cache_path.exists():
            return _read_payload(cache_path)

        validated_qids = _validated_qids(item_qids) if item_qids else ()
        batch_directory = cache_path.parent / f"{cache_path.stem}-details"
        batch_directory.mkdir(parents=True, exist_ok=True)
        all_bindings: list[Binding] = []

        for batch_number, start_index in enumerate(
            range(0, len(validated_qids), self._detail_batch_size),
            start=1,
        ):
            batch_qids = validated_qids[
                start_index : start_index + self._detail_batch_size
            ]
            batch_path = batch_directory / f"batch-{batch_number:06d}.json"
            payload: dict[str, Any]
            if batch_path.exists():
                cached_payload = _read_payload(batch_path)
                if _binding_qids(cached_payload) == batch_qids:
                    payload = cached_payload
                else:
                    payload = self._http.post_json(
                        self._endpoint,
                        {"query": build_detail_query(batch_qids), "format": "json"},
                    )
                    _write_payload_atomic(batch_path, payload)
            else:
                payload = self._http.post_json(
                    self._endpoint,
                    {"query": build_detail_query(batch_qids), "format": "json"},
                )
                _write_payload_atomic(batch_path, payload)
            all_bindings.extend(_extract_bindings(payload))

        final_payload = _payload_for_bindings(all_bindings)
        _write_payload_atomic(cache_path, final_payload)
        return final_payload

    def fetch_interval(
        self,
        media_type: MediaType,
        start: datetime,
        end: datetime,
        cache_path: Path,
        *,
        limit: int,
    ) -> list[SourceRecord]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")

        if cache_path.exists():
            payload = _read_payload(cache_path)
        else:
            movie_classes = frozenset(
                self.fetch_classes(
                    MediaType.MOVIE,
                    cache_path.parent / "movie-classes.json",
                )
            )
            series_classes = frozenset(
                self.fetch_classes(
                    MediaType.SERIES,
                    cache_path.parent / "series-classes.json",
                )
            )
            candidates = self._fetch_candidates(start, end, cache_path.parent)
            selected_qids = tuple(
                candidate.qid
                for candidate in candidates
                if _candidate_media_type(
                    candidate,
                    movie_classes,
                    series_classes,
                )
                is media_type
            )[:limit]
            payload = self._fetch_details(selected_qids, cache_path)

        records: list[SourceRecord] = []
        for binding in _extract_bindings(payload):
            record = binding_to_source(binding, media_type)
            if record is not None:
                records.append(record)
        return sorted(records, key=lambda record: record.qid)
