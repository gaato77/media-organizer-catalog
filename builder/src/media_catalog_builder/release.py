from __future__ import annotations

import json
import os
import shutil
import sqlite3
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from media_catalog_builder.config import CatalogConfig
from media_catalog_builder.database import CatalogDatabase
from media_catalog_builder.manifest import (
    Asset,
    DeltaPath,
    ReleaseManifest,
    choose_update_path,
    load_manifest,
    write_manifest,
)
from media_catalog_builder.model import MediaType, SourceRecord
from media_catalog_builder.names import to_catalog_record
from media_catalog_builder.normalize import normalize_lookup
from media_catalog_builder.package import enforce_size, package_zip, sha256_file


@dataclass(frozen=True, slots=True)
class BuildStats:
    source_rows: int
    catalog_records: int
    skipped_records: int
    database_bytes: int


def _text_sort_key(value: str) -> tuple[str, str, str]:
    return (normalize_lookup(value), value.casefold(), value)


def _first_label(records: Sequence[SourceRecord], attribute: str) -> str | None:
    values = {
        value.strip()
        for record in records
        if (value := getattr(record, attribute)) is not None and value.strip()
    }
    return min(values, key=_text_sort_key) if values else None


def _merge_source_records(records: Sequence[SourceRecord]) -> SourceRecord:
    if not records:
        raise ValueError("source record group cannot be empty")
    originals = {
        title.strip() for record in records for title in record.original_titles if title.strip()
    }
    modified_values = [record.modified_at for record in records if record.modified_at]
    return SourceRecord(
        qid=records[0].qid,
        media_type=max((record.media_type for record in records), key=int),
        year=min(record.year for record in records),
        original_titles=tuple(sorted(originals, key=_text_sort_key)),
        english_label=_first_label(records, "english_label"),
        spanish_label=_first_label(records, "spanish_label"),
        modified_at=max(modified_values) if modified_values else None,
    )


