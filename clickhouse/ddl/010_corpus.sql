-- The corpus.
--
-- Two changes from docs/BUILD_SPEC.md 4 that exist to prevent silent-wrong data,
-- which is the worst failure mode this product has:
--
--   1. annualized_wage fails CLOSED. OFLC wage-unit spellings are not stable across
--      fiscal years: newer files use Year/Hour/Week/Month/Bi-Weekly, older ones use
--      YR/HR/WK/MTH/BI. The spec's multiIf falls through to the raw value, so every
--      unmatched hourly row enters the distribution as if $52.00 were an annual
--      salary and the p50 for an occupation quietly collapses. See REVIEW A8.
--
--   2. Dates that can legitimately be absent are Nullable. A missing Date lands on
--      1970-01-01, and dateDiff into a UInt16 from there is nonsense with no error.
--      See REVIEW A7.

CREATE TABLE IF NOT EXISTS lca_filings (
  case_number      String,
  case_status      LowCardinality(String),
  received_date    Date,
  decision_date    Nullable(Date),
  begin_date       Nullable(Date),
  end_date         Nullable(Date),
  employer_name    String,
  employer_name_norm String MATERIALIZED
    lowerUTF8(replaceRegexpAll(employer_name, '[^\\w\\s]|\\b(inc|llc|corp|corporation|ltd|co)\\b', '')),
  -- Nullable and NOT trusted as a key. Recent OFLC disclosure files do not
  -- reliably publish FEIN; verify the actual headers before depending on it.
  -- See REVIEW C2.
  employer_fein    Nullable(String),
  soc_code         LowCardinality(String),
  soc_title        String,
  job_title        String,
  full_time        UInt8,
  worksite_city    String,
  worksite_state   LowCardinality(String),
  worksite_msa     Nullable(String),          -- availability varies by FY. REVIEW C3.
  wage_rate_from   Nullable(Decimal(12,2)),
  wage_unit        LowCardinality(String),
  prevailing_wage  Nullable(Decimal(12,2)),
  pw_level         Nullable(UInt8),
  fiscal_year      UInt16,                    -- year of the disclosure FILE. REVIEW C4.
  source_file      LowCardinality(String),

  -- Fails closed: NULL on an unrecognised unit rather than a wrong number.
  annualized_wage  Nullable(Decimal(14,2)) MATERIALIZED
    multiIf(wage_rate_from IS NULL, NULL,
            wage_unit IN ('Year','YR','Annual'),      wage_rate_from,
            wage_unit IN ('Hour','HR','Hourly'),      wage_rate_from * 2080,
            wage_unit IN ('Month','MTH','Monthly'),   wage_rate_from * 12,
            wage_unit IN ('Week','WK','Weekly'),      wage_rate_from * 52,
            wage_unit IN ('Bi-Weekly','BI'),          wage_rate_from * 26,
            NULL),

  -- A single $150,000/hour typo moves a p90. Flag rather than silently include.
  wage_suspect     UInt8 MATERIALIZED
    if(annualized_wage IS NULL, 1,
       if(annualized_wage < 10000 OR annualized_wage > 3000000, 1, 0))
) ENGINE = MergeTree
ORDER BY (soc_code, worksite_state, fiscal_year);

CREATE TABLE IF NOT EXISTS perm_filings (
  case_number      String,
  case_status      LowCardinality(String),
  received_date    Date,
  decision_date    Nullable(Date),
  employer_name    String,
  employer_fein    Nullable(String),
  soc_code         LowCardinality(String),
  worksite_state   LowCardinality(String),
  wage_offer       Nullable(Decimal(12,2)),
  country_of_citizenship LowCardinality(String),
  class_of_admission LowCardinality(String),
  fiscal_year      UInt16,
  source_file      LowCardinality(String),
  -- Nullable Int32, not UInt16. A pending case has no decision date, and the
  -- spec's column silently reports a wrapped or clamped garbage value for every
  -- one of them. Pending cases are a large share of recent fiscal years and are
  -- the interesting ones. See REVIEW A7.
  days_to_decision Nullable(Int32) MATERIALIZED
    if(decision_date IS NULL, NULL, dateDiff('day', received_date, decision_date))
) ENGINE = MergeTree
ORDER BY (soc_code, received_date);

CREATE TABLE IF NOT EXISTS visa_bulletin (
  bulletin_month    Date,
  category          LowCardinality(String),
  country_chg       LowCardinality(String),
  final_action_date Nullable(Date),
  filing_date       Nullable(Date),
  is_current_note   LowCardinality(String)   -- 'C' / 'U' / '' as published
  -- is_current dropped: a mutable flag in a MergeTree needs an ALTER UPDATE
  -- mutation to maintain. Derive it from max(bulletin_month) instead.
) ENGINE = MergeTree
ORDER BY (category, country_chg, bulletin_month);
