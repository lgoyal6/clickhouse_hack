# Build Spec v2 — Review

Reviewed against [BUILD_SPEC.md](./BUILD_SPEC.md). Two audiences: the team, deciding
what to build in the time available, and the demo, which has to survive a database
person reading the DDL over your shoulder.

**Rating: 8.5 / 10 as a pitch. 6 / 10 as a build plan.**

The thesis is the best part and it is genuinely good. "Every number traces to a
citation and a date" is a real product constraint, not a slogan, and it forces a
schema that a judge can look at and see the point of. The component justifications
in §2 are the strongest section in the document; most hackathon specs cannot explain
why they need two databases and this one can.

The gap is between §2 and §4/§5. Several of the things the pitch claims as
architecturally load-bearing are not actually implemented by the SQL and pseudocode
below them. The marquee replay query does not replay. The stale-advice
strikethrough, which is the demo, does not fire for the demo's own dates. Those are
not polish items; they are the two beats you are going to stand up and show.

Findings are ordered by what breaks first.

**Verification status of this review.** Contrast ratios (§F) and all date arithmetic
(§A2, §F3) were computed and are verified.

§A1, §A3, §A7 and §A8 have since been **executed** against Postgres 17 and ClickHouse
26.7.5 on `track/data`, and the numbers are in `TRACK_DATA.md`: the spec's replay
query returns zero rows where the corrected one returns both affected users; the
layer-scoped exclusion constraint accepts cap-gap overlapping OPT and still rejects a
second overlapping primary status; a pending PERM case stores **45,447** days under
the spec's `UInt16` column; a `$150,000/hour` typo becomes **$312,000,000** in the
wage distribution under the spec's `multiIf`.

§A5 is **partly resolved**: the materialized views create and populate with their
source expressions inlined, which was the recommendation. Whether the spec's original
form referencing `MATERIALIZED` columns would also have worked was not tested, because
inlining costs nothing and the question stopped mattering.

Every item in §E is a claim about primary legal sources and none of it is verified
here. That is the team's job and the spec already says so.

---

## A. Blockers — these break the demo or silently produce a wrong number

### A1. The rule-change replay query does not replay anything

`§2.2`. The query reads historical rows and labels the pre-cutover ones "under_old":

```sql
argMax(days_remaining, evaluated_at)                                        AS under_new,
argMaxIf(days_remaining, evaluated_at, rule_effective_from < {cutover:Date}) AS under_old
```

That is a read of the past, not a counterfactual. Three consequences:

1. For a **pending** rule (the H-1B grace elimination, which is the example the spec
   itself uses) there are no rows evaluated under the new rule, so `under_new` and
   `under_old` both resolve to the current rule and the diff is empty. The headline
   query returns zero rows on the exact case it was written for.
2. `argMaxIf(..., rule_effective_from < cutover)` returns the *most recent* old-rule
   evaluation, which was computed against a different `as_of` date. You are
   subtracting days-remaining values measured from different days, so `days_lost` is
   contaminated by calendar drift even when it is non-empty.
3. A user who joined after the cutover has no old-rule history at all and silently
   drops out of the population.

**Fix.** Replay is a write, not a read. Add a scenario dimension to
`clock_evaluations` and run the engine twice:

```sql
scenario_id  LowCardinality(String) DEFAULT 'actual',   -- 'actual' | 'rule:h1b_grace_0d' | ...
rule_set_id  UUID,                                      -- the exact rule bundle used
```

Then the diff is a self-join on `(user_id, clock_key, eval_date, scenario_id)` where
both sides were computed as of the same day. This also makes `what_if()` (§6, listed
last, no design) the same code path as the population replay, which is a much better
story: *one engine, two scenarios, one diff.* Build this early; it is the query the
whole architecture argument rests on.

### A2. The stale-advice strikethrough will not fire on the demo's own dates

`§5`. The supersession callout is driven by:

```
prior = resolve_rule(clock_key, as_of - 1 year)
superseded: prior if prior.id != rule.id else None
```

With `as_of = 2026-08-28`, `as_of - 1 year = 2025-08-28`, which resolves to the
**same** `cap_gap_end` row (effective 2025-01-17). Verified: `2025-08-28 >=
2025-01-17`. So `prior.id == rule.id`, `superseded` is `None`, and the cap-gap Field
Card renders with no strikethrough. That is the demo beat in §8, gone.

The one-year lookback is an arbitrary window that happens to be shorter than the age
of the rule change you want to show.

**Fix.** Drive it off the chain, not off a time window:

```sql
SELECT r.*, p.effective_from AS prior_from, p.params AS prior_params, p.citation AS prior_citation
FROM rules r LEFT JOIN rules p ON p.id = r.supersedes
WHERE r.rule_key = $1 AND r.effective_from <= $2
  AND (r.effective_to IS NULL OR r.effective_to > $2)
ORDER BY r.effective_from DESC LIMIT 1;
```

Show the strikethrough whenever `supersedes IS NOT NULL` **and** the superseded
version was in force at some point that overlaps this user's relevant period. That
last clause is what makes it honest rather than decorative: it fires for the person
whose OPT window straddles 2025-01-17, and not for someone who started in 2026.

### A3. The exclusion constraint rejects the demo's own persona

`§2.1 / §3`. `no_overlapping_status` forbids any two overlapping status periods for a
user. But `status_type` includes `CAP_GAP`, `GRACE`, and `AOS_PENDING`, and those are
concurrent by construction:

- Cap-gap **is** an extension of F-1 status and F-1 work authorization while an H-1B
  petition is pending. It does not replace the OPT period; it overlaps it.
- `AOS_PENDING` routinely coexists with H-1B status. People hold H-1B and a pending
  I-485 at the same time; that coexistence is the entire premise of the
  `i485_portability` clock.
- `GRACE` is a clock, not a status.

So the constraint the spec presents as its flagship Postgres correctness guarantee
will refuse to accept Maria's history. You will discover this while seeding.

**Fix.** Keep the constraint, narrow its scope. Add a layer discriminator and only
forbid overlap within the primary layer:

```sql
ALTER TABLE status_periods ADD COLUMN layer TEXT NOT NULL DEFAULT 'primary'
  CHECK (layer IN ('primary','authorization','pending'));

ALTER TABLE status_periods ADD CONSTRAINT no_overlapping_primary_status
EXCLUDE USING gist (
  user_id WITH =,
  layer   WITH =,
  daterange(start_date, COALESCE(end_date,'infinity'::date),'[)') WITH &&
) WHERE (layer = 'primary');
```

This is a *better* demo than the original, because now you can say: overlap is
forbidden where overlap is impossible and permitted where the law actually stacks
authorizations, and the database knows the difference. That is a more sophisticated
claim than "no overlaps."

### A4. `documents` is referenced before it exists

`§3`. `status_periods.source_doc_id UUID REFERENCES documents(id)` appears roughly 60
lines before `CREATE TABLE documents`. The script fails on first run with
`relation "documents" does not exist`. Trivial, but it means nobody has executed this
DDL yet, which is worth knowing about everything else in it.

**Fix.** Order the tables, or add the FK in a later `ALTER`. Split into numbered
migrations so the ordering is enforced by filenames.

### A5. Both materialized views depend on `MATERIALIZED` columns of their source table

`§4`. `wage_baselines` selects `annualized_wage`; `risk_rollup` selects and groups by
`eval_date`. Both are `MATERIALIZED` columns on the source tables. A ClickHouse
materialized view is a trigger over the **inserted block**, and what is visible in
that block is a version-sensitive detail that has burned a lot of people.

Do not bet the demo on it. Inline the expressions in the view definitions
(`toDate(evaluated_at)`, and the full `multiIf` for the wage) and keep the source
column as a convenience for ad-hoc queries. Costs nothing, removes the class of bug.

Related and independent: neither MV uses `POPULATE`, and MVs only see inserts that
arrive **after** creation. If you load 8M rows of OFLC data and then create
`wage_baselines`, it is empty, the Standing screen shows nothing, and the failure is
silent. Either create the views before loading, or use `POPULATE`, or backfill with
an explicit `INSERT INTO wage_baselines SELECT ...`. Put this in the loader script,
not in someone's head.

### A6. `wage_baselines` cannot answer the question the product asks of it

`§4 / §6`. The MV stores `quantileState` aggregates: p10, p25, p50, p75, p90. Those
give you **value at a quantile**. The product needs the inverse: given this person's
wage, **what quantile are they at**. `wage_percentile(soc, state, wage)` is the
headline corpus tool and the whole of screen 6, and it cannot be computed from these
states. Interpolating between five stored cut points is not a percentile; it is a
guess with a citation attached, which is precisely the sin the product exists to
oppose.

