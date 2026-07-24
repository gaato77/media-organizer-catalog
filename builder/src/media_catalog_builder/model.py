from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class MediaType(IntEnum):
    MOVIE = 1
    SERIES = 2


@dataclass(frozen=True, slots=True)
class SourceRecord:
    qid: int
    media_type: MediaType
    year: int
    original_titles: tuple[str, ...]
    english_label: str | None
    spanish_label: str | None
    modified_at: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    qid: int
    media_type: MediaType
    year: int
    canonical_title: str
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.qid <= 0:
            raise ValueError("qid must be positive")
        if not 1800 <= self.year <= 2200:
            raise ValueError("year outside supported range")
        if not self.canonical_title.strip():
            raise ValueError("canonical title is required")
        if not 1 <= len(self.names) <= 4:
            raise ValueError("record must contain at least 1 and at most 4 names")
        if len(set(self.names)) != len(self.names):
            raise ValueError("record names must be unique")
