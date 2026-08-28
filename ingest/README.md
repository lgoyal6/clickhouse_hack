# ingest/

The long pole. Read `docs/REVIEW.md` C1 through C7 before writing a loader.

## Why this is not one CREATE TABLE and a COPY

OFLC column schemas are **not stable across fiscal years**. Column names, column
counts, and file formats all move between years, including a substantial break
around FY2020, and several years ship as `.xlsx` rather than CSV. A single fixed
schema spanning FY2019 to FY2026 will not ingest cleanly.

So: a per-fiscal-year column map into one canonical target, then a single load path.

## Order of operations matters

A ClickHouse materialized view only sees inserts that arrive **after** it is
created. Load 8M rows first and `wage_baselines` is empty, the Standing screen shows
nothing, and the failure is silent. `load.py` enforces:

1. `clickhouse/ddl/010_corpus.sql`
2. `clickhouse/ddl/020_evaluations.sql`
3. `clickhouse/ddl/030_views.sql`   <- views exist BEFORE any data lands
4. load
5. `clickhouse/queries/data_quality.sql`  <- and it must pass

## Check these before writing any query that depends on them

```bash
make -f Makefile.data quality
```

- **`employer_fein`**: recent LCA and PERM disclosure files may not publish it at
  all. `employer_profiles` keys on a normalised employer name for exactly this
  reason. If FEIN turns out to be present and populated, add it back as a second
  key. Do not put a column that may not exist into a primary key. (REVIEW C2)
- **`wage_unit`**: must be a closed set. A surprise value means those rows are
  excluded, not silently annualised wrong. (REVIEW A8)
- **`worksite_msa`**: availability varies by year. State is the contract; MSA is
  optional enrichment. (REVIEW C3)

## Convert once

Convert each source file to Parquet on first read and load from Parquet after
that. Reloads during a hackathon happen more often than anyone plans for, and
`.xlsx` parsing is slow enough to hurt.
