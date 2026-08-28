"""Per-fiscal-year OFLC column maps.

One canonical target schema, one map per source vintage. See ingest/README.md and
docs/REVIEW.md C1.

VERIFIED against the real files for FY2024 Q4 and FY2025 Q4 (98 columns each,
identical headers). Three things the real data settled:

  * EMPLOYER_FEIN IS present, at index 30. docs/REVIEW.md C2 raised the possibility
    that it was absent from recent files; it is not. Coverage is a separate question,
    answered by clickhouse/queries/data_quality.sql.
  * WORKSITE_MSA does NOT exist. There is WORKSITE_COUNTY and a PW_TRACKING_NUMBER,
    and nothing else. docs/REVIEW.md C3 is confirmed: state is the contract.
  * PW_UNIT_OF_PAY is a SEPARATE column from WAGE_UNIT_OF_PAY. The prevailing wage
    carries its own unit, so comparing a raw prevailing_wage against an annualised
    offered wage compares an hourly figure to a yearly one. Both must be annualised
    independently. This is not in the build spec's schema at all.

Verify with:

    python -m ingest.headers path/to/LCA_Disclosure_Data_FY2025_Q4.xlsx
"""

CANONICAL = (
    "case_number", "case_status", "visa_class", "received_date", "decision_date",
    "begin_date", "end_date", "employer_name", "employer_fein",
    "soc_code", "soc_title", "job_title", "full_time",
    "worksite_city", "worksite_county", "worksite_state",
    "wage_rate_from", "wage_unit", "prevailing_wage", "pw_unit", "pw_level",
)

# FY2020 onward. Column names in the modern disclosure files.
LCA_MODERN = {
    "case_number": "CASE_NUMBER",
    "case_status": "CASE_STATUS",
    "visa_class": "VISA_CLASS",       # H-1B, H-1B1 Chile/Singapore, E-3 Australia
    "received_date": "RECEIVED_DATE",
    "decision_date": "DECISION_DATE",
    "begin_date": "BEGIN_DATE",
    "end_date": "END_DATE",
    "employer_name": "EMPLOYER_NAME",
    "employer_fein": "EMPLOYER_FEIN", # present. REVIEW C2 resolved.
    "soc_code": "SOC_CODE",
    "soc_title": "SOC_TITLE",
    "job_title": "JOB_TITLE",
    "full_time": "FULL_TIME_POSITION",
    "worksite_city": "WORKSITE_CITY",
    "worksite_county": "WORKSITE_COUNTY",
    "worksite_state": "WORKSITE_STATE",
    # No MSA column exists. REVIEW C3 confirmed; state is the contract.
    "wage_rate_from": "WAGE_RATE_OF_PAY_FROM",
    "wage_unit": "WAGE_UNIT_OF_PAY",
    "prevailing_wage": "PREVAILING_WAGE",
    "pw_unit": "PW_UNIT_OF_PAY",      # its OWN unit. Not the offered-wage unit.
    "pw_level": "PW_WAGE_LEVEL",
}

# FY2019 and earlier used a different vintage of names.
# FY2019 and earlier are a different vintage and have NOT been checked. Run
# ingest.headers on one before adding it here; do not assume it matches.
LCA_LEGACY = dict(LCA_MODERN)

LCA_MAPS = {
    # Verified against the real file.
    2024: LCA_MODERN, 2025: LCA_MODERN,
    # Same vintage, unverified. Run ingest.headers before loading one of these.
    2020: LCA_MODERN, 2021: LCA_MODERN, 2022: LCA_MODERN, 2023: LCA_MODERN,
    2026: LCA_MODERN,
}

# The closed set of wage units. A value outside this set means the row cannot be
# annualised and must be excluded, never coerced. REVIEW A8.
KNOWN_WAGE_UNITS = {
    "Year", "YR", "Annual",
    "Hour", "HR", "Hourly",
    "Month", "MTH", "Monthly",
    "Week", "WK", "Weekly",
    "Bi-Weekly", "BI",
}


def map_for(dataset: str, fiscal_year: int) -> dict:
    if dataset != "lca":
        raise NotImplementedError(f"no column map for {dataset!r} yet")
    try:
        return LCA_MAPS[fiscal_year]
    except KeyError:
        raise KeyError(
            f"no LCA column map for FY{fiscal_year}. Print the headers and add one "
            f"rather than guessing; see ingest/README.md."
        ) from None
