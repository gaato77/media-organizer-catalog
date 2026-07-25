# Year-Sharded Historical Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic 2016–2025 probe with independently resumable annual jobs and a network-free consolidation job.

**Architecture:** GitHub Actions runs one matrix job per year with `max-parallel: 2`, stores each completed year as its own cache and artifact, then a dependent job downloads all shards, verifies completeness, consolidates by QID, and builds the existing compact release package. The historical workflow is manual only.

**Tech Stack:** Python 3.12, pytest, Ruff, mypy, SQLite, GitHub Actions cache/artifact actions.

## Global Constraints

- Work only on `feature/compact-catalog-builder`.
- Do not modify or merge `main`.
- Do not publish a GitHub Release.
- Do not automatically launch the full historical download from ordinary pushes.
- Limit Wikidata concurrency to two annual jobs.
- Preserve the single consolidated SQLite package for Media Organizer.

---

### Task 1: Add network-free annual-shard consolidation

**Files:**
- Modify: `builder/src/media_catalog_builder/multi_year_probe.py`
- Modify: `builder/tests/test_multi_year_probe.py`
- Create: `builder/scripts/consolidate_year_shards.py`

**Interfaces:**
- Consumes: completed annual directories containing `summary.json`, `movie.json`, and `series.json`.
- Produces: `consolidate_year_shards(output_dir: Path, start_year: int, end_year: int) -> dict[str, object]`.

- [ ] **Step 1: Write failing tests**

Add tests that create two completed annual shards directly, call `consolidate_year_shards`, and assert cross-year QID deduplication. Add a second test that omits one expected year and expects `ValueError("missing completed annual shard: YYYY")`.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest builder/tests/test_multi_year_probe.py -q`
Expected: import failure because `consolidate_year_shards` does not exist.

- [ ] **Step 3: Implement minimal consolidation**

Extract the annual-summary reading and `_consolidate_caches` loop from `run_multi_year_probe` into `consolidate_year_shards`. Require every annual directory and all three expected files. Keep summary schema 2 and deterministic year order.

- [ ] **Step 4: Add the CLI script**

Create `builder/scripts/consolidate_year_shards.py` with required `--output-dir`, `--start-year`, and `--end-year` arguments. It must print the resulting JSON summary and perform no network setup.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest builder/tests/test_multi_year_probe.py -q`
Expected: all focused tests pass.

---

### Task 2: Replace the monolithic workflow with annual matrix jobs

**Files:**
- Modify: `.github/workflows/probe-wikidata-decade.yml`
- Modify: `builder/tests/test_tooling.py`

**Interfaces:**
- Produces: yearly artifacts named `year-2016` through `year-2025` and a final `complete-2016-2025-catalog-probe` artifact.

- [ ] **Step 1: Write failing workflow assertions**

Require `workflow_dispatch`, reject `push:`, require `matrix.year`, the ten years, `max-parallel: 2`, `year-probe-${{ matrix.year }}-`, `actions/upload-artifact@v4`, `actions/download-artifact@v4`, `needs: shards`, and `consolidate_year_shards.py`. Reject `probe_wikidata_multi_year.py` in the workflow.

- [ ] **Step 2: Run tooling test to verify RED**

Run: `python -m pytest builder/tests/test_tooling.py::test_decade_probe_reuses_2025_and_packages_2016_through_2025 -q`
Expected: failure against the current monolithic workflow.

- [ ] **Step 3: Implement annual matrix workflow**

Create job `shards` with matrix years 2016–2025 and `max-parallel: 2`. Restore/save `year-probe-YYYY-*`, optionally restore `annual-2025-*` for the 2025 entry, run `probe_wikidata_year.py`, validate the annual files, and upload one artifact per year.

- [ ] **Step 4: Implement consolidation job**

Create job `consolidate` with `needs: shards`. Download yearly artifacts without merging them, move them to `multi-year-probe-output/years/YYYY`, call `consolidate_year_shards.py`, call `build_probe_release`, and upload the final review artifact. Do not commit generated result files from this manual workflow.

- [ ] **Step 5: Run tooling test**

Run: `python -m pytest builder/tests/test_tooling.py -q`
Expected: all tooling tests pass.

---

### Task 3: Verify the complete implementation

**Files:**
- No additional production files.

- [ ] **Step 1: Run complete tests**

Run: `python -m pytest builder/tests -q`
Expected: all tests pass.

- [ ] **Step 2: Run static validation**

Run:

```bash
python -m ruff check builder
python -m ruff format --check builder
python -m mypy builder/src/media_catalog_builder
python builder/scripts/smoke_lookup.py
```

Expected: all commands exit 0.

- [ ] **Step 3: Inspect branch isolation**

Compare `main` with `feature/compact-catalog-builder`; confirm `main` remains at its existing implementation-plan commit and no release was published.
