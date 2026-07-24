from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from media_catalog_builder.package import enforce_size, package_zip, sha256_file

_MIB = 1024 * 1024


def test_zip_is_byte_deterministic_with_fixed_metadata(tmp_path: Path) -> None:
    source = tmp_path / "catalog.sqlite"
    source.write_bytes((b"catalog-data\n" * 1000) + bytes(range(256)))
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_info = package_zip(source, first, "catalog.sqlite")
    second_info = package_zip(source, second, "catalog.sqlite")

    assert first.read_bytes() == second.read_bytes()
    assert first_info.sha256 == second_info.sha256 == sha256_file(first)
    assert first_info.archive_bytes == first.stat().st_size
    assert first_info.source_bytes == source.stat().st_size
    with zipfile.ZipFile(first) as archive:
        entries = archive.infolist()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.filename == "catalog.sqlite"
        assert entry.date_time == (1980, 1, 1, 0, 0, 0)
        assert entry.compress_type == zipfile.ZIP_DEFLATED
        assert entry.external_attr >> 16 == 0o100644
        assert archive.read(entry) == source.read_bytes()


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "asset.bin"
    path.write_bytes(b"abc" * 10000)

    assert sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "archive_name",
    ("", "../catalog.sqlite", "folder/catalog.sqlite", "folder\\catalog.sqlite"),
)
def test_zip_rejects_unsafe_archive_name(
    tmp_path: Path,
    archive_name: str,
) -> None:
    source = tmp_path / "catalog.sqlite"
    source.write_bytes(b"catalog")

    with pytest.raises(ValueError, match="archive name"):
        package_zip(source, tmp_path / "catalog.zip", archive_name)


def test_package_failure_preserves_existing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import media_catalog_builder.package as package_module

    source = tmp_path / "catalog.sqlite"
    source.write_bytes(b"catalog")
    destination = tmp_path / "catalog.zip"
    destination.write_bytes(b"existing package")
    existing = destination.read_bytes()

    def fail_copy(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated packaging interruption")

    monkeypatch.setattr(package_module, "_copy_to_archive", fail_copy)

    with pytest.raises(RuntimeError, match="simulated packaging interruption"):
        package_zip(source, destination, "catalog.sqlite")

    assert destination.read_bytes() == existing
    assert list(tmp_path.glob("*.tmp")) == []


def test_size_gate_accepts_exact_limit_and_rejects_one_byte_over(
    tmp_path: Path,
) -> None:
    exact = tmp_path / "exact.bin"
    with exact.open("wb") as handle:
        handle.truncate(100 * _MIB)
    too_large = tmp_path / "too-large.bin"
    with too_large.open("wb") as handle:
        handle.truncate((100 * _MIB) + 1)

    enforce_size(exact, 100, label="compressed catalog")
    with pytest.raises(ValueError, match="compressed catalog.*100 MiB"):
        enforce_size(too_large, 100, label="compressed catalog")


def test_installed_catalog_gate_rejects_over_250_mib(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    with database.open("wb") as handle:
        handle.truncate((250 * _MIB) + 1)

    with pytest.raises(ValueError, match="installed catalog.*250 MiB"):
        enforce_size(database, 250, label="installed catalog")
