# Codex Phase A1 Master Plan — Stable Catalog Distribution

## Authority

This document is the single authoritative execution plan for the current Codex task.
It replaces and overrides conflicting execution instructions in all earlier prompts, handoffs, and cross-repository plans.

Do not stop because an older document asks for real publication before merge. Real publication is Phase A2 and is explicitly outside this task.

## Repository and branch

- Repository: `gaato77/media-organizer-catalog`
- Required working branch: `codex/stable-channel-backfill`
- Pull-request base: `main`
- Never commit directly to `main`.
- Never merge the pull request.

## Goal of Phase A1

Implement, test, review, and submit all code required to distribute the catalog through durable GitHub Releases and a strict stable-channel contract.

Phase A1 ends with a green, unmerged pull request. It does **not** publish the real base, supplement, or current-year components.

## Root-cause resolution for workflow dispatch

A newly created `workflow_dispatch` workflow cannot be manually dispatched until its file exists on the repository default branch.
Therefore:

- During A1, create and test workflow definitions in this feature branch.
- Open the pull request and obtain green CI.
- Do not dispatch the new workflow from the feature branch.
- After a human reviews and merges the PR, Phase A2 executes workflows from `main` and verifies public assets.

This also applies to new publication inputs and behavior added to existing workflows. Real publication is deferred until the reviewed implementation exists on `main`.

## Existing contracts

- Python: `3.12`.
- Catalog SQLite schema: exactly `1`.
- Existing release manifest schema: exactly `1`.
- Public distribution origin: the public GitHub repository and GitHub Releases, without user authentication.
- Durable assets come from GitHub Releases, never temporary Actions artifacts.
- First Media Organizer integration uses complete ZIP packages; delta generation and application are out of scope.
- Stable-channel generation never hardcodes a permanent current year.
- Historical release tags are immutable after successful publication.
- A stable channel never references an unpublished or unvalidated release.

## Mandatory workflow safeguards

These requirements apply to every publishing workflow and are review-blocking:

1. **Shared publication lock**
   - Base, supplement, and current-year publication use the same repository-wide concurrency group: `stable-catalog-publication`.
   - `cancel-in-progress` is `false`.
   - This prevents two workflows from rebuilding and pushing `catalog/channel/stable.json` concurrently.

2. **Immutable historical releases**
   - Base and supplement workflows must not overwrite historical assets with `--clobber`.
   - When a historical tag does not exist, create it.
   - When it already exists, verify the existing asset names, sizes, and SHA-256 values against the newly validated package.
   - Continue idempotently only when the existing release is byte-for-byte equivalent; otherwise fail without changing the release or pointers.
   - Current-year publication may retain its existing same-version replacement behavior only if its pointer is regenerated from the final uploaded bytes.

3. **1950–2015 source-artifact preflight**
   - The recovery workflow exposes optional string input `source_run_id`, default `30157271026`.
   - Before downloading yearly artifacts, verify the referenced workflow run exists and contains all required `year-1950` through `year-2015` artifacts.
   - Fail with an actionable message before building or publishing when artifacts are missing or expired.
   - Never publish from a partial set and never generate a pointer from stale local output.
   - Phase A2 should be performed promptly after merge because source artifacts are not durable distribution assets.

4. **Workflow syntax validation**
   - Modify `.github/workflows/ci.yml` so PR CI validates every `.github/workflows/*.yml` file with `actionlint`.
   - Pin a concrete official actionlint version and checksum or immutable image digest; mutable `latest` references are prohibited.
   - Existing Python tests remain responsible for project-specific workflow ordering and contract assertions.

5. **Generated-file boundary**
   - Publishing workflows may commit only the intended generated pointer files, `catalog/current/latest.json` when applicable, and `catalog/channel/stable.json`.
   - They must fail when unrelated tracked changes are present before the generated commit.

6. **Release-before-pointer rule**
   - No component pointer or stable channel is written or committed until release creation/upload and verification succeed.
   - A failed release leaves all committed distribution pointers unchanged.

7. **Safe Git synchronization**
   - Every publishing workflow pulls/rebases immediately before the generated commit.
   - Shared concurrency is the primary race prevention; a non-fast-forward push must fail clearly rather than force-push.

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
- deterministic component order is priority descending, then `from_year`, `to_year`, and `id` ascending;
- JSON writes are atomic using temporary file, flush/fsync, and replace.

Priorities:

- base 1950–2015: `100`
- supplement 2016–2025: `200`
- current year: `400`

## Required implementation tasks

Use TDD for every task: failing test, minimal implementation, passing tests, focused commit, self-review, and independent task review.

### Task 1 — Stable-channel models

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

Tests cover exact fields, invalid and uppercase hashes, unsafe names, invalid years, boolean integers, duplicate IDs, overlap rules, deterministic ordering, UTC timestamp serialization, invalid schemas, and atomic-write cleanup.

Commit:

`feat: define stable catalog channel contract`

### Task 2 — Verified component pointers

Create:

- `builder/src/media_catalog_builder/component_pointer.py`
- `builder/scripts/write_component_pointer.py`
- `builder/tests/test_component_pointer.py`

Provide:

`build_component_pointer(release_dir, installed_database, *, component_id, component_type, from_year, to_year, release_tag, priority)`

It must:

- load the existing validated release manifest;
- require the declared full package;
- verify package size and SHA-256 against the manifest;
- require the installed SQLite;
- verify installed size against the manifest;
- compute installed SQLite SHA-256 directly;
- open SQLite read-only;
- require `PRAGMA integrity_check == ok`;
- require metadata schema and version to match the manifest;
- write the component atomically;
- expose an explicit CLI and nonzero validation failures.

Commit:

`feat: derive verified catalog component pointers`

### Task 3 — Stable-channel assembler

Create:

- `builder/scripts/assemble_stable_channel.py`
- `builder/tests/test_stable_channel_cli.py`

The CLI accepts repeated `--component`, `--output`, and optional `--published-at`.
It loads strict component files, rejects empty or invalid combinations, sorts deterministically, and writes atomically.

Commit:

`feat: assemble atomic stable catalog channel`

### Task 4 — Prepare durable 1950–2015 base publication

Modify:

- `.github/workflows/recover-1950-2015.yml`
- `.github/workflows/ci.yml`
- `builder/tests/test_distribution_workflows.py`

Implement:

- boolean `publish` input, default false;
- optional string `source_run_id`, default `30157271026`;
- source-run artifact preflight for every year 1950–2015;
- shared `stable-catalog-publication` concurrency for the publication path;
- publication only after complete package validation;
- immutable/idempotent historical release behavior for tag `base-1950-2015-2026.07.25`;
- pointer generation only after public release verification;
- stable-channel generation only from component pointers that actually exist;
- pull/rebase and generated-file boundary checks before commit;
- final failure conditions covering every requested publication stage;
- pinned actionlint validation in CI.

During A1, test statically and locally. Do not dispatch it and do not create fake `base.json` or `stable.json`.

Commit:

`ci: publish durable 1950-2015 base catalog`

### Task 5 — Prepare 2016–2025 supplement workflow

Create:

- `.github/workflows/build-historical-range.yml`

Modify:

- `builder/tests/test_distribution_workflows.py`

Dispatch inputs:

- `version`: required string matching `YYYY.MM.DD`;
- `publish`: required boolean, default false.

Workflow:

1. Matrix probes every year 2016–2025 using existing probe machinery.
2. Each year uploads `summary.json`, `movie.json`, and `series.json` as `year-<year>`.
3. Build waits for all ten years, downloads all artifacts, assembles the yearly tree, consolidates with the existing script, and builds/validates one release package.
4. Final SQLite verifies minimum 2016, maximum 2025, and ten distinct years.
5. Diagnostics and package artifacts are retained 14 days.
6. Publish runs only with `publish=true` after successful validation.
7. Publication uses shared `stable-catalog-publication` concurrency.
8. Historical release tag is `supplement-2016-2025-<version>` and follows immutable/idempotent rules.
9. During A2, generate priority-200 pointer, regenerate channel, verify generated-file boundary, pull/rebase, commit, and push.

During A1, do not dispatch or publish real assets.

Commit:

`ci: build and publish 2016-2025 catalog supplement`

### Task 6 — Integrate current-year pointer and stable channel

Modify:

- `.github/workflows/current-year-catalog.yml`
- `builder/tests/test_distribution_workflows.py`

Preserve `catalog/current/latest.json` during migration.
Publication uses the shared `stable-catalog-publication` concurrency group.

Required order after successful package creation:

