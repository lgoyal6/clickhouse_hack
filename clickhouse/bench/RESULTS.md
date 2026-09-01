# Benchmark: the queries the architecture argument rests on

Measured, not asserted. Every figure below came from `system.query_log` and `\timing`
on this machine, and `run_benchmark.py` reproduces it.

**What is real and what is not.** `lca_filings` and `perm_filings` hold 1,396,903 rows
of actual DOL OFLC disclosure data. `clock_evaluations` holds **synthetic** evaluations
at the scale `docs/BUILD_SPEC.md` §2.2 claims: 50,000 users × 7 clocks × 365 days =
127,750,000 rows. §9 of the spec is explicit that the corpus is real and the user base
is not. Every number here is a performance number, never a product number.

Hardware: Apple Silicon laptop, Docker Desktop, ClickHouse 26.7.5 and Postgres 17 in
containers, sharing the machine. Absolute timings are laptop-noisy; **rows read is
deterministic and identical across every run**, so where the two disagree, trust rows.

---

## Storage

| | rows | on disk | per row |
|---|---|---|---|
| ClickHouse `clock_evaluations` | 127,750,000 | 3.68 GiB | ~31 B |
| Postgres `bench_evaluations` | 12,780,000 | 1,731 MB | ~142 B |

10.48 GiB uncompressed → 3.68 GiB on disk, **20.6× compression**, on a table that is
mostly `LowCardinality` strings and small integers.

Extrapolated, the same 127.75M rows in Postgres would be roughly **17 GB** against
ClickHouse's 3.68 GB. That is the difference between "keep every evaluation forever"
being a design choice and being a budget line.

---

## 1. The marquee query: rule-change replay across the population

*Who loses days if the H-1B 60-day grace period is eliminated?*
`clickhouse/queries/replay_diff.sql`, 50,000 users out.

| | rows read | of total | time |
|---|---|---|---|
| **projection ON** | **107,344** | 0.08% | 98–760 ms |
| projection OFF | 6,688,736 | 5.2% | 133–645 ms |

The `by_clock` projection cuts rows read **62×**. It does not reliably cut wall time at
this scale, because 6.7M rows is already inside what this machine does in ~100 ms; the
projection is what stops that number growing with the table.

Both configurations return the same 50,000 rows. The table holds 127.75M and the query
touches 107 thousand of them, because `ORDER BY (clock_key, scenario_id, as_of, user_id)`
means the answer is contiguous on disk. That is the entire argument for the ordering,
in one number.

**The spec's version of this query returns zero rows.** Its `argMaxIf` reads history
back, and no history exists under a rule that has not taken effect. Verified on
identical data. See `docs/REVIEW.md` A1.

## 2. One person's history

*What the Timeline screen reads: every clock, every day, for one user.*

548,864 rows read → 2,555 rows out, 126–198 ms.

Reads more than the population query does, because this table is ordered for the
population query. Both access paths are wanted, which is why the projection exists.

## 3. Population risk over time

*365-day severity series for one clock.*

| | rows read | time |
|---|---|---|
| direct from `clock_evaluations` | 18,576,755 | 1,278–2,143 ms |
| from the `risk_rollup` view | 9,855 | 1,789–2,527 ms |

**The rollup reads 1,884× fewer rows and is not faster.** Worth stating plainly rather
than quietly dropping: at this scale the cost is in `uniqMerge` over aggregate states,
not in I/O, so precomputation buys nothing yet. It will matter at 10× the users, and it
is what keeps the query cost flat as history grows. Right now it is insurance, not a
speedup, and claiming otherwise on a slide would be the kind of thing this project is
supposed to be against.

## 4. Full-history scan, no filter

*Every severity transition for every user and clock: `lagInFrame` over the whole table.*

127,750,000 rows read, 2,558 MB, **12.3–14.3 s**.

This is the honest worst case: no filter, no index help, a window function over the
entire corpus. It is the shape of "show me the day everyone's risk moved."

---

## The index decision, and the one that did not work

`clickhouse/queries/replay_diff.sql` has said "run `EXPLAIN indexes = 1`" since
it was written, and nothing above did. Rows read is the outcome; the plan is
the reason, and without it the ordering argument is a preference with a number
next to it.

Four arms over the same 127.75M rows, same query (one clock, one scenario, one
day), everything merged to steady state first. `clickhouse/bench/index_arms.sh`
reproduces it, `index_arms.sql` builds the comparison table.

| arm | index available | rows read | bytes read | time |
|---|---|---|---|---|
| C | nothing | 127,800,336 | 1.19 GiB | 282 ms |
| B | minmax skip index on `as_of` | 127,800,336 | 1.19 GiB | 270 ms |
| A | `PARTITION BY toYYYYMM(as_of)` | 9,850,336 | 94 MiB | 22 ms |
| A+ | partition + the `by_clock` projection | 55,264 | 540 KiB | 8 ms |

**B is the point of the table.** A minmax index on `as_of` is the obvious
alternative to partitioning, it reads every one of the 127.8M rows, and it is
not faster. The plan says why in one line:

```
Skip
  Name: as_of_mm
  Description: minmax GRANULARITY 1
  Parts: 1/1
  Granules: 15610/15610
```

Nothing pruned. A min/max index can only skip a granule whose values are
*bounded*, and `ORDER BY (user_id, clock_key, scenario_id, as_of)` puts a
random UUID first, so every granule holds an almost full year of `as_of` and
no granule can be excluded. The index is not broken; it is being asked about a
column the data is not clustered by.

