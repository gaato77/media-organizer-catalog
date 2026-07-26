from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REFERENCE = re.compile(r'^[^<>:"/\\|?*\x00-\x1f]+$')
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
    | {f"{prefix}{suffix}" for prefix in ("COM", "LPT") for suffix in "¹²³"}
)
_COMPONENT_FIELDS = frozenset(
    {
        "id",
        "type",
        "from_year",
        "to_year",
        "version",
        "release_tag",
        "manifest_asset",
        "package_name",
        "package_bytes",
        "package_sha256",
        "installed_name",
        "installed_bytes",
        "installed_sha256",
        "catalog_schema",
        "minimum_app_version",
        "priority",
    }
)
_CHANNEL_FIELDS = frozenset({"schema_version", "channel", "published_at", "components"})
type JsonObject = dict[str, Any]


class ComponentType(StrEnum):
    BASE = "base"
    SUPPLEMENT = "supplement"
    PREVIOUS_YEAR = "previous-year"
    CURRENT_YEAR = "current-year"


def _validate_fields(payload: JsonObject, expected: frozenset[str], label: str) -> None:
    actual = frozenset(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(f"invalid {label} fields: missing={missing}, unknown={unknown}")


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _safe_reference(value: object, label: str) -> str:
    stem = value.split(".", 1)[0].rstrip(" ").upper() if isinstance(value, str) else ""
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or value.endswith((".", " "))
        or _SAFE_REFERENCE.fullmatch(value) is None
        or stem in _WINDOWS_RESERVED_NAMES
    ):
        raise ValueError(f"{label} must be a safe non-empty reference")
    return value


def _utc_timestamp(value: object) -> datetime:
    if isinstance(value, str):
        if not value.endswith("Z"):
            raise ValueError("published_at must be a UTC timestamp ending in Z")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as exc:
            raise ValueError("invalid published_at") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError("invalid published_at")
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("published_at must be a UTC timestamp")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CatalogComponent:
    id: str
    type: ComponentType
    from_year: int
    to_year: int
    version: str
    release_tag: str
    manifest_asset: str
    package_name: str
    package_bytes: int
    package_sha256: str
    installed_name: str
    installed_bytes: int
    installed_sha256: str
    catalog_schema: int
    minimum_app_version: str
    priority: int

    def __post_init__(self) -> None:
        try:
            component_type = ComponentType(self.type)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid component type") from exc
        object.__setattr__(self, "type", component_type)
        _safe_reference(self.id, "component id")
        from_year = _positive_int(self.from_year, "from_year")
        to_year = _positive_int(self.to_year, "to_year")
        if not 1800 <= from_year <= to_year <= 2200:
            raise ValueError("component year range must be within 1800 through 2200")
        _safe_reference(self.version, "component version")
        _safe_reference(self.release_tag, "release tag")
        _safe_reference(self.manifest_asset, "manifest asset")
        _safe_reference(self.package_name, "package name")
        _positive_int(self.package_bytes, "package_bytes")
        if (
            not isinstance(self.package_sha256, str)
            or _SHA256.fullmatch(self.package_sha256) is None
        ):
            raise ValueError("package SHA-256 must contain 64 lowercase hexadecimal characters")
        _safe_reference(self.installed_name, "installed name")
        _positive_int(self.installed_bytes, "installed_bytes")
        if (
            not isinstance(self.installed_sha256, str)
            or _SHA256.fullmatch(self.installed_sha256) is None
        ):
            raise ValueError("installed SHA-256 must contain 64 lowercase hexadecimal characters")
        if type(self.catalog_schema) is not int or self.catalog_schema != 1:
            raise ValueError("catalog schema must be 1")
        if not isinstance(self.minimum_app_version, str) or not self.minimum_app_version.strip():
            raise ValueError("minimum_app_version is required")
        _positive_int(self.priority, "priority")

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "type": self.type.value,
            "from_year": self.from_year,
            "to_year": self.to_year,
            "version": self.version,
            "release_tag": self.release_tag,
            "manifest_asset": self.manifest_asset,
            "package_name": self.package_name,
            "package_bytes": self.package_bytes,
            "package_sha256": self.package_sha256,
            "installed_name": self.installed_name,
            "installed_bytes": self.installed_bytes,
            "installed_sha256": self.installed_sha256,
            "catalog_schema": self.catalog_schema,
            "minimum_app_version": self.minimum_app_version,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, payload: JsonObject) -> CatalogComponent:
        _validate_fields(payload, _COMPONENT_FIELDS, "component")
        return cls(
            id=payload["id"],
            type=payload["type"],
            from_year=payload["from_year"],
            to_year=payload["to_year"],
            version=payload["version"],
            release_tag=payload["release_tag"],
            manifest_asset=payload["manifest_asset"],
            package_name=payload["package_name"],
            package_bytes=payload["package_bytes"],
            package_sha256=payload["package_sha256"],
            installed_name=payload["installed_name"],
            installed_bytes=payload["installed_bytes"],
            installed_sha256=payload["installed_sha256"],
            catalog_schema=payload["catalog_schema"],
            minimum_app_version=payload["minimum_app_version"],
            priority=payload["priority"],
        )


