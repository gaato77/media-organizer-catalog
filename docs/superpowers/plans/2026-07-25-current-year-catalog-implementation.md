# Current-Year Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, validate, publish, and automatically refresh a partial current-year movie/series catalog beginning with 2026, without rebuilding the 1950–2015 historical source.

**Architecture:** Add a small current-year planning module that resolves elapsed months and refresh policy, then reuse the existing month probe, source consolidation, SQLite builder, release manifest, checksum, and delta machinery. A scheduled GitHub Actions workflow will rebuild only selected current-year months, validate the resulting package, publish durable release assets, and update a stable `catalog/current/latest.json` pointer only after success.

**Tech Stack:** Python 3.12, SQLite, pytest, Ruff, mypy, GitHub Actions, GitHub Releases.

## Global Constraints

- The production catalog version format remains exactly `YYYY.MM.DD`.
- Future months must never be queried or required.
- Daily mode refreshes the active month and the previous month.
- Weekly and full modes refresh all elapsed months.
- Failed runs must preserve diagnostics and must not update `catalog/current/latest.json`.
- The 1950–2015 workflow must never be invoked by this feature.
- Full packages are always produced; deltas are optional optimizations and retained for at most eight versions.
- Scheduled runs publish automatically; manual runs publish only when `publish=true`.

---

### Task 1: Resolve current-year windows and refresh policy

**Files:**
- Create: `builder/src/media_catalog_builder/current_year.py`
- Create: `builder/tests/test_current_year.py`

**Interfaces:**
- Produces: `RefreshMode`, `MonthWindow`, `CurrentYearPlan`, and `resolve_current_year_plan(...)`.

- [ ] **Step 1: Write failing tests**

```python
from datetime import UTC, datetime

from media_catalog_builder.current_year import RefreshMode, resolve_current_year_plan


def test_midyear_daily_plan_excludes_future_months() -> None:
    plan = resolve_current_year_plan(
        now=datetime(2026, 7, 25, 12, tzinfo=UTC),
        refresh_mode=RefreshMode.DAILY,
    )
    assert plan.year == 2026
    assert [window.month for window in plan.elapsed_months] == list(range(1, 8))
    assert [window.month for window in plan.refresh_months] == [6, 7]
    assert plan.elapsed_months[-1].complete is False


def test_january_daily_plan_refreshes_only_january() -> None:
    plan = resolve_current_year_plan(
        now=datetime(2027, 1, 3, 8, tzinfo=UTC),
        refresh_mode=RefreshMode.DAILY,
    )
    assert [window.month for window in plan.refresh_months] == [1]


def test_weekly_plan_refreshes_every_elapsed_month() -> None:
    plan = resolve_current_year_plan(
        now=datetime(2026, 4, 10, tzinfo=UTC),
        refresh_mode=RefreshMode.WEEKLY,
    )
    assert [window.month for window in plan.refresh_months] == [1, 2, 3, 4]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest builder/tests/test_current_year.py -q`
Expected: import failure because `current_year.py` does not exist.

- [ ] **Step 3: Implement the planner**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class RefreshMode(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class MonthWindow:
    year: int
    month: int
    start: datetime
    end: datetime
    complete: bool


@dataclass(frozen=True, slots=True)
class CurrentYearPlan:
    year: int
    through: datetime
    elapsed_months: tuple[MonthWindow, ...]
    refresh_months: tuple[MonthWindow, ...]
    refresh_mode: RefreshMode


def resolve_current_year_plan(
    *,
    now: datetime,
    refresh_mode: RefreshMode,
    year: int | None = None,
    through: datetime | None = None,
) -> CurrentYearPlan:
    ...
```

The implementation must normalize timestamps to UTC, reject a `through` value outside the selected year, create January through the active month only, mark the active month partial, and select `[previous, active]` for daily mode or all elapsed months for weekly/full mode.

- [ ] **Step 4: Run focused and full tests**

Run: `python -m pytest builder/tests/test_current_year.py -q`
Expected: PASS.

Run: `python -m pytest builder/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add builder/src/media_catalog_builder/current_year.py builder/tests/test_current_year.py
git commit -m "feat: resolve current-year refresh windows"
```

---

### Task 2: Probe and consolidate a partial year

**Files:**
- Modify: `builder/src/media_catalog_builder/year_probe.py`
- Modify: `builder/scripts/probe_wikidata_year.py`
- Modify: `builder/tests/test_year_probe.py`

**Interfaces:**
- Extend `run_year_probe(..., through: datetime | None = None, refresh_months: frozenset[int] | None = None)`.
- CLI adds `--through` and repeatable `--refresh-month`.

- [ ] **Step 1: Write failing tests**

```python
def test_partial_year_probe_queries_only_elapsed_months(tmp_path: Path) -> None:
    source = FakeYearSource()
    summary = run_year_probe(
        source,
        tmp_path,
        2026,
        limit=5000,
        through=datetime(2026, 3, 15, tzinfo=UTC),
    )
    assert source.downloads == 6
    assert summary["month_count"] == 3
    assert summary["through"] == "2026-03-15T00:00:00Z"
    assert summary["active_partial_month"] == "2026-03"


def test_partial_year_probe_rebuilds_only_selected_cached_months(tmp_path: Path) -> None:
    source = FakeYearSource()
    through = datetime(2026, 3, 15, tzinfo=UTC)
    run_year_probe(source, tmp_path, 2026, limit=5000, through=through)
    first_downloads = source.downloads
    (tmp_path / "summary.json").unlink()
    run_year_probe(
        source,
        tmp_path,
        2026,
        limit=5000,
        through=through,
        refresh_months=frozenset({2, 3}),
    )
    assert source.downloads == first_downloads + 4
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest builder/tests/test_year_probe.py -q`
Expected: `run_year_probe()` rejects the new keyword arguments.

- [ ] **Step 3: Implement partial intervals and selective refresh**

Add a helper that returns month windows clipped to `through`. Before calling `run_probe`, remove the selected month directory so that only requested refresh months are downloaded again. Completed unselected month caches remain reusable. The summary must include `through`, `complete_month_count`, and `active_partial_month`; full-year behavior must remain backward compatible with the existing 12-month tests.

- [ ] **Step 4: Extend CLI parsing**

Parse `--through` as an ISO-8601 UTC datetime and `--refresh-month` as integers 1–12, then pass them to `run_year_probe`.

- [ ] **Step 5: Run verification**

Run: `python -m pytest builder/tests/test_year_probe.py -q`
Expected: PASS.

Run: `python -m pytest builder/tests -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add builder/src/media_catalog_builder/year_probe.py builder/scripts/probe_wikidata_year.py builder/tests/test_year_probe.py
git commit -m "feat: support resumable partial-year probes"
```

---

### Task 3: Validate a current-year-only SQLite package

**Files:**
- Modify: `builder/src/media_catalog_builder/probe_release.py`
- Modify: `builder/src/media_catalog_builder/release.py`
- Modify: `builder/tests/test_probe_release.py`

**Interfaces:**
- Add optional `required_year: int | None = None` to `build_probe_release(...)` and `validate_release(...)`.

- [ ] **Step 1: Write failing regression test**

Create a fixture containing one 2026 record and one 2025 record. Call `build_probe_release(..., required_year=2026)` and assert it raises `ValueError("catalog contains records outside required year")`.

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest builder/tests/test_probe_release.py -q`
Expected: unexpected keyword argument `required_year`.

- [ ] **Step 3: Implement year validation**

After opening the final SQLite database, execute a count of rows whose `release_year` differs from `required_year`. Reject a nonzero count before package publication. Keep historical package calls unchanged when `required_year` is omitted.

- [ ] **Step 4: Run verification**

Run: `python -m pytest builder/tests/test_probe_release.py -q`
Expected: PASS.

Run: `python -m pytest builder/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add builder/src/media_catalog_builder/probe_release.py builder/src/media_catalog_builder/release.py builder/tests/test_probe_release.py
git commit -m "feat: validate current-year catalog boundaries"
```

---

### Task 4: Build publication metadata and preserve the previous release on failure

**Files:**
- Create: `builder/src/media_catalog_builder/current_release.py`
- Create: `builder/tests/test_current_release.py`
- Create: `catalog/current/latest.json`

**Interfaces:**
- Produce `LatestCatalog` with `year`, `version`, `published_at`, `release_tag`, `manifest_asset`, and `full_sha256`.
- Produce `write_latest_atomic(path, latest)`.

- [ ] **Step 1: Write failing tests**

Test JSON validation, atomic replacement, rejection of invalid versions, and confirm that a simulated publication exception leaves the prior `latest.json` byte-for-byte unchanged.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest builder/tests/test_current_release.py -q`
Expected: module import failure.

- [ ] **Step 3: Implement the metadata model and atomic writer**

Use the existing `YYYY.MM.DD` validation rules, write to a sibling `.tmp` file, `fsync`, and `os.replace` only after all fields are validated.

- [ ] **Step 4: Run verification**

Run: `python -m pytest builder/tests/test_current_release.py -q`
Expected: PASS.

Run: `python -m pytest builder/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add builder/src/media_catalog_builder/current_release.py builder/tests/test_current_release.py catalog/current/latest.json
git commit -m "feat: add stable current catalog pointer"
```

---

### Task 5: Add the scheduled/manual current-year workflow

**Files:**
- Create: `.github/workflows/current-year-catalog.yml`
- Create: `builder/tests/test_current_year_workflow.py`

**Interfaces:**
- Manual inputs: `year`, `through`, `refresh_mode`, `publish`.
- Scheduled daily and weekly runs.

- [ ] **Step 1: Write failing workflow contract test**

Assert that the workflow contains `workflow_dispatch`, two schedules, dynamic year resolution, `probe_wikidata_year.py`, diagnostics with `if: always()`, GitHub Release publication guarded by validation, and no reference to the 1950–2015 workflow.

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest builder/tests/test_current_year_workflow.py -q`
Expected: workflow file is missing.

- [ ] **Step 3: Implement workflow**

The workflow must:

1. Resolve the current UTC year and `through` date.
2. Restore month caches for the selected year.
3. Run the planner to determine elapsed and refresh months.
4. Probe only selected months and consolidate all elapsed months.
5. Build a versioned full package with `required_year=<year>`.
6. Download the previous successful current-year release when available and let existing release code retain efficient deltas.
7. Upload diagnostics on every run.
8. Publish release assets only after validation and only when scheduled or `publish=true`.
9. Update `catalog/current/latest.json` only after release upload succeeds.

Use `permissions: contents: write, actions: read`, concurrency protection, and explicit timeouts.

- [ ] **Step 4: Run all static verification**

Run: `python -m pytest builder/tests -q`
Expected: PASS.

Run: `python -m ruff check builder`
Expected: PASS.

Run: `python -m ruff format --check builder`
Expected: PASS.

Run: `python -m mypy builder/src/media_catalog_builder`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/current-year-catalog.yml builder/tests/test_current_year_workflow.py
git commit -m "feat: automate current-year catalog releases"
```

---

### Task 6: Initial 2026 build and production acceptance

**Files:**
- Update: `catalog/current/latest.json` only after successful publication.
- Update: implementation PR description with run and artifact links.

- [ ] **Step 1: Open implementation PR and wait for CI/CodeQL**

Expected: tests, Ruff, formatting, mypy, and CodeQL all green.

- [ ] **Step 2: Run diagnostic 2026 build**

Manual inputs: `year=2026`, `through=<next UTC day>`, `refresh_mode=full`, `publish=false`.

Expected: validated current-year SQLite, manifest, checksums, summary, skip audit, and diagnostics artifact.

- [ ] **Step 3: Inspect summary and package limits**

Verify all rows have release year 2026, both movie and series representative lookups pass, and package sizes are within configuration limits.

- [ ] **Step 4: Run production publication**

Manual inputs: same year/through, `refresh_mode=full`, `publish=true`.

Expected: durable GitHub Release, full SQLite ZIP, optional efficient delta, manifest, checksums, and updated `catalog/current/latest.json`.

- [ ] **Step 5: Verify app-facing pointer**

Fetch `catalog/current/latest.json`, follow its release tag and manifest asset, and verify the full asset checksum.

- [ ] **Step 6: Merge implementation PR**

Merge only after all acceptance criteria pass and the first 2026 release is available.
