# Compact Media Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the public `gaato77/media-organizer-catalog` repository so it can generate, validate, package, and publish a compact movie/series catalog plus weekly differential updates for Media Organizer.

**Architecture:** A Python 3.12 builder obtains narrowly scoped, redistributable metadata from Wikidata, normalizes it into a deterministic SQLite catalog, compares it with the previous release, and publishes ZIP-compressed full and differential packages through GitHub Releases. The public latest-release manifest is the only endpoint Media Organizer needs; the client never processes Wikidata source data.

**Tech Stack:** Python 3.12, standard-library `sqlite3`, `requests`, `pytest`, SQLite 3, ZIP/Deflate, GitHub Actions, GitHub CLI.

## Global Constraints

- Repository contains catalog builder source, schemas, workflows, tests, and release metadata only.
- Media Organizer application source remains outside this repository.
- Catalog contains movies and series/miniseries only.
- Catalog stores canonical output title, release year, media type, compact Wikidata QID, and no more than four normalized recognition names per work.
- Canonical output title is the original Latin-script title; otherwise it is a source-provided Latin-script title used as the romanized/international form.
- Catalog excludes episodes, seasons, synopses, cast, crew, images, ratings, runtime, genres, and personal data.
- Full compressed package must be `<= 100 MiB`; target is `60–80 MiB`.
- Installed SQLite database must be `<= 250 MiB`.
- Weekly differential target is `<= 5 MiB`.
- Release assets contain data only and are verified with SHA-256.
- Public downloads require no GitHub token.
- Package format must be extractable on Windows PowerShell 5.1 with .NET ZIP support.
- Every source request uses a descriptive User-Agent, throttling, retry limits, and resumable shard caches.
- Tests, integrity validation, and size gates block publication on failure.

---

## Planned repository structure

```text
.github/workflows/
├── ci.yml
├── build-catalog.yml
└── update-catalog.yml
builder/
├── pyproject.toml
├── config/catalog.toml
├── src/media_catalog_builder/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── model.py
│   ├── normalize.py
│   ├── names.py
│   ├── classify.py
│   ├── http.py
│   ├── wikidata.py
│   ├── database.py
│   ├── delta.py
│   ├── package.py
│   ├── manifest.py
│   └── release.py
├── tests/
│   ├── fixtures/
│   ├── conftest.py
│   ├── test_cli.py
│   ├── test_normalize.py
│   ├── test_names.py
│   ├── test_classify.py
│   ├── test_http.py
│   ├── test_wikidata.py
│   ├── test_database.py
│   ├── test_delta.py
│   ├── test_package.py
│   ├── test_manifest.py
│   ├── test_release.py
│   └── test_workflows.py
└── scripts/
    ├── build_full.sh
    ├── build_update.sh
    └── smoke_lookup.py
schema/
├── catalog-schema-v1.sql
├── delta-schema-v1.sql
└── manifest-schema-v1.json
samples/
├── manifest.example.json
└── lookup-cases.json
README.md
LICENSE
.gitignore
```

SQLite is selected because exact normalized-name lookup is enough for Media Organizer, transactions make updates safe, and the schema avoids the duplicated text cost of FTS. ZIP is selected because Windows PowerShell 5.1 can extract it without another executable.

---

### Task 1: Initialize the Python package and CI

**Files:**
- Create: `builder/pyproject.toml`
- Create: `builder/src/media_catalog_builder/__init__.py`
- Create: `builder/src/media_catalog_builder/__main__.py`
- Create: `builder/src/media_catalog_builder/cli.py`
- Create: `builder/tests/test_cli.py`
- Create: `.github/workflows/ci.yml`
- Create: `.gitignore`

**Interfaces:**
- Produces: `media_catalog_builder.cli.main(argv: Sequence[str] | None = None) -> int`
- Commands: `build-full`, `build-update`, `validate`, `lookup`, `apply-delta`

- [ ] **Step 1: Write failing CLI tests**