**Fix.** Two options, both cheap:

```sql
-- Exact, and fast enough: this is what ClickHouse is for.
SELECT countIf(annualized_wage <= {wage:Decimal(12,2)}) / count() AS pct, count() AS n
FROM lca_filings
WHERE case_status='CERTIFIED' AND soc_code={soc:String}
  AND worksite_state={state:String} AND fiscal_year={fy:UInt16};
```

Keep the quantile MV for rendering the distribution and the level cut points, and do
the inverse lookup as a direct scan. Measure it and put the number on the
architecture slide. If you want it precomputed, store a histogram
(`histogramState` or a fixed set of wage buckets) which *is* invertible.

### A7. `days_to_decision UInt16` corrupts every pending case

`§4`. ClickHouse `Date` has no representation before 1970-01-01, so an absent
`decision_date` lands on the epoch and `dateDiff('day', received_date, decision_date)`
returns a large negative number. Storing that in `UInt16` produces either a wrapped
large positive or a clamp to zero depending on version and cast settings; both are
wrong and neither raises. Pending PERM cases, which are a large share of recent
fiscal years and the interesting ones, report nonsense processing times with no error
anywhere. Unverified locally (no ClickHouse available), but the negative input is
arithmetic, not behaviour, so the column type is wrong regardless of which cast you
get.

**Fix.** `decision_date Nullable(Date)` and `days_to_decision Nullable(Int32)
MATERIALIZED if(decision_date IS NULL, NULL, dateDiff('day', received_date,
decision_date))`. Same treatment for any other date that can legitimately be absent.

### A8. `annualized_wage` fails open, and silently mixes hourly with annual

`§4`. The `multiIf` falls through to bare `wage_rate_from` for any unrecognised
`wage_unit`. OFLC unit spellings are **not stable across fiscal years**: newer files
use `Year`/`Hour`/`Week`/`Month`/`Bi-Weekly`, older ones use `YR`/`HR`/`WK`/`MTH`/`BI`.
Every unmatched hourly row therefore enters the distribution as if `$52.00` were an
annual salary. The p50 for an occupation quietly collapses and nothing raises a
flag.

**Fix.** Fail closed. `Nullable(Decimal)`, `NULL` on unrecognised unit, plus a hard
data-quality gate in the loader:

```sql
SELECT wage_unit, count() FROM lca_filings GROUP BY wage_unit ORDER BY 2 DESC;
-- must be a closed set you have enumerated; any surprise fails the load
SELECT count() FROM lca_filings WHERE annualized_wage IS NULL;         -- must be ~0
SELECT count() FROM lca_filings WHERE annualized_wage NOT BETWEEN 10000 AND 3000000;
```

Add sanity bounds too: entries where an annual figure was typed into an hourly field
exist in this dataset and a single `$150,000/hour` row moves a p90.

### A9. The `>= 20 hours` test is applied per episode instead of per day

`§5`, clock 1: "sum gap days where the person had no episode with
`hours_per_week >= 20`". Concurrent employment is legal on OPT and hours across
employers aggregate. Two 15-hour jobs is 30 hours a week and is not unemployment,
but this algorithm counts it as unemployment for the entire overlap.

**Fix.** The unemployment calculation is a per-day sum, not a per-episode filter:
for each day in the authorization window, sum `hours_per_week` over all episodes
covering that day where `counts_as_employment`, and compare the total to the
threshold. In SQL that is a `generate_series` join, or a sweep over sorted episode
boundaries in the engine. Either way it is a different shape of code than the spec
describes, so decide now.

### A10. The unemployment count is not bounded to the OPT authorization window

`§5`, clock 1 walks employment episodes over the person's whole history. The 90 days
are days of unemployment **during the post-completion OPT period**, which starts on
the EAD start date. A gap between graduation and OPT approval, or any pre-OPT gap,
must not count. As written, anyone with a normal F-1 study period and no job shows up
already over the ceiling.

**Fix.** Intersect the gap set with `[ead_start, ead_end]` before summing, and make
the window an explicit input to the clock so it appears in `inputs_hash`.

---

## B. Serious — architecture and product logic

### B1. `clock_evaluations` is ordered for the query you will run least

`ORDER BY (user_id, clock_key, evaluated_at)` is right for "show me my history." The
query the spec says justifies the architecture filters on `clock_key` across the
entire population, so it cannot use the primary index at all and reads every part.

Add a projection rather than choosing:

```sql
ALTER TABLE clock_evaluations ADD PROJECTION by_clock (
  SELECT * ORDER BY (clock_key, eval_date, user_id)
);
```

Then benchmark both and put the timings on the slide. A database hackathon judge
wants to see that you know which access path each query takes.

### B2. `risk_rollup` counts rows and calls them users

`count() AS users` in a `SummingMergeTree`. If the nightly job runs twice, or a
backfill replays a day, the same user is counted repeatedly and population risk
inflates with no way to tell. Use `AggregatingMergeTree` with
`uniqState(user_id)`, read with `uniqMerge`. Same class of problem: `count()` and
`any(employer_name)` as plain columns inside an `AggregatingMergeTree` are not
aggregate states and do not combine correctly on merge; they need `countState()` /
`anyState()`.

### B3. The engine writes to two systems with no transaction spanning them

`§5`: "regenerate alerts in a single Postgres transaction" plus "append to
`clock_evaluations`" in ClickHouse. There is no shared transaction. If the ClickHouse
append lands and the Postgres commit rolls back, the retained history disagrees with
the alerts, and the spec's own argument is that a stale alert is active harm.

**Fix.** One write path. Write evaluations into a Postgres outbox table inside the
same transaction as the alerts, and let CDC carry them to ClickHouse. Postgres stays
the system of record for anything the UI treats as authoritative; ClickHouse holds
the analytical copy. This also removes the awkwardness of the product's most-cited
table being the one table with no upstream source of truth.

### B4. The rule chain has no integrity constraints, and the chain is the product

`§3`. `UNIQUE (rule_key, effective_from)` is the only guard. Nothing prevents:

- two rows superseding the same predecessor (a forked chain);
- overlapping effective windows for the same `rule_key`;
- a gap between one version's `effective_to` and the next version's `effective_from`,
  in which resolution silently returns nothing and the clock renders empty.

Given §2.1 says an unbroken chain is what makes provenance verifiable, enforce it:

```sql
ALTER TABLE rules ADD CONSTRAINT one_successor_per_rule UNIQUE (supersedes);
ALTER TABLE rules ADD CONSTRAINT no_overlapping_rule_windows
EXCLUDE USING gist (
  rule_key WITH =,
  daterange(effective_from, COALESCE(effective_to,'infinity'::date),'[)') WITH &&
);
ALTER TABLE rules ADD CONSTRAINT supersedes_same_key
  CHECK (supersedes IS NULL OR rule_key IS NOT NULL);  -- enforce same key via trigger
```

Also: the seed table marks the 2008 `cap_gap_end` and 2020 `lottery_selection` rows
"superseded" but supplies no `effective_to` for them. Resolution still works because
of `ORDER BY effective_from DESC LIMIT 1`, which means `effective_to` is decorative
and the exclusion constraint above will be the thing that forces you to set it.
Set it in the same transaction that inserts the successor.

### B5. `params JSONB` is unvalidated, in a product where a missing key is harm

A typo in `{"days":90}` reads back as `NULL`, and the engine computes a wrong
countdown rather than failing. Add a per-`rule_key` shape check (a `CHECK` with
`jsonb_typeof`, or validate on load against a small schema map) and make the engine
raise on a missing param instead of coercing.

### B6. `inputs_hash` cannot distinguish what the spec says it distinguishes

`§4 / §5`: it "detects whether inputs or the rule moved." For that to work the hash
must cover user facts **only** and exclude both `as_of` and the rule params.
Otherwise it changes every night simply because the calendar advanced, and the
signal is gone. There are three cases, not two, and the UI copy in §7 implies you
will name them: your facts changed, the law changed, only time passed. Store
`inputs_hash` (facts) and `rule_id` (law) separately and derive the third case from
neither having changed.

### B7. `h1b_max_stay` cannot be computed; the required data has no table

`§5`, clock 6 is "six years minus recaptured time abroad." There is no table of
trips abroad anywhere in §3. Either add one (`absences(user_id, departed, returned,
evidence_doc_id)`) or cut the clock and say so. Shipping a six-year meter that
silently ignores recapture is exactly the failure mode the product is pitched
against, and it always over- or under-counts.

