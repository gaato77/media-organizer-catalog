# Codex Phase A1 Master Plan — Stable Catalog Distribution

## Authority

This document is the single authoritative execution plan for the current Codex task.
It replaces and overrides conflicting execution instructions in earlier prompts, handoffs, and the cross-repository plan.

Do not stop because an older document asks for real publication before merge. Real publication is Phase A2 and is explicitly outside this task.

## Repository and branch

- Repository: `gaato77/media-organizer-catalog`
- Required working branch: `codex/stable-channel-backfill`
- Base branch for the final pull request: `main`
- Never commit directly to `main`.
- Never merge the pull request.

## Goal of Phase A1

Implement, test, review, and submit all code required to distribute the catalog through durable GitHub Releases and a stable channel contract.

Phase A1 ends with a green pull request. It does **not** publish the real base, supplement, or current-year components.

## Root-cause resolution for workflow dispatch

A newly created `workflow_dispatch` workflow cannot be manually dispatched until its file exists on the repository default branch.
Therefore:

- During A1, create and test the workflow files in this feature branch.
- Open the pull request and obtain green CI.
- Do not dispatch the new workflow from the feature branch.
- After a human reviews and merges the PR, Phase A2 will execute the workflows from `main` and verify public assets.

This rule also applies to newly added dispatch inputs or publication behavior in existing workflows: real publication is deferred until the reviewed implementation exists on `main`.

## Existing contracts that must remain compatible

- Python: 3.12.
- Catalog SQLite schema: exactly `1`.
- Existing release manifest schema: exactly `1`.
- Public distribution origin: unauthenticated GitHub repository and GitHub Releases.
- Durable assets come from GitHub Releases, not temporary Actions artifacts.
- First Media Organizer integration uses complete ZIP packages; delta generation/application is out of scope.
- No permanent hardcoded current year in the stable-channel generation logic.
- Historical release tags are immutable after publication.
- A stable channel must never reference an unpublished or unvalidated release.

## Stable-channel component contract

Component types are exactly:

- `base`
- `supplement`
- `previous-year`
- `current-year`

Each component JSON contains exactly:

- `id`
- `type`
- `from_year`
- `to_year`
- `version`
- `release_tag`
- `manifest_asset`
- `package_name`
- `package_bytes`
- `package_sha256`
- `installed_name`
- `installed_bytes`
- `installed_sha256`
- `catalog_schema`
- `minimum_app_version`
- `priority`

The stable channel contains exactly:

- `schema_version`
- `channel`
- `published_at`
- `components`

Validation rules:

- stable schema version is `1`;
- channel name is `stable`;
- catalog schema is `1`;
- SHA-256 values are 64 lowercase hexadecimal characters;
- file names and release references are non-empty and path-safe;
- byte counts and priorities are positive integers, rejecting booleans;
- year ranges are within 1800–2200 and `from_year <= to_year`;
- component IDs are unique;
- equal-priority overlapping year ranges are rejected;
- different-priority overlaps are allowed and higher priority wins;
- deterministic component order: priority descending, then `from_year`, `to_year`, and `id` ascending;
- JSON writes are atomic using a temporary file, flush/fsync, and replace.

Priorities for this implementation:

- base 1950–2015: `100`
- supplement 2016–2025: `200`
- current year: `400`

## Required implementation tasks

Use TDD for every task: failing test, minimal implementation, passing tests, focused commit, self-review, independent task review.

### Task 1 — Stable channel models

Create:

- `builder/src/media_catalog_builder/channel.py`
- `builder/tests/test_channel.py`

Provide:

- `ComponentType`
- immutable `CatalogComponent`
- immutable `StableChannel`
- `load_component(path)`
- `write_component_atomic(path, component)`
- `load_stable_channel(path)`
- `write_stable_channel_atomic(path, channel)`

Tests cover exact fields, invalid/uppercase hashes, unsafe names, invalid years, boolean integers, duplicate IDs, overlap rules, deterministic ordering, UTC timestamp serialization, invalid schemas, and atomic-write cleanup.

Commit message:

`feat: define stable catalog channel contract`

### Task 2 — Verified component pointers

Create:

- `builder/src/media_catalog_builder/component_pointer.py`
- `builder/scripts/write_component_pointer.py`
- `builder/tests/test_component_pointer.py`

Provide:

`build_component_pointer(release_dir, installed_database, *, component_id, component_type, from_year, to_year, release_tag, priority)`

The implementation must:

- load the existing validated release manifest;
- require the declared full package to exist;
- verify package size and SHA-256 against the manifest;
- require the installed SQLite to exist;
- verify installed size against the manifest;
- compute installed SQLite SHA-256 directly;
- open SQLite read-only;
- require `PRAGMA integrity_check == ok`;
- require metadata schema/version to match the manifest;
- write the component atomically;
- expose a CLI with explicit arguments and nonzero exit on validation failure.

Commit message:

`feat: derive verified catalog component pointers`

### Task 3 — Stable channel assembler

Create:

- `builder/scripts/assemble_stable_channel.py`
- `builder/tests/test_stable_channel_cli.py`

The CLI accepts repeated `--component`, `--output`, and optional `--published-at`.
It loads strict component files, rejects an empty set and invalid combinations, sorts deterministically, and writes atomically.

Commit message:

`feat: assemble atomic stable catalog channel`

### Task 4 — Prepare durable 1950–2015 base publication

Modify:

- `.github/workflows/recover-1950-2015.yml`
- `builder/tests/test_distribution_workflows.py`

Implement workflow code for a boolean `publish` input defaulting to false and publication only after package validation succeeds.
When publication is enabled on `main` during A2, it must:

1. publish or update release tag `base-1950-2015-2026.07.25`;
2. upload the validated release directory plus diagnostics required by maintainers;
3. generate `catalog/components/base.json` only after release success;
4. regenerate `catalog/channel/stable.json` from component pointers that actually exist;
5. pull/rebase before committing generated pointer/channel files;
6. commit only generated pointer/channel files;
7. fail if any requested publication, pointer, channel, commit, or push step fails.

During A1, test this workflow statically and locally. Do not dispatch it and do not create fake `base.json` or `stable.json` files.

Commit message:

`ci: publish durable 1950-2015 base catalog`

### Task 5 — Prepare 2016–2025 supplement workflow

Create:

- `.github/workflows/build-historical-range.yml`

Modify:

- `builder/tests/test_distribution_workflows.py`

Required dispatch inputs:

- `version`: required string matching `YYYY.MM.DD`;
- `publish`: required boolean, default false.

Required workflow structure:

1. Matrix probe jobs for every year 2016 through 2025 using existing probe machinery.
2. Each year uploads `summary.json`, `movie.json`, and `series.json` as `year-<year>`.
3. Build waits for all ten years, downloads all artifacts, assembles the expected yearly tree, consolidates with the existing consolidation script, and builds/validates one release package.
4. Final SQLite explicitly verifies minimum year 2016, maximum year 2025, and ten distinct years.
5. Diagnostics and package artifacts are retained for 14 days.
6. Publish job runs only when `publish=true` and build validation succeeded.
7. During A2 on `main`, publish tag `supplement-2016-2025-<version>`, generate pointer with priority 200, regenerate stable channel, pull/rebase, commit generated files, and push.

During A1, do not dispatch this new workflow and do not publish real assets.

Commit message:

`ci: build and publish 2016-2025 catalog supplement`

### Task 6 — Integrate current-year pointer and stable channel

Modify:

- `.github/workflows/current-year-catalog.yml`
- `builder/tests/test_distribution_workflows.py`

Preserve the existing `catalog/current/latest.json` migration pointer.
After successful release publication, workflow order must be:

1. package validation succeeds;
2. release publication succeeds;
3. existing latest pointer is updated;
4. `catalog/components/current-year.json` is generated with dynamic ID `current-<year>`, selected year range, and priority 400;
5. stable channel is regenerated from real committed component pointers;
6. generated latest/component/channel files are committed together after pull/rebase.

The year comes from workflow plan output, never a permanent literal `2026`.
No pointer changes are allowed if release publication fails.

During A1, modify and test the workflow only. Do not force a real publication.

Commit message:

`ci: publish current-year component to stable channel`

### Task 7 — Distribution tests and documentation

Create:

- `builder/tests/test_public_distribution.py`

Modify:

- `builder/tests/test_distribution_workflows.py`
- `README.md`

Test modes:

1. Default/offline PR mode, with `CATALOG_DISTRIBUTION_ROOT` unset:
   - test models, local fixtures, scripts, and committed files that actually exist;
   - do not require real component pointers or stable channel before A2;
   - do not contact the network;
   - do not create or accept fake pointers/hashes/releases.

2. Opt-in network mode, with `CATALOG_DISTRIBUTION_ROOT` set:
   - download stable JSON without authentication;
   - download each declared release package from GitHub Releases;
   - verify exact bytes and package SHA-256;
   - safely extract exactly one expected SQLite file;
   - verify installed bytes and SHA-256;
   - run SQLite integrity check;
   - verify schema/version metadata;
   - perform representative lookup per component;
   - verify continuous year coverage from 1950 through the declared current-year component.

README documents the stable pointer, component fields, priorities, release URL construction, lifecycle, year rollover, unauthenticated download, hashes/integrity, immutable historical releases, and A2 maintainer publication procedure.

Commit message:

`test: verify stable catalog distribution contracts`

### Task 8 — Final A1 verification and pull request

Run from a clean worktree:

```bash
python -m pip install -e "builder[test]"
python -m pytest builder/tests -q
python -m ruff check builder
python -m ruff format --check builder
python -m mypy builder/src/media_catalog_builder
```

Also verify:

- clean working tree;
- focused task commits;
- no fake generated component pointer or stable channel;
- no required network access in default PR tests;
- no permanent current-year literal in contract generation;
- workflow publication steps occur only after validation/release success;
- no public distribution depends on Actions artifact retention;
- security of JSON fields, paths, ZIP extraction assumptions, and workflow shell quoting;
- generated pointer/channel commits are limited to intended files;
- workflow concurrency and pull/rebase behavior are safe.

Perform a whole-branch independent review and address findings.
Push `codex/stable-channel-backfill` and open a PR to `main`.
Do not merge it.

A1 completion criteria:

- all implementation tasks complete;
- all local checks pass;
- GitHub PR CI is green;
- PR describes what is implemented and explicitly lists A2 as post-merge work;
- no real publication is required yet.

Suggested PR title:

`Prepare stable catalog channel and complete historical coverage`

## Phase A2 — explicitly outside the current Codex task

A2 begins only after a human reviews and merges the A1 PR to `main`.
Then, from `main`:

1. dispatch the durable base workflow with publication enabled;
2. dispatch the historical-range workflow for 2016–2025 with publication enabled;
3. dispatch or verify current-year publication;
4. allow successful workflows to commit real component pointers and `catalog/channel/stable.json`;
5. run opt-in network verification;
6. record public release URLs, asset sizes, SHA-256 values, SQLite integrity, representative lookups, and continuous year coverage.

Codex must not perform A2, merge the PR, or directly commit to `main` in this task.

## SDD execution rules

- Use an isolated worktree for this plan.
- Maintain a persistent ledger identifying this exact master plan.
- Continue from the existing ledger only if it names this master plan; otherwise initialize a fresh ledger for this plan.
- Use a fresh implementer per task.
- After each task, run independent specification-compliance and code-quality review.
- Do not run conflicting implementation tasks in parallel within this repository.
- Commit after each approved task.
- Continue without asking the user between tasks.
- Stop only for a genuine new blocker that cannot be resolved from this document or repository evidence.
- A blocker report must include exact command, output, path, branch, commit, and the decision required.

## Immediate instruction

Start or resume Phase A1 at Task 1. Do not execute any real publication step. Do not stop because older plans require pre-merge publication; this document explicitly supersedes them.