```python
from media_catalog_builder.cli import main


def test_cli_requires_command(capsys):
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().err.lower()


def test_cli_rejects_unknown_command(capsys):
    assert main(["unknown"]) == 2
    assert "invalid choice" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Verify RED**

```bash
cd builder
python -m pytest tests/test_cli.py -q
```

Expected: import error because the package does not exist.

- [ ] **Step 3: Add package metadata and minimal CLI**

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "media-organizer-catalog-builder"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["requests>=2.32,<3"]

[project.optional-dependencies]
test = ["pytest>=8.3,<9"]

[project.scripts]
media-catalog-builder = "media_catalog_builder.cli:console_main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.pytest.ini_options]
testpaths = ["tests"]
```

```python
# builder/src/media_catalog_builder/cli.py
from __future__ import annotations

import argparse
from collections.abc import Sequence

COMMANDS = ("build-full", "build-update", "validate", "lookup", "apply-delta")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="media-catalog-builder")
    parser.add_argument("command", choices=COMMANDS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    return 0


def console_main() -> int:
    return main()
```

- [ ] **Step 4: Add CI and verify GREEN**

```yaml
name: CI
on: [push, pull_request]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: builder/pyproject.toml
      - run: python -m pip install -e "builder[test]"
      - run: python -m pytest builder/tests -q
```

Run: `python -m pytest builder/tests -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add .gitignore .github/workflows/ci.yml builder
git commit -m "build: initialize catalog builder and CI"
```

---

### Task 2: Define configuration and immutable records

**Files:**
- Create: `builder/config/catalog.toml`
- Create: `builder/src/media_catalog_builder/config.py`
- Create: `builder/src/media_catalog_builder/model.py`
- Create: `builder/tests/test_config.py`
- Create: `builder/tests/test_model.py`

**Interfaces:**
- Produces: `CatalogConfig.load(path: Path) -> CatalogConfig`
- Produces: `SourceRecord`, `CatalogRecord`, `MediaType`

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path
import pytest

from media_catalog_builder.config import CatalogConfig
from media_catalog_builder.model import CatalogRecord, MediaType


def test_config_preserves_hard_limits():
    path = Path(__file__).parents[1] / "config" / "catalog.toml"
    config = CatalogConfig.load(path)
    assert config.max_names_per_work == 4
    assert config.max_compressed_mib == 100
    assert config.max_installed_mib == 250


def test_record_rejects_five_names():
    with pytest.raises(ValueError, match="at most 4"):
        CatalogRecord(1, MediaType.MOVIE, 2000, "Example", ("a", "b", "c", "d", "e"))
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest builder/tests/test_config.py builder/tests/test_model.py -q`

- [ ] **Step 3: Add exact configuration**

```toml
schema_version = 1
manifest_schema_version = 1
bootstrap_start_year = 1870
future_years = 2
languages = ["en", "es"]
max_names_per_work = 4
max_compressed_mib = 100
max_installed_mib = 250
target_delta_mib = 5
request_timeout_seconds = 90
request_interval_seconds = 1.0
request_retries = 5
modified_window_overlap_hours = 24
supported_delta_versions = 8
user_agent = "MediaOrganizerCatalog/1.0 (https://github.com/gaato77/media-organizer-catalog)"
sparql_endpoint = "https://query.wikidata.org/sparql"
```

- [ ] **Step 4: Implement records and validation**

```python
from dataclasses import dataclass
from enum import IntEnum


class MediaType(IntEnum):
    MOVIE = 1
    SERIES = 2


@dataclass(frozen=True, slots=True)
class SourceRecord:
    qid: int
    media_type: MediaType
    year: int
    original_titles: tuple[str, ...]
    english_label: str | None
    spanish_label: str | None
    modified_at: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    qid: int
    media_type: MediaType
    year: int
    canonical_title: str
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.qid <= 0:
            raise ValueError("qid must be positive")
        if not 1800 <= self.year <= 2200:
            raise ValueError("year outside supported range")
        if not self.canonical_title.strip():
            raise ValueError("canonical title is required")
        if not 1 <= len(self.names) <= 4:
            raise ValueError("record must contain at most 4 names")
        if len(set(self.names)) != len(self.names):
            raise ValueError("record names must be unique")
```

`CatalogConfig.load()` must use `tomllib`, convert languages to a tuple, reject any configuration above the approved hard limits, and require schema version `1`.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest builder/tests/test_config.py builder/tests/test_model.py -q
git add builder/config builder/src/media_catalog_builder/config.py builder/src/media_catalog_builder/model.py builder/tests
git commit -m "feat: define catalog configuration and records"
```