def _published_at(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_database_from_sources(
    records: Iterable[SourceRecord],
    output: Path,
    *,
    version: str,
    now: datetime,
    schema_path: Path,
) -> BuildStats:
    source_rows = list(records)
    grouped: dict[int, list[SourceRecord]] = {}
    for record in source_rows:
        grouped.setdefault(record.qid, []).append(record)

    catalog_records = []
    skipped_records = 0
    for qid in sorted(grouped):
        merged = _merge_source_records(grouped[qid])
        catalog_record = to_catalog_record(merged)
        if catalog_record is None:
            skipped_records += 1
        else:
            catalog_records.append(catalog_record)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with CatalogDatabase.create(output, schema_path) as database:
        database.set_meta_many(
            {
                "catalog_schema": "1",
                "catalog_version": version,
                "published_at": _published_at(now),
                "source_rows": str(len(source_rows)),
                "work_count": str(len(catalog_records)),
            }
        )
        database.upsert_many(catalog_records)
        database.finalize()

    return BuildStats(
        source_rows=len(source_rows),
        catalog_records=len(catalog_records),
        skipped_records=skipped_records,
        database_bytes=output.stat().st_size,
    )


def _retained_delta_chain(
    deltas: Sequence[DeltaPath],
    target_version: str,
    *,
    limit: int,
) -> tuple[DeltaPath, ...]:
    if limit < 0:
        raise ValueError("delta retention limit cannot be negative")
    if limit == 0:
        return ()
    incoming: dict[str, list[DeltaPath]] = {}
    for delta in deltas:
        incoming.setdefault(delta.to_version, []).append(delta)
    for edges in incoming.values():
        edges.sort(key=lambda edge: (edge.from_version, edge.download_bytes, edge.name))

    paths: list[tuple[DeltaPath, ...]] = []

    def visit(
        version: str,
        reversed_path: tuple[DeltaPath, ...],
        visited: frozenset[str],
    ) -> None:
        if reversed_path:
            paths.append(tuple(reversed(reversed_path)))
        for delta in incoming.get(version, []):
            if delta.from_version in visited:
                continue
            visit(
                delta.from_version,
                (*reversed_path, delta),
                visited | {delta.from_version},
            )

    visit(target_version, (), frozenset({target_version}))
    if not paths:
        return ()
    selected = max(
        paths,
        key=lambda path: (
            len(path),
            -sum(delta.download_bytes for delta in path),
            tuple(delta.name for delta in path),
        ),
    )
    return selected[-limit:]


def _catalog_metadata(path: Path) -> dict[str, str]:
    with CatalogDatabase.open(path, readonly=True) as database:
        if database.integrity_check() != "ok":
            raise ValueError("catalog integrity check failed")
        keys = ("catalog_schema", "catalog_version")
        values = {key: database.get_meta(key) for key in keys}
    if any(value is None for value in values.values()):
        raise ValueError("catalog metadata is incomplete")
    return {key: cast(str, value) for key, value in values.items()}


def _copy_verified_asset(source_dir: Path, destination_dir: Path, asset: DeltaPath) -> None:
    source = source_dir / asset.name
    if not source.is_file():
        raise ValueError(f"previous delta asset is missing: {asset.name}")
    if source.stat().st_size != asset.download_bytes:
        raise ValueError(f"previous delta asset size mismatch: {asset.name}")
    if sha256_file(source) != asset.sha256:
        raise ValueError(f"previous delta asset checksum mismatch: {asset.name}")
    shutil.copyfile(source, destination_dir / asset.name)


def _write_checksums(directory: Path, names: Sequence[str]) -> None:
    entries = sorted((name, sha256_file(directory / name)) for name in names)
    (directory / "checksums.sha256").write_text(
        "".join(f"{checksum}  {name}\n" for name, checksum in entries),
        encoding="utf-8",
    )


def _load_lookup_cases(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid lookup cases") from exc
    if not isinstance(payload, list):
        raise ValueError("lookup cases must be a list")
    required = {"name", "year", "media_type", "canonical_title"}
    cases: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError("invalid lookup case")
        cases.append(cast(dict[str, Any], item))
    if not cases:
        raise ValueError("at least one lookup case is required")
    return tuple(cases)


def _extract_single_zip(asset_path: Path, destination: Path, expected_name: str) -> Path:
    try:
        with zipfile.ZipFile(asset_path) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise ValueError(f"asset must contain one file: {asset_path.name}")
            entry = entries[0]
            mode = entry.external_attr >> 16
            if (
                entry.is_dir()
                or entry.filename != expected_name
                or Path(entry.filename).name != entry.filename
                or (mode & 0o170000) not in {0, 0o100000}
            ):
                raise ValueError(f"unsafe ZIP entry: {asset_path.name}")
            extracted = destination / expected_name
            with archive.open(entry) as source, extracted.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"invalid ZIP asset: {asset_path.name}") from exc
    return extracted


def _validate_full_database(
    path: Path,
    manifest: ReleaseManifest,
    lookup_cases_path: Path,
) -> None:
    with CatalogDatabase.open(path, readonly=True) as database:
        if database.integrity_check() != "ok":
            raise ValueError("full catalog integrity check failed")
        if database.get_meta("catalog_schema") != str(manifest.catalog_schema):
            raise ValueError("full catalog schema mismatch")
        if database.get_meta("catalog_version") != manifest.catalog_version:
            raise ValueError("full catalog version mismatch")
        for case in _load_lookup_cases(lookup_cases_path):
            media_type_text = str(case["media_type"])
            mapping = {"movie": MediaType.MOVIE, "series": MediaType.SERIES}
            if media_type_text not in mapping:
                raise ValueError("invalid lookup media type")
            results = database.lookup(
                str(case["name"]),
                year=int(case["year"]),
                media_type=mapping[media_type_text],
            )
            expected = str(case["canonical_title"])
            if not any(result.canonical_title == expected for result in results):
                raise ValueError(f"representative lookup failed: {case['name']}")


def _validate_delta_database(path: Path, descriptor: DeltaPath, catalog_schema: int) -> None:
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or str(integrity[0]) != "ok":
                raise ValueError("delta integrity check failed")
            metadata = {
                str(row["key"]): str(row["value"])
                for row in connection.execute("SELECT key, value FROM meta")
            }
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"invalid delta database: {descriptor.name}") from exc
    if metadata.get("delta_schema") != "1":
        raise ValueError("delta schema mismatch")
    if metadata.get("catalog_schema") != str(catalog_schema):
        raise ValueError("delta catalog schema mismatch")
    if metadata.get("from_version") != descriptor.from_version:
        raise ValueError("delta from_version mismatch")
    if metadata.get("to_version") != descriptor.to_version:
        raise ValueError("delta to_version mismatch")


