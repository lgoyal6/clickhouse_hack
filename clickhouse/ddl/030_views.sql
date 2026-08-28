-- Materialized views.
--
-- Two deliberate departures from docs/BUILD_SPEC.md 4:
--
--   1. Source expressions are INLINED rather than referencing the source table's
--      MATERIALIZED columns. A materialized view is a trigger over the inserted
--      block, and whether a MATERIALIZED column is visible there is a
--      version-sensitive detail that has burned a lot of people. Inlining costs
--      nothing and removes the class of bug. See REVIEW A5.
--
--   2. Aggregate columns use -State combinators. A plain count() or any() inside an
--      AggregatingMergeTree is not an aggregate state and does not combine on
--      merge, so counts silently collapse to an arbitrary part's value.
--      See REVIEW B2.
--
-- NOTE ON ORDERING: a materialized view only sees inserts that arrive AFTER it is
-- created. Create these BEFORE loading the corpus, or backfill explicitly. Loading
-- 8M rows and then creating the view leaves it empty and the failure is silent.
-- ingest/load.py enforces the order. See REVIEW A5.

CREATE MATERIALIZED VIEW IF NOT EXISTS wage_baselines
ENGINE = AggregatingMergeTree
ORDER BY (soc_code, worksite_state, fiscal_year)
AS SELECT
  soc_code,
  worksite_state,
  fiscal_year,
  countState()                     AS filings,
  quantileState(0.10)(annualized)  AS p10,
  quantileState(0.25)(annualized)  AS p25,
  quantileState(0.50)(annualized)  AS p50,
  quantileState(0.75)(annualized)  AS p75,
  quantileState(0.90)(annualized)  AS p90,
  avgState(toFloat64(pw_level))    AS avg_level
FROM (
  SELECT
    soc_code, worksite_state, fiscal_year, pw_level,
    multiIf(wage_rate_from IS NULL, NULL,
            wage_unit IN ('Year','YR','Annual'),    wage_rate_from,
            wage_unit IN ('Hour','HR','Hourly'),    wage_rate_from * 2080,
            wage_unit IN ('Month','MTH','Monthly'), wage_rate_from * 12,
            wage_unit IN ('Week','WK','Weekly'),    wage_rate_from * 52,
            wage_unit IN ('Bi-Weekly','BI'),        wage_rate_from * 26,
            NULL) AS annualized,
    case_status
  FROM lca_filings
)
WHERE case_status = 'CERTIFIED'
  AND annualized IS NOT NULL
  AND annualized BETWEEN 10000 AND 3000000
GROUP BY soc_code, worksite_state, fiscal_year;

-- Invertible companion to wage_baselines.
--
-- quantileState gives value-at-quantile. The product asks the inverse: given this
-- wage, what quantile. Interpolating between five stored cut points is a guess with
-- a citation attached, which is the sin this product exists to oppose. A bucket
-- histogram IS invertible, and the exact scan in queries/wage_percentile.sql is the
-- authoritative answer. See REVIEW A6.
CREATE MATERIALIZED VIEW IF NOT EXISTS wage_histogram
ENGINE = SummingMergeTree
ORDER BY (soc_code, worksite_state, fiscal_year, bucket)
AS SELECT
  soc_code, worksite_state, fiscal_year,
  intDiv(toUInt32(annualized), 5000) * 5000 AS bucket,
  count() AS n
FROM (
  SELECT
    soc_code, worksite_state, fiscal_year, case_status,
    multiIf(wage_rate_from IS NULL, NULL,
            wage_unit IN ('Year','YR','Annual'),    wage_rate_from,
            wage_unit IN ('Hour','HR','Hourly'),    wage_rate_from * 2080,
            wage_unit IN ('Month','MTH','Monthly'), wage_rate_from * 12,
            wage_unit IN ('Week','WK','Weekly'),    wage_rate_from * 52,
            wage_unit IN ('Bi-Weekly','BI'),        wage_rate_from * 26,
            NULL) AS annualized
  FROM lca_filings
)
WHERE case_status = 'CERTIFIED'
  AND annualized IS NOT NULL
  AND annualized BETWEEN 10000 AND 3000000
GROUP BY soc_code, worksite_state, fiscal_year, bucket;

-- Employer behaviour, keyed on the normalised name rather than on FEIN, because
-- FEIN may not exist in the source. If it does, add it back as a second key.
-- See REVIEW C2.
CREATE MATERIALIZED VIEW IF NOT EXISTS employer_profiles
ENGINE = AggregatingMergeTree
ORDER BY (employer_key, fiscal_year)
AS SELECT
  lowerUTF8(replaceRegexpAll(employer_name, '[^\\w\\s]|\\b(inc|llc|corp|corporation|ltd|co)\\b', '')) AS employer_key,
  anyState(employer_name)   AS employer_name,
  fiscal_year,
  countState()              AS lca_count,
  uniqState(soc_code)       AS distinct_socs,
  maxState(received_date)   AS latest_filing
FROM lca_filings
WHERE case_status = 'CERTIFIED'
GROUP BY employer_key, fiscal_year;

-- Population risk. uniqState over user_id, not count().
--
-- count() in a SummingMergeTree counts ROWS, so a nightly job that runs twice, or
-- a backfill that replays a day, inflates population risk with no way to tell.
-- The scenario_id dimension keeps replay rows out of the actual rollup.
-- See REVIEW B2.
CREATE MATERIALIZED VIEW IF NOT EXISTS risk_rollup
ENGINE = AggregatingMergeTree
ORDER BY (as_of, clock_key, scenario_id, severity)
AS SELECT
  as_of, clock_key, scenario_id, severity,
  uniqState(user_id) AS users
FROM clock_evaluations
WHERE applicable = 1
GROUP BY as_of, clock_key, scenario_id, severity;