---

### Task 3: Normalize names and choose canonical output

**Files:**
- Create: `builder/src/media_catalog_builder/normalize.py`
- Create: `builder/src/media_catalog_builder/names.py`
- Create: `builder/tests/test_normalize.py`
- Create: `builder/tests/test_names.py`

**Interfaces:**
- Produces: `normalize_lookup(value: str) -> str`
- Produces: `is_latin_output_candidate(value: str) -> bool`
- Produces: `to_catalog_record(source: SourceRecord) -> CatalogRecord | None`

- [ ] **Step 1: Write failing tests**

```python
from media_catalog_builder.normalize import normalize_lookup
from media_catalog_builder.model import MediaType, SourceRecord
from media_catalog_builder.names import to_catalog_record


def test_normalization_removes_accents_and_punctuation():
    assert normalize_lookup("Amélie: Le Fabuleux Destin") == "amelie le fabuleux destin"


def test_latin_original_is_canonical():
    result = to_catalog_record(SourceRecord(1, MediaType.MOVIE, 2001, ("Amélie",), "Amelie", "Amélie"))
    assert result.canonical_title == "Amélie"


def test_non_latin_original_uses_latin_source_label():
    result = to_catalog_record(SourceRecord(2, MediaType.MOVIE, 2001, ("千と千尋の神隠し",), "Sen to Chihiro no Kamikakushi", "El viaje de Chihiro"))
    assert result.canonical_title == "Sen to Chihiro no Kamikakushi"
    assert len(result.names) == 3
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest builder/tests/test_normalize.py builder/tests/test_names.py -q`

- [ ] **Step 3: Implement normalization**

```python
import re
import unicodedata

_SPACES = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize_lookup(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.strip().casefold())
    unmarked = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    separated = _NON_WORD.sub(" ", unmarked.replace("&", " and "))
    return _SPACES.sub(" ", separated).strip()


def is_latin_output_candidate(value: str) -> bool:
    letters = [ch for ch in value if ch.isalpha()]
    if not letters:
        return False
    return sum("LATIN" in unicodedata.name(ch, "") for ch in letters) / len(letters) >= 0.8
```

- [ ] **Step 4: Implement name selection**

`to_catalog_record()` must use this deterministic order:

1. first Latin-script original title;
2. English label when the original title is not Latin;
3. first other source-provided Latin title;
4. reject the record when no usable Latin output title exists.