Related: `h1b_first_entry` lives on `status_periods`, so a user with several H-1B
periods can hold several conflicting values for the date that starts the six-year
meter. It belongs on `users` or on a dedicated H-1B history record.

### B8. The clock inventory does not match itself

§5 lists seven clocks. The Clock Wall in §7 says "7 clocks" and shows
`I-94 EXPIRY`, which is not one of the seven, while omitting `opt_filing_window` and
`h1b_grace_period`. The home screen and the engine disagree about what the product
computes. Pick the seven, put them in one list, and let both the engine and the UI
read that list.

### B9. The visa bulletin is loaded but never becomes a clock

`visa_bulletin`, `users.country_chg`, and `bulletin_movement()` all exist, but no
clock consumes them. For much of this population the priority-date wait is the
largest countdown in their life, and it is the one where "how it moved" history
genuinely beats a static number. Either add the clock (retrogression exposure:
your priority date versus the cutoff, and the movement rate implied by the last 24
bulletins) or drop the table and the tool. Right now it is a dependency with no
payoff, which is the most expensive kind.

### B10. The wage percentile may be the wrong statistic for the lottery claim

`§2.2` says selection odds depend on "where your offered wage sits in that
distribution." The proposed wage-weighted mechanism weights entries by **OES wage
level** (I through IV) relative to the prevailing wage for that occupation and area,
not by percentile among peer LCA filings. Those are different numbers and can point
opposite ways: a wage at the 80th percentile of what employers actually offer in
your metro can still be a Level II wage.

If the mechanism is level-based, screen 6 should show **which level your offer
lands in** and what wage crosses into the next one, computed against prevailing wage
data, with the peer distribution as context rather than as the answer. This is worth
getting right because it is the one screen that makes a numeric claim about
someone's odds.

### B11. The Clock Wall in §7 shows a person who cannot exist

The mock is labelled `Maria O.` and renders `UNEMPLOYMENT`, `CAP-GAP`, `AC21 · 365`,
`H-1B MAX`, and `PORTABILITY` on one screen. Those clocks cannot run for one person
at one time. Someone in cap-gap is in F-1 status with an H-1B petition still pending,
so the six-year meter has not started, AC21 §106(a) has nothing to extend, and there
is no I-485 to port from. §8 confirms this by offering the persona as "a home health
aide on STEM OPT, **or** an adjunct instructor on H-1B"; the wall draws both at once.

This matters twice. It is the screenshot, so an immigration-literate judge spots it
immediately. And it means the engine has no concept of **applicability**: §5 says "for
each applicable clock_key" and then never defines applicable.

**Fix.** Give every clock an explicit applicability predicate over user state, and
have `evaluate()` return one of three states per clock: running, not-applicable, or
not-yet-started with the reason. Render only what is running, and give the wall a
quieter secondary row for "not running yet, and why" if you want the reassurance. Then
demo two personas, which the spec already wants for the stale-advice beat anyway.

The fixtures in `contracts/fixtures/` are split this way on purpose: three clocks for
the STEM OPT persona, three for the H-1B persona, and no screen that mixes them.

---

## C. Data ingestion — the actual long pole

### C1. OFLC column schemas change across fiscal years

One `CREATE TABLE lca_filings` for FY2019 through FY2026 will not ingest cleanly.
Column names, column counts, and file formats all move between years, including a
substantial break around FY2020, and several years ship as `.xlsx` rather than CSV.
Budget for a per-fiscal-year column mapping layer and a canonical target schema, and
convert once to Parquet so reloads are fast. This is where the day goes if you do
not plan it.

### C2. `employer_fein` is load-bearing and may not exist in the source

`lca_filings.ORDER BY` ends with it, `employer_profiles` is keyed entirely on it, and
`employment_episodes.employer_fein` is described as "join key into the OFLC corpus."
Recent LCA and PERM public disclosure files do not reliably publish FEIN. If the
column is absent or mostly empty, `employer_profiles` degenerates to a single bucket
and the employer tool returns garbage.

Check the actual headers before writing any of this. If FEIN is not there, key on a
normalised employer name with an explicit `employer_id` resolution table, surface the
match confidence as §9 already promises, and let the user correct it. Do not let a
column that may not exist sit in a primary key.

### C3. `worksite_msa` availability varies

Present in some years, derived in others, absent in others. The Standing screen is
specified as "occupation and state," so make state the contract and treat MSA as
optional enrichment.

