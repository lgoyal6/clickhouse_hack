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


MAPS = {"lca": None, "perm": None}   # populated below


def map_for(dataset: str, fiscal_year: int) -> dict:
    table = {"lca": LCA_MAPS, "perm": PERM_MAPS}.get(dataset)
    if table is None:
        raise NotImplementedError(f"no column map for {dataset!r} yet")
    try:
        return table[fiscal_year]
    except KeyError:
        raise KeyError(
            f"no {dataset.upper()} column map for FY{fiscal_year}. Print the headers "
            f"and add one rather than guessing; see ingest/README.md."
        ) from None


# ---------------------------------------------------------------- PERM ----------
#
# Verified against the real FY2025 Q4 file: 137 columns, and NOT a variation of the
# LCA layout. Employer columns are EMP_*, not EMPLOYER_*; the SOC lives in
# PWD_SOC_CODE; the wage is JOB_OPP_WAGE_FROM with its own JOB_OPP_WAGE_PER unit.
#
# Two columns docs/BUILD_SPEC.md 4 models and the file DOES NOT HAVE:
#   country_of_citizenship, class_of_admission
# Both existed in older PERM vintages and are gone. Anything keyed on them returns
# nothing.

PERM_MODERN = {
    "case_number":          "CASE_NUMBER",
    "case_status":          "CASE_STATUS",
    "received_date":        "RECEIVED_DATE",
    "decision_date":        "DECISION_DATE",
    "occupation_type":      "OCCUPATION_TYPE",
    "employer_name":        "EMP_BUSINESS_NAME",
    "employer_fein":        "EMP_FEIN",
    "employer_state":       "EMP_STATE",
    "employer_num_payroll": "EMP_NUM_PAYROLL",
    "soc_code":             "PWD_SOC_CODE",
    "soc_title":            "PWD_SOC_TITLE",
    "job_title":            "JOB_TITLE",
    "wage_from":            "JOB_OPP_WAGE_FROM",
    "wage_to":              "JOB_OPP_WAGE_TO",
    "wage_unit":            "JOB_OPP_WAGE_PER",
    "worksite_city":        "PRIMARY_WORKSITE_CITY",
    "worksite_county":      "PRIMARY_WORKSITE_COUNTY",
    "worksite_state":       "PRIMARY_WORKSITE_STATE",
    # The metro-level geography the LCA files do not carry at all. REVIEW C3.
    "worksite_bls_area":    "PRIMARY_WORKSITE_BLS_AREA",
}

# FY2024 is a DIFFERENT LAYOUT AGAIN, in the same dataset, one fiscal year apart.
# Employer columns are EMPLOYER_*, the SOC is PW_SOC_CODE rather than PWD_SOC_CODE,
# the wage is WAGE_OFFER_FROM rather than JOB_OPP_WAGE_FROM, and there is no BLS area
# column at all. The loader refused the file rather than mismapping it, which is the
# whole point of the header gate. docs/REVIEW.md C1, confirmed at its strongest: the
# schema moves between CONSECUTIVE fiscal years within one dataset.
PERM_FY2024 = {
    "case_number":          "CASE_NUMBER",
    "case_status":          "CASE_STATUS",
    "received_date":        "RECEIVED_DATE",
    "decision_date":        "DECISION_DATE",
    "occupation_type":      None,
    "employer_name":        "EMPLOYER_NAME",
    "employer_fein":        "EMPLOYER_FEIN",
    "employer_state":       "EMPLOYER_STATE_PROVINCE",
    "employer_num_payroll": "EMPLOYER_NUM_EMPLOYEES",
    "soc_code":             "PW_SOC_CODE",
    "soc_title":            "PW_SOC_TITLE",
    "job_title":            "JOB_TITLE",
    "wage_from":            "WAGE_OFFER_FROM",
    "wage_to":              "WAGE_OFFER_TO",
    "wage_unit":            "WAGE_OFFER_UNIT_OF_PAY",
    "worksite_city":        "WORKSITE_CITY",
    "worksite_county":      None,
    "worksite_state":       "WORKSITE_STATE",
    "worksite_bls_area":    None,     # absent in this vintage
}

PERM_MAPS = {2024: PERM_FY2024, 2025: PERM_MODERN}
