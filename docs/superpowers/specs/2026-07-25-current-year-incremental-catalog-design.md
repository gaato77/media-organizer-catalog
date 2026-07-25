# Current-Year Incremental Catalog Design

**Status:** Approved for planning  
**Date:** 2026-07-25  
**Repository:** `gaato77/media-organizer-catalog`

## Objective

Build and maintain a production-ready catalog for the current calendar year, beginning with a complete year-to-date 2026 catalog and continuing with automatic daily updates. The system must keep the newest movies and series available to the app without rebuilding the historical 1950–2015 source data.

The same workflow must roll over automatically to 2027 and later years.

## Scope

### Included

- Initial source build from January 1, 2026 through the current UTC day.
- Movies and series stored in the existing catalog schema.
- Partial-year support: only elapsed months and the active month are required.
- Daily scheduled updates plus manual execution.
- Resumable monthly shards so a failed month can be retried independently.
- Daily refresh of the active month and a rolling recent-month window.
- Periodic refresh of all elapsed months to capture late Wikidata additions and corrections.
- A validated full SQLite package for the current year.
- A delta package against the previous successful current-year release when the delta is smaller than the configured threshold.
- Durable publication through GitHub Releases, not only temporary Actions artifacts.
- A machine-readable pointer to the latest successful manifest for use by the app.
- Automatic year rollover without hard-coding 2026 in the implementation.

### Not included

- Re-querying or rebuilding the 1950–2015 catalog.
- Redesigning the SQLite schema.
- App-side catalog download or installation logic.
- A single combined 1950–current-year SQLite database. Combining the validated historical, 2016–2025, and current-year packages is a separate integration step.
- Real-time updates. The production target is daily freshness.

## Existing foundations

The repository already provides:

- A resumable annual Wikidata probe split into monthly work.
- Catalog normalization, deterministic source merging, SQLite construction, lookup validation, checksums, and package validation.
- Release manifests with full package assets and support for up to eight delta versions.
- Configuration for request retries, a 24-hour modified-window overlap, size limits, and delta retention.

The new work should reuse these components and generalize the annual workflow instead of creating a second independent catalog builder.

## Recommended architecture

### 1. Current-year source controller

Add a controller that resolves:

- `year`: the current UTC year unless explicitly supplied for a recovery run.
- `through`: the beginning of the next UTC day, so records available during the current day are included.
- `elapsed_months`: January through the active month.
- `refresh_mode`: `daily`, `weekly`, or `full`.

The controller must support a manual `year` and `through` input for deterministic recovery and testing.

### 2. Monthly source shards

The source build remains month-sharded.

Each shard contains:

- `movie.json`
- `series.json`
- `summary.json`
- query log and retry information
- explicit `window_start` and `window_end`
- whether the month is `complete` or `partial`

Shard policy:

- Completed old months are restored from cache/artifact during ordinary daily runs.
- The active month is always rebuilt.
- The previous month is rebuilt daily to catch late records around month boundaries.
- A weekly run rebuilds every elapsed month of the current year.
- A manual full refresh can rebuild every elapsed month at any time.
- Future months are never required and are not queried.

This strategy gives daily freshness while periodically correcting older 2026 data without querying historical decades.

### 3. Partial-year consolidation

Generalize consolidation so it accepts a partial range:

- start: January 1 of the selected year
- end: `through`
- required shards: only elapsed months

The consolidated summary must record:

- selected year
- `through` timestamp
- elapsed month count
- complete month count
- active partial month
- source rows, unique records, duplicates, query time, and cache sizes

A missing elapsed-month shard is a hard failure. A future-month shard is irrelevant.

### 4. Current-year SQLite package

Build a clean current-year SQLite database from the consolidated current-year sources using the existing catalog builder.

Validation must include:

- SQLite integrity check
- manifest and checksum validation
- representative movie and series lookups selected from the final SQLite database
- configured compressed and installed size limits
- catalog metadata matching the release version
- verification that all stored release years equal the selected current year

The catalog version remains the existing date format `YYYY.MM.DD`. Only one production version is published per UTC day. Re-running the same date is idempotent and replaces the draft assets before publication rather than creating a second catalog version.