### C4. `fiscal_year` means "the year of the file," not the year of the case

Cases spanning a fiscal-year boundary get bucketed by which disclosure file they
arrived in. Fine, but the Standing screen labels a distribution with a year, so
document what the year means or derive it from `received_date` consistently.

### C5. The embedding step is an undeclared external dependency

§2.2 treats `soc_embeddings` as free. Something has to generate those vectors, which
means an embedding API, a key, a cost, and a step in the loader. Also worth one
search before building: O\*NET publishes an alternate-titles list and there are
published SOC crosswalks, which cover a large share of the "Senior SWE II" cases by
lookup. Recommended shape: exact and alias match first, vector search as the
fallback for the tail, and show the score either way. That is both cheaper and a
better answer, and it is still a legitimate ClickHouse vector demo.

Scope the claim honestly too. Brute-force `cosineDistance` over a few tens of
thousands of SOC rows is instant and is what you will actually run; approximate
vector indexes are a separate and more recent feature. "Vector similarity in the same
store as the filings" is true and sufficient. Do not overclaim the index.

### C6. CDC is the highest-risk infrastructure item in the plan

PeerDB in a hackathon means logical replication, a slot, a publication, `wal_level`,
and a new service. Timebox it hard, and decide the fallback before you start: a
scheduled batch copy, or ClickHouse's native Postgres integration, or if you are on
ClickHouse Cloud, the built-in Postgres CDC pipe. Any of those demos the same claim.
Losing three hours to a replication slot on a day this long is the single most likely
way this project ends up incomplete. One search before building applies here.

### C7. `ReplacingMergeTree ORDER BY (id)` will show deleted and stale rows

The CDC target note omits two things that matter: reads need `FINAL` (or an explicit
dedup) or they see multiple versions of a row, and deletes need an `is_deleted`
column with `ReplacingMergeTree(version, is_deleted)`. The Postgres schema uses
`ON DELETE CASCADE`, so deletes will happen, and a deleted user reappearing in a
population risk count is a bad look for a product about correctness.

---

## D. Security and privacy — the biggest unaddressed risk

### D1. `get_my_clocks(user_id)` is an IDOR with an LLM holding the parameter

`§6`. The tool takes `user_id` as an argument the model supplies. Any prompt that
produces a different UUID reads another person's immigration status, employer, and
wage. In the demo this is a feature, because it is how you switch personas, which
means there is no authorization boundary to accidentally leave in place; there is
simply none.

**Fix.** The user identity comes from the session, never from the model. Tools take
zero identity parameters and the MCP layer injects the authenticated subject. Add
Postgres RLS keyed on a session GUC so the database enforces it too, and demo persona
switching with two separate sessions. This is a five-line change and it is the
difference between "prototype" and "someone could run this."

### D2. There is no auth model at all

`users.email UNIQUE` and nothing else. For a hackathon that is acceptable if stated,
but say it out loud in §9 rather than leaving a judge to notice. The data here is
immigration status, employer, and salary for identifiable people, which is about as
sensitive as consumer data gets.

### D3. "Never deleted" collides with deletion rights and with your own cascade

`clock_evaluations` is specified as never deleted, while `users` cascades deletes
across every Postgres table. So a deletion request removes the record of the person
and leaves a complete daily behavioural history keyed to their UUID. Decide the
policy: either the UUID is a pseudonym you keep with the mapping deleted, or
evaluations are deleted by partition on request. Both are defensible; silence is not.
This is also a nice thing to have an answer for, because it is the first question a
serious judge asks about an append-only table of personal data.

---

## E. Domain correctness — verify each of these against the primary source

The pitch is that other people's numbers are stale, so these have to be right, and
this review cannot substitute for reading the sources. Treat all of the below as
unverified until `verified_by` and `verified_at` are filled.

### E1. `lottery_selection` effective 2026-02-27 is the weakest citation in the table

The row cites "Final Rule 2025-12-29" with no Federal Register number and no URL, and
asserts "first run March 2026," which is in the past as of today. Every other row
cites a CFR section or a named rule. In a product whose entire thesis is provenance,
the one row with a vague citation is the row a judge will pull on, and it is also the
row that powers your most quantitative screen. Get the FR citation and the exact
effective date, or mark the rule unverified and let the UI show its warning band.
Doing the latter on stage would actually be a strong move: the product flagging its
own weakest rule is the thesis working.

