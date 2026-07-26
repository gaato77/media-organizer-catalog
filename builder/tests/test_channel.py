from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from media_catalog_builder.channel import (
    CatalogComponent,
    ComponentType,
    StableChannel,
    load_component,
    load_stable_channel,
    write_component_atomic,
    write_stable_channel_atomic,
)


def _component(
    *,
    component_id: str = "base-1950-2015",
    component_type: ComponentType = ComponentType.BASE,
    from_year: int = 1950,
    to_year: int = 2015,
    priority: int = 100,
) -> CatalogComponent:
    return CatalogComponent(
        id=component_id,
        type=component_type,
        from_year=from_year,
        to_year=to_year,
        version="2026.07.25",
        release_tag="base-1950-2015-2026.07.25",
        manifest_asset="manifest.json",
        package_name="catalog.zip",
        package_bytes=123,
        package_sha256="a" * 64,
        installed_name="catalog.sqlite",
        installed_bytes=456,
        installed_sha256="b" * 64,
        catalog_schema=1,
        minimum_app_version="2.0.0",
        priority=priority,
    )


def test_component_round_trip_uses_exact_contract_fields(tmp_path: Path) -> None:
    component = _component()
    path = tmp_path / "base.json"

    write_component_atomic(path, component)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert list(payload) == sorted(
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
    assert payload["type"] == "base"
    assert load_component(path) == component


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"package_sha256": "A" * 64}, "SHA-256"),
        ({"installed_sha256": "f" * 63}, "SHA-256"),
        ({"package_name": "../catalog.zip"}, "safe"),
        ({"release_tag": "release/tag"}, "safe"),
        ({"from_year": 1799}, "year"),
        ({"from_year": 2020, "to_year": 2019}, "year"),
        ({"package_bytes": True}, "positive"),
        ({"priority": False}, "positive"),
        ({"catalog_schema": 2}, "catalog schema"),
    ],
)
def test_component_rejects_invalid_contract_values(changes: dict[str, object], match: str) -> None:
    values = _component().to_dict()
    values.update(changes)

    with pytest.raises(ValueError, match=match):
        CatalogComponent.from_dict(values)


def test_component_loader_rejects_extra_and_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "component.json"
    payload = _component().to_dict()
    payload["extra"] = "nope"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="fields"):
        load_component(path)

    payload = _component().to_dict()
    del payload["priority"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="fields"):
        load_component(path)


def test_stable_channel_sorts_components_and_serializes_utc_with_z(tmp_path: Path) -> None:
    low = _component(component_id="a", from_year=2016, to_year=2025, priority=100)
    high_later = _component(component_id="z", from_year=2020, to_year=2020, priority=400)
    high_earlier = _component(component_id="b", from_year=1950, to_year=2015, priority=400)
    channel = StableChannel(
        schema_version=1,
        channel="stable",
        published_at=datetime(2026, 7, 25, 12, 34, 56, tzinfo=UTC),
        components=(low, high_later, high_earlier),
    )
    path = tmp_path / "stable.json"

    write_stable_channel_atomic(path, channel)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert list(payload) == ["channel", "components", "published_at", "schema_version"]
    assert payload["published_at"] == "2026-07-25T12:34:56Z"
    assert [item["id"] for item in payload["components"]] == ["b", "z", "a"]
    assert load_stable_channel(path) == channel


def test_stable_channel_rejects_duplicate_ids_and_equal_priority_overlap() -> None:
    first = _component(component_id="first", from_year=2000, to_year=2010, priority=100)
    duplicate = _component(component_id="first", from_year=2011, to_year=2020, priority=200)
    equal_priority_overlap = _component(
        component_id="second", from_year=2010, to_year=2020, priority=100
    )

    with pytest.raises(ValueError, match="duplicate"):
        StableChannel(1, "stable", datetime.now(UTC), (first, duplicate))
    with pytest.raises(ValueError, match="overlap"):
        StableChannel(1, "stable", datetime.now(UTC), (first, equal_priority_overlap))


def test_stable_channel_allows_different_priority_overlap_and_rejects_invalid_metadata() -> None:
    base = _component(component_id="base", from_year=1950, to_year=2025, priority=100)
    current = _component(component_id="current", from_year=2025, to_year=2025, priority=400)

    channel = StableChannel(1, "stable", "2026-07-25T12:34:56Z", (base, current))

    assert [component.id for component in channel.components] == ["current", "base"]
    with pytest.raises(ValueError, match="schema"):
        StableChannel(2, "stable", datetime.now(UTC), ())
    with pytest.raises(ValueError, match="channel"):
        StableChannel(1, "beta", datetime.now(UTC), ())
    with pytest.raises(ValueError, match="UTC"):
        StableChannel(
            1,
            "stable",
            datetime(2026, 7, 25, 12, 34, 56, tzinfo=timezone(timedelta(hours=-3))),
            (),
        )


def test_atomic_writes_remove_temporary_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    component_path = tmp_path / "component.json"
    channel_path = tmp_path / "stable.json"

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("media_catalog_builder.channel.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_component_atomic(component_path, _component())
    with pytest.raises(OSError, match="replace failed"):
        write_stable_channel_atomic(
            channel_path,
            StableChannel(1, "stable", datetime.now(UTC), (_component(),)),
        )

    assert not (tmp_path / "component.json.tmp").exists()
    assert not (tmp_path / "stable.json.tmp").exists()
