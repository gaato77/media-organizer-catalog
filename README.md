# Media Organizer catalog

This repository builds and publishes the catalog used by Media Organizer. Durable public
downloads are GitHub Release assets. GitHub Actions artifacts are temporary build inputs and
diagnostics; clients must never use them as a distribution source.

## Stable distribution contract

The application-facing pointer is
[`catalog/channel/stable.json`](catalog/channel/stable.json). After Phase A2 publishes the first
channel, it is available without authentication at:

```text
https://raw.githubusercontent.com/gaato77/media-organizer-catalog/main/catalog/channel/stable.json
```

The stable document has exactly four top-level fields:

- `schema_version`: stable-channel schema, currently `1`.
- `channel`: exactly `stable`.
- `published_at`: a UTC timestamp ending in `Z`.
- `components`: component pointers ordered by descending priority, then year range and ID.

Each component has exactly these fields:

- Identity and selection: `id`, `type`, `from_year`, `to_year`, and `priority`.
- Release identity: `version`, `release_tag`, `manifest_asset`, and `package_name`.
- Download integrity: `package_bytes` and `package_sha256`.
- Installed integrity: `installed_name`, `installed_bytes`, and `installed_sha256`.
- Compatibility: `catalog_schema` and `minimum_app_version`.

Component types are `base`, `supplement`, `previous-year`, and `current-year`. Higher priority
wins when different-priority year ranges overlap; equal-priority ranges may not overlap. The
reserved priorities are:

| Priority | Component | Lifecycle |
| ---: | --- | --- |
| 400 | `current-year` | Frequently refreshed active UTC year |
| 300 | `previous-year` | Completed former current year retained during rollover |
| 200 | `supplement` | Immutable historical supplement, initially 2016–2025 |
| 100 | `base` | Immutable historical base, initially 1950–2015 |

Construct release URLs from the pointer, encoding the tag and asset as individual URL path
segments:

```text
https://github.com/gaato77/media-organizer-catalog/releases/download/<release_tag>/<package_name>
https://github.com/gaato77/media-organizer-catalog/releases/download/<release_tag>/<manifest_asset>
```

No token, cookie, GitHub CLI login, or `Authorization` header is required for the stable pointer,
manifest, or package. A client must fail closed if any JSON has missing or unknown fields, if an
unsupported schema is declared, or if a download redirects away from HTTPS.

## Installation and integrity

The first application integration installs complete ZIP packages; delta installation is outside
this phase. For every selected component:

1. Reject a package whose byte count differs from `package_bytes` or whose SHA-256 differs from
   `package_sha256`.
2. Treat the ZIP as untrusted input. It must contain exactly one non-encrypted regular file whose
   name is exactly `installed_name`; do not accept directories, links, absolute paths, traversal,
   or extra entries.
3. After extraction, verify `installed_bytes` and `installed_sha256` against the exact SQLite
   bytes.
4. Open SQLite read-only, require `PRAGMA integrity_check` to return `ok`, and require both the
   `catalog_schema` and `catalog_version` metadata to match the component.
5. Enforce `minimum_app_version` before activation and perform a representative indexed lookup.

Install components in priority order. The union of selected component ranges must remain
continuous from 1950 through the active current-year component.

## Release lifecycle

The base workflow recovers 1950–2015 from 66 annual source artifacts. Its `source_run_id` input
defaults to `30157271026`; before downloading anything, the workflow verifies that the source run
completed successfully and contains exactly one unexpired `year-1950` through `year-2015`
artifact. Missing, duplicate, expired, or incomplete artifacts stop publication before a release
or pointer can change.

The supplement workflow builds 2016–2025 from ten annual shards. Base and supplement release tags
are immutable: a new tag is created once, while an existing tag is accepted only when every asset
name, size, and SHA-256 is byte-for-byte identical. Mismatches fail without clobbering the release
or historical pointers.

The current-year workflow publishes daily Monday–Saturday and performs a full weekly Sunday
refresh. Manual runs can request daily, weekly, or full refreshes. It resolves the active year
from UTC rather than embedding a permanent year, publishes and publicly verifies an immutable
versioned release, then updates the legacy `catalog/current/latest.json`, the priority-400 current
component, and the stable channel together.

Rollover promotion is **not automated in Phase A1**. The current workflow's empty `year` input
selects the new UTC year automatically, but by itself it replaces `current-year.json`; it does not
create a priority-300 pointer for the former year. Before the first scheduled publication of a new
UTC year, maintainers must land a separately reviewed procedure that retains the completed former
current-year release as a `previous-year` component (or incorporates it into a new immutable
supplement), regenerates the channel, and proves continuous coverage. Pause the scheduled publisher
until that procedure is complete. Do not add a permanent year literal as a rollover workaround.

All publication jobs share the job-scoped `stable-catalog-publication` lock and do not cancel an
in-progress publisher. They run only from the repository default branch with least privilege.
Release creation and unauthenticated byte verification finish before pointer generation. The job
then pulls with rebase, permits only its documented generated pointer/channel files, and performs
a normal non-forced push. A release, verification, generation, rebase, or push failure leaves
committed pointers unchanged.

## Verification modes

Normal development and pull-request tests are offline:

```powershell
Remove-Item Env:CATALOG_DISTRIBUTION_ROOT -ErrorAction SilentlyContinue
python -m pytest builder/tests/test_public_distribution.py -q
```

With the variable unset, tests load only models, local fixtures and scripts, the legacy latest
pointer, and component/channel files that really exist in the checkout. They do not contact the
network, require Phase A2 output, or create placeholder pointers, hashes, releases, or channel
files.

After publication, opt in to the end-to-end public verifier with either the repository raw root or
the full stable JSON URL:

```powershell
$env:CATALOG_DISTRIBUTION_ROOT = 'https://raw.githubusercontent.com/gaato77/media-organizer-catalog/main'
python -m pytest builder/tests/test_public_distribution.py -q
```

The opt-in test downloads the stable JSON and every declared manifest/package without
authentication, verifies exact package and installed hashes and sizes, extracts safely, validates
SQLite integrity/schema/version, performs a lookup for every component, and requires continuous
1950-through-current coverage.

## Phase A2: post-merge publication

Phase A1 only prepares and reviews the implementation. Do not dispatch the new publication flow
from a feature branch: `workflow_dispatch` definitions and inputs must first exist on the default
branch. After a human reviews and merges the green Phase A1 pull request to `main`, perform Phase
A2 promptly in this order:

1. Preflight the 1950–2015 source run immediately. If any source artifact has expired, stop and
   implement a separately reviewed regeneration path; never build from a partial set.
2. Dispatch `recover-1950-2015.yml` with `publish=true` and the reviewed `source_run_id`. Verify the
   durable base GitHub Release, committed base pointer, and base-only stable channel.
3. Dispatch `build-historical-range.yml` from `main` with a `YYYY.MM.DD` version and `publish=true`.
   Verify the durable supplement release and continuous 1950–2025 coverage.
4. Dispatch `current-year-catalog.yml` with empty `year` and `through`, `refresh_mode=full`, and
   `publish=true`, or verify an equivalent scheduled publication. Verify its durable release and
   the atomic latest/component/channel commit.
5. Run the opt-in public verifier above against `main` and confirm every public asset, hash,
   installed SQLite, metadata value, representative lookup, priority, and year range.

The GitHub Releases produced in A2 are the durable distribution. Actions artifacts remain only
short-lived build handoffs and diagnostics and must not appear in `stable.json` or client download
logic.
