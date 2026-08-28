"""Per-fiscal-year OFLC column maps.

One canonical target schema, one map per source vintage. See ingest/README.md and
docs/REVIEW.md C1.

THESE MAPS ARE UNVERIFIED. Nobody has run them against a real file yet. Print the
actual headers first:

    python -m ingest.headers path/to/LCA_Disclosure_Data_FY2025_Q4.xlsx

and correct the map before loading. A silently mismapped wage column is the worst
outcome available here.
"""

CANONICAL = (
    "case_number", "case_status", "received_date", "decision_date",
    "begin_date", "end_date", "employer_name", "employer_fein",
    "soc_code", "soc_title", "job_title", "full_time",
    "worksite_city", "worksite_state", "worksite_msa",
    "wage_rate_from", "wage_unit", "prevailing_wage", "pw_level",
)

# FY2020 onward. Column names in the modern disclosure files.
LCA_MODERN = {
    "case_number": "CASE_NUMBER",
    "case_status": "CASE_STATUS",
    "received_date": "RECEIVED_DATE",
    "decision_date": "DECISION_DATE",
    "begin_date": "BEGIN_DATE",
    "end_date": "END_DATE",
    "employer_name": "EMPLOYER_NAME",
    "employer_fein": None,            # verify: may be absent. REVIEW C2.
    "soc_code": "SOC_CODE",
    "soc_title": "SOC_TITLE",
    "job_title": "JOB_TITLE",
    "full_time": "FULL_TIME_POSITION",
    "worksite_city": "WORKSITE_CITY",
    "worksite_state": "WORKSITE_STATE",
    "worksite_msa": None,             # verify per year. REVIEW C3.
    "wage_rate_from": "WAGE_RATE_OF_PAY_FROM",
    "wage_unit": "WAGE_UNIT_OF_PAY",
    "prevailing_wage": "PREVAILING_WAGE",
    "pw_level": "PW_WAGE_LEVEL",
}

# FY2019 and earlier used a different vintage of names.
LCA_LEGACY = {
    **LCA_MODERN,
    "case_number": "CASE_NUMBER",
    "case_status": "CASE_STATUS",
    "wage_rate_from": "WAGE_RATE_OF_PAY_FROM",
    "wage_unit": "WAGE_UNIT_OF_PAY",
    "pw_level": "PW_WAGE_LEVEL",
    "worksite_city": "WORKSITE_CITY",
    "worksite_state": "WORKSITE_STATE",
}

LCA_MAPS = {
    2019: LCA_LEGACY,
    2020: LCA_MODERN, 2021: LCA_MODERN, 2022: LCA_MODERN,
    2023: LCA_MODERN, 2024: LCA_MODERN, 2025: LCA_MODERN, 2026: LCA_MODERN,
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
