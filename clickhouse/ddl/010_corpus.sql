-- The corpus.
--
-- Verified against the real DOL OFLC LCA disclosure files for FY2024 Q4 and
-- FY2025 Q4 (98 columns, identical headers). Four things the real data forced,
-- none of which are in docs/BUILD_SPEC.md 4:
--
--   1. `case_status` is 'Certified', NOT 'CERTIFIED'. Every filter in the spec (and
--      in the first draft of this file) used the uppercase form and would have
--      matched ZERO rows. `case_status_norm` normalises once so no query has to
--      guess. This is the single most dangerous kind of bug this product can have:
--      an empty result that looks like a working query.
--
--   2. `PW_UNIT_OF_PAY` is a SEPARATE column from `WAGE_UNIT_OF_PAY`. The prevailing
--      wage carries its own unit, so comparing a raw prevailing wage against an
--      annualised offered wage compares hourly to yearly. Both are annualised
--      independently here. Without this, any wage-level comparison is wrong.
--
--   3. `annualized_wage` fails CLOSED. Real unit values in these files are
--      Year / Hour / Month / Week / Bi-Weekly, but a fall-through to the raw value
--      means an unmatched hourly row enters the distribution as if $52.00 were an
--      annual salary and the p50 for an occupation quietly collapses. See REVIEW A8.
--
--   4. `WORKSITE_MSA` does not exist in the source. State is the contract.
--      See REVIEW C3. `EMPLOYER_FEIN` does exist, which REVIEW C2 doubted.
--
--   5. SOC codes appear in TWO spellings: '15-1252.00' (236,886 rows, 623 codes) and
--      bare '15-1252' (2,591 rows, 189 codes). For Software Developers that is
--      74,504 rows versus 547. Querying either spelling alone silently loses most of
--      the corpus and still returns a confident percentile, which is the exact
--      failure mode this product exists to prevent. `soc_code_norm` strips the
--      O*NET detail suffix; every view and every query keys on it.

DROP TABLE IF EXISTS lca_filings;

CREATE TABLE lca_filings (
  case_number      String,
  case_status      LowCardinality(String),
  -- Normalised once, at write time. Query this, never case_status.
  case_status_norm LowCardinality(String) MATERIALIZED upperUTF8(trim(BOTH ' ' FROM case_status)),
  visa_class       LowCardinality(String),   -- H-1B | H-1B1 Chile | E-3 Australian | ...
  received_date    Nullable(Date),
  decision_date    Nullable(Date),
  begin_date       Nullable(Date),
  end_date         Nullable(Date),
  employer_name    String,
  employer_name_norm String MATERIALIZED
    lowerUTF8(trim(BOTH ' ' FROM replaceRegexpAll(employer_name,
      '(?i)[^\\w\\s]|\\b(inc|llc|l\\.l\\.c|corp|corporation|incorporated|ltd|limited|co)\\b', ' '))),
  employer_fein    String,
  soc_code         LowCardinality(String),
  -- '15-1252.00' and '15-1252' are the same occupation. Query this, not soc_code.
  soc_code_norm    LowCardinality(String) MATERIALIZED
    splitByChar('.', trim(BOTH ' ' FROM soc_code))[1],
  soc_title        String,
  job_title        String,
  full_time        LowCardinality(String),
  worksite_city    String,
  worksite_county  String,
  worksite_state   LowCardinality(String),
  wage_rate_from   Nullable(Decimal(14,2)),
  wage_unit        LowCardinality(String),
  prevailing_wage  Nullable(Decimal(14,2)),
  pw_unit          LowCardinality(String),
  pw_level         LowCardinality(String),   -- 'I'..'IV', and blank on non-OES sources
  fiscal_year      UInt16,
  source_file      LowCardinality(String),

  annualized_wage  Nullable(Decimal(16,2)) MATERIALIZED
    multiIf(wage_rate_from IS NULL, NULL,
            wage_unit IN ('Year','YR','Annual'),      wage_rate_from,
            wage_unit IN ('Hour','HR','Hourly'),      wage_rate_from * 2080,
            wage_unit IN ('Month','MTH','Monthly'),   wage_rate_from * 12,
            wage_unit IN ('Week','WK','Weekly'),      wage_rate_from * 52,
            wage_unit IN ('Bi-Weekly','BI'),          wage_rate_from * 26,
            NULL),

  -- Annualised with pw_unit, not wage_unit. They differ on real rows.
  annualized_pw    Nullable(Decimal(16,2)) MATERIALIZED
    multiIf(prevailing_wage IS NULL, NULL,
            pw_unit IN ('Year','YR','Annual'),        prevailing_wage,
            pw_unit IN ('Hour','HR','Hourly'),        prevailing_wage * 2080,
            pw_unit IN ('Month','MTH','Monthly'),     prevailing_wage * 12,
            pw_unit IN ('Week','WK','Weekly'),        prevailing_wage * 52,
            pw_unit IN ('Bi-Weekly','BI'),            prevailing_wage * 26,
            NULL),

  -- A single $150,000/hour typo moves a p90. Flag rather than silently include.
  wage_suspect     UInt8 MATERIALIZED
    if(annualized_wage IS NULL, 1,
       if(annualized_wage < 10000 OR annualized_wage > 3000000, 1, 0)),

  -- Ratio of offer to prevailing wage. This, not the peer percentile, is the shape
  -- of the number the wage-weighted selection mechanism cares about. See REVIEW B10.
  pw_ratio         Nullable(Float64) MATERIALIZED
    if(annualized_pw IS NULL OR annualized_pw = 0 OR annualized_wage IS NULL, NULL,
       toFloat64(annualized_wage) / toFloat64(annualized_pw))
) ENGINE = MergeTree
ORDER BY (soc_code_norm, worksite_state, fiscal_year);

-- perm_filings now lives in 015_perm.sql: the real file has 137 columns and a
-- naming convention with nothing in common with LCA. See that file.

CREATE TABLE IF NOT EXISTS visa_bulletin (
  bulletin_month    Date,
  category          LowCardinality(String),
  country_chg       LowCardinality(String),
  final_action_date Nullable(Date),
  filing_date       Nullable(Date),
  is_current_note   LowCardinality(String)
) ENGINE = MergeTree
ORDER BY (category, country_chg, bulletin_month);
