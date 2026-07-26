PRAGMA page_size = 4096;
PRAGMA journal_mode = DELETE;
PRAGMA synchronous = NORMAL;
PRAGMA auto_vacuum = NONE;
PRAGMA user_version = 1;

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE target_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE target_stat1 (
    row_id INTEGER PRIMARY KEY CHECK (row_id > 0),
    table_name TEXT NOT NULL,
    index_name TEXT,
    statistics TEXT NOT NULL
);

CREATE TABLE upsert_works (
    qid INTEGER PRIMARY KEY,
    media_type INTEGER NOT NULL CHECK (media_type IN (1, 2)),
    release_year INTEGER NOT NULL CHECK (release_year BETWEEN 1800 AND 2200),
    canonical_title TEXT NOT NULL
);

CREATE TABLE upsert_names (
    normalized_name TEXT NOT NULL,
    work_qid INTEGER NOT NULL,
    name_rank INTEGER NOT NULL CHECK (name_rank BETWEEN 0 AND 3),
    PRIMARY KEY (normalized_name, work_qid),
    UNIQUE (work_qid, name_rank)
) WITHOUT ROWID;

CREATE TABLE delete_works (
    qid INTEGER PRIMARY KEY
);
