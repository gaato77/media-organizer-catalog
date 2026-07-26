from __future__ import annotations

import io
import os
import sqlite3
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import pytest
import requests

from media_catalog_builder.channel import (
    CatalogComponent,
    ComponentType,
    load_component,
    load_stable_channel,
)
from media_catalog_builder.current_release import load_latest
from media_catalog_builder.database import CatalogDatabase
from media_catalog_builder.manifest import load_manifest
from media_catalog_builder.package import sha256_file

ROOT = Path(__file__).resolve().parents[2]
_DISTRIBUTION_ENV = "CATALOG_DISTRIBUTION_ROOT"
_RELEASE_ROOT = "https://github.com/gaato77/media-organizer-catalog/releases/download"
_MAX_CHANNEL_BYTES = 2 * 1024 * 1024
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_PACKAGE_BYTES = 100 * 1024 * 1024
_MAX_INSTALLED_BYTES = 250 * 1024 * 1024
_MAX_REDIRECTS = 5
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class _UnauthenticatedSession(requests.Session):
    def prepare_request(self, request: requests.Request) -> requests.PreparedRequest:
        prepared = super().prepare_request(request)
        prepared.headers.pop("Authorization", None)
        return prepared

    def rebuild_auth(
        self,
        prepared_request: requests.PreparedRequest,
        response: requests.Response,
    ) -> None:
        prepared_request.headers.pop("Authorization", None)


def _response(url: str) -> requests.Response:
    response = requests.Response()
    response.url = url
    response.request = requests.Request("GET", url).prepare()
    response.raw = io.BytesIO()
    _ = response.content
    return response


class _RedirectRecordingSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.requested: list[str] = []

    def get(self, url: str, **kwargs: object) -> requests.Response:
        self.requested.append(url)
        unsafe_target = "http://127.0.0.1/private"
        if kwargs.get("allow_redirects", True):
            self.requested.append(unsafe_target)
            raise AssertionError("automatic redirect reached an unsafe target")
        response = _response(url)
        response.status_code = 302
        response.headers["Location"] = unsafe_target
        return response


def _committed_distribution_state() -> dict[Path, bytes]:
    catalog = ROOT / "catalog"
    return {
        path.relative_to(ROOT): path.read_bytes()
        for directory in (catalog / "components", catalog / "channel")
        if directory.is_dir()
        for path in directory.rglob("*")
        if path.is_file()
    }


def _load_committed_distribution() -> tuple[CatalogComponent, ...]:
    latest = ROOT / "catalog" / "current" / "latest.json"
    if latest.is_file():
        load_latest(latest)

    component_dir = ROOT / "catalog" / "components"
    components = tuple(load_component(path) for path in sorted(component_dir.glob("*.json")))
    component_by_id = {component.id: component for component in components}
    assert len(component_by_id) == len(components)
    stable_path = ROOT / "catalog" / "channel" / "stable.json"
    if not stable_path.is_file():
        return components

    channel = load_stable_channel(stable_path)
    assert len(channel.components) == len(components)
    assert all(component_by_id.get(component.id) == component for component in channel.components)
    return channel.components