### E2. The 150-day STEM total is contested by the spec's own framing

The spec asserts 150 is correct and 120 is a common misprint, then makes that
disagreement part of the pitch. Read 81 FR 13040 and the SEVP STEM OPT guidance
directly and record the exact language, because you are going to be asked to defend
the number on stage. Note also that the aggregate applies across the whole OPT
period including the extension; it does not reset when the extension starts.

### E3. `opt_min_hours` has an authority outside the schema's own allowed list

The `authority` comment restricts values to Federal Register, 8 CFR, and USCIS Policy
Manual. `opt_min_hours` is cited to "SEVP guidance," which is not in that set, and
the 20-hour minimum for post-completion OPT comes from SEVP policy guidance rather
than from the regulation text. Widen the allowed list to include ICE/SEVP guidance and
record the exact document, or the weakest-sourced rule in the product is also the one
with the least legible provenance. It also gates the flagship unemployment clock.

### E4. Unemployment accrual during cap-gap deserves an explicit citation

§5 states days continue accruing during cap-gap as a bare assertion. Published
guidance is thinner here than for the 90/150 ceiling. If you cannot source it
cleanly, say so in the UI rather than picking a side silently.

### E5. `ac21_365` conflates an eligibility condition with a deadline

AC21 §106(a) is about eligibility for one-year extensions beyond the sixth year when
a PERM or I-140 has been pending 365 days or more. The clock reframes that as a
deadline ("days until you must have filed"), which is a genuinely useful derived
framing and probably the single most valuable number in the product. But the citation
attached to it supports the eligibility rule, not the deadline. Label it as derived,
show the arithmetic, and cite the underlying rule for the input rather than for the
conclusion. The provenance contract should distinguish "this number is in the
regulation" from "this number is our arithmetic over a regulation," and right now it
does not have a way to.

---

## F. Design and accessibility — measured, not guessed

Contrast ratios computed against `--paper #F1F3EE` (WCAG 2.1 relative luminance):

| token | hex | ratio | verdict |
|---|---|---|---|
| `--ink` | `#16191C` | 15.79:1 | passes AAA |
| `--stamp` | `#2B4C7E` | 7.71:1 | passes AAA |
| `--urgent` | `#B03A2E` | 5.38:1 | passes AA |
| `--clear` | `#3F7D58` | **4.39:1** | **fails AA for normal text** |
| `--rule` | `#8A9187` | **2.90:1** | **fails AA badly** |

### F1. The citation line fails contrast, and the citation line is the product

§7 specifies the citation and effective date at **11px in `--rule`**, which measures
2.90:1. The one element the spec calls non-optional and part of the typographic
object is the least readable text on the screen. Keep `#8A9187` for hairlines, which
are decorative, and add a darker token for citation text. `#666D62` measures 4.78:1
and reads as the same grey-green.

### F2. `--clear` passes only as large text

4.39:1 clears the 3:1 large-text threshold, so the enormous counts are fine. The
`document verified` confidence tag on the Intake screen (§7, screen 5) is small text
and fails. `#2F6244` measures 6.37:1 and holds the same character.

### F3. "216 days of work authorization" is mislabelled

The cap-gap Field Card in §7 reads `APR 01 2027` and `216 days of work
authorization`. From `as_of = 2026-08-28` to `2027-04-01` is exactly 216 days, so
that number is **days remaining**, not the length of the authorization. The cap-gap
window itself, `2026-09-30` to `2027-04-01`, is 183 days. Both are verified
arithmetic.

In a product whose promise is that every number is traceable, the hero card's second
line names the wrong quantity. Two numbers, two labels: `216 days remaining` and
`183 days gained`. The second one is the better number anyway, because it is the
thirteen weeks the demo is about.

### F4. The ticking count needs an accessible-name strategy, not just reduced motion

§7 handles `prefers-reduced-motion`, which is right. It does not say what a screen
reader hears during a 400ms animation from zero. Render the final value in the
accessible name from the start and keep the animated digits `aria-hidden`, so
assistive tech never reads an intermediate number. A wrong number spoken aloud is the
same harm as a wrong number displayed.

### F5. Small copy inconsistency worth fixing before the screenshot

The Clock Wall shows `AC21 · 365` with `38 days` and `no PERM`, sorted with critical
first, and the card is annotated as red. §7 also says critical "moves to position
one," but the mock has AC21 in position three. Fix the mock or the rule; a judge
reading both will notice.