1. release publication succeeds;
2. final uploaded release assets are verified;
3. existing latest pointer is updated from final bytes;
4. `catalog/components/current-year.json` is generated with dynamic ID `current-<year>`, selected-year range, and priority 400;
5. stable channel is regenerated from real component pointers;
6. generated-file boundary is verified;
7. latest/component/channel files are committed together after pull/rebase.

The year comes from workflow plan output, never a permanent literal `2026`.
No pointer changes are allowed when release publication or verification fails.

During A1, modify and test only. Do not force a real publication.

Commit:

`ci: publish current-year component to stable channel`

### Task 7 — Distribution tests and documentation

Create:

- `builder/tests/test_public_distribution.py`

Modify:

- `builder/tests/test_distribution_workflows.py`
- `README.md`

Default/offline PR mode, with `CATALOG_DISTRIBUTION_ROOT` unset:

- test models, fixtures, scripts, and committed files that actually exist;
- do not require real pointers or stable channel before A2;
- do not contact the network;
- do not create or accept fake pointers, hashes, or releases.

Opt-in network mode, with `CATALOG_DISTRIBUTION_ROOT` set:

- download stable JSON without authentication;
- download every declared package from GitHub Releases;
- verify bytes and package SHA-256;
- safely extract exactly one expected SQLite file;
- verify installed bytes and SHA-256;
- run integrity check and verify schema/version metadata;
- perform representative lookup per component;
- verify continuous coverage from 1950 through current-year component.

Workflow contract tests also assert:

- shared concurrency group across all publishing workflows;
- immutable historical behavior and absence of historical `--clobber`;
- source artifact preflight;
- release-before-pointer ordering;
- generated-file boundary;
- dynamic current year;
- actionlint present and pinned in CI.

README documents stable pointer, fields, priorities, URL construction, lifecycle, year rollover, unauthenticated download, integrity requirements, immutable historical releases, source-artifact preflight, and A2 publication procedure.

Commit:

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

Run the exact pinned actionlint command used by CI locally when the environment supports it. CI must run it regardless.

Verify:

- clean worktree and focused commits;
- no fake generated pointer or channel;
- no required network in default tests;
- no permanent current-year literal in generation;
- shared publication concurrency;
- immutable historical releases;
- complete source-artifact preflight;
- release-before-pointer ordering;
- safe JSON, paths, ZIP assumptions, and shell quoting;
- generated-file boundary;
- pull/rebase without force-push;
- no public distribution dependence on artifact retention.

Perform whole-branch independent review and address findings.
Push `codex/stable-channel-backfill` and open a PR to `main`. Do not merge it.

A1 completion:

- all tasks approved;
- all local checks pass;
- PR CI is green, including actionlint;
- PR explicitly lists A2 as post-merge work;
- no real publication is required.

Suggested PR title:

`Prepare stable catalog channel and complete historical coverage`

## Phase A2 — outside this Codex task

A2 starts only after human review and merge of A1 to `main`.

Order:

1. Immediately preflight the source run and 1950–2015 artifacts.
2. Dispatch durable base publication.
3. Verify base release and committed base-only channel.
4. Dispatch 2016–2025 publication.
5. Verify supplement release and contiguous 1950–2025 coverage.
6. Dispatch or verify current-year publication.
7. Verify final public channel, all assets, hashes, SQLite integrity, lookups, and contiguous coverage.

If the source artifacts are expired, stop A2 before publication and implement a separately reviewed regeneration path; never generate a pointer from incomplete data.

Codex must not perform A2, merge the PR, or directly commit to `main` now.

## SDD execution rules

- Use an isolated worktree.
- Maintain a persistent ledger naming this exact plan.
- Reuse a ledger only when its first line names `docs/codex/PHASE-A1-MASTER-PLAN.md`; otherwise initialize a fresh one.
- Use a fresh implementer per task.
- After each task, perform independent spec-compliance and code-quality review.
- Resolve findings before marking complete.
- Do not run conflicting implementation tasks in parallel.
- Commit after every approved task.
- Continue without user confirmation between tasks.
- Stop only for a genuine new blocker not resolved by this document or repository evidence.
- Blocker reports include exact command, output, path, branch, commit, investigation, and one required decision.

## Immediate instruction

Start or resume A1 at Task 1. Do not execute any real publication step. Do not stop because older plans require pre-merge publication; this document supersedes them.
