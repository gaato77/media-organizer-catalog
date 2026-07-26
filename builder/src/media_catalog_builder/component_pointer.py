from __future__ import annotations

import sqlite3
from pathlib import Path

from media_catalog_builder.channel import CatalogComponent, ComponentType
from media_catalog_builder.database import CatalogDatabase
from media_catalog_builder.manifest import load_manifest
from media_catalog_builder.package import sha256_file


def build_component_pointer(
    release_dir: Path,
    installed_database: Path,
    *,
    component_id: str,
    component_type: ComponentType,
    from_year: int,
    to_year: int,
    release_tag: str,
    priority: int,
) -> CatalogComponent:
    """Derive a component pointer only after validating its release inputs."""
    manifest = load_manifest(release_dir / "manifest.json")
    package = release_dir / manifest.full.name
    if not package.is_file():
        raise ValueError("declared full package is missing")
    if package.stat().st_size != manifest.full.download_bytes:
        raise ValueError("full package size does not match manifest")
    if sha256_file(package) != manifest.full.sha256:
        raise ValueError("full package SHA-256 does not match manifest")

    if not installed_database.is_file():
        raise ValueError("installed SQLite is missing")
    if installed_database.stat().st_size != manifest.full.installed_bytes:
        raise ValueError("installed SQLite size does not match manifest")
    installed_sha256 = sha256_file(installed_database)
    _validate_installed_database(
        installed_database, manifest.catalog_schema, manifest.catalog_version
    )

    return CatalogComponent(
        id=component_id,
        type=component_type,
        from_year=from_year,
        to_year=to_year,
        version=manifest.catalog_version,
        release_tag=release_tag,
        manifest_asset="manifest.json",
        package_name=manifest.full.name,
        package_bytes=manifest.full.download_bytes,
        package_sha256=manifest.full.sha256,
        installed_name=installed_database.name,
        installed_bytes=manifest.full.installed_bytes,
        installed_sha256=installed_sha256,
        catalog_schema=manifest.catalog_schema,
        minimum_app_version=manifest.minimum_app_version,
        priority=priority,
    )


def _validate_installed_database(path: Path, catalog_schema: int, catalog_version: str) -> None:
    try:
        with CatalogDatabase.open(path, readonly=True) as database:
            if database.integrity_check() != "ok":
                raise ValueError("installed SQLite integrity check failed")
            if database.get_meta("catalog_schema") != str(catalog_schema):
                raise ValueError("installed SQLite catalog schema does not match manifest")
            if database.get_meta("catalog_version") != catalog_version:
                raise ValueError("installed SQLite catalog version does not match manifest")
    except sqlite3.DatabaseError as exc:
        raise ValueError("invalid installed SQLite") from exc