def _stable_url(distribution_root: str) -> str:
    value = distribution_root.strip().rstrip("/")
    parsed = urlsplit(value)
    if (
        not value
        or parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{_DISTRIBUTION_ENV} must be an unauthenticated HTTPS URL")
    if parsed.path.endswith(".json"):
        return value
    return f"{value}/catalog/channel/stable.json"


def test_distribution_transport_rejects_an_insecure_redirect_hop() -> None:
    insecure_redirect = _response("http://downloads.example.invalid/catalog.zip")
    final_response = _response("https://downloads.example.invalid/catalog.zip")
    final_response.history = [insecure_redirect]

    with pytest.raises(ValueError, match="redirected away from HTTPS"):
        _assert_unauthenticated_https(final_response)


def test_download_rejects_an_unsafe_redirect_before_requesting_it(tmp_path: Path) -> None:
    session = _RedirectRecordingSession()
    initial_url = "https://github.com/gaato77/media-organizer-catalog/releases/download/tag/file"

    with pytest.raises(ValueError, match="allowed HTTPS"):
        _download(session, initial_url, tmp_path / "file", maximum_bytes=10)

    assert session.requested == [initial_url]


def _assert_unauthenticated_https(response: requests.Response) -> None:
    for hop in (*response.history, response):
        try:
            _validate_download_target(hop.url)
        except ValueError as exc:
            raise ValueError(
                "distribution download redirected away from HTTPS or to an unsafe target"
            ) from exc
        if "Authorization" in hop.request.headers:
            raise ValueError("distribution download unexpectedly used authentication")


def _release_url(component: CatalogComponent, asset_name: str) -> str:
    tag = quote(component.release_tag, safe="")
    asset = quote(asset_name, safe="")
    return f"{_RELEASE_ROOT}/{tag}/{asset}"


def _validate_download_target(url: str) -> str:
    if url != url.strip() or any(ord(character) < 32 for character in url):
        raise ValueError("distribution target must be an allowed HTTPS URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("distribution target must be an allowed HTTPS URL") from exc
    hostname = parsed.hostname
    github_host = hostname in {"github.com", "raw.githubusercontent.com"}
    github_content_host = hostname is not None and hostname.endswith(".githubusercontent.com")
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not (github_host or github_content_host)
    ):
        raise ValueError("distribution target must be an allowed HTTPS URL")
    return url


def _get_with_safe_redirects(session: requests.Session, url: str) -> requests.Response:
    current_url = _validate_download_target(url)
    for redirect_count in range(_MAX_REDIRECTS + 1):
        response = session.get(
            current_url,
            allow_redirects=False,
            stream=True,
            timeout=(10, 120),
        )
        _assert_unauthenticated_https(response)
        if response.status_code not in _REDIRECT_STATUS_CODES:
            return response
        location = response.headers.get("Location")
        if location is None:
            response.close()
            raise ValueError("distribution redirect did not declare a target")
        next_url = urljoin(response.url, location)
        try:
            _validate_download_target(next_url)
        except ValueError:
            response.close()
            raise
        response.close()
        if redirect_count == _MAX_REDIRECTS:
            raise ValueError("distribution download exceeded the redirect limit")
        current_url = next_url
    raise AssertionError("unreachable redirect loop")


def _download(
    session: requests.Session,
    url: str,
    destination: Path,
    *,
    maximum_bytes: int,
    expected_bytes: int | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _get_with_safe_redirects(session, url) as response:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            declared_bytes = int(content_length)
            if declared_bytes > maximum_bytes:
                raise ValueError("distribution download exceeds its size limit")
            if expected_bytes is not None and declared_bytes != expected_bytes:
                raise ValueError("distribution Content-Length does not match the stable channel")

        downloaded = 0
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > maximum_bytes:
                    raise ValueError("distribution download exceeds its size limit")
                if expected_bytes is not None and downloaded > expected_bytes:
                    raise ValueError("distribution package exceeds its declared size")
                handle.write(chunk)
    if downloaded == 0:
        raise ValueError("distribution download was empty")
    if expected_bytes is not None and downloaded != expected_bytes:
        raise ValueError("distribution package size does not match the stable channel")


def _extract_component_package(
    package: Path,
    installed: Path,
    component: CatalogComponent,
) -> None:
    if component.installed_bytes > _MAX_INSTALLED_BYTES:
        raise ValueError("installed catalog exceeds its size limit")
    try:
        with zipfile.ZipFile(package) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise ValueError("catalog package must contain exactly one file")
            entry = entries[0]
            entry_mode = (entry.external_attr >> 16) & 0o170000
            if (
                entry.is_dir()
                or entry.filename != component.installed_name
                or entry.file_size != component.installed_bytes
                or entry.flag_bits & 0x1
                or entry_mode not in {0, stat.S_IFREG}
            ):
                raise ValueError(
                    "catalog package does not contain the expected regular SQLite file"
                )
            installed.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(entry) as source, installed.open("wb") as destination:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    written += len(chunk)
                    if written > component.installed_bytes:
                        raise ValueError("installed catalog exceeds its declared size")
                    destination.write(chunk)
            if written != component.installed_bytes:
                raise ValueError("installed catalog size does not match the stable channel")
            if archive.testzip() is not None:
                raise ValueError("catalog package failed its ZIP CRC check")
    except zipfile.BadZipFile as exc:
        raise ValueError("catalog package is not a valid ZIP file") from exc


def _verify_manifest(component: CatalogComponent, manifest_path: Path) -> None:
    manifest = load_manifest(manifest_path)
    assert manifest.catalog_schema == component.catalog_schema
    assert manifest.catalog_version == component.version
    assert manifest.minimum_app_version == component.minimum_app_version
    assert manifest.full.name == component.package_name
    assert manifest.full.download_bytes == component.package_bytes
    assert manifest.full.installed_bytes == component.installed_bytes
    assert manifest.full.sha256 == component.package_sha256


def _verify_sqlite(component: CatalogComponent, installed: Path) -> None:
    if installed.stat().st_size != component.installed_bytes:
        raise ValueError("installed catalog size does not match the stable channel")
    if sha256_file(installed) != component.installed_sha256:
        raise ValueError("installed catalog SHA-256 does not match the stable channel")

    with CatalogDatabase.open(installed, readonly=True) as database:
        assert database.integrity_check() == "ok"
        assert database.get_meta("catalog_schema") == str(component.catalog_schema)
        assert database.get_meta("catalog_version") == component.version

    uri = f"{installed.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        outside_range = connection.execute(
            "SELECT COUNT(*) FROM works WHERE release_year < ? OR release_year > ?",
            (component.from_year, component.to_year),
        ).fetchone()
        representative = connection.execute(
            "SELECT n.normalized_name, w.qid, w.release_year "
            "FROM names AS n JOIN works AS w ON w.qid = n.work_qid "
            "WHERE w.release_year BETWEEN ? AND ? "
            "ORDER BY w.release_year, w.qid, n.name_rank LIMIT 1",
            (component.from_year, component.to_year),
        ).fetchone()
        lookup_plan = ()
        if representative is not None:
            lookup_plan = connection.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT w.qid FROM names AS n JOIN works AS w ON w.qid = n.work_qid "
                "WHERE n.normalized_name = ? AND w.release_year = ? "
                "ORDER BY w.release_year, w.media_type, w.qid",
                (representative[0], representative[2]),
            ).fetchall()
    assert outside_range == (0,)
    assert representative is not None
    if not any(
        "SEARCH n USING" in str(row[3]) and "normalized_name=?" in str(row[3])
        for row in lookup_plan
    ):
        raise ValueError("representative lookup did not use the catalog name index")
    normalized_name, qid, year = representative
    with CatalogDatabase.open(installed, readonly=True) as database:
        matches = database.lookup(str(normalized_name), year=int(year))
    assert any(match.qid == int(qid) for match in matches)


