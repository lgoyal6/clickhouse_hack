-- PERM disclosure data.
--
-- Verified against the real FY2025 Q4 file: 137 columns, and a naming convention
-- with nothing in common with the LCA files. docs/BUILD_SPEC.md 4 models
-- perm_filings on LCA-style names and assumes two columns that DO NOT EXIST in the
-- current file:
--
--   country_of_citizenship  -- absent
--   class_of_admission      -- absent
--
-- Both were present in older PERM vintages and have been dropped. Any query keyed on
-- them returns nothing. This is docs/REVIEW.md C1 at its strongest: PERM and LCA are
-- not variations of one schema, they are different datasets that happen to come from
-- the same agency.
--
-- One thing PERM has that LCA does not: PRIMARY_WORKSITE_BLS_AREA, which is the
-- metro-level geography docs/REVIEW.md C3 found missing from LCA entirely.

DROP TABLE IF EXISTS perm_filings;

CREATE TABLE perm_filings (
  case_number        String,
  case_status        LowCardinality(String),
  case_status_norm   LowCardinality(String) MATERIALIZED upperUTF8(trim(BOTH ' ' FROM case_status)),
  received_date      Nullable(Date),
  decision_date      Nullable(Date),
  occupation_type    LowCardinality(String),

  employer_name      String,
  employer_name_norm String MATERIALIZED
    lowerUTF8(trim(BOTH ' ' FROM replaceRegexpAll(employer_name,
      '(?i)[^\\w\\s]|\\b(inc|llc|l\\.l\\.c|corp|corporation|incorporated|ltd|limited|co)\\b', ' '))),
  employer_fein      String,
  employer_state     LowCardinality(String),
  employer_num_payroll Nullable(UInt32),

  soc_code           LowCardinality(String),
  soc_code_norm      LowCardinality(String) MATERIALIZED
    splitByChar('.', trim(BOTH ' ' FROM soc_code))[1],
  soc_title          String,
  job_title          String,

  wage_from          Nullable(Decimal(14,2)),
  wage_to            Nullable(Decimal(14,2)),
  wage_unit          LowCardinality(String),

  worksite_city      String,
  worksite_county    String,
  worksite_state     LowCardinality(String),
  worksite_bls_area  String,              -- the metro geography LCA does not carry
  fiscal_year        UInt16,
  source_file        LowCardinality(String),

  -- Nullable Int32, not UInt16. A pending case has no decision date, and the spec's
  -- column stores 45,447 for such a row. Verified. See docs/REVIEW.md A7.
  days_to_decision   Nullable(Int32) MATERIALIZED
    if(decision_date IS NULL OR received_date IS NULL, NULL,
       dateDiff('day', received_date, decision_date)),

  annualized_wage    Nullable(Decimal(16,2)) MATERIALIZED
    multiIf(wage_from IS NULL, NULL,
            wage_unit IN ('Year','YR','Annual'),      wage_from,
            wage_unit IN ('Hour','HR','Hourly'),      wage_from * 2080,
            wage_unit IN ('Month','MTH','Monthly'),   wage_from * 12,
            wage_unit IN ('Week','WK','Weekly'),      wage_from * 52,
            wage_unit IN ('Bi-Weekly','BI'),          wage_from * 26,
            NULL)
) ENGINE = MergeTree
ORDER BY (soc_code_norm, worksite_state, fiscal_year);

-- How long PERM actually takes, which is the number the ac21_365 clock is really
-- about: whether an employer's filing will have been pending long enough in time.
CREATE MATERIALIZED VIEW IF NOT EXISTS perm_timelines
ENGINE = AggregatingMergeTree
ORDER BY (fiscal_year, case_status_key)
AS SELECT
  fiscal_year,
  upperUTF8(trim(BOTH ' ' FROM case_status)) AS case_status_key,
  countState()                                AS filings,
  quantileState(0.50)(toFloat64(dtd))         AS p50_days,
  quantileState(0.90)(toFloat64(dtd))         AS p90_days
FROM (
  SELECT fiscal_year, case_status, received_date, decision_date,
         if(decision_date IS NULL OR received_date IS NULL, NULL,
            dateDiff('day', received_date, decision_date)) AS dtd
  FROM perm_filings
)
WHERE dtd IS NOT NULL AND dtd BETWEEN 0 AND 2000
GROUP BY fiscal_year, case_status_key;
