# Status Clock — Build Spec v2

**Hackathon:** ClickHouse × Postgres, KOHO SF
**Track:** Open ("your everyday crisis")
**Bonus target:** Most impressive use of LibreChat

> This file is the spec as authored. It is the design intent of record.
> Corrections, contradictions and open questions are tracked separately in
> [REVIEW.md](./REVIEW.md) rather than edited into this document, so that the
> delta between "what we meant to build" and "what survives contact with the
> primary sources" stays visible.

---

## 1. The thesis

Every person on a US work or student visa is running countdowns they cannot see. Unemployment days. Grace periods. Cap-gap. The 365-day AC21 threshold. The six-year maximum. I-94 expiry, which is not the date on the visa stamp. Miss one and you lose status - which means losing the job, the apartment, the life, and often the ability to come back.

The rules governing those countdowns change faster than the information about them. Cap-gap moved from September 30 to April 1 under a rule effective January 2025. A year and a half later, most published guidance still shows the old date, and some university DSO templates were never updated. Published sources actively disagree on the STEM OPT unemployment ceiling - 90 + 60 = 150 is correct, and some 2026 sources print 120. Someone reading the wrong one plans around a number that is thirty days short.

**Status Clock computes your countdowns against rules that carry effective dates, shows which version governs your specific case, and flags the moment the advice you were given stopped being true.**

The product promise, and the design constraint that follows from it: **every number on the screen can be traced to a citation and a date.**

---

## 2. Why each component is structural

This section exists because a judge will ask. The answers should be architectural, not decorative.

### 2.1 Postgres is the system of record - and enforces correctness the domain requires

A person's status history is not append-only. It is corrected. A DSO reissues an I-20 with a different program end date. A layoff date gets amended. An I-140 approval arrives and retroactively changes which AC21 rule applies. These are updates to authoritative facts, and getting them wrong changes a countdown that determines whether someone can stay in the country.

Three things Postgres does here that nothing else in the stack can:

**Atomic multi-table writes.** Adding an employment episode must simultaneously recompute unemployment day totals, regenerate the alert set, and invalidate cached evaluations. Half of that landing is worse than none of it - a stale alert that says "you're fine" is an active harm.

**Exclusion constraints on temporal data.** Overlapping status periods are physically impossible and must be rejected at write time, not caught in a report:

```sql
ALTER TABLE status_periods ADD CONSTRAINT no_overlapping_status
EXCLUDE USING gist (
  user_id WITH =,
  daterange(start_date, COALESCE(end_date, 'infinity'::date), '[)') WITH &&
);
```

This is a genuine OLTP correctness guarantee. A columnar store has no equivalent and shouldn't.

**Referential integrity on the rule version chain.** `rules.supersedes` is a self-referencing foreign key. The chain from the current rule back through every prior version must be unbroken, or provenance - the entire product - becomes unverifiable.

Postgres is also the CDC source. Every write replicates to ClickHouse within seconds via PeerDB, which is what lets the analytical layer reason about individual users without querying the transactional store.

### 2.2 ClickHouse is not a reporting layer - it is where the product's core loop lives

The naive version of this product is a calculator: you press a button, it computes your days, it shows a number. That version doesn't need ClickHouse and doesn't need to exist.

The real product is a **continuous re-evaluation system**. Four things make that a columnar workload.

**Every clock, every user, every day, retained forever.** Seven clocks recomputed daily per user. At 50,000 users that's 127 million rows a year; at 500,000 it's 1.3 billion. This is not a log you archive - it is queried constantly, because it's what powers "your risk moved" and "this is the day your rule changed." Keeping a full evaluation history is what lets the tool say something a calculator never can: *not just where you stand, but how you got here.* Nobody else keeps this. Every other tool in the space recomputes and discards.

**Rule-change replay across the whole population.** This is the query that justifies the architecture on its own. When a rule flips - and one is pending right now, the proposed elimination of the H-1B 60-day grace period - you must recompute every affected user's entire history under both the old and new rule version and surface everyone whose outcome diverges. That is a full-corpus scan joined against a version table, producing a diff. It runs in seconds in ClickHouse and is a multi-hour disaster anywhere else.

