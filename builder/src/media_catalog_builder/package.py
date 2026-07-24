from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

_MIB = 1024 * 1024
_COPY_BUFFER = 1024 * 1024
_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_FIXED_MODE = 0o100644


@dataclass(frozen=True, slots=True)
class PackageInfo:
    archive_path: Path
    archive_name: str
    archive_bytes: int
    source_bytes: int
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_BUFFER), b""):
            digest.update(chunk)
    return digest.hexdigest()


def enforce_size(path: Path, max_mib: int, *, label: str = "file") -> None:
    if max_mib < 0:
        raise ValueError("size limit cannot be negative")
    maximum_bytes = max_mib * _MIB
    actual_bytes = path.stat().st_size
    if actual_bytes > maximum_bytes:
        raise ValueError(
            f"{label} exceeds {max_mib} MiB "
            f"({actual_bytes} bytes > {maximum_bytes} bytes)"
        )


def _validated_archive_name(value: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
        or Path(value).name != value
    ):
        raise ValueError("archive name must be a safe file name")
    return value


def _copy_to_archive(source: BinaryIO, destination: BinaryIO) -> None:
    shutil.copyfileobj(source, destination, length=_COPY_BUFFER)


def package_zip(source: Path, destination: Path, archive_name: str) -> PackageInfo:
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.resolve() == destination.resolve():
        raise ValueError("ZIP destination must differ from source")
    safe_name = _validated_archive_name(archive_name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.tmp")
    temporary.unlink(missing_ok=True)

    try:
        info = zipfile.ZipInfo(safe_name, date_time=_FIXED_TIMESTAMP)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = _FIXED_MODE << 16
        info.internal_attr = 0
        info.flag_bits = 0
        info._compresslevel = 9  # type: ignore[attr-defined]

        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
            strict_timestamps=True,
        ) as archive, source.open("rb") as input_handle, archive.open(
            info, mode="w", force_zip64=False
        ) as output_handle:
            _copy_to_archive(input_handle, output_handle)

        with temporary.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return PackageInfo(
        archive_path=destination,
        archive_name=safe_name,
        archive_bytes=destination.stat().st_size,
        source_bytes=source.stat().st_size,
        sha256=sha256_file(destination),
    )