Recognition names are canonical title, native original title, English label, and Spanish label, normalized and deduplicated in that order, stopping at four.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest builder/tests/test_normalize.py builder/tests/test_names.py -q
git add builder/src/media_catalog_builder/normalize.py builder/src/media_catalog_builder/names.py builder/tests
git commit -m "feat: normalize and select compact catalog names"
```

---

### Task 4: Read narrow, resumable Wikidata shards

**Files:**
- Create: `builder/src/media_catalog_builder/classify.py`
- Create: `builder/src/media_catalog_builder/http.py`
- Create: `builder/src/media_catalog_builder/wikidata.py`
- Create: `builder/tests/fixtures/*.json`
- Create: `builder/tests/test_classify.py`
- Create: `builder/tests/test_http.py`
- Create: `builder/tests/test_wikidata.py`

**Interfaces:**
- Produces: `binding_to_source(binding, media_type) -> SourceRecord | None`
- Produces: `RetryingHttpClient.get_json(url, params) -> dict`
- Produces: `WikidataSource.fetch_year(media_type, year) -> list[SourceRecord]`
- Produces: `WikidataSource.fetch_modified(media_type, start, end) -> list[SourceRecord]`

- [ ] **Step 1: Write failing parser, retry, and query tests**

Tests must prove:

- QID URI parsing returns the numeric QID;
- missing year is rejected;
- HTTP 503 is retried;
- HTTP 404 is not retried;
- year query requires IMDb ID `P345`, release date `P577`, and one approved media root;
- modified query uses a half-open UTC interval;
- completed shard JSON is reused without a network request.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest builder/tests/test_classify.py builder/tests/test_http.py builder/tests/test_wikidata.py -q`

- [ ] **Step 3: Implement strict source parsing**

`binding_to_source()` must require item URI and year, accept only years `1800..2200`, and map bindings into `SourceRecord`. It must never infer a title from a description.

- [ ] **Step 4: Implement throttled HTTP**

`RetryingHttpClient` must:

- set the configured User-Agent and SPARQL JSON Accept header;
- wait at least `request_interval_seconds` between calls;
- retry connection errors, timeouts, 429, 502, 503, and 504;
- fail immediately on other 4xx responses;
- use capped exponential backoff;
- stop after `request_retries` attempts.

- [ ] **Step 5: Implement year and modified-window queries**

Media roots:

```python
ROOTS = {
    MediaType.MOVIE: ("Q11424",),
    MediaType.SERIES: ("Q5398426", "Q1259759"),
}
```

Each query must require:

```sparql
?item wdt:P31/wdt:P279* ?root ;
      wdt:P345 ?imdbId ;
      wdt:P577 ?releaseDate .
OPTIONAL { ?item wdt:P1476 ?original . }
OPTIONAL { ?item rdfs:label ?enLabel FILTER(LANG(?enLabel) = "en") }
OPTIONAL { ?item rdfs:label ?esLabel FILTER(LANG(?esLabel) = "es") }
OPTIONAL { ?item schema:dateModified ?modified . }
```

Year shards add `FILTER(YEAR(?releaseDate) = YEAR)`. Modified shards add `start <= ?modified < end`. Cached payloads are written through a temporary file and atomically renamed.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest builder/tests/test_classify.py builder/tests/test_http.py builder/tests/test_wikidata.py -q
git add builder/src/media_catalog_builder builder/tests
git commit -m "feat: add resumable Wikidata source reader"
```

---

### Task 5: Build the compact SQLite catalog

**Files:**
- Create: `schema/catalog-schema-v1.sql`
- Create: `builder/src/media_catalog_builder/database.py`
- Create: `builder/src/media_catalog_builder/release.py`
- Create: `builder/tests/conftest.py`
- Create: `builder/tests/test_database.py`
- Create: `builder/tests/test_release.py`
- Create: `builder/scripts/smoke_lookup.py`

**Interfaces:**
- Produces: `CatalogDatabase.create/open/upsert/delete/lookup/finalize`
- Produces: `build_database_from_sources(records, output, version, now) -> BuildStats`

- [ ] **Step 1: Write failing database tests**

Tests must prove:

- upsert removes stale names;
- identical normalized names can map to different years;
- exact name/year/type lookup returns the canonical output title;
- source ordering does not change final database bytes on the same SQLite runtime;
- no work stores more than four names;
- `PRAGMA integrity_check` returns `ok`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest builder/tests/test_database.py builder/tests/test_release.py -q`

- [ ] **Step 3: Add schema**

```sql
PRAGMA page_size = 4096;
PRAGMA foreign_keys = ON;

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE works (
    qid INTEGER PRIMARY KEY,
    media_type INTEGER NOT NULL CHECK (media_type IN (1, 2)),
    release_year INTEGER NOT NULL CHECK (release_year BETWEEN 1800 AND 2200),
    canonical_title TEXT NOT NULL
);

CREATE TABLE names (
    normalized_name TEXT NOT NULL,
    work_qid INTEGER NOT NULL REFERENCES works(qid) ON DELETE CASCADE,
    name_rank INTEGER NOT NULL CHECK (name_rank BETWEEN 0 AND 3),
    PRIMARY KEY (normalized_name, work_qid)
) WITHOUT ROWID;

CREATE INDEX idx_names_work_qid ON names(work_qid);
```

- [ ] **Step 4: Implement transactional database operations**

`upsert()` must replace the work row, delete all prior names for that QID, and insert the complete current name set in one transaction. `lookup()` must filter by exact normalized name with optional year/type. `finalize()` must run `ANALYZE`, `PRAGMA optimize`, `VACUUM`, then integrity validation.

- [ ] **Step 5: Implement deterministic full build**

Group source rows by QID, merge original titles, choose the earliest valid release year, choose a deterministic media type and label order, convert through `to_catalog_record()`, insert QIDs in numeric order, and create a new database instead of mutating the prior full catalog.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest builder/tests/test_database.py builder/tests/test_release.py -q
python builder/scripts/smoke_lookup.py
sqlite3 build/sample.sqlite "PRAGMA integrity_check;"
git add schema/catalog-schema-v1.sql builder/src/media_catalog_builder builder/tests builder/scripts/smoke_lookup.py
git commit -m "feat: build compact SQLite catalog"
```

---

### Task 6: Generate and apply transactional deltas

**Files:**
- Create: `schema/delta-schema-v1.sql`
- Create: `builder/src/media_catalog_builder/delta.py`
- Create: `builder/tests/test_delta.py`

**Interfaces:**
- Produces: `create_delta(old_catalog, new_catalog, delta_path, from_version, to_version) -> DeltaStats`
- Produces: `apply_delta(base_catalog, delta_path, output_catalog) -> None`

- [ ] **Step 1: Write failing round-trip tests**

Tests must cover add, update, delete, unchanged catalog, wrong source version, corrupted delta, and interrupted application. Applying the generated delta must create a catalog with the same logical rows and final SHA-256 as the target full catalog on the same runtime.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest builder/tests/test_delta.py -q`

- [ ] **Step 3: Add delta schema**

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE upsert_works (
    qid INTEGER PRIMARY KEY,
    media_type INTEGER NOT NULL,
    release_year INTEGER NOT NULL,
    canonical_title TEXT NOT NULL
);
CREATE TABLE upsert_names (
    normalized_name TEXT NOT NULL,
    work_qid INTEGER NOT NULL,
    name_rank INTEGER NOT NULL,
    PRIMARY KEY (normalized_name, work_qid)
) WITHOUT ROWID;
CREATE TABLE delete_works (qid INTEGER PRIMARY KEY);
```

- [ ] **Step 4: Implement comparison and safe apply**

Changed works are emitted as complete replacements. Application must copy the active database to a temporary path, validate schema/from-version, attach the delta, apply deletes and replacements inside `BEGIN IMMEDIATE`, update metadata, commit, optimize, vacuum, run integrity check, then atomically activate the output. Any error leaves the input database untouched.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest builder/tests/test_delta.py -q
git add schema/delta-schema-v1.sql builder/src/media_catalog_builder/delta.py builder/tests/test_delta.py
git commit -m "feat: generate and apply catalog deltas"
```

---

### Task 7: Package assets and enforce size gates

**Files:**
- Create: `builder/src/media_catalog_builder/package.py`
- Create: `builder/tests/test_package.py`

**Interfaces:**
- Produces: `package_zip(source, destination, archive_name) -> PackageInfo`
- Produces: `sha256_file(path) -> str`
- Produces: `enforce_size(path, max_mib) -> None`

- [ ] **Step 1: Write failing tests**

Tests must prove ZIP bytes are deterministic, entry timestamps are fixed, SHA-256 is correct, full ZIP over 100 MiB is rejected, and installed DB over 250 MiB is rejected.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest builder/tests/test_package.py -q`

- [ ] **Step 3: Implement deterministic ZIP**

Use one ZIP entry, Deflate level 9, a fixed `1980-01-01 00:00:00` timestamp, fixed file permissions, and streamed SHA-256. A delta above 5 MiB is reported; it is omitted from the manifest when its ZIP is at least 80% of the full ZIP.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python -m pytest builder/tests/test_package.py -q
git add builder/src/media_catalog_builder/package.py builder/tests/test_package.py
git commit -m "feat: package and size-gate catalog releases"
```

---

### Task 8: Define the public manifest and release assembly

**Files:**
- Create: `schema/manifest-schema-v1.json`
- Create: `samples/manifest.example.json`
- Create: `samples/lookup-cases.json`
- Create: `builder/src/media_catalog_builder/manifest.py`
- Extend: `builder/src/media_catalog_builder/release.py`
- Create: `builder/tests/test_manifest.py`
- Create: `builder/tests/test_release_end_to_end.py`

**Interfaces:**
- Produces: `ReleaseManifest`, `Asset`, `DeltaPath`
- Produces: `choose_update_path(manifest, installed_version) -> tuple[Asset | DeltaPath, ...]`
- Produces: `assemble_release(...)` and `validate_release(directory)`
- Stable endpoint: `https://github.com/gaato77/media-organizer-catalog/releases/latest/download/manifest.json`

- [ ] **Step 1: Write failing manifest and release tests**

Tests must prove deterministic JSON, schema/version validation, maximum eight supported deltas, contiguous-chain selection, fallback to full when no chain exists, fallback to full when deltas reach 80% of full size, checksum validation, lookup smoke cases, and self-consistent release directory.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest builder/tests/test_manifest.py builder/tests/test_release_end_to_end.py -q`

- [ ] **Step 3: Add manifest contract**

Required fields:

```json
{
  "manifest_schema": 1,
  "catalog_schema": 1,
  "catalog_version": "2026.07.24",
  "published_at": "2026-07-24T12:00:00Z",
  "minimum_app_version": "2.0.0-beta.10",
  "full": {
    "name": "catalog-full-2026.07.24.sqlite.zip",
    "download_bytes": 1,
    "installed_bytes": 1,
    "sha256": "64 lowercase hex characters"
  },
  "deltas": []
}
```

- [ ] **Step 4: Implement release assembly**

Release assembly must package the full catalog, optionally package an efficient delta, retain at most eight contiguous delta descriptors, write sorted compact JSON, write `checksums.sha256`, validate every hash and SQLite file, run representative lookups, enforce all size limits, and rename the staging directory only after complete success.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest builder/tests/test_manifest.py builder/tests/test_release_end_to_end.py -q
python -m media_catalog_builder validate --release-dir dist/fixture-release
git add schema samples builder/src/media_catalog_builder builder/tests
git commit -m "feat: assemble validated catalog releases"
```

---

### Task 9: Implement full and weekly build commands

**Files:**
- Modify: `builder/src/media_catalog_builder/cli.py`
- Extend: `builder/src/media_catalog_builder/release.py`
- Create: `builder/scripts/build_full.sh`
- Create: `builder/scripts/build_update.sh`
- Extend: `builder/tests/test_release.py`

**Interfaces:**
- Full command creates a new authoritative catalog from year shards.
- Update command copies the latest valid catalog, queries modified UTC day windows with 24-hour overlap, applies idempotent QID upserts, creates a delta, and advances the watermark only after validation.
- Monthly full reconciliation is authoritative for removals.

- [ ] **Step 1: Write failing command tests**

Tests must prove argument validation, cached resume, 24-hour overlap, idempotent replay, invalid previous hash rejection, and no output activation on partial failure.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest builder/tests/test_cli.py builder/tests/test_release.py -q`

- [ ] **Step 3: Implement full command**

```bash
python -m media_catalog_builder build-full \
  --config builder/config/catalog.toml \
  --work-dir work/full-2026.07.24 \
  --output-dir dist/release-2026.07.24 \
  --version 2026.07.24
```

It must iterate `1870..current_year+2`, both media types, reuse completed shard JSON, build a new DB, compare with the previous release when supplied, and print one JSON summary.

- [ ] **Step 4: Implement weekly update command**

```bash
python -m media_catalog_builder build-update \
  --config builder/config/catalog.toml \
  --base dist/previous/catalog.sqlite \
  --previous-manifest dist/previous/manifest.json \
  --work-dir work/update-2026.07.24 \
  --output-dir dist/release-2026.07.24 \
  --version 2026.07.24 \
  --end 2026-07-24T12:00:00Z
```

Modified-window queries are split by UTC day and media type. A monthly full rebuild catches records that become irrelevant by losing all identifying statements.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest builder/tests -q
git add builder/src/media_catalog_builder builder/scripts builder/tests
git commit -m "feat: add full and weekly catalog builds"
```

---

### Task 10: Automate CI, monthly reconciliation, and weekly publication

**Files:**
- Create: `.github/workflows/build-catalog.yml`
- Create: `.github/workflows/update-catalog.yml`
- Create: `builder/tests/test_workflows.py`

**Interfaces:**
- Release tag: `catalog-YYYY.MM.DD`
- Full reconciliation: monthly plus manual trigger.
- Incremental publication: weekly Monday plus manual trigger.
- Publication uses GitHub CLI and `permissions: contents: write`.

- [ ] **Step 1: Write failing workflow assertions**

Require `workflow_dispatch`, schedules, `contents: write`, a shared concurrency group, Python 3.12, complete tests before build, validation before publication, and `gh release create`. Reject third-party release actions.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest builder/tests/test_workflows.py -q`

- [ ] **Step 3: Add monthly/manual workflow**

Workflow steps:

1. checkout;
2. setup Python 3.12;
3. install `builder[test]`;
4. run all tests;
5. calculate UTC version;
6. run `build_full.sh`;
7. validate release directory;
8. publish assets with `gh release create` only when `publish=true`.

Use `concurrency: catalog-publication`, `cancel-in-progress: false`, and `timeout-minutes: 330`.

- [ ] **Step 4: Add weekly/manual workflow**

Workflow steps:

1. perform the same test gate;
2. download the latest manifest and selected full catalog with `gh release download`;
3. verify hashes;
4. skip when a same-date full release already exists;
5. run `build_update.sh`;
6. validate;
7. publish with GitHub CLI.

- [ ] **Step 5: Run dry-run workflows**

Both workflows initially expose a `publish` boolean input defaulting to `false`. The dry run must upload the release directory as a workflow artifact and create no GitHub Release.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest builder/tests/test_workflows.py -q
python -m pytest builder/tests -q
git add .github/workflows builder/tests/test_workflows.py
git commit -m "ci: automate validated catalog releases"
```

---

### Task 11: Document and publish the first release

**Files:**
- Create: `README.md`
- Create: `builder/README.md`
- Create: `LICENSE`
- Create: `builder/tests/test_docs.py`

- [ ] **Step 1: Write failing documentation assertions**

Require documentation for repository scope, Wikidata/CC0 source, no IMDb-derived offline database, 100 MiB hard limit, anonymous latest-manifest endpoint, manual client updates, data-only assets, cache/resume behavior, and separate Media Organizer source.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest builder/tests/test_docs.py -q`

- [ ] **Step 3: Write exact maintainer commands**

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e "builder[test]"
python -m pytest builder/tests -q
builder/scripts/build_full.sh 2026.07.24
python -m media_catalog_builder validate --release-dir dist/release-2026.07.24
```

- [ ] **Step 4: Run real bootstrap in dry-run mode**

Acceptance evidence:

```text
Tests: 0 failures
SQLite integrity: ok
Catalog schema: 1
Manifest schema: 1
Maximum names per work: 4
Full ZIP: <= 100 MiB
Installed SQLite: <= 250 MiB
Representative lookups: pass
All SHA-256 values: match
Release validation: ok
```

When the full ZIP exceeds 100 MiB, do not raise the limit. Remove duplicate labels, omit names normalizing identically to another stored name, then tighten relevance while retaining the required IMDb ID, known year, and approved media class.

- [ ] **Step 5: Publish first release**

Rerun the full workflow with `publish=true`. Confirm these assets exist:

```text
catalog-full-YYYY.MM.DD.sqlite.zip
manifest.json
checksums.sha256
```

Confirm the latest-manifest endpoint returns HTTP 200 anonymously and every downloaded hash matches.

- [ ] **Step 6: Commit**

```bash
git add README.md builder/README.md LICENSE builder/tests/test_docs.py
git commit -m "docs: document catalog build and distribution"
```

---

## Final verification gate

```bash
python -m pip install -e "builder[test]"
python -m pytest builder/tests -q
python -m media_catalog_builder validate --release-dir dist/release-$(date -u +%Y.%m.%d)
```

Required before completion:

```text
- 0 test failures
- SQLite integrity = ok
- full compressed package <= 100 MiB
- installed catalog <= 250 MiB
- no work has more than four names
- no executable release assets
- all SHA-256 checks match
- delta application preserves the old catalog on failure
- delta result matches the target catalog
- anonymous latest manifest works
- dry-run monthly and weekly workflows succeed
```

## Follow-on plan boundary

After the first validated release exists, create a separate Media Organizer implementation plan. It will remove the IMDb builder flow, install/query the released catalog on Windows PowerShell 5.1, add `Descargar e instalar` and `Actualizar catálogo`, apply deltas to a temporary copy, activate atomically, and preserve the current preview and file-safety behavior.
