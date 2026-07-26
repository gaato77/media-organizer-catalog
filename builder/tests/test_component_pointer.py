from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from media_catalog_builder.channel import CatalogComponent, ComponentType
from media_catalog_builder.database import CatalogDatabase
from media_catalog_builder.manifest import Asset, ReleaseManifest, write_manifest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_database(
    path: Path, schema_path: Path, *, schema: str = "1", version: str = "2026.07.25"
) -> None:
    with CatalogDatabase.create(path, schema_path) as database:
        database.set_meta_many({"catalog_schema": schema, "catalog_version": version})


def _release_directory(tmp_path: Path, installed: Path) -> Path:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    package = release_dir / "catalog-full-2026.07.25.sqlite.zip"
    package.write_bytes(b"verified catalog package")
    write_manifest(
        release_dir / "manifest.json",
        ReleaseManifest(
            manifest_schema=1,
            catalog_schema=1,
            catalog_version="2026.07.25",
            published_at="2026-07-25T12:00:00Z",
            minimum_app_version="1.0.0",
            full=Asset(
                name=package.name,
                download_bytes=package.stat().st_size,
                installed_bytes=installed.stat().st_size,
                sha256=_sha256(package),
            ),
            deltas=(),
        ),
    )
    return release_dir


@pytest.fixture
def verified_release(tmp_path: Path, schema_path: Path) -> tuple[Path, Path]:
    installed = tmp_path / "catalog.sqlite"
    _create_database(installed, schema_path)
    return _release_directory(tmp_path, installed), installed


def _build(release_dir: Path, installed: Path) -> CatalogComponent:
    from media_catalog_builder.component_pointer import build_component_pointer

    return build_component_pointer(
        release_dir,
        installed,
        component_id="base-1950-2015",
        component_type=ComponentType.BASE,
        from_year=1950,
        to_year=2015,
        release_tag="base-1950-2015-2026.07.25",
        priority=100,
    )


def test_build_component_pointer_derives_verified_component(
    verified_release: tuple[Path, Path],
) -> None:
    release_dir, installed = verified_release

    component = _build(release_dir, installed)

    assert component.to_dict() == {
        "id": "base-1950-2015",
        "type": "base",
        "from_year": 1950,
        "to_year": 2015,
        "version": "2026.07.25",
        "release_tag": "base-1950-2015-2026.07.25",
        "manifest_asset": "manifest.json",
        "package_name": "catalog-full-2026.07.25.sqlite.zip",
        "package_bytes": 24,
        "package_sha256": "34b7e8b3e836b44bd791d5fb6cb4176ec0d99fad3d24eaf048dd51f5f197e3d4",
        "installed_name": "catalog.sqlite",
        "installed_bytes": installed.stat().st_size,
        "installed_sha256": _sha256(installed),
        "catalog_schema": 1,
        "minimum_app_version": "1.0.0",
        "priority": 100,
    }


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("manifest.json", "manifest"),
        ("catalog-full-2026.07.25.sqlite.zip", "full package"),
    ],
)
def test_build_component_pointer_requires_valid_manifest_and_declared_package(
    verified_release: tuple[Path, Path], path: str, message: str
) -> None:
    release_dir, installed = verified_release
    (release_dir / path).unlink()

    with pytest.raises(ValueError, match=message):
        _build(release_dir, installed)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("package-size", "package size"),
        ("package-sha", "package SHA-256"),
        ("installed-size", "installed SQLite size"),
    ],
)
def test_build_component_pointer_rejects_size_and_checksum_mismatches(
    verified_release: tuple[Path, Path], mutation: str, message: str
) -> None:
    release_dir, installed = verified_release
    manifest_path = release_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "package-size":
        manifest["full"]["download_bytes"] += 1
    elif mutation == "package-sha":
        manifest["full"]["sha256"] = "0" * 64
    else:
        manifest["full"]["installed_bytes"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        _build(release_dir, installed)


def test_build_component_pointer_requires_installed_sqlite(
    verified_release: tuple[Path, Path],
) -> None:
    release_dir, installed = verified_release
    installed.unlink()

    with pytest.raises(ValueError, match="installed SQLite"):
        _build(release_dir, installed)


def test_build_component_pointer_rejects_invalid_sqlite(
    verified_release: tuple[Path, Path],
) -> None:
    release_dir, installed = verified_release
    installed.write_bytes(b"not a database")
    manifest_path = release_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["full"]["installed_bytes"] = installed.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="installed SQLite"):
        _build(release_dir, installed)


def test_build_component_pointer_requires_an_ok_integrity_check(
    verified_release: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    release_dir, installed = verified_release
    monkeypatch.setattr(CatalogDatabase, "integrity_check", lambda _: "database corruption")

    with pytest.raises(ValueError, match="integrity check"):
        _build(release_dir, installed)


@pytest.mark.parametrize(
    ("schema", "version", "message"),
    [
        ("2", "2026.07.25", "catalog schema"),
        ("1", "2026.07.24", "catalog version"),
    ],
)
def test_build_component_pointer_requires_manifest_metadata(
    tmp_path: Path, schema_path: Path, schema: str, version: str, message: str
) -> None:
    installed = tmp_path / "catalog.sqlite"
    _create_database(installed, schema_path, schema=schema, version=version)
    release_dir = _release_directory(tmp_path, installed)

    with pytest.raises(ValueError, match=message):
        _build(release_dir, installed)


def test_write_component_pointer_cli_writes_component_atomically(
    verified_release: tuple[Path, Path], tmp_path: Path
) -> None:
    release_dir, installed = verified_release
    output = tmp_path / "component.json"
    script = Path(__file__).resolve().parents[1] / "scripts" / "write_component_pointer.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--release-dir",
            str(release_dir),
            "--installed-database",
            str(installed),
            "--component-id",
            "base-1950-2015",
            "--component-type",
            "base",
            "--from-year",
            "1950",
            "--to-year",
            "2015",
            "--release-tag",
            "base-1950-2015-2026.07.25",
            "--priority",
            "100",
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(output.read_text(encoding="utf-8"))["id"] == "base-1950-2015"
    assert not list(tmp_path.glob("component.json.*.tmp"))


def test_write_component_pointer_cli_returns_nonzero_for_validation_failure(
    verified_release: tuple[Path, Path], tmp_path: Path
) -> None:
    release_dir, installed = verified_release
    (release_dir / "catalog-full-2026.07.25.sqlite.zip").unlink()
    script = Path(__file__).resolve().parents[1] / "scripts" / "write_component_pointer.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--release-dir",
            str(release_dir),
            "--installed-database",
            str(installed),
            "--component-id",
            "base-1950-2015",
            "--component-type",
            "base",
            "--from-year",
            "1950",
            "--to-year",
            "2015",
            "--release-tag",
            "base-1950-2015-2026.07.25",
            "--priority",
            "100",
            "--output",
            str(tmp_path / "component.json"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "full package" in result.stderr
