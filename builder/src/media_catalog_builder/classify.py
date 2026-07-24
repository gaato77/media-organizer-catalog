from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime

from media_catalog_builder.model import MediaType, SourceRecord

_QID = re.compile(r"^https?://www\.wikidata\.org/entity/Q([1-9][0-9]*)$")
_TITLE_SEPARATOR = "\x1f"

Binding = Mapping[str, Mapping[str, str]]


def parse_qid(value: str) -> int | None:
    match = _QID.fullmatch(value.strip())
    if match is None:
        return None
    return int(match.group(1))


def _binding_value(binding: Binding, key: str) -> str | None:
    entry = binding.get(key)
    if entry is None:
        return None
    value = entry.get("value", "").strip()
    return value or None


def _parse_year(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if not 1800 <= parsed.year <= 2200:
        return None
    return parsed.year


def _parse_titles(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    titles: list[str] = []
    seen: set[str] = set()
    for candidate in value.split(_TITLE_SEPARATOR):
        cleaned = candidate.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            titles.append(cleaned)
    return tuple(titles)


def binding_to_source(binding: Binding, media_type: MediaType) -> SourceRecord | None:
    item = _binding_value(binding, "item")
    qid = parse_qid(item) if item is not None else None
    year = _parse_year(_binding_value(binding, "releaseDate"))
    if qid is None or year is None:
        return None

    return SourceRecord(
        qid=qid,
        media_type=media_type,
        year=year,
        original_titles=_parse_titles(_binding_value(binding, "originals")),
        english_label=_binding_value(binding, "enLabel"),
        spanish_label=_binding_value(binding, "esLabel"),
        modified_at=_binding_value(binding, "modified"),
        alternate_titles=_parse_titles(_binding_value(binding, "aliases")),
    )