@dataclass(frozen=True, slots=True)
class StableChannel:
    schema_version: int
    channel: str
    published_at: datetime | str
    components: tuple[CatalogComponent, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("stable channel schema version must be 1")
        if self.channel != "stable":
            raise ValueError("channel must be stable")
        object.__setattr__(self, "published_at", _utc_timestamp(self.published_at))
        components = tuple(self.components)
        if any(not isinstance(component, CatalogComponent) for component in components):
            raise ValueError("components must be catalog components")
        ids = [component.id for component in components]
        if len(ids) != len(set(ids)):
            raise ValueError("stable channel contains duplicate component IDs")
        _validate_component_overlaps(components)
        object.__setattr__(self, "components", tuple(sorted(components, key=_component_order)))

    def to_dict(self) -> JsonObject:
        published_at = cast(datetime, self.published_at)
        timestamp_precision = "microseconds" if published_at.microsecond else "seconds"
        return {
            "schema_version": self.schema_version,
            "channel": self.channel,
            "published_at": published_at.isoformat(timespec=timestamp_precision).replace(
                "+00:00", "Z"
            ),
            "components": [component.to_dict() for component in self.components],
        }

    @classmethod
    def from_dict(cls, payload: JsonObject) -> StableChannel:
        _validate_fields(payload, _CHANNEL_FIELDS, "stable channel")
        raw_components = payload["components"]
        if not isinstance(raw_components, list) or any(
            not isinstance(component, dict) for component in raw_components
        ):
            raise ValueError("components must be a list of component objects")
        return cls(
            schema_version=payload["schema_version"],
            channel=payload["channel"],
            published_at=payload["published_at"],
            components=tuple(
                CatalogComponent.from_dict(cast(JsonObject, component))
                for component in raw_components
            ),
        )


def _component_order(component: CatalogComponent) -> tuple[int, int, int, str]:
    return (-component.priority, component.from_year, component.to_year, component.id)


def _validate_component_overlaps(components: tuple[CatalogComponent, ...]) -> None:
    for index, component in enumerate(components):
        for other in components[index + 1 :]:
            if component.priority != other.priority:
                continue
            if component.from_year <= other.to_year and other.from_year <= component.to_year:
                raise ValueError("equal-priority component year ranges may not overlap")


def _write_atomic(path: Path, payload: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            serialized = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if temporary is None:
            raise RuntimeError("temporary file was not created")
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _load_json(path: Path, label: str) -> JsonObject:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label} JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid {label} fields")
    return cast(JsonObject, payload)


def load_component(path: Path) -> CatalogComponent:
    return CatalogComponent.from_dict(_load_json(path, "component"))


def write_component_atomic(path: Path, component: CatalogComponent) -> None:
    _write_atomic(path, component.to_dict())


def load_stable_channel(path: Path) -> StableChannel:
    return StableChannel.from_dict(_load_json(path, "stable channel"))


def write_stable_channel_atomic(path: Path, channel: StableChannel) -> None:
    _write_atomic(path, channel.to_dict())