def _verify_continuous_coverage(components: tuple[CatalogComponent, ...]) -> None:
    expected_priorities = {
        ComponentType.BASE: 100,
        ComponentType.SUPPLEMENT: 200,
        ComponentType.PREVIOUS_YEAR: 300,
        ComponentType.CURRENT_YEAR: 400,
    }
    assert all(
        component.priority == expected_priorities[component.type] for component in components
    )
    current_year = datetime.now(UTC).year
    current = tuple(
        component for component in components if component.type is ComponentType.CURRENT_YEAR
    )
    assert len(current) == 1
    assert current[0].from_year == current[0].to_year == current_year

    next_uncovered = 1950
    for component in sorted(components, key=lambda item: (item.from_year, item.to_year)):
        if component.to_year < next_uncovered:
            continue
        assert component.from_year <= next_uncovered
        next_uncovered = component.to_year + 1
        if next_uncovered > current_year:
            break
    assert next_uncovered > current_year


def _verify_network_distribution(
    distribution_root: str,
    download_root: Path,
) -> tuple[CatalogComponent, ...]:
    session = _UnauthenticatedSession()
    try:
        channel_path = download_root / "stable.json"
        _download(
            session,
            _stable_url(distribution_root),
            channel_path,
            maximum_bytes=_MAX_CHANNEL_BYTES,
        )
        channel = load_stable_channel(channel_path)
        assert channel.components
        for index, component in enumerate(channel.components):
            if component.package_bytes > _MAX_PACKAGE_BYTES:
                raise ValueError("catalog package exceeds its size limit")
            component_root = download_root / f"{index:02d}-{component.id}"
            manifest_path = component_root / component.manifest_asset
            package_path = component_root / component.package_name
            installed_path = component_root / component.installed_name
            _download(
                session,
                _release_url(component, component.manifest_asset),
                manifest_path,
                maximum_bytes=_MAX_MANIFEST_BYTES,
            )
            _verify_manifest(component, manifest_path)
            _download(
                session,
                _release_url(component, component.package_name),
                package_path,
                maximum_bytes=_MAX_PACKAGE_BYTES,
                expected_bytes=component.package_bytes,
            )
            if sha256_file(package_path) != component.package_sha256:
                raise ValueError("catalog package SHA-256 does not match the stable channel")
            _extract_component_package(package_path, installed_path, component)
            _verify_sqlite(component, installed_path)
        _verify_continuous_coverage(channel.components)
        return channel.components
    finally:
        session.close()


