from __future__ import annotations

from collections.abc import Iterable

from media_catalog_builder.model import CatalogRecord, SourceRecord
from media_catalog_builder.normalize import is_latin_output_candidate, normalize_lookup


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _first_latin(values: Iterable[str | None]) -> str | None:
    for value in values:
        cleaned = _clean(value)
        if cleaned is not None and is_latin_output_candidate(cleaned):
            return cleaned
    return None


def _recognition_names(source: SourceRecord, canonical_title: str) -> tuple[str, ...]:
    first_original = next(
        (cleaned for title in source.original_titles if (cleaned := _clean(title))),
        None,
    )
    candidates = (
        canonical_title,
        first_original,
        _clean(source.english_label),
        _clean(source.spanish_label),
    )

    names: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        normalized = normalize_lookup(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(normalized)
        if len(names) == 4:
            break
    return tuple(names)


def to_catalog_record(source: SourceRecord) -> CatalogRecord | None:
    original_titles = tuple(
        cleaned
        for title in source.original_titles
        if (cleaned := _clean(title)) is not None
    )

    canonical_title = _first_latin(original_titles)
    if canonical_title is None:
        canonical_title = _first_latin((source.english_label, source.spanish_label))
    if canonical_title is None:
        return None

    names = _recognition_names(source, canonical_title)
    if not names:
        return None

    return CatalogRecord(
        qid=source.qid,
        media_type=source.media_type,
        year=source.year,
        canonical_title=canonical_title,
        names=names,
    )
