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

## What has now been executed

The SQL is no longer unrun. Against Postgres 17 and ClickHouse 26.7.5 in
`infra/data.compose.yml`:

```
db/migrations/0001..0006      6/6 applied clean on first run
db/seeds/010, 020            applied; 13 rules, 2 supersession chains, all unverified
clickhouse/ddl/010, 020, 030 applied; 4 materialized views created
clickhouse/queries/*.sql     all execute
engine/tests                 24 passed
contracts/validate.py        contract green
```

Behaviour, not just syntax. Each of these was run and checked:

| Check | Result |
|---|---|
| STEM OPT primary period accepted | ok |
| CAP_GAP stacked on top, overlapping it | **accepted** |
| AOS_PENDING also stacked | **accepted** |
| A second overlapping primary status | rejected, 23P01 |
| Two overlapping CAP_GAP periods | rejected, 23P01 |
| CAP_GAP mislabelled as `layer='primary'` | rejected, check constraint |
| A forked `supersedes` chain | rejected, `one_successor_per_rule` |
| Overlapping rule effective windows | rejected, `no_overlapping_rule_windows` |
| `{"dayz":60}` instead of `{"days":60}` | rejected, param-shape trigger |
| Superseding a different `rule_key` | rejected, trigger |

Three findings, proven with numbers rather than argued:

- **A8, wage annualisation.** A row with unit `PER HOUR` annualises to NULL and is
  excluded; a `$150,000/hour` typo is flagged `wage_suspect` and excluded. Under the
  spec's `multiIf` the first would have entered the distribution as a $52 annual
  salary and the second as $312,000,000.
- **A7, `days_to_decision`.** A pending PERM case now yields NULL. The spec's
  `UInt16` column stores **45,447** for the same row.
- **A1, replay.** On identical data, the spec's `argMaxIf` query returns **zero
  rows** for the pending grace-period change, and `clickhouse/queries/replay_diff.sql`
  returns both users with `days_lost` of 60 and 41 and `newly_critical` set.

## What is still NOT verified

- **The API has never served a computed clock.** Every route in `api/main.py` returns
  a fixture with a `_warning` field. Nothing is wired to the engine or to Postgres.
- **RLS has never been exercised through the API.** The policies exist and apply, but
  no request has set the `status_clock.subject` GUC.
- **No real OFLC file has been loaded.** `ingest/load.py --dry-run` was tested against
  synthetic CSVs only. The column maps in `ingest/column_maps.py` are still guesses;
  run `python -m ingest.headers` on a real file first.
- **`employer_fein` and `worksite_msa` are 100% missing** in the synthetic data, which
  proves the quality query works and says nothing about the real corpus. Check it.
- **PeerDB has not been attempted.**
- **Every rule is unverified against its primary source.** That is deliberate and the
  UI depends on it, but E2, E3 and E4 are yours to close.

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