```sql
-- Who is newly at risk under a rule change?
WITH replayed AS (
  SELECT
    user_id,
    clock_key,
    argMax(days_remaining, evaluated_at) AS under_new,
    argMaxIf(days_remaining, evaluated_at, rule_effective_from < {cutover:Date}) AS under_old
  FROM clock_evaluations
  WHERE clock_key = {clock:String}
  GROUP BY user_id, clock_key
)
SELECT user_id, under_old, under_new, under_old - under_new AS days_lost
FROM replayed
WHERE under_new < under_old
ORDER BY days_lost DESC;
```

**Corpus baselines nobody can precompute.** DOL's OFLC disclosure data - LCA, PERM, and prevailing wage determinations across FY2019-FY2026 - is roughly six to eight million rows. The questions are quantile aggregations across tens of thousands of groups: wage distribution by occupation × metro × year, employer filing velocity, approval patterns. Under the wage-weighted lottery effective February 2026, a person's selection odds depend on where their offered wage sits in that distribution. That percentile cannot be cached because the cut points move every fiscal year and the question is always "where do *I* land."

**Vector search for intake normalization.** People do not describe their job as "15-1252 Software Developers." They write "Senior SWE II" or "backend engineer, platform team." Mapping free text to SOC codes by string matching fails constantly, and getting it wrong means the wrong wage baseline and the wrong odds. ClickHouse does vector similarity natively, so embeddings of SOC titles and historical job titles live in the same store as the filings they index - no second database, no sync problem. The same index handles matching a user's description of a rule they were told against the actual rule text.

### 2.3 LibreChat is the intake mechanism, not a chat window bolted on the side

The hardest UX problem in this product is not display. It is getting accurate dates out of a frightened person who does not know the vocabulary.

A form that says "select your status type" fails immediately, because someone on a STEM OPT extension with a pending H-1B in cap-gap does not know which of those words describes them. They have a stack of paper. They know that one of the documents has a date on it.

Conversation solves this in a way a form cannot: *"Find your most recent I-797. Top left, there's a receipt number starting with three letters. What is it?"* Then: *"Now the I-94 - that's the number from the CBP site, not the sticker in your passport. They're often different, and the sticker is the one people get wrong."*

That is a guided extraction, and it needs to branch on every answer. It's a conversation.

Four things make LibreChat structural rather than ornamental:

**Multi-file document upload and parsing.** I-20s, EADs, I-797s, I-94 printouts. LibreChat handles the upload surface; the agent reads dates out and writes them to Postgres through a tool call, showing its work so the user can correct it.

**Multi-agent decomposition.** Agent Builder supports sub-agents, and this problem decomposes cleanly: an **Intake** agent that extracts and validates dates, a **Clock** agent that queries computed countdowns with provenance, a **Corpus** agent that runs the ClickHouse aggregations, and a **Translation** agent that renders any of it into the user's language without losing citation fidelity.

**Language is the access barrier.** The population most exposed to these deadlines is disproportionately not reading English regulations. Answering "¿cuántos días me quedan?" with a correct number, a citation, and an effective date is the product working. Seed Spanish plus one of Portuguese, Mandarin, or Tagalog.

**The stale-advice check is inherently conversational.** A user pastes what their DSO or a forum told them. The agent checks the claim against the rule table, identifies which version it corresponds to, and reports when that version was superseded. There is no form field for "here's what someone told me."

---