### 5. Incremental release generation

For each successful production run:

1. Download the previous successful current-year release.
2. Build the new full current-year SQLite package.
3. Produce a SQLite delta from the previous version to the new version.
4. Include the delta only when it meets the existing efficiency threshold.
5. Retain a connected chain of at most eight supported delta versions.
6. Validate both full installation and every retained delta path before publication.

The full package is always available; the delta is an optimization, never the only recovery path.

### 6. Durable publication

Publish validated assets to a GitHub Release tagged with the catalog version. Assets include:

- `manifest.json`
- `checksums.sha256`
- `catalog-full-<version>.sqlite.zip`
- zero or more validated delta ZIP files
- source and release summaries
- skip audit

Temporary workflow artifacts remain available for diagnostics and recovery, but the app must consume durable release assets.

Maintain a small repository file, `catalog/current/latest.json`, containing:

- catalog year
- catalog version
- publication timestamp
- release tag
- manifest asset name
- full asset checksum

This file is updated only after the release has passed all validation and publication steps.

### 7. Workflow scheduling

Create one workflow with:

- `workflow_dispatch` inputs: `year`, `through`, `refresh_mode`, and `publish`
- daily schedule for `daily` refresh
- weekly schedule for `weekly` refresh
- concurrency protection so two production updates cannot publish simultaneously

Scheduled runs publish automatically. Manual runs default to diagnostic mode unless `publish=true` is explicitly selected.

### 8. Failure and recovery behavior

- Monthly outputs are saved even when another month fails.
- Consolidation and packaging run only after all required elapsed-month shards succeed.
- Diagnostics are uploaded with `if: always()`.
- Publication occurs only after complete validation.
- `latest.json` is never changed by a failed run.
- A failed scheduled run can be resumed using the existing monthly caches or artifacts.
- No failure in this workflow triggers the 1950–2015 historical workflow.

## Data flow

```text
Wikidata
  -> elapsed monthly shards for current year
  -> partial-year consolidation
  -> deterministic source records
  -> current-year catalog.sqlite
  -> full package + optional delta
  -> validation
  -> GitHub Release
  -> catalog/current/latest.json
  -> app update client (later integration)
```

## Testing strategy

### Unit tests

- Resolve elapsed months for dates in January, mid-year, and December.
- Exclude future months.
- Mark the active month partial.
- Select daily versus weekly refresh months.
- Validate current-year-only records.
- Generate lookup cases from the final SQLite database.
- Preserve a connected delta chain capped at eight versions.
- Keep `latest.json` unchanged when publication fails.

### Workflow contract tests

- Workflow has manual, daily, and weekly triggers.
- Current year is derived dynamically.
- No command invokes the 1950–2015 probe.
- Active and previous months are refreshed daily.
- All elapsed months are refreshed weekly.
- Diagnostics upload on failure.
- Release publication requires successful validation.

### Integration tests

- Build a partial-year fixture containing completed and active months.
- Rebuild with a newly added title and verify the full package contains it.
- Build a second version and apply its delta to the first version.
- Verify the delta result is byte-equivalent or logically equivalent to the new catalog according to the release validator.
- Simulate a failed release upload and confirm `latest.json` still references the prior release.

## Acceptance criteria

The feature is complete when:

1. A manual run produces a validated 2026 year-to-date catalog without querying future months.
2. The workflow can resume after a monthly failure without restarting successful months.
3. A second run containing a newly added movie or series produces an updated full package and a valid delta when efficient.
4. The validated assets are published durably in a GitHub Release.
5. `catalog/current/latest.json` points to the successful release.
6. Daily and weekly schedules are active.
7. CI, Ruff, formatting, mypy, CodeQL, and all new regression tests pass.
8. The historical 1950–2015 workflow is never invoked by this process.

## Implementation sequence

1. Generalize partial-year and refresh-window calculation.
2. Add current-year source orchestration and tests.
3. Add partial-year consolidation and validation.
4. Add full and delta release construction.
5. Add durable publication and `latest.json` update.
6. Add the scheduled/manual workflow.
7. Run the initial 2026 year-to-date build in diagnostic mode.
8. Review its summary and package sizes.
9. Publish the first validated 2026 release.
