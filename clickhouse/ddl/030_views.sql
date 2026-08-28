-- Materialized views.
--
-- Four deliberate departures from docs/BUILD_SPEC.md 4:
--
--   1. Every filter uses `case_status_norm = 'CERTIFIED'`. The source value is
--      'Certified'. The spec's `case_status = 'CERTIFIED'` matches zero rows, which
--      is an empty screen that looks like a working query.
--
--   2. Source expressions are INLINED rather than referencing the source table's
--      MATERIALIZED columns. A materialized view is a trigger over the inserted
--      block, and whether a MATERIALIZED column is visible there is a
--      version-sensitive detail. Inlining costs nothing. See REVIEW A5.
--
--   3. Aggregates use -State combinators. A plain count() or any() inside an
--      AggregatingMergeTree is not an aggregate state and collapses on merge.
--      See REVIEW B2.
--
--   4. wage_histogram exists because quantile states give value-at-quantile and the
--      product asks the inverse. See REVIEW A6.
--
--   5. Every view groups by `soc_code_norm`, not `soc_code`. The source carries both
--      '15-1252.00' and bare '15-1252' for the same occupation, 74,504 rows against
--      547. Grouping on the raw column splits every occupation in two and hands back
--      a percentile computed over the smaller half.
--
-- ORDERING: a materialized view only sees inserts that arrive AFTER it is created.
-- ingest/load.py refuses to load until these exist. See REVIEW A5.
--
-- SCOPE DECISION, stated so it is reversible: only 'CERTIFIED' is included.
-- 'CERTIFIED - WITHDRAWN' was certified by DOL and then withdrawn, so the wage was
-- offered but the job may not have happened. data_quality.sql reports how many rows
-- that excludes so the choice stays visible rather than buried.

DROP VIEW IF EXISTS wage_baselines;
DROP VIEW IF EXISTS wage_histogram;
DROP VIEW IF EXISTS employer_profiles;
DROP VIEW IF EXISTS wage_levels;

CREATE MATERIALIZED VIEW wage_baselines
ENGINE = AggregatingMergeTree
ORDER BY (soc_code, worksite_state, fiscal_year)
AS SELECT
  soc_code_norm AS soc_code, worksite_state, fiscal_year,
  countState()                     AS filings,
  quantileState(0.10)(annualized)  AS p10,
  quantileState(0.25)(annualized)  AS p25,
  quantileState(0.50)(annualized)  AS p50,
  quantileState(0.75)(annualized)  AS p75,
  quantileState(0.90)(annualized)  AS p90
FROM (
  SELECT
    splitByChar('.', trim(BOTH ' ' FROM soc_code))[1] AS soc_code_norm,
    worksite_state, fiscal_year,
    upperUTF8(trim(BOTH ' ' FROM case_status)) AS status_norm,
    multiIf(wage_rate_from IS NULL, NULL,
            wage_unit IN ('Year','YR','Annual'),    wage_rate_from,
            wage_unit IN ('Hour','HR','Hourly'),    wage_rate_from * 2080,
            wage_unit IN ('Month','MTH','Monthly'), wage_rate_from * 12,
            wage_unit IN ('Week','WK','Weekly'),    wage_rate_from * 52,
            wage_unit IN ('Bi-Weekly','BI'),        wage_rate_from * 26,
            NULL) AS annualized
  FROM lca_filings
)
WHERE status_norm = 'CERTIFIED'
  AND annualized IS NOT NULL
  AND annualized BETWEEN 10000 AND 3000000
GROUP BY soc_code_norm, worksite_state, fiscal_year;

-- Invertible companion. Buckets of $5k, so a percentile can be read off a running
-- sum without a full scan when the corpus grows past a scan budget.
CREATE MATERIALIZED VIEW wage_histogram
ENGINE = SummingMergeTree
ORDER BY (soc_code, worksite_state, fiscal_year, bucket)
AS SELECT
  soc_code_norm AS soc_code, worksite_state, fiscal_year,
  -- assumeNotNull is safe because the WHERE below excludes NULL, and it is REQUIRED
  -- because a nullable expression cannot sit in a sorting key.
  intDiv(toUInt32(assumeNotNull(annualized)), 5000) * 5000 AS bucket,
  count() AS n
