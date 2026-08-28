# track/data — Person A

You own `db/`, `clickhouse/`, `engine/`, `ingest/`, `api/`, `infra/data.compose.yml`,
`Makefile.data`, and this file. Nothing else. See `docs/OWNERSHIP.md`.

## First thing

```bash
make -f Makefile.data verify
```

That runs the engine tests and the contract check without needing a database.
Both should be green before you change anything.

## What is already true

**22 engine tests pass.** They are not decoration; each one locks down a finding
from `docs/REVIEW.md` that changes a number:

- the cap-gap strikethrough fires on the demo date, and there is a test showing the
  spec's one-year lookback would not have fired (A2)
- two concurrent 15-hour jobs is not unemployment, with a companion test showing how
  much the spec's per-episode test would have overcounted (A9)
- the unemployment count is bounded to the OPT authorization window (A10)
- 216 remaining, 243-day window, 183 days gained are three separate numbers (F3)
- a STEM OPT person does not get H-1B clocks and vice versa (B11)
- replay overrides rule params and produces a real diff for the same `as_of` (A1)
- a missing rule param raises instead of coercing to null (B5)
- `inputs_hash` does not move when only the calendar moves (B6)

## What is NOT verified

**None of the SQL has been executed.** No Postgres and no running Docker daemon were
available when this was written. The DDL in `db/` and `clickhouse/` is unrun. Expect
to fix something on the first `make migrate`.

Order of business:

```bash
make -f Makefile.data up
make -f Makefile.data migrate      # 0001..0006, in order
make -f Makefile.data seed         # param shapes MUST load before rules
make -f Makefile.data ch-ddl       # views before data. REVIEW A5.
```

The seed deliberately leaves every rule unverified, so the API returns
`verified: false` and the UI renders its warning band. Do not fill `verified_by`
without opening the primary source.

## Then, in order

1. **Wire `/v1/clocks` to the engine.** Load `UserState` from Postgres with the
   subject GUC set, resolve the `RuleSet`, call `engine.evaluate.evaluate()`. The
   fixtures in `api/main.py` exist only so Person B is not blocked; every stub
   response carries a `_warning` field saying it must not be demoed.
2. **`make -f Makefile.data ch-ddl` before loading anything.** A materialized view
   only sees inserts that arrive after it is created.
3. **`python -m ingest.headers <file>` before writing a loader.** Confirm whether
   `employer_fein` and `worksite_msa` exist at all. The design already assumes they
   may not (REVIEW C2, C3), but confirm rather than assume.
4. **`make -f Makefile.data quality` must pass** before any corpus query is trusted.
   Unknown wage units mean rows are excluded, never coerced.
5. **Measure the replay query.** `rows_scanned` and `elapsed_ms` are zero in the
   fixtures on purpose. Run it with and without the `by_clock` projection and put
   both timings on the architecture slide. One measured number beats three
   paragraphs of "runs in seconds in ClickHouse".
6. **Timebox PeerDB.** Decide the fallback before you start: batch copy, ClickHouse's
   native Postgres integration, or ClickHouse Cloud's Postgres CDC pipe. Losing three
   hours to a replication slot is the most likely way this project ends up
   incomplete (REVIEW C6).

## Your review findings

A1, A3-A10, B1-B7, C1-C7, D1, D3, and E2, E3, E4 on the primary sources.

B8, B9 and B10 need a joint decision with Person B before either of you builds:
the canonical clock list, whether the visa bulletin becomes a clock, and whether the
lottery statistic is a percentile or a wage level.

## Clocks not yet built

`h1b_grace_period`, `i485_portability`, `opt_filing_window`. They are listed in
`engine/clocks/ALL_CLOCK_KEYS` and appear in `NOT_YET_IMPLEMENTED`, so the engine
skips them without pretending. Add a module with `applies()` and `compute()` and
register it.