def _read_checksums(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("checksums.sha256 is missing") from exc
    result: dict[str, str] = {}
    for line in lines:
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64 or any(
            character not in "0123456789abcdef" for character in parts[0]
        ):
            raise ValueError("invalid checksums.sha256")
        checksum, name = parts
        if not name or Path(name).name != name or name in result:
            raise ValueError("invalid checksums.sha256")
        result[name] = checksum
    return result


def validate_release(
    release_dir: Path,
    *,
    config: CatalogConfig,
    lookup_cases_path: Path,
) -> ReleaseManifest:
    if not release_dir.is_dir():
        raise ValueError("release directory is missing")
    manifest_path = release_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    if manifest.manifest_schema != config.manifest_schema_version:
        raise ValueError("manifest schema does not match configuration")
    if manifest.catalog_schema != config.schema_version:
        raise ValueError("catalog schema does not match configuration")

    assets: tuple[Asset | DeltaPath, ...] = (manifest.full, *manifest.deltas)
    expected_files = {"manifest.json", "checksums.sha256", *(asset.name for asset in assets)}
    actual_files = {path.name for path in release_dir.iterdir() if path.is_file()}
    if actual_files != expected_files or any(path.is_dir() for path in release_dir.iterdir()):
        raise ValueError("release directory contains unexpected files")

    checksums = _read_checksums(release_dir / "checksums.sha256")
    checksum_names = {"manifest.json", *(asset.name for asset in assets)}
    if set(checksums) != checksum_names:
        raise ValueError("checksums.sha256 does not match release assets")
    for name, expected_checksum in checksums.items():
        if sha256_file(release_dir / name) != expected_checksum:
            raise ValueError(f"checksum mismatch: {name}")

    for asset in assets:
        asset_path = release_dir / asset.name
        if asset_path.stat().st_size != asset.download_bytes:
            raise ValueError(f"asset size mismatch: {asset.name}")
        if sha256_file(asset_path) != asset.sha256:
            raise ValueError(f"asset checksum mismatch: {asset.name}")

    enforce_size(
        release_dir / manifest.full.name,
        config.max_compressed_mib,
        label="compressed catalog",
    )

    temporary = release_dir / ".validation"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir()
    try:
        full_database = _extract_single_zip(
            release_dir / manifest.full.name,
            temporary,
            "catalog.sqlite",
        )
        if full_database.stat().st_size != manifest.full.installed_bytes:
            raise ValueError("installed catalog size mismatch")
        enforce_size(full_database, config.max_installed_mib, label="installed catalog")
        _validate_full_database(full_database, manifest, lookup_cases_path)

        for index, delta in enumerate(manifest.deltas, start=1):
            delta_directory = temporary / f"delta-{index}"
            delta_directory.mkdir()
            delta_database = _extract_single_zip(
                release_dir / delta.name,
                delta_directory,
                "catalog-delta.sqlite",
            )
            if delta_database.stat().st_size != delta.installed_bytes:
                raise ValueError(f"installed delta size mismatch: {delta.name}")
            _validate_delta_database(delta_database, delta, manifest.catalog_schema)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    for delta in manifest.deltas:
        path = choose_update_path(manifest, delta.from_version)
        if not path or any(not isinstance(item, DeltaPath) for item in path):
            raise ValueError("manifest contains a disconnected delta")
        if cast(DeltaPath, path[-1]).to_version != manifest.catalog_version:
            raise ValueError("manifest delta chain does not reach current version")
    return manifest


def assemble_release(
    catalog_path: Path,
    output_dir: Path,
    *,
    version: str,
    published_at: datetime,
    minimum_app_version: str,
    config: CatalogConfig,
    lookup_cases_path: Path,
    previous_release_dir: Path | None = None,
    delta_path: Path | None = None,
    delta_from_version: str | None = None,
) -> ReleaseManifest:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if (delta_path is None) != (delta_from_version is None):
        raise ValueError("delta_path and delta_from_version must be provided together")
    metadata = _catalog_metadata(catalog_path)
    if metadata["catalog_schema"] != str(config.schema_version):
        raise ValueError("catalog schema does not match configuration")
    if metadata["catalog_version"] != version:
        raise ValueError("catalog version does not match release version")

    staging = output_dir.with_name(f"{output_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        enforce_size(catalog_path, config.max_installed_mib, label="installed catalog")
        full_name = f"catalog-full-{version}.sqlite.zip"
        full_info = package_zip(catalog_path, staging / full_name, "catalog.sqlite")
        enforce_size(staging / full_name, config.max_compressed_mib, label="compressed catalog")
        full_asset = Asset(
            name=full_name,
            download_bytes=full_info.archive_bytes,
            installed_bytes=full_info.source_bytes,
            sha256=full_info.sha256,
        )

        deltas: list[DeltaPath] = []
        if delta_path is not None and delta_from_version is not None:
            current_name = f"catalog-delta-{delta_from_version}-to-{version}.sqlite.zip"
            delta_info = package_zip(
                delta_path,
                staging / current_name,
                "catalog-delta.sqlite",
            )
            efficient = delta_info.archive_bytes * 5 < full_info.archive_bytes * 4
            if efficient:
                previous_chain: tuple[DeltaPath, ...] = ()
                if previous_release_dir is not None:
                    previous_manifest = validate_release(
                        previous_release_dir,
                        config=config,
                        lookup_cases_path=lookup_cases_path,
                    )
                    if previous_manifest.catalog_version != delta_from_version:
                        raise ValueError("previous release version does not match delta")
                    previous_chain = _retained_delta_chain(
                        previous_manifest.deltas,
                        previous_manifest.catalog_version,
                        limit=max(0, config.supported_delta_versions - 1),
                    )
                    for previous_delta in previous_chain:
                        _copy_verified_asset(previous_release_dir, staging, previous_delta)
                deltas.extend(previous_chain)
                deltas.append(
                    DeltaPath(
                        from_version=delta_from_version,
                        to_version=version,
                        name=current_name,
                        download_bytes=delta_info.archive_bytes,
                        installed_bytes=delta_info.source_bytes,
                        sha256=delta_info.sha256,
                    )
                )
            else:
                (staging / current_name).unlink()

        manifest = ReleaseManifest(
            manifest_schema=config.manifest_schema_version,
            catalog_schema=config.schema_version,
            catalog_version=version,
            published_at=_published_at(published_at),
            minimum_app_version=minimum_app_version,
            full=full_asset,
            deltas=tuple(deltas[-config.supported_delta_versions :]),
        )
        write_manifest(staging / "manifest.json", manifest)
        _write_checksums(
            staging,
            [manifest.full.name, *(delta.name for delta in manifest.deltas), "manifest.json"],
        )
        validate_release(staging, config=config, lookup_cases_path=lookup_cases_path)
        os.replace(staging, output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest
