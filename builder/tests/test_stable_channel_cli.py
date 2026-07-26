from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from media_catalog_builder.channel import CatalogComponent, ComponentType, write_component_atomic

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "assemble_stable_channel.py"
_SHA256 = "a" * 64


def _component(
    component_id: str,
    *,
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
        release_tag=f"{component_id}-2026.07.25",
        manifest_asset="manifest.json",
        package_name=f"{component_id}.zip",
        package_bytes=100,
        package_sha256=_SHA256,
        installed_name=f"{component_id}.sqlite",
        installed_bytes=200,
        installed_sha256=_SHA256,
        catalog_schema=1,
        minimum_app_version="1.0.0",
        priority=priority,
    )


def _write_component(path: Path, component: CatalogComponent) -> Path:
    write_component_atomic(path, component)
    return path


def _run(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *(str(argument) for argument in arguments)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )


def test_assemble_stable_channel_cli_writes_sorted_channel_atomically(tmp_path: Path) -> None:
    base = _write_component(tmp_path / "base.json", _component("base-1950-2015"))
    supplement = _write_component(
        tmp_path / "supplement.json",
        _component(
            "supplement-2016-2025",
            component_type=ComponentType.SUPPLEMENT,
            from_year=2016,
            to_year=2025,
            priority=200,
        ),
    )
    current = _write_component(
        tmp_path / "current.json",
        _component(
            "current-2026",
            component_type=ComponentType.CURRENT_YEAR,
            from_year=2026,
            to_year=2026,
            priority=400,
        ),
    )
    output = tmp_path / "stable.json"
    output.write_text("outdated channel", encoding="utf-8")

    result = _run(
        "--component",
        base,
        "--component",
        supplement,
        "--component",
        current,
        "--output",
        output,
        "--published-at",
        "2026-07-25T12:34:56Z",
    )

    assert result.returncode == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["published_at"] == "2026-07-25T12:34:56Z"
    assert [component["id"] for component in payload["components"]] == [
        "current-2026",
        "supplement-2016-2025",
        "base-1950-2015",
    ]
    assert not list(tmp_path.glob("stable.json.*.tmp"))


def test_assemble_stable_channel_cli_uses_a_utc_timestamp_when_omitted(tmp_path: Path) -> None:
    component = _write_component(tmp_path / "base.json", _component("base-1950-2015"))
    output = tmp_path / "stable.json"

    result = _run("--component", component, "--output", output)

    assert result.returncode == 0
    published_at = json.loads(output.read_text(encoding="utf-8"))["published_at"]
    assert published_at.endswith("Z")
    assert datetime.fromisoformat(published_at[:-1] + "+00:00").tzinfo == UTC


def test_assemble_stable_channel_cli_requires_at_least_one_component(tmp_path: Path) -> None:
    result = _run("--output", tmp_path / "stable.json")

    assert result.returncode != 0
    assert "--component" in result.stderr


@pytest.mark.parametrize(
    ("component_paths", "message"),
    [
        ("missing", "invalid component JSON"),
        ("malformed", "invalid component JSON"),
        ("invalid", "catalog schema must be 1"),
        ("duplicate", "duplicate component IDs"),
        ("overlap", "equal-priority component year ranges may not overlap"),
    ],
)
def test_assemble_stable_channel_cli_rejects_invalid_components_without_replacing_output(
    tmp_path: Path, component_paths: str, message: str
) -> None:
    output = tmp_path / "stable.json"
    output.write_text("known-good channel", encoding="utf-8")
    if component_paths == "missing":
        paths = [tmp_path / "missing.json"]
    elif component_paths == "malformed":
        malformed = tmp_path / "malformed.json"
        malformed.write_text("{not JSON", encoding="utf-8")
        paths = [malformed]
    elif component_paths == "invalid":
        invalid = tmp_path / "invalid.json"
        payload = _component("base-1950-2015").to_dict()
        payload["catalog_schema"] = 2
        invalid.write_text(json.dumps(payload), encoding="utf-8")
        paths = [invalid]
    elif component_paths == "duplicate":
        paths = [
            _write_component(tmp_path / "one.json", _component("base-1950-2015")),
            _write_component(tmp_path / "two.json", _component("base-1950-2015")),
        ]
    else:
        paths = [
            _write_component(tmp_path / "one.json", _component("one")),
            _write_component(
                tmp_path / "two.json",
                _component("two", from_year=2000, to_year=2020),
            ),
        ]

    arguments = [item for path in paths for item in ("--component", path)]
    result = _run(*arguments, "--output", output)

    assert result.returncode != 0
    assert message in result.stderr
    assert output.read_text(encoding="utf-8") == "known-good channel"
    assert not list(tmp_path.glob("stable.json.*.tmp"))


@pytest.mark.parametrize("timestamp", ["", "2026-07-25T12:00:00+00:00", "not-a-timestamp"])
def test_assemble_stable_channel_cli_rejects_non_utc_timestamps_without_temp_output(
    tmp_path: Path, timestamp: str
) -> None:
    component = _write_component(tmp_path / "base.json", _component("base-1950-2015"))
    output = tmp_path / "stable.json"
    output.write_text("known-good channel", encoding="utf-8")

    result = _run(
        "--component",
        component,
        "--output",
        output,
        "--published-at",
        timestamp,
    )

    assert result.returncode != 0
    assert result.stderr.startswith("error:")
    assert output.read_text(encoding="utf-8") == "known-good channel"
    assert not list(tmp_path.glob("stable.json.*.tmp"))
