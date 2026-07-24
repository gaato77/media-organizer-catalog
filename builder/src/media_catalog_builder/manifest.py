from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CATALOG_VERSION = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$")
_SAFE_NAME = re.compile(r"^[^/\\\x00]+$")
_ASSET_FIELDS = frozenset({"name", "download_bytes", "installed_bytes", "sha256"})
_DELTA_FIELDS = _ASSET_FIELDS | {"from_version", "to_version"}
_MANIFEST_FIELDS = frozenset(
    {
        "manifest_schema",
        "catalog_schema",
        "catalog_version",
        "published_at",
        "minimum_app_version",
        "full",
        "deltas",
    }
)
type JsonObject = dict[str, Any]


def _validate_version(value: str, label: str) -> None:
    if _CATALOG_VERSION.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")
    try:
        datetime.strptime(value, "%Y.%m.%d")
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc


def _validated_fields(payload: JsonObject, expected: frozenset[str], label: str) -> None:
    actual = frozenset(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(f"invalid {label} fields: missing={missing}, unknown={unknown}")


@dataclass(frozen=True, slots=True)
class Asset:
    name: str
    download_bytes: int
    installed_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if (
            not self.name
            or self.name in {".", ".."}
            or _SAFE_NAME.fullmatch(self.name) is None
            or Path(self.name).name != self.name
        ):
            raise ValueError("asset name must be a safe file name")
        if self.download_bytes <= 0:
            raise ValueError("asset download_bytes must be positive")
        if self.installed_bytes <= 0:
            raise ValueError("asset installed_bytes must be positive")
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("asset SHA-256 must contain 64 lowercase hexadecimal characters")

    def to_dict(self) -> JsonObject:
        return {
            "name": self.name,
            "download_bytes": self.download_bytes,
            "installed_bytes": self.installed_bytes,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, payload: JsonObject) -> Asset:
        _validated_fields(payload, _ASSET_FIELDS, "asset")
        return cls(
            name=str(payload["name"]),
            download_bytes=int(payload["download_bytes"]),
            installed_bytes=int(payload["installed_bytes"]),
            sha256=str(payload["sha256"]),
        )


@dataclass(frozen=True, slots=True)
class DeltaPath:
    from_version: str
    to_version: str
    name: str
    download_bytes: int
    installed_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _validate_version(self.from_version, "delta from_version")
        _validate_version(self.to_version, "delta to_version")
        if self.from_version == self.to_version:
            raise ValueError("delta versions must differ")
        Asset(
            name=self.name,
            download_bytes=self.download_bytes,
            installed_bytes=self.installed_bytes,
            sha256=self.sha256,
        )

    def to_dict(self) -> JsonObject:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "name": self.name,
            "download_bytes": self.download_bytes,
            "installed_bytes": self.installed_bytes,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, payload: JsonObject) -> DeltaPath:
        _validated_fields(payload, _DELTA_FIELDS, "delta")
        return cls(
            from_version=str(payload["from_version"]),
            to_version=str(payload["to_version"]),
            name=str(payload["name"]),
            download_bytes=int(payload["download_bytes"]),
            installed_bytes=int(payload["installed_bytes"]),
            sha256=str(payload["sha256"]),
        )


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    manifest_schema: int
    catalog_schema: int
    catalog_version: str
    published_at: str
    minimum_app_version: str
    full: Asset
    deltas: tuple[DeltaPath, ...]

    def __post_init__(self) -> None:
        if self.manifest_schema != 1:
            raise ValueError("manifest schema must be 1")
        if self.catalog_schema != 1:
            raise ValueError("catalog schema must be 1")
        _validate_version(self.catalog_version, "catalog_version")
        try:
            parsed = datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid published_at") from exc
        if not self.published_at.endswith("Z") or parsed.utcoffset() is None:
            raise ValueError("published_at must be a UTC timestamp ending in Z")
        if not self.minimum_app_version.strip():
            raise ValueError("minimum_app_version is required")
        if len(self.deltas) > 8:
            raise ValueError("manifest may contain at most 8 deltas")
        edges = [(delta.from_version, delta.to_version) for delta in self.deltas]
        if len(edges) != len(set(edges)):
            raise ValueError("manifest contains duplicate delta paths")
        names = [self.full.name, *(delta.name for delta in self.deltas)]
        if len(names) != len(set(names)):
            raise ValueError("manifest asset names must be unique")

    def to_dict(self) -> JsonObject:
        return {
            "manifest_schema": self.manifest_schema,
            "catalog_schema": self.catalog_schema,
            "catalog_version": self.catalog_version,
            "published_at": self.published_at,
            "minimum_app_version": self.minimum_app_version,
            "full": self.full.to_dict(),
            "deltas": [delta.to_dict() for delta in self.deltas],
        }

    @classmethod
    def from_dict(cls, payload: JsonObject) -> ReleaseManifest:
        _validated_fields(payload, _MANIFEST_FIELDS, "manifest")
        full_payload = payload["full"]
        delta_payloads = payload["deltas"]
        if not isinstance(full_payload, dict) or not isinstance(delta_payloads, list):
            raise ValueError("invalid manifest fields")
        return cls(
            manifest_schema=int(payload["manifest_schema"]),
            catalog_schema=int(payload["catalog_schema"]),
            catalog_version=str(payload["catalog_version"]),
            published_at=str(payload["published_at"]),
            minimum_app_version=str(payload["minimum_app_version"]),
            full=Asset.from_dict(cast(JsonObject, full_payload)),
            deltas=tuple(
                DeltaPath.from_dict(cast(JsonObject, item))
                for item in delta_payloads
                if isinstance(item, dict)
            ),
        )


def write_manifest(path: Path, manifest: ReleaseManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        temporary.write_text(
            json.dumps(
                manifest.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        with temporary.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_manifest(path: Path) -> ReleaseManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid manifest JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid manifest fields")
    return ReleaseManifest.from_dict(cast(JsonObject, payload))


def choose_update_path(
    manifest: ReleaseManifest,
    installed_version: str,
) -> tuple[Asset | DeltaPath, ...]:
    _validate_version(installed_version, "installed_version")
    if installed_version == manifest.catalog_version:
        return ()

    outgoing: dict[str, list[DeltaPath]] = {}
    for delta in manifest.deltas:
        outgoing.setdefault(delta.from_version, []).append(delta)
    for edges in outgoing.values():
        edges.sort(key=lambda edge: (edge.to_version, edge.download_bytes, edge.name))

    candidates: list[tuple[DeltaPath, ...]] = []

    def visit(
        version: str,
        path: tuple[DeltaPath, ...],
        visited: frozenset[str],
    ) -> None:
        if version == manifest.catalog_version:
            candidates.append(path)
            return
        if len(path) >= 8:
            return
        for delta in outgoing.get(version, []):
            if delta.to_version in visited:
                continue
            visit(delta.to_version, (*path, delta), visited | {delta.to_version})

    visit(installed_version, (), frozenset({installed_version}))
    if not candidates:
        return (manifest.full,)

    selected = min(
        candidates,
        key=lambda path: (
            sum(item.download_bytes for item in path),
            len(path),
            tuple(item.name for item in path),
        ),
    )
    total_delta_bytes = sum(item.download_bytes for item in selected)
    if total_delta_bytes * 5 >= manifest.full.download_bytes * 4:
        return (manifest.full,)
    return selected