A partition key works on the same column because it does not depend on
clustering at all: it physically separates the rows into 13 monthly parts
before any ordering question arises.

```
Min-Max     Parts: 1/13   Granules: 1207/15640
Partition   Parts: 1/1    Granules: 1207/1207
PrimaryKey  Parts: 1/1    Granules: 1207/1207   Search Algorithm: generic exclusion search
```

Read the third line. **On the base table the primary key prunes nothing.** All
13x of arm A comes from the partition key, and the ordering contributes zero
to this query, because `user_id` leads it and the query does not filter on
`user_id`. "generic exclusion search" rather than "binary search" is
ClickHouse saying exactly that.

The projection is what makes the ordering pay:

```
ReadFromMergeTree (by_clock)   PrimaryKey   Granules: 7/1210   binary search
```

### What the projection costs

| | on disk | parts |
|---|---|---|
| base table, partitioned | 266 MiB | 13 |
| the same rows, unpartitioned (`ce_skipidx`) | 187 MiB | 1 |
| `by_clock` projection | **3.16 GiB** | 13 |

A projection is not an index. It is a second copy of the table sorted
differently, and re-sorting decides what compresses. Per column:

| column | base | inside `by_clock` |
|---|---|---|
| `inputs_hash` | 25.55 MiB | **1.92 GiB** |
| `user_id` | 13.08 MiB | 488.58 MiB |
| `days_consumed` | 78.67 MiB | 353.75 MiB |
| `rule_id` | 32.41 MiB | 8.40 MiB |

`inputs_hash` and `user_id` are constant per user, so ordering by `user_id`
puts identical values next to each other and they nearly vanish. Ordering by
`clock_key` interleaves them across all 50,000 users and they become
incompressible. `rule_id` moves the other way, because it correlates with
`clock_key`.

So the honest statement of the ordering argument is: the projection buys 178x
fewer rows on the population query and costs roughly twelve times the base
table on disk. At this size that is 3 GiB and obviously worth it. It is worth
knowing which way it scales before it is 300.

**And the partition key is not free either:** 266 MiB across 13 parts against
187 MiB in one, about 43% more, because thirteen smaller parts compress worse
than one large one.

### A methodology note that changed a number

Both tables are merged with `OPTIMIZE ... FINAL` before anything is read.
Before merging, arm A read 987,694 rows; after merging it reads 9,850,336. The
day being queried happened to sit in two small parts, and since the primary
key cannot prune inside a part, a bigger part means more of the month gets
scanned. The pre-merge figure was an artifact of insert order. The post-merge
one is what the table costs.

The first run of the arms also reported B at 506 ms against C at 1,228 ms,
which looked like the skip index helping. Re-running in the opposite order put
them at 270 ms and 282 ms. Rows read was identical in both runs, which is why
rows read is the number this file leads with.

---

## Postgres, same queries, one tenth the scale

12,780,000 rows, indexed on `(clock_key, scenario_id, as_of)`, `ANALYZE`d.

| query | Postgres @ 12.78M | ClickHouse @ 127.75M | notes |
|---|---|---|---|
| replay diff | **754 ms** | 98–760 ms | ClickHouse does 10× the rows in the same time |
| 365-day risk series | **6,736 ms** | 1,278–2,143 ms | 10× the rows, 3–5× faster |
| every severity transition | **67,574 ms** | 12,253 ms | 10× the rows, 5.5× faster |

Per row, on the full scan, that is roughly **55×**.

### The spec overclaims, and the true number is still decisive

`docs/BUILD_SPEC.md` §2.2 says the replay is "a multi-hour disaster anywhere else."

That is not what the measurement says. Extrapolating the full-scan query linearly from
12.78M to 127.75M rows gives Postgres roughly **11 minutes**, against 12 seconds in
ClickHouse. Eleven minutes is not multi-hour. It is still the difference between a
question you can ask on stage and a batch job you schedule, which is the real argument
and does not need inflating.

Use the measured figure. A judge who has run Postgres at 100M rows will know
"multi-hour" is wrong, and being caught inflating one number costs you the credibility
of every other number on the slide. That is a bad trade for a product whose entire
thesis is that other people's numbers are unreliable.

### This is not a criticism of Postgres

Postgres is doing something ClickHouse cannot do at all: the exclusion constraint that
makes overlapping status periods impossible, the foreign key that keeps the rule chain
walkable, and the transaction that stops an alert disagreeing with the evaluation that
produced it. Neither engine is being asked to do the other's job. That is the
architecture, and the benchmark is what makes it an argument rather than a preference.

---

## Reproducing

```bash
make -f Makefile.data up ch-ddl
docker compose -f infra/data.compose.yml exec -T clickhouse clickhouse-client \
  --password devonly --param_users=50000 --param_rows=127750000 \
  --multiquery < clickhouse/bench/seed_evaluations.sql       # ~4 min
python clickhouse/bench/run_benchmark.py
```

Postgres side: `clickhouse/bench/postgres_comparison.sql`, about 100 s to build.

`run_benchmark.py` correlates each query to its `system.query_log` row by `query_id`,
because ClickHouse strips leading `/* */` comments from the logged query text and a
tagged query cannot be found again. It **raises rather than reporting a zero** if the
log row is missing, since a silent zero would read as "free."
