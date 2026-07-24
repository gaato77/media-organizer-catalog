# Media Organizer Catalog — Design Specification

Date: 2026-07-24
Status: Approved for implementation planning
Repository: `gaato77/media-organizer-catalog`

## 1. Purpose

Provide Media Organizer with a compact, local catalog used only to identify movies and television series well enough to create consistent folder and file names.

The catalog is not an entertainment database. It must not contain descriptive or editorial information that is unnecessary for file organization.

## 2. User-facing goals

Media Organizer must be able to:

- identify whether a detected title is a movie or a series;
- recover the canonical original title;
- use an official romanized title when the original title uses a non-Latin writing system;
- recover the release year;
- recognize a limited number of useful alternate names;
- organize movies as `Original Title (Year)`;
- organize series as `Original Title (Year)\Season 01\S01E01.ext`;
- keep episode filenames limited to the season and episode code, without episode titles;
- install the catalog without locally processing millions of source records;
- update the catalog only when the user presses `Actualizar catálogo`.

## 3. Scope

### Included

- movies;
- television series and miniseries treated as series for organization purposes;
- original title;
- official romanized title when needed;
- release year;
- media type;
- up to four useful names per work;
- a stable compact internal identifier;
- full catalog packages;
- weekly differential packages;
- manifest and checksum validation;
- TVmaze fallback for unresolved series;
- manual review for unresolved or ambiguous cases.

### Excluded

- episodes and episode titles;
- seasons as catalog records;
- synopses;
- cast and crew;
- images and artwork;
- ratings and popularity scores;
- runtime;
- genres;
- release calendars;
- commercial metadata;
- user libraries or personal data;
- IMDb datasets or redistributed IMDb-derived offline databases.

## 4. Naming rules

### Movies

```text
Original Title (Year)
```

### Series

```text
Original Title (Year)
└── Season 01
    ├── S01E01.mkv
    ├── S01E02.mkv
    └── S01E03.spa.srt
```

### Non-Latin titles

When the original title uses a non-Latin writing system, use the official romanized title when available.

Example:

```text
Sen to Chihiro no Kamikakushi (2001)
```

The catalog may retain the native-script title as one of the limited recognition aliases, but the folder name uses the official romanized form.

## 5. Catalog size constraints

Catalog size is a primary design constraint.

- Target initial compressed download: 60–80 MB.
- Hard maximum initial compressed download: 100 MB.
- Target installed size: no more than 250 MB.
- Weekly differential packages should normally remain below 5 MB.
- A work may have at most four stored names.
- Near-duplicate names must be normalized and removed.
- No field may be added unless it directly improves identification or naming.

If the catalog cannot remain under the hard download limit, the builder must reduce aliases and irrelevant records before considering a larger package.

## 6. Record model

Each work contains only:

- compact internal ID;
- media type code: movie or series;
- release year;
- canonical output title;
- optional native-script original title;
- up to three additional recognition names, for a maximum of four total names;
- optional external stable source ID used by the builder, not required for normal application display.

The canonical output title is:

1. the original title when it uses Latin characters;
2. otherwise, the official romanized title.

## 7. Relevance filter

A record is included only when all required identification data is present:

- known media type;
- known release year;
- usable original or romanized title;
- stable source identifier;
- minimum relevance signal such as a recognized audiovisual database identifier, a Wikipedia/Wikidata presence with sufficient metadata, or another trusted source relationship.

The builder excludes:

- individual episodes;
- seasons;
- trailers;
- incomplete projects without usable release metadata;
- duplicated works;
- records with no usable title;
- records that cannot be confidently classified as movie or series;
- extremely obscure or malformed records that add disproportionate size without improving normal organization.

Excluded titles may still be resolved through the online fallback or manual review.

## 8. Source and publication architecture

### Source

The master catalog is built from redistributable structured sources, with Wikidata as the primary source. IMDb offline datasets are not redistributed.

### Repository

`gaato77/media-organizer-catalog` contains only:

- catalog builder source;
- schema and format documentation;
- manifest examples and validation rules;
- GitHub Actions workflows;
- catalog release metadata.

The Media Organizer application source remains outside this repository.

### GitHub Releases

Large generated files are published as release assets, not committed to the Git repository.

A release contains:

```text
catalog-full-YYYY-MM-DD.<archive>
catalog-delta-FROM-TO.<archive>
manifest.json
checksums.sha256
```

The exact archive format will be chosen during implementation by measuring real package sizes and Windows compatibility. The format must require no administrator privileges and must work on Windows PowerShell 5.1 systems supported by Media Organizer.

## 9. Manifest contract

The public manifest provides at least:

- catalog format version;
- current catalog data version;
- publication date;
- minimum compatible Media Organizer version;
- full package URL;
- full package compressed size;
- full package installed size;
- full package SHA-256;
- available differential paths;
- each differential package size and SHA-256;
- fallback rule when a differential chain is unavailable or too large.

Media Organizer reads this manifest anonymously over HTTPS. It does not require a GitHub account or token.

## 10. Installation flow

When a catalog-dependent action is requested and no catalog is installed:

1. Media Organizer fetches the public manifest.
2. It shows catalog version, download size and expected installed size.
3. The user presses `Descargar e instalar`.
4. The app downloads to a temporary file.
5. The app verifies SHA-256.
6. The app extracts or installs into a temporary catalog directory.
7. The app validates schema and basic integrity.
8. The app atomically activates the new catalog.
9. Temporary files are removed.

At no point does the client parse the original source datasets or build millions of records locally.

## 11. Manual update flow

The interface includes a button:

```text
Actualizar catálogo
```

When pressed:

1. fetch the current manifest;
2. compare installed and current versions;
3. show the available update and download size;
4. use a differential package when a valid efficient path exists;
5. otherwise download the latest full package;
6. verify all hashes;
7. apply the update to a temporary copy;
8. validate the updated catalog;
9. atomically replace the active catalog;
10. preserve the previous version until activation succeeds.

There are no automatic background updates in the first version.

## 12. Differential update policy

- A new catalog version is published weekly.
- Differentials contain additions, changes and removals required to transform one supported version into another.
- The builder may publish direct differentials only for a limited recent window.
- If the installed catalog is too old, if a delta is unavailable, or if the total delta chain is not meaningfully smaller than the full package, Media Organizer downloads the full package.
- Failed updates never damage or remove the last valid catalog.

## 13. Lookup flow inside Media Organizer

```text
Filename and folder parser
→ local compact catalog
→ TVmaze fallback for unresolved series
→ manual review
→ optional AI as final assistance only
```

The catalog returns candidate works using normalized title matching, optional year hints and media type hints. The app never executes a file move solely from a low-confidence ambiguous match.

## 14. Error handling

Media Organizer must handle:

- no internet connection;
- GitHub unavailable;
- manifest unavailable or malformed;
- insufficient disk space;
- download interruption;
- checksum mismatch;
- incompatible catalog format;
- failed extraction;
- invalid differential chain;
- catalog validation failure;
- locked files;
- user cancellation.

In every failure case:

- the current valid catalog remains usable;
- temporary files are cleaned when safe;
- the user sees a plain-language error;
- technical details are written to a log;
- retrying does not require rebuilding source data.

## 15. Security and privacy

- All downloads use HTTPS.
- Every package is verified with SHA-256 before activation.
- Release assets contain no executable code.
- The catalog contains no personal data or user library information.
- Media Organizer does not upload filenames or folder paths to GitHub.
- Public downloads require no credentials.

## 16. Builder responsibilities

The external builder must:

- retrieve redistributable source data;
- filter to movies and series;
- select the canonical title;
- romanize non-Latin titles using source-provided official romanization where available;
- select no more than four useful names;
- normalize and deduplicate names;
- remove irrelevant and incomplete records;
- produce the compact catalog;
- measure compressed and installed sizes;
- reject a release that exceeds the 100 MB compressed hard limit;
- compare against the previous catalog;
- produce differential packages;
- generate the manifest and checksums;
- run integrity and lookup tests before publishing.

## 17. Weekly automation

A GitHub Actions workflow runs weekly and may also be triggered manually.

Pipeline:

```text
Fetch sources
→ normalize and filter
→ build compact catalog
→ run tests
→ enforce size limits
→ compare with previous version
→ generate full and differential packages
→ calculate checksums
→ publish GitHub Release
→ update public manifest
```

A failed validation or size check prevents publication.

## 18. Testing requirements

### Builder tests

- title normalization;
- romanized output selection;
- alias limit enforcement;
- duplicate removal;
- movie/series classification;
- relevance filtering;
- deterministic builds from the same input;
- schema validation;
- full package integrity;
- differential apply and rollback;
- hard size-limit enforcement.

### Media Organizer integration tests

- install without an existing catalog;
- install cancellation;
- checksum failure;
- interrupted download;
- update when current;
- differential update;
- fallback to full update;
- rollback after failed update;
- lookup of original, romanized, English and Spanish names;
- ambiguous title handling;
- preservation of existing file safety rules.

## 19. Acceptance criteria

The first implementation is accepted when:

1. the compressed full catalog is 100 MB or less;
2. catalog installation requires no source-data processing on the user's computer;
3. a clean Windows PowerShell 5.1 environment can install it through Media Organizer;
4. the user can manually check and apply an update;
5. an update failure preserves the previous valid catalog;
6. movies are organized as `Original Title (Year)`;
7. series are organized as `Original Title (Year)\Season NN\SxxEyy.ext`;
8. non-Latin works use an official romanized output title when available;
9. no work stores more than four names;
10. the catalog contains none of the explicitly excluded metadata;
11. GitHub Releases provide anonymous public downloads without tokens;
12. the Media Organizer repository and application source remain separate from this catalog repository.

## 20. Implementation boundary

This specification defines the approved architecture and behavior. It does not yet select the final on-disk engine, compression format or exact binary schema. Those choices must be made in the implementation plan through measured prototypes, while respecting Windows PowerShell 5.1 compatibility and the hard 100 MB compressed catalog limit.
