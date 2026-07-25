from __future__ import annotations

import os
from pathlib import Path

import pytest

from media_catalog_builder.current_release import (
    LatestCatalog,
    load_latest,
    write_latest_atomic,
)


def _latest() -> LatestCatalog:
    return LatestCatalog(
        year=2026,
        version="2026.07.25",
        published_at="2026-07-25T21:00:00Z",
        release_tag="current-2026-2026.07.25",
        manifest_asset="manifest.json",
        full_sha256="a" * 64,
    )


def test_latest_catalog_round_trips_through_atomic_json(tmp_path: Path) -> None:
    path = tmp_path / "catalog" / "current" / "latest.json"

    write_latest_atomic(path, _latest())

    assert load_latest(path) == _latest()
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert list(path.parent.glob("*.tmp")) == []


def test_latest_catalog_rejects_invalid_version() -> None:
    with pytest.raises(ValueError, match="invalid catalog version"):
        LatestCatalog(
            year=2026,
            version="2026.07.25-current",
            published_at="2026-07-25T21:00:00Z",
            release_tag="current-2026-2026.07.25",
            manifest_asset="manifest.json",
            full_sha256="a" * 64,
        )


def test_latest_catalog_rejects_unknown_json_fields(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    path.write_text(
        '{"year":2026,"version":"2026.07.25","published_at":"2026-07-25T21:00:00Z",'
        '"release_tag":"current-2026-2026.07.25","manifest_asset":"manifest.json",'
        '"full_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"unknown":true}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid latest catalog fields"):
        load_latest(path)


def test_failed_atomic_replace_preserves_previous_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "latest.json"
    previous = b"previous-pointer\n"
    path.write_bytes(previous)

    def fail_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        del source, destination
        raise OSError("simulated publication failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated publication failure"):
        write_latest_atomic(path, _latest())

    assert path.read_bytes() == previous
    assert list(tmp_path.glob("*.tmp")) == []
