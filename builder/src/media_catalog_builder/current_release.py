from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

_CATALOG_VERSION = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = frozenset(
    {
        "year",
        "version",
        "published_at",
        "release_tag",
        "manifest_asset",
        "full_sha256",
    }
)
type JsonObject = dict[str, Any]


def _validate_version(value: str) -> None:
    if _CATALOG_VERSION.fullmatch(value) is None:
        raise ValueError("invalid catalog version")
    try:
        datetime.strptime(value, "%Y.%m.%d")
    except ValueError as exc:
        raise ValueError("invalid catalog version") from exc


def _validate_published_at(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid publication timestamp") from exc
    if not value.endswith("Z") or parsed.utcoffset() is None:
        raise ValueError("publication timestamp must be UTC and end in Z")


def _validate_asset_name(value: str) -> None:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
        or Path(value).name != value
    ):
        raise ValueError("manifest asset must be a safe file name")


@dataclass(frozen=True, slots=True)
class LatestCatalog:
    year: int
    version: str
    published_at: str
    release_tag: str
    manifest_asset: str
    full_sha256: str

    def __post_init__(self) -> None:
        if isinstance(self.year, bool) or not 1 <= self.year <= 9999:
            raise ValueError("catalog year must be between 1 and 9999")
        _validate_version(self.version)
        _validate_published_at(self.published_at)
        if (
            not self.release_tag
            or self.release_tag != self.release_tag.strip()
            or "\x00" in self.release_tag
        ):
            raise ValueError("release tag is invalid")
        _validate_asset_name(self.manifest_asset)
        if _SHA256.fullmatch(self.full_sha256) is None:
            raise ValueError(
                "full catalog SHA-256 must contain 64 lowercase hexadecimal characters"
            )

    def to_dict(self) -> JsonObject:
        return {
            "year": self.year,
            "version": self.version,
            "published_at": self.published_at,
            "release_tag": self.release_tag,
            "manifest_asset": self.manifest_asset,
            "full_sha256": self.full_sha256,
        }

    @classmethod
    def from_dict(cls, payload: JsonObject) -> LatestCatalog:
        if frozenset(payload) != _FIELDS:
            raise ValueError("invalid latest catalog fields")
        return cls(
            year=int(payload["year"]),
            version=str(payload["version"]),
            published_at=str(payload["published_at"]),
            release_tag=str(payload["release_tag"]),
            manifest_asset=str(payload["manifest_asset"]),
            full_sha256=str(payload["full_sha256"]),
        )


def load_latest(path: Path) -> LatestCatalog:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid latest catalog JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid latest catalog fields")
    return LatestCatalog.from_dict(cast(JsonObject, payload))


def write_latest_atomic(path: Path, latest: LatestCatalog) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        payload = json.dumps(
            latest.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        temporary.write_text(payload + "\n", encoding="utf-8")
        with temporary.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