FROM (
  SELECT
    splitByChar('.', trim(BOTH ' ' FROM soc_code))[1] AS soc_code_norm,
    worksite_state, fiscal_year,
    upperUTF8(trim(BOTH ' ' FROM case_status)) AS status_norm,
    multiIf(wage_rate_from IS NULL, NULL,
            wage_unit IN ('Year','YR','Annual'),    wage_rate_from,
            wage_unit IN ('Hour','HR','Hourly'),    wage_rate_from * 2080,
            wage_unit IN ('Month','MTH','Monthly'), wage_rate_from * 12,
            wage_unit IN ('Week','WK','Weekly'),    wage_rate_from * 52,
            wage_unit IN ('Bi-Weekly','BI'),        wage_rate_from * 26,
            NULL) AS annualized
  FROM lca_filings
)
WHERE status_norm = 'CERTIFIED'
  AND annualized IS NOT NULL
  AND annualized BETWEEN 10000 AND 3000000
GROUP BY soc_code_norm, worksite_state, fiscal_year, bucket;

-- OES wage-level bands, from the prevailing wage the filing actually cited.
--
-- This is the view REVIEW B10 says the Standing screen needs. The selection
-- mechanism is understood to weight by wage LEVEL relative to the prevailing wage
-- for the occupation and area, not by percentile among peer offers, and those are
-- different numbers that can point opposite ways. The prevailing wage is annualised
-- with pw_unit, which is a different column from wage_unit.
CREATE MATERIALIZED VIEW wage_levels
ENGINE = AggregatingMergeTree
ORDER BY (soc_code, worksite_state, fiscal_year, pw_level)
AS SELECT
  soc_code_norm AS soc_code, worksite_state, fiscal_year, pw_level,
  countState()                    AS filings,
  minState(annualized_pw_calc)    AS pw_min,
  quantileState(0.50)(annualized_pw_calc) AS pw_median,
  maxState(annualized_pw_calc)    AS pw_max
FROM (
  SELECT
    splitByChar('.', trim(BOTH ' ' FROM soc_code))[1] AS soc_code_norm,
    worksite_state, fiscal_year, pw_level,
    upperUTF8(trim(BOTH ' ' FROM case_status)) AS status_norm,
    multiIf(prevailing_wage IS NULL, NULL,
            pw_unit IN ('Year','YR','Annual'),    prevailing_wage,
            pw_unit IN ('Hour','HR','Hourly'),    prevailing_wage * 2080,
            pw_unit IN ('Month','MTH','Monthly'), prevailing_wage * 12,
            pw_unit IN ('Week','WK','Weekly'),    prevailing_wage * 52,
            pw_unit IN ('Bi-Weekly','BI'),        prevailing_wage * 26,
            NULL) AS annualized_pw_calc
  FROM lca_filings
)
WHERE status_norm = 'CERTIFIED'
  AND pw_level != ''
  AND annualized_pw_calc IS NOT NULL
  AND annualized_pw_calc BETWEEN 10000 AND 3000000
GROUP BY soc_code_norm, worksite_state, fiscal_year, pw_level;

CREATE MATERIALIZED VIEW employer_profiles
ENGINE = AggregatingMergeTree
ORDER BY (employer_key, fiscal_year)
AS SELECT
  employer_key,
  -- Aliased distinctly from the source column: `anyState(employer_name) AS
  -- employer_name` shadows it, and the employer_key expression then resolves against
  -- an AggregateFunction and the view fails to create.
  anyState(raw_name)        AS employer_name_state,
  anyState(fein)            AS fein_state,
  fiscal_year,
  countState()              AS lca_count,
  uniqState(soc_code)       AS distinct_socs,
  maxState(received_date)   AS latest_filing
FROM (
  SELECT
    employer_name AS raw_name,
    employer_fein AS fein,
    lowerUTF8(trim(BOTH ' ' FROM replaceRegexpAll(employer_name,
      '(?i)[^\\w\\s]|\\b(inc|llc|l\\.l\\.c|corp|corporation|incorporated|ltd|limited|co)\\b',
      ' '))) AS employer_key,
    splitByChar('.', trim(BOTH ' ' FROM soc_code))[1] AS soc_code, received_date, fiscal_year,
    upperUTF8(trim(BOTH ' ' FROM case_status)) AS status_norm
  FROM lca_filings
)
WHERE status_norm = 'CERTIFIED' AND employer_key != ''
GROUP BY employer_key, fiscal_year;

-- Population risk. uniqState over user_id, not count(): a nightly job that runs
-- twice would otherwise inflate it with no way to tell. See REVIEW B2.
CREATE MATERIALIZED VIEW IF NOT EXISTS risk_rollup
ENGINE = AggregatingMergeTree
ORDER BY (as_of, clock_key, scenario_id, severity)
AS SELECT
  as_of, clock_key, scenario_id, severity,
  uniqState(user_id) AS users
FROM clock_evaluations
WHERE applicable = 1
GROUP BY as_of, clock_key, scenario_id, severity;
