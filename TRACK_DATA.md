# track/data — Person A

You own `db/`, `clickhouse/`, `engine/`, `ingest/`, `api/`, `infra/data.compose.yml`,
`Makefile.data`, and this file. Nothing else. See `docs/OWNERSHIP.md`.

## First thing

```bash
make -f Makefile.data deps up migrate seed ch-ddl
make -f Makefile.data verify     # 52 tests + the contract check
make -f Makefile.data demo       # both personas' clocks, computed, from the API
```

`demo` prints real output. If it prints `Días de desempleo remaining=16` and a
cap-gap card with `struck SEP 30 2026 delta=+183d`, the whole spine is working:
Postgres to engine to contract to API.

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

## What works end to end

`GET /v1/clocks` computes. It loads the person from Postgres inside a transaction
bound to the session subject, resolves the governing rule set, runs the engine,
fills `change_reason`, appends to the outbox, and serialises to the contract.

```
== sess_maria  as_of=2026-08-28  needs_attention=1
   [critical] Días de desempleo  remaining=16
        8 CFR 214.2(f)(10) | eff. 2008-04-08 | verified=False
   [clear   ] Periodo cap-gap  remaining=216
        struck SEP 30 2026  delta=+183d
        H-1B Modernization Final Rule | eff. 2025-01-17 | verified=False
   [not running] ac21_365       not in H-1B status; the six-year meter has not started
   [not running] h1b_max_stay   not in H-1B status; the six-year meter has not started
```

Verified against Postgres 17 and ClickHouse 26.7.5:

```
db/migrations/0001..0007     applied clean
db/seeds/010, 020, 030       13 rules, 2 supersession chains, 2 personas
clickhouse/ddl/010,020,030   4 materialized views created and populating
engine/tests                 28 passed   (no database)
api/tests                    24 passed   (real Postgres, real routes)
contracts/validate.py        contract green
```

**RLS is load-bearing, not decorative.** `api/repository.py` deliberately omits
`WHERE user_id` on every query. Migration 0007 adds an app role with
`NOBYPASSRLS`, because a superuser bypasses row security unconditionally and the
policies would exist and never fire. Tests assert that a transaction bound to Maria
sees exactly 3 status periods and 1 user, that naming Daniel's id explicitly returns
zero rows, and that passing `?user_id=` changes nothing.

**Ten constraint behaviours checked individually.** Cap-gap and a pending I-485 are
accepted overlapping the primary status; a second overlapping primary status, two
overlapping cap-gaps, a forked `supersedes` chain, overlapping rule windows,
`{"dayz":60}`, and superseding a different `rule_key` are all rejected.

**Three findings now carry numbers.** A pending PERM case stores **45,447** days
under the spec's `UInt16`. A `$150,000/hour` typo becomes **$312,000,000** in the
wage distribution under the spec's `multiIf`. On identical data the spec's replay
query returns **zero rows** where `replay_diff.sql` returns both affected users.

## What is still NOT verified

- **`/v1/claims/check` and `/v1/corpus/wage-percentile` are still fixtures.** Both
  carry a `_warning`. The wage one says outright that a fabricated percentile is the
  harm this product exists to prevent.
- **No real OFLC file has been loaded.** `ingest/load.py --dry-run` was tested
  against synthetic CSVs only, so `ingest/column_maps.py` is still guesses. Run
  `python -m ingest.headers` on a real file before trusting it.
- **`employer_fein` and `worksite_msa` were 100% missing** in the synthetic data,
  which proves the quality query works and says nothing about the real corpus.
- **The outbox is never drained.** Rows accumulate with `replicated_at IS NULL`;
  nothing carries them to ClickHouse yet.
- **PeerDB has not been attempted.**
- **No alerts are generated or delivered**, and `alert_templates` is empty.
- **Every rule is unverified against its primary source.** Deliberate, and the UI
  depends on it, but E2, E3 and E4 are yours to close.

## Then, in order

1. **Load two fiscal years of LCA data.** `python -m ingest.headers <file>` first,
   fix `column_maps.py`, then `--dry-run`, then load. `make -f Makefile.data quality`
   must pass before any corpus query is trusted.
2. **Wire `/v1/corpus/wage-percentile`** to `clickhouse/queries/wage_percentile.sql`.
   Exact scan, not interpolated from quantile states. Return `n_filings` always.
3. **Drain the outbox to ClickHouse.** Simplest working version first: a loop that
   selects `WHERE replicated_at IS NULL`, inserts into `clock_evaluations`, and
   stamps the rows. That is a real CDC path and it takes twenty minutes. PeerDB is
   an upgrade, not a prerequisite.
4. **Measure the replay query.** `rows_scanned` and `elapsed_ms` come back real from
   `/v1/scenarios/replay` now, but the population-scale query has never run on
   volume. Seed 50k synthetic users, run it with and without the `by_clock`
   projection, and put both timings on the architecture slide.
5. **Generate alerts** in the same transaction as the evaluations, using
   `template_key` plus params. Person B writes the reviewed Spanish.
6. **Timebox PeerDB.** Decide the fallback before starting: step 3 above already is
   one.

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