---

## G. Safety-critical translation

§2.3 and §6 route localisation through a Translation agent at read time. For
explanatory prose that is right and it is a genuinely good use of the model. For the
**alert** text in `alerts.headline` / `alerts.detail`, it is the wrong architecture:
those are the sentences that tell someone a deadline is approaching, and generating
them freshly per read means nobody has ever reviewed the Spanish that a user actually
receives.

**Fix.** Alerts become `template_key` plus a JSONB params blob, with a small set of
reviewed translations per locale. Dates and counts interpolate; the sentence does
not get regenerated. The model handles open-ended conversation, and the fixed
safety-critical strings are reviewed once by a human. This is also a good answer to
have ready, because "you used an LLM to translate legal deadlines" is a fair
criticism and the template approach answers it in one sentence.

---

## H. Two smaller notes

### H1. `claude-sonnet-4-6` is probably not a valid model id

§6 pins the agent model to `claude-sonnet-4-6`. Check the id against the current
model list before the demo; if you are competing for a LibreChat prize, pin the
current Sonnet or Opus release explicitly rather than a guessed string, and put the
id in one config file so it is a one-line change.

### H2. Enforce the citation contract in the tool schema, not only in the prompt

§6 puts "never state a rule without citation, authority, and effective date" in the
system prompt. Prompt-level contracts leak under pressure, which for this product
means an uncited number reaching a user. Make `citation`, `authority`, and
`effective_from` **required fields of every tool's response schema**, so the model
physically cannot receive a number without its provenance and has nothing uncited to
repeat. That is a structural guarantee, it is one sentence on the architecture
slide, and it is a much better answer than "we told it not to."

### H3. Nothing in the spec sends an alert

`alerts` has `fires_on`, `severity`, and `acknowledged_at`, and no delivery
mechanism. A product whose thesis is "you cannot see these countdowns" needs to
reach the person who is not looking at the dashboard. Either add one channel (email
is enough) or state that delivery is out of scope, because a judge will ask how she
finds out.

---

## I. Scope — the honest cut

Seven clocks, four agents, nine tools, six screens, CDC, three materialized views,
vector search, an 8M-row multi-year ingest, and two languages is more than a
hackathon. Cutting from the top of the list below is what makes the difference
between a demo and a deck.

**Build (this is the whole pitch):**

1. `opt_unemployment` and `cap_gap_window`, computed correctly per A9, A10, A2.
2. `ac21_365`, because it is the most emotionally effective card on the wall.
3. `clock_evaluations` with `scenario_id`, plus the replay diff from A1 and
   `what_if()` on the same code path.
4. LCA corpus, two fiscal years, one state, exact wage percentile per A6.
5. Clock Wall and Ask. Two screens.
6. One agent with four tools, provenance enforced in the tool schemas per H2.
7. Spanish.

**Defer, and say you deferred it:** PERM, visa bulletin, employer profiles, vector
SOC matching, Timeline, Standing, Rule Detail, Intake-as-a-screen, the fourth
language, PeerDB if it is not working within its timebox.

**Add, because it is cheap and it is what these judges want:** a benchmark slide.
Row counts, the replay query's wall-clock time, rows scanned, and the same query's
shape against Postgres for contrast. One measured number beats three paragraphs of
"runs in seconds in ClickHouse."

---

## J. What is genuinely strong, so it does not get cut by accident

- **The thesis.** "Every number traces to a citation and a date" is a real constraint
  that shapes the schema, the UI, and the agent contract. That coherence is rare.
- **Rule versioning as a first-class table** with `supersedes`, `effective_from`,
  `authority`, and `verified_by`. This is the good idea. The strikethrough is the
  right visual for it.
- **The observation that the information about the rules is staler than the rules.**
  That is the actual insight, it is true, and it is the reason this is a product and
  not a calculator.
- **Retaining every evaluation** so the product can distinguish "your facts changed"
  from "the law changed." Fix B6 and it is the strongest architectural claim here.
- **Conversation as intake** for people who do not know the vocabulary. The I-94
  versus visa-sticker example is the most convincing single line in the document.
- **Provenance inside the Field Card rather than in a tooltip.** A design decision
  that enforces the product promise instead of describing it.
- **§9 existing at all.** Naming your weaknesses before a judge does is worth real
  points and most teams do not do it.