## 3. Postgres schema

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT UNIQUE NOT NULL,
  locale        TEXT NOT NULL DEFAULT 'en',
  country_chg   TEXT,                    -- chargeability country, drives priority dates
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE status_periods (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status_type   TEXT NOT NULL
                CHECK (status_type IN ('F1','OPT','STEM_OPT','H1B','H4','O1','L1',
                                       'TN','J1','AOS_PENDING','GRACE','CAP_GAP')),
  start_date    DATE NOT NULL,
  end_date      DATE,
  i94_expiry    DATE,
  ead_expiry    DATE,
  program_end   DATE,
  is_stem       BOOLEAN NOT NULL DEFAULT false,
  cap_exempt    BOOLEAN NOT NULL DEFAULT false,
  h1b_first_entry DATE,                  -- starts the six-year meter
  source_doc_id UUID REFERENCES documents(id),
  confidence    TEXT NOT NULL DEFAULT 'user_stated'
                CHECK (confidence IN ('document_verified','user_stated','inferred')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT sane_dates CHECK (end_date IS NULL OR end_date >= start_date)
);

ALTER TABLE status_periods ADD CONSTRAINT no_overlapping_status
EXCLUDE USING gist (
  user_id WITH =,
  daterange(start_date, COALESCE(end_date, 'infinity'::date), '[)') WITH &&
);

CREATE TABLE employment_episodes (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  employer_name TEXT NOT NULL,
  employer_fein TEXT,                    -- join key into the OFLC corpus
  start_date    DATE NOT NULL,
  end_date      DATE,
  hours_per_week SMALLINT,               -- under 20 does not count as employed on OPT
  soc_code      TEXT,                    -- resolved via vector match, user-confirmable
  soc_confidence REAL,
  worksite_state TEXT,
  worksite_msa  TEXT,
  offered_wage  NUMERIC(12,2),
  wage_unit     TEXT,
  wage_level    SMALLINT CHECK (wage_level BETWEEN 1 AND 4),
  employment_kind TEXT
                CHECK (employment_kind IN ('paid','unpaid_training','self_employed',
                                           'volunteer','contract')),
  counts_as_employment BOOLEAN NOT NULL DEFAULT true,

  CONSTRAINT sane_dates CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE INDEX ON employment_episodes (user_id, start_date);

CREATE TABLE gc_milestones (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  milestone     TEXT NOT NULL
                CHECK (milestone IN ('PWD_FILED','PWD_ISSUED','RECRUITMENT_START',
                                     'PERM_FILED','PERM_APPROVED','I140_FILED',
                                     'I140_APPROVED','I485_FILED','AP_APPROVED')),
  event_date    DATE NOT NULL,
  priority_date DATE,
  category      TEXT CHECK (category IN ('EB1','EB2','EB3','EB2_NIW')),
  receipt_number TEXT,
  UNIQUE (user_id, milestone, event_date)
);

CREATE TABLE documents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  doc_type      TEXT NOT NULL,           -- I20 | EAD | I797 | I94 | VISA | PERM_NOTICE
  uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  extracted     JSONB,                   -- what the intake agent pulled out
  user_confirmed BOOLEAN NOT NULL DEFAULT false
);

-- The provenance backbone.
CREATE TABLE rules (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_key      TEXT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to  DATE,
  params        JSONB NOT NULL,
  citation      TEXT NOT NULL,
  source_url    TEXT NOT NULL,
  authority     TEXT NOT NULL,           -- 'Federal Register' | '8 CFR' | 'USCIS Policy Manual'
  supersedes    UUID REFERENCES rules(id),
  note          TEXT,
  verified_by   TEXT,                    -- who on the team checked the primary source
  verified_at   TIMESTAMPTZ,

  UNIQUE (rule_key, effective_from),
  CONSTRAINT sane_window CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE INDEX ON rules (rule_key, effective_from DESC);

CREATE TABLE alerts (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  clock_key     TEXT NOT NULL,
  fires_on      DATE NOT NULL,
  severity      TEXT NOT NULL CHECK (severity IN ('info','warn','critical')),
  headline      TEXT NOT NULL,
  detail        TEXT,
  rule_id       UUID REFERENCES rules(id),
  acknowledged_at TIMESTAMPTZ,
  UNIQUE (user_id, clock_key, fires_on)
);
```

### Seed rules - verify every one against its primary source

| rule_key | effective_from | params | authority | note |
|---|---|---|---|---|
| `opt_unemployment_max` | 2008-04-08 | `{"days":90}` | 8 CFR 214.2(f)(10) | standard post-completion |
| `stem_opt_unemployment_add` | 2016-05-10 | `{"days":60}` | STEM OPT Final Rule | total 150 - **frequently mis-printed as 120** |
| `cap_gap_end` | 2008-04-08 | `{"end_rule":"SEPT_30"}` | prior regulation | **superseded** |
| `cap_gap_end` | 2025-01-17 | `{"end_rule":"APRIL_1"}` | H-1B Modernization Final Rule | still mis-stated across the web |
| `h1b_grace_period` | 2017-01-17 | `{"days":60}` | 8 CFR 214.1(l)(2) | elimination proposed, RIN 1615-AD22 |
| `ac21_extension_threshold` | 2000-10-17 | `{"days":365}` | AC21 §106(a) | |
| `ac21_three_year` | 2000-10-17 | `{"basis":"I140_APPROVED_PD_NOT_CURRENT"}` | AC21 §104(c) | |
| `i485_portability` | 2000-10-17 | `{"days":180}` | INA §204(j) | |
| `h1b_max_stay` | 1990-11-29 | `{"years":6}` | INA §214(g)(4) | recapture allowed |
| `lottery_selection` | 2020-03-01 | `{"method":"RANDOM"}` | - | **superseded** |
| `lottery_selection` | 2026-02-27 | `{"method":"WAGE_WEIGHTED"}` | Final Rule 2025-12-29 | first run March 2026 |
| `opt_filing_window` | 2008-04-08 | `{"before":90,"after":60,"i20_days":30}` | 8 CFR 214.2(f)(11) | |
| `opt_min_hours` | 2008-04-08 | `{"hours":20}` | SEVP guidance | below this, you are unemployed |

Fill `verified_by` and `verified_at` for each. An unverified row should not render in the UI without a visible warning - the entire pitch is that other people's numbers are stale.

---

## 4. ClickHouse schema

```sql
-- ---------- The corpus ----------

CREATE TABLE lca_filings (
  case_number      String,
  case_status      LowCardinality(String),
  received_date    Date,
  decision_date    Date,
  begin_date       Date,
  end_date         Date,
  employer_name    String,
  employer_fein    String,
  soc_code         LowCardinality(String),
  soc_title        String,
  job_title        String,
  full_time        UInt8,
  worksite_city    String,
  worksite_state   LowCardinality(String),
  worksite_msa     String,
  wage_rate_from   Decimal(12,2),
  wage_unit        LowCardinality(String),
  prevailing_wage  Decimal(12,2),
  pw_level         UInt8,
  fiscal_year      UInt16,
  annualized_wage  Decimal(12,2) MATERIALIZED
    multiIf(wage_unit = 'Year',      wage_rate_from,
            wage_unit = 'Hour',      wage_rate_from * 2080,
            wage_unit = 'Month',     wage_rate_from * 12,
            wage_unit = 'Week',      wage_rate_from * 52,
            wage_unit = 'Bi-Weekly', wage_rate_from * 26,
            wage_rate_from)
) ENGINE = MergeTree
ORDER BY (soc_code, worksite_state, fiscal_year, employer_fein);

CREATE TABLE perm_filings (
  case_number      String,
  case_status      LowCardinality(String),
  received_date    Date,
  decision_date    Date,
  employer_name    String,
  employer_fein    String,
  soc_code         LowCardinality(String),
  worksite_state   LowCardinality(String),
  wage_offer       Decimal(12,2),
  country_of_citizenship LowCardinality(String),
  class_of_admission LowCardinality(String),
  fiscal_year      UInt16,
  days_to_decision UInt16 MATERIALIZED dateDiff('day', received_date, decision_date)
) ENGINE = MergeTree
ORDER BY (employer_fein, received_date);

-- Monthly Visa Bulletin cutoffs. Small in rows, pure time series in shape.
CREATE TABLE visa_bulletin (
  bulletin_month   Date,
  category         LowCardinality(String),
  country_chg      LowCardinality(String),
  final_action_date Nullable(Date),
  filing_date      Nullable(Date),
  is_current       UInt8
) ENGINE = MergeTree
ORDER BY (category, country_chg, bulletin_month);

-- ---------- The loop ----------

-- Append-only. Every clock, every user, every day. Never deleted.
CREATE TABLE clock_evaluations (
  evaluated_at        DateTime,
  eval_date           Date MATERIALIZED toDate(evaluated_at),
  user_id             UUID,
  clock_key           LowCardinality(String),
  days_remaining      Int32,
  days_consumed       Int32,
  denominator         Int32,
  severity            LowCardinality(String),
  rule_id             UUID,
  rule_key            LowCardinality(String),
  rule_effective_from Date,
  inputs_hash         String,           -- detects whether inputs or the rule moved
  engine_version      LowCardinality(String)
) ENGINE = MergeTree
PARTITION BY toYYYYMM(evaluated_at)
ORDER BY (user_id, clock_key, evaluated_at);

-- ---------- Intake support ----------

CREATE TABLE soc_embeddings (
  soc_code    LowCardinality(String),
  soc_title   String,
  variant     String,                    -- observed job titles from lca_filings
  embedding   Array(Float32)
) ENGINE = MergeTree
ORDER BY soc_code;

-- ---------- CDC targets (replicated from Postgres via PeerDB) ----------
-- users, status_periods, employment_episodes, gc_milestones, rules
-- ReplacingMergeTree ORDER BY (id) with a version column
```

### Materialized views

```sql
-- Wage distribution by occupation × state × year. Powers lottery odds.
CREATE MATERIALIZED VIEW wage_baselines
ENGINE = AggregatingMergeTree
ORDER BY (soc_code, worksite_state, fiscal_year)
AS SELECT
  soc_code, worksite_state, fiscal_year,
  count()                              AS filings,
  quantileState(0.10)(annualized_wage) AS p10,
  quantileState(0.25)(annualized_wage) AS p25,
  quantileState(0.50)(annualized_wage) AS p50,
  quantileState(0.75)(annualized_wage) AS p75,
  quantileState(0.90)(annualized_wage) AS p90,
  avgState(pw_level)                   AS avg_level
FROM lca_filings
WHERE case_status = 'CERTIFIED'
GROUP BY soc_code, worksite_state, fiscal_year;

-- Employer sponsorship behaviour. Powers "will they actually file for me."
CREATE MATERIALIZED VIEW employer_profiles
ENGINE = AggregatingMergeTree
ORDER BY (employer_fein, fiscal_year)
AS SELECT
  employer_fein,
  any(employer_name)   AS employer_name,
  fiscal_year,
  count()              AS lca_count,
  uniqState(soc_code)  AS distinct_socs,
  avgState(annualized_wage) AS avg_wage,
  maxState(received_date)   AS latest_filing
FROM lca_filings
WHERE case_status = 'CERTIFIED'
GROUP BY employer_fein, fiscal_year;

-- Daily population risk. Powers the operator view and the rule-change diff.
CREATE MATERIALIZED VIEW risk_rollup
ENGINE = SummingMergeTree
ORDER BY (eval_date, clock_key, severity)
AS SELECT
  eval_date, clock_key, severity, count() AS users
FROM clock_evaluations
GROUP BY eval_date, clock_key, severity;
```

---

## 5. The clock engine

A pure function over Postgres state plus the governing rule set. No side effects except the append to `clock_evaluations`.

```
evaluate(user_id, as_of) -> Clock[]

for each applicable clock_key:
    rule    = resolve_rule(clock_key, as_of)
    prior   = resolve_rule(clock_key, as_of - 1 year)   # for the stale-advice callout
    result  = compute(clock_key, user_state, rule.params)
    emit Clock {
        days_remaining, days_consumed, denominator, severity,
        rule.citation, rule.effective_from, rule.source_url,
        superseded: prior if prior.id != rule.id else None
    }
    append to clock_evaluations
```

**Rule resolution:**

```sql
SELECT * FROM rules
WHERE rule_key = $1
  AND effective_from <= $2
  AND (effective_to IS NULL OR effective_to > $2)
ORDER BY effective_from DESC
LIMIT 1;
```

**Clocks, in build order:**

1. **`opt_unemployment`** - walk employment episodes chronologically, sum gap days where the person had no episode with `hours_per_week >= 20 AND counts_as_employment`. Ceiling is 90, or 150 with a STEM extension. Days continue accruing during cap-gap.
2. **`cap_gap_window`** - resolve `cap_gap_end` for the user's dates. **This is the demo.** Under the pre-2025 version the window closes September 30; under the current version it runs to April 1. Same user, same facts, thirteen weeks of difference.
3. **`h1b_grace_period`** - 60 days from employment end. Flag that elimination is under review.
4. **`ac21_365`** - days until (six-year mark − 365). If no PERM or I-140 is on file by then, extensions beyond year six are unavailable. Most people have no visibility into their employer's filing.
5. **`i485_portability`** - 180 days from I-485 filing, after which job changes to a same-or-similar occupation are permitted.
6. **`h1b_max_stay`** - six years minus recaptured time abroad.
7. **`opt_filing_window`** - 90 days before to 60 days after program end, and USCIS must receive the application within 30 days of the DSO's I-20 recommendation.

**Nightly job:** re-evaluate every user, append every result, regenerate alerts in a single Postgres transaction. `inputs_hash` distinguishes "your facts changed" from "the law changed" - a distinction the UI surfaces explicitly, and one no other tool in the space can make because no other tool retains yesterday's evaluation.

---

## 6. LibreChat agent architecture

Agent Builder, model `claude-sonnet-4-6`, ClickHouse MCP server plus a small custom MCP for the Postgres side.

### Agents

| Agent | Job |
|---|---|
| **Intake** | Guided date extraction. Reads uploaded documents, asks branching questions, writes to Postgres via tools, always shows what it wrote for confirmation. |
| **Clock** | Answers "where do I stand" from computed evaluations. Never states a number without its citation and effective date. |
| **Corpus** | Runs ClickHouse aggregations - wage percentiles, employer profiles, bulletin movement. |
| **Verify** | Takes a claim the user was given and checks it against the rule version table. |

Route through a thin supervisor that picks the sub-agent and enforces the citation contract on every response.

### Tools

| Tool | Backed by | Returns |
|---|---|---|
| `get_my_clocks(user_id)` | Postgres + CH | active countdowns with full provenance |
| `explain_rule(rule_key, as_of)` | Postgres | governing version + complete version history |
| `check_claim(text, rule_key)` | Postgres + vector | which version the claim matches, and when it was superseded |
| `wage_percentile(soc, state, wage)` | ClickHouse | position in the certified LCA distribution |
| `employer_profile(name_or_fein)` | ClickHouse | filing volume, wage bands, recency |
| `resolve_soc(free_text)` | CH vector search | ranked SOC candidates with scores |
| `bulletin_movement(cat, country)` | ClickHouse | cutoff date history and movement rate |
| `what_if(scenario)` | engine | recomputed clocks under a hypothetical |
| `record_fact(user_id, kind, payload)` | Postgres | writes an extracted date, returns it for confirmation |

### System prompt contract

- Never state a rule without citation, authority, and effective date.
- When sources conflict, say so and name the governing version.
- Never assert a date the user has not confirmed - echo extractions back.
- Respond in the user's locale without degrading citation fidelity.
- Close with: this is information, not legal advice.

---

## 7. UI

### Design direction

**Subject.** The world this product lives in is bureaucratic paper: receipt notices, I-94 printouts, visa foils, date stamps, security paper. The user's emotional state is dread of a number they cannot see. The design job is to make that paper legible without making it feel casual - this is not a productivity app, and softening it into one would be a lie about the stakes.

**The thesis, stated as a rule:** every number is traceable, so every number carries its citation *in the same visual unit*. Provenance is not a tooltip. It is part of the typographic object.

**Palette** - drawn from security paper and passport stamps, not from a UI kit.

```
--paper    #F1F3EE   pale green-grey, the colour of a check or a certificate
--ink      #16191C   near-black document ink, all body text
--stamp    #2B4C7E   passport-stamp blue: structure, labels, links
--clear    #3F7D58   muted document green: a clock in good standing
--urgent   #B03A2E   stamp red: critical only, never decorative
--rule     #8A9187   hairlines, field labels, dividers
```

Red is rationed. If more than one thing on screen is red, the design has failed and so has the user's situation.

**Type** - three roles, deliberately split.

- **Display:** a tight condensed grotesque (Archivo Condensed or similar) for screen titles and field headers. Reads as form header, not as marketing.
- **Body:** Inter, 15/22, for prose and explanation.
- **Data:** IBM Plex Mono, tabular figures, for *every date and every count in the product*. This is the signature decision. Numbers never render in a proportional face anywhere. It gives the whole product the cadence of an official record and makes counts visually scannable in a column.

**Signature element - the Field Card.** Each countdown renders as a document field: a hairline-boxed unit with a small-caps eyebrow (the clock name), the count set enormous in tabular mono, a denominator in `--rule`, and beneath a hairline divider, the citation and its effective date in 11px mono. The provenance is inside the box, always, non-optional.

```
┌──────────────────────────────────────────┐
│ UNEMPLOYMENT DAYS                        │
│                                          │
│   71 / 90                                │
│   19 days remaining                      │
│                                          │
│ ─────────────────────────────────────    │
│ 8 CFR 214.2(f)(10)  ·  eff. 2008-04-08   │
└──────────────────────────────────────────┘
```

**Second signature - the strikethrough.** When a governing rule has been superseded, the old value renders struck through above the current one, with the supersession date. This is the stale-advice beat as a visual device rather than a modal, and it should appear inline in the Field Card, not in a separate "what changed" screen.

```
┌──────────────────────────────────────────┐
│ CAP-GAP WINDOW                           │
│                                          │
│   ̶S̶E̶P̶ ̶3̶0̶ ̶2̶0̶2̶6̶                            │
│   APR 01 2027                            │
│   216 days of work authorization         │
│                                          │
│ ─────────────────────────────────────    │
│ H-1B Modernization Final Rule            │
│ eff. 2025-01-17 · supersedes 2008 rule   │
└──────────────────────────────────────────┘
```

**Motion.** One orchestrated moment, nothing scattered. On load, counts tick from zero to value over ~400ms with tabular figures holding width so nothing reflows - it reads as *computed*, not typed. The strikethrough draws left to right, once, on first reveal of a superseded rule. Everything else is static. `prefers-reduced-motion` disables both and renders final values immediately.

### Screens

**1 · Clock Wall** - the home screen and the whole product in one view.

```
┌────────────────────────────────────────────────────────────┐
│  STATUS CLOCK                          Maria O.  ·  ES  ▾  │
├────────────────────────────────────────────────────────────┤
│  As of 28 Aug 2026 · 7 clocks · 1 needs attention          │
│                                                            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ UNEMPLOYMENT │ │ CAP-GAP      │ │ AC21 · 365   │        │
│  │  71 / 90     │ │  APR 01 2027 │ │  38 days     │  ◀ red │
│  │  19 left     │ │  216 days    │ │  no PERM     │        │
│  │ ──────────── │ │ ──────────── │ │ ──────────── │        │
│  │ 8 CFR 214.2  │ │ eff 2025-01  │ │ AC21 §106(a) │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
│                                                            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ I-94 EXPIRY  │ │ H-1B MAX     │ │ PORTABILITY  │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
│                                                            │
│  ─────────────────────────────────────────────────────     │
│  ⚑ One clock is governed by a rule that changed.           │
│    Review what changed →                                   │
└────────────────────────────────────────────────────────────┘
```

Cards sort by urgency, never alphabetically. A card in good standing uses `--clear` on its count; warn uses ink with an amber hairline; critical uses `--urgent` and moves to position one.

**2 · Timeline** - status history on one axis, rule changes on another.

Horizontal band showing status periods as filled segments (F-1 → OPT → STEM OPT → cap-gap), employment episodes as a second track above, unemployment gaps rendered as voids in `--urgent` at 15% opacity. Below the axis, rule-change markers as vertical stamp-blue rules with dates.

The insight this screen delivers, which no competitor's screen does: **where your history and the law's history intersect.** A vertical line at 2025-01-17 crossing your OPT period is the moment your cap-gap answer changed. Hovering a gap shows the exact days it cost you.

**3 · Rule Detail** - the version stack.

Reached from any Field Card's citation line. Shows the full chain of a rule as a vertical stack, newest at top, each version with effective window, parameters, authority, source link, and who on the team verified it. Superseded versions render at 60% opacity with the strikethrough treatment. Unverified rules render with a visible warning band - the product does not pretend to certainty it hasn't earned.

**4 · Ask** - LibreChat, embedded, full height.

Not a corner bubble. A peer surface reachable from the top nav, because for many users it is the primary interface, not a helper. When the agent cites a rule, the citation renders as the same small-caps mono treatment used on Field Cards and links through to Rule Detail. Language switcher lives in the header, not buried in settings.

**5 · Intake** - conversational, one question at a time.

No multi-field form. A single question, a large input, and where relevant a document drop zone. Above the input, a running list of what has been captured so far, each item editable and each tagged with its confidence: `document verified` in `--clear`, `you told us` in `--rule`, `we inferred` in stamp blue with a "confirm this" affordance.

**6 · Standing** - the corpus view.

Where the ClickHouse aggregations surface to the user. Wage percentile against certified LCAs for the person's occupation and state, rendered as a distribution with a marker at their position and the wage-level cut points labelled. Beneath it, what the current selection method means for them and what wage would move them a tier. This screen exists to answer one question honestly: *what are my actual odds.*

### Copy rules

Name things by what the person controls. "Unemployment days," never "gap accumulation metric." Actions say what happens: "Add a job," not "Submit." Empty states direct: "No employment on file. Add your first job to start the unemployment count." Errors state what went wrong and what to do: "These dates overlap an existing status period ending 12 Mar 2026. Adjust one of them." No apologies, no vagueness, no exclamation marks anywhere in the product.

### Quality floor

Responsive to 375px - the Clock Wall stacks to one column, cards keep full provenance. Visible keyboard focus in `--stamp`. Reduced motion respected. Every count reachable and readable by screen reader with its citation as an accessible description.

---

## 8. Demo script

**The person.** Not an engineer. A home health aide on STEM OPT, or an adjunct instructor on H-1B. Four countdowns running, none visible to her. Establish stakes in twenty seconds and move.

**The stale-advice beat.** Two personas, identical graduation dates. One was told cap-gap ends September 30 - that is what her DSO's handout says. Show the Field Card resolve the governing version, strike the old date, and reveal April 1. Thirteen weeks of work authorization that one of them didn't know she had, and the other planned around losing.

**The wall.** One screen, seven clocks, one red. AC21 at 38 days with no PERM filed - a deadline set by an employer's inaction that she cannot see from inside her own life.

**The corpus, in Spanish.** Ask the agent whether her wage clears the bar. It hits ClickHouse, returns her percentile against millions of certified filings for her occupation and state, and answers with the citation attached, in her language.

**The architecture.** Postgres holds the person and enforces that her history is coherent. ClickHouse holds the corpus and every evaluation ever made, which is how the product knows the day her rule changed. LibreChat is how she talks to both. One slide. Then stop.

---

## 9. Known weaknesses - name them before a judge does

**Accuracy is the product.** A wrong clock is an active harm. Nothing renders without provenance; unverified rules carry a visible warning band.

**Not legal advice.** Stated once in the UI, once in the agent contract. Not repeated, because repetition reads as fear.

**Rubric risk.** "Improving lives" reads weaker for visa holders than for children who can't read. Countered by persona choice: the same clocks govern home health aides, hotel workers, and adjuncts, and falling out of status means losing a life you built.

**Cold start.** The corpus is real; the user base is not. Say plainly that evaluation-history claims are demonstrated on seeded users, and show the query that would run at scale rather than pretending the scale exists.

**Entity resolution.** Matching employer names to FEINs across the OFLC corpus is genuinely messy. Handle the common cases, show confidence, let users correct.

---

## 10. Data sources

- **DOL OFLC Performance Data** - LCA (H-1B) and PERM disclosure files, quarterly, by fiscal year
- **USCIS H-1B Employer Data Hub** - approvals and denials by employer and year
- **State Department Visa Bulletin** - monthly cutoff dates, full archive
- **Rule citations** - Federal Register, 8 CFR, INA, USCIS Policy Manual, ICE SEVP guidance

Verify every rule against its primary source. The entire pitch is that other people's numbers are stale. Do not ship a stale number.
