# track/data — Person A

You own `db/`, `clickhouse/`, `engine/`, `ingest/`, `api/`, `infra/data.compose.yml`,
`Makefile.data`, and this file. Nothing else. See `docs/OWNERSHIP.md`.

## First thing

```bash
make -f Makefile.data deps up migrate seed ch-ddl
make -f Makefile.data corpus     # fetch + convert + load FY2024 and FY2025, then gate
make -f Makefile.data verify     # 70 tests + the contract check
make -f Makefile.data demo       # both personas' clocks, computed, from the API
```

`corpus` downloads roughly 155 MB from DOL and takes a few minutes. Everything else
is seconds.

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

**Clocks.** `GET /v1/clocks` computes. It loads the person from Postgres inside a
transaction bound to the session subject, resolves the governing rule set, runs the
engine, fills `change_reason`, appends to the outbox, and serialises to the contract.

```
== sess_maria  as_of=2026-08-28  needs_attention=1
   [critical] Días de desempleo  remaining=16
        8 CFR 214.2(f)(10) | eff. 2008-04-08 | verified=False
   [clear   ] Periodo cap-gap  remaining=216
        struck SEP 30 2026  delta=+183d
        H-1B Modernization Final Rule | eff. 2025-01-17 | verified=False
   [not running] ac21_365       not in H-1B status; the six-year meter has not started
```

**Corpus.** `GET /v1/corpus/wage-percentile` runs an exact scan over 239,477 real
rows of DOL OFLC LCA disclosure data in roughly 20 to 45 ms.

```
Software Developers  CA  $188,000  FY2025
   percentile 50.3  of n=5,991
   wage_level 3     next_level_wage $213,512
   bands: I=$135,699(n=465) II=$161,637(n=1,424) III=$187,574(n=1,125) IV=$213,512(n=1,020)
```

That divergence is finding B10 demonstrated: the same wage is **middling among peers**
and **Level III** by the OES measure. The response says in words that a percentile is
not a selection probability.

An uncovered occupation refuses rather than estimates. Home Health Aides have **one**
certified filing in the whole corpus, and that is the build spec's own demo persona.
See `docs/REVIEW.md` C8; it affects the demo script.

**Verified**, against Postgres 17 and ClickHouse 26.7.5:

```
db/migrations/0001..0007     applied clean
db/seeds/010, 020, 030       13 rules, 2 supersession chains, 2 personas
clickhouse/ddl/010,020,030   5 materialized views, all populating
corpus                       239,477 rows / 216,775 certified / FY2024 Q4 + FY2025 Q4
data_quality.sql             10 gates, all pass
engine/tests                 28 passed   (no database)
api/tests                    42 passed   (real Postgres, real ClickHouse, real routes)
contracts/validate.py        contract green
```

**RLS is load-bearing.** `api/repository.py` deliberately omits `WHERE user_id`
everywhere. Migration 0007 adds an app role with `NOBYPASSRLS`, because a superuser
bypasses row security unconditionally and the policies would exist and never fire.
Tests assert a transaction bound to Maria sees exactly 3 status periods and 1 user,
that naming Daniel's id explicitly returns zero rows, and that `?user_id=` changes
nothing.

**Silent-wrong bugs caught by running it, not reading it.** Each has a regression
test:

| What | Consequence if unfixed |
|---|---|
| `case_status = 'CERTIFIED'` (source says `Certified`) | every view empty, no error |
| SOC `15-1252.00` vs `15-1252` | percentile over 1% of the occupation |
| `{fy:UInt16} AS fiscal_year` shadowing the column | fiscal-year filter vanishes; both years summed |
| `PW_UNIT_OF_PAY` ignored | offered-vs-prevailing out by ~2,080x |
| 445,109 blank spreadsheet rows | distributions over mostly nothing |
| `days_to_decision UInt16` | pending PERM case reads 45,447 days |
| `$150k/hour` typo | $312,000,000 in the wage distribution |

## What is still NOT verified

- **`/v1/claims/check` is still a fixture.** It carries a `_warning`. Claim matching
  needs exact/alias lookup first and vector search for the tail (REVIEW C5).
- **The outbox is never drained.** Rows accumulate with `replicated_at IS NULL`;
  nothing carries them to `clock_evaluations` in ClickHouse yet.
- **The population replay has never run on volume.** `/v1/scenarios/replay` returns
  real `rows_scanned` and `elapsed_ms` for one person. Seed 50k synthetic users
  before putting a number on the architecture slide.
- **PeerDB has not been attempted.**
- **No alerts are generated or delivered**, and `alert_templates` is empty.
- **PERM and the Visa Bulletin are not loaded.** Both tables exist and are empty.
- **`soc_embeddings` is empty.** No embedding step has been run (REVIEW C5).
- **Only Q4 files are loaded**, one per fiscal year. They span the year by decision
  date, but they are not the full quarterly set.
- **Every rule is unverified against its primary source.** Deliberate, and the UI
  depends on it, but E2, E3 and E4 are yours to close.

## Then, in order

1. **Drain the outbox to ClickHouse.** A loop that selects `WHERE replicated_at IS
   NULL`, inserts into `clock_evaluations`, and stamps the rows. That is a real CDC
   path and it is maybe twenty minutes. PeerDB is an upgrade, not a prerequisite.
2. **Seed 50k synthetic users and measure the population replay.** Run
   `clickhouse/queries/replay_diff.sql` with and without the `by_clock` projection and
   put both timings on the architecture slide. One measured number beats three
   paragraphs of "runs in seconds in ClickHouse".
3. **Decide the Standing-screen persona with Person B.** The corpus cannot answer for
   a home health aide. Either demo an occupation it covers, or demo the honest
   refusal, which is a defensible and arguably stronger choice. What cannot happen is
   the §8 script as written.
4. **Generate alerts** in the same transaction as the evaluations, using
   `template_key` plus params. Person B writes the reviewed Spanish.
5. **Wire `/v1/claims/check`.** Exact and alias match first, vector search for the
   tail. It is the stale-advice beat and it is currently a fixture.
6. **Load PERM** if there is time. `perm_filings` exists and `days_to_decision` is
   already correct for pending cases.

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