def _verify_distribution_if_configured(download_root: Path) -> tuple[CatalogComponent, ...]:
    distribution_root = os.environ.get(_DISTRIBUTION_ENV)
    if distribution_root is None:
        return _load_committed_distribution()
    return _verify_network_distribution(distribution_root, download_root)


def test_default_distribution_verification_is_offline_and_does_not_materialize_a2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CATALOG_DISTRIBUTION_ROOT", raising=False)
    before = _committed_distribution_state()

    def reject_network(*args: object, **kwargs: object) -> object:
        pytest.fail("default distribution verification attempted a network request")

    monkeypatch.setattr(requests.Session, "request", reject_network)

    assert _verify_distribution_if_configured(tmp_path) == _load_committed_distribution()
    assert _committed_distribution_state() == before


def test_sqlite_verification_rejects_an_unindexed_representative_lookup(tmp_path: Path) -> None:
    installed = tmp_path / "catalog.sqlite"
    with sqlite3.connect(installed) as connection:
        connection.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE works (
                qid INTEGER PRIMARY KEY,
                media_type INTEGER NOT NULL,
                release_year INTEGER NOT NULL,
                canonical_title TEXT NOT NULL
            );
            CREATE TABLE names (
                normalized_name TEXT NOT NULL,
                work_qid INTEGER NOT NULL,
                name_rank INTEGER NOT NULL
            );
            INSERT INTO meta VALUES ('catalog_schema', '1'), ('catalog_version', '2026.07.26');
            INSERT INTO works VALUES (1, 1, 2020, 'Example');
            INSERT INTO names VALUES ('example', 1, 0);
            """
        )
    component = CatalogComponent(
        id="base-test",
        type=ComponentType.BASE,
        from_year=2020,
        to_year=2020,
        version="2026.07.26",
        release_tag="base-test-2026.07.26",
        manifest_asset="manifest.json",
        package_name="catalog.zip",
        package_bytes=1,
        package_sha256="0" * 64,
        installed_name="catalog.sqlite",
        installed_bytes=installed.stat().st_size,
        installed_sha256=sha256_file(installed),
        catalog_schema=1,
        minimum_app_version="1.0.0",
        priority=100,
    )

    with pytest.raises(ValueError, match="name index"):
        _verify_sqlite(component, installed)


@pytest.mark.skipif(
    os.environ.get(_DISTRIBUTION_ENV) is None,
    reason=f"set {_DISTRIBUTION_ENV} to opt in to public release verification",
)
def test_opt_in_public_distribution(tmp_path: Path) -> None:
    components = _verify_distribution_if_configured(tmp_path)

    assert components
