# Year-Sharded Historical Catalog Design

## Goal

Replace the monolithic 2016–2025 Wikidata probe with independently resumable yearly shards, bounded parallelism, and a separate consolidation stage that produces the same single release database consumed by Media Organizer.

## Architecture

The historical workflow has two jobs:

1. `shards`: a matrix with one entry per year from 2016 through 2025. Each entry restores only its own cache, runs the existing annual probe, validates the completed annual shard, saves its cache, and uploads a `year-YYYY` artifact.
2. `consolidate`: runs only after all yearly jobs succeed. It downloads every yearly artifact, verifies that all ten expected years are present, merges movie and series bindings by QID, builds the compact SQLite database, and validates ZIP, manifest, and checksums.

The matrix uses `max-parallel: 2` so Wikidata receives at most two yearly workloads concurrently. The workflow is manual (`workflow_dispatch`) and does not run automatically after ordinary code commits.

## Shard format

Each artifact contains:

```text
year-YYYY/
├── summary.json
├── movie.json
└── series.json
```

The files remain source-cache artifacts, not public application assets. The final application release remains:

```text
catalog-full-AAAA.MM.DD.sqlite.zip
manifest.json
checksums.sha256
```

## Reuse and recovery

- Every year has an independent cache key: `year-probe-YYYY-*`.
- A failed year can be rerun without repeating completed years.
- The 2025 matrix entry may seed itself from the existing `annual-2025-*` cache when a dedicated yearly cache does not yet exist.
- Candidate pages and detail batches remain resumable inside each year.
- A missing or malformed annual shard blocks consolidation with an explicit year-specific error.

## Consolidation interface

`consolidate_year_shards(output_dir: Path, start_year: int, end_year: int) -> dict[str, object]` reads only completed yearly shards from `output_dir / "years" / YYYY`. It performs no network requests. It writes consolidated `movie.json`, `series.json`, and `summary.json` using probe schema 2.

`run_multi_year_probe(...)` remains available for local or controlled sequential use, but delegates its final merge to `consolidate_year_shards`.

## Testing

- Unit tests prove inclusive year validation, missing-shard rejection, cross-year deduplication, and network-free consolidation.
- Tooling tests require a manual matrix workflow, `max-parallel: 2`, per-year cache keys, per-year artifacts, a dependent consolidation job, and no monolithic decade command in the workflow.
- Normal CI validates Python tests, Ruff, formatting, mypy, and SQLite smoke tests.

## Scope

This change does not publish a release, modify `main`, or launch the complete historical download automatically. It only installs and verifies the safer execution architecture.