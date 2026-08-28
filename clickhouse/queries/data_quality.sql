-- Data quality gates. Run after every load, before trusting any corpus query.
-- Silent-wrong is the worst failure mode this product has. See docs/REVIEW.md A8.

-- 1. Case status spellings. The source says 'Certified', NOT 'CERTIFIED'. Every
--    filter in the build spec used the uppercase form and would have matched zero
--    rows. This report exists so that never becomes invisible again.
SELECT 'case_status_spellings' AS check, case_status, case_status_norm, count() AS n
FROM lca_filings GROUP BY case_status, case_status_norm ORDER BY n DESC;

-- 2. SOC code spellings. The corpus carries both '15-1252.00' and bare '15-1252'.
--    Querying the raw column splits every occupation and returns a confident
--    percentile over a fraction of the data.
SELECT 'soc_code_spellings' AS check,
       countIf(position(soc_code, '.') > 0) AS with_suffix,
       countIf(position(soc_code, '.') = 0) AS bare,
       uniqExact(soc_code)      AS distinct_raw,
       uniqExact(soc_code_norm) AS distinct_normalised
FROM lca_filings;

-- 3. wage_unit must be a closed set. Anything new means those rows cannot be
--    annualised, and they are excluded rather than silently coerced.
SELECT 'unknown_wage_units' AS check, wage_unit, count() AS n
FROM lca_filings
WHERE wage_unit NOT IN ('Year','YR','Annual','Hour','HR','Hourly',
                        'Month','MTH','Monthly','Week','WK','Weekly',
                        'Bi-Weekly','BI')
GROUP BY wage_unit ORDER BY n DESC;

-- 4. Same closed-set check for PW_UNIT_OF_PAY, which is a SEPARATE column. Comparing
--    a raw prevailing wage against an annualised offered wage compares hourly to
--    yearly.
SELECT 'unknown_pw_units' AS check, pw_unit, count() AS n
FROM lca_filings
WHERE pw_unit NOT IN ('Year','YR','Annual','Hour','HR','Hourly',
                      'Month','MTH','Monthly','Week','WK','Weekly',
                      'Bi-Weekly','BI')
GROUP BY pw_unit ORDER BY n DESC;

-- 5. How much of the corpus is unusable for wage analysis, and why.
SELECT 'wage_usability' AS check,
       count()                                            AS total,
       countIf(annualized_wage IS NULL)                   AS unannualisable,
       countIf(wage_suspect = 1)                          AS suspect,
       round(100 * countIf(wage_suspect = 1) / count(), 2) AS suspect_pct,
       countIf(annualized_pw IS NULL)                     AS pw_unannualisable
FROM lca_filings;

-- 6. FEIN coverage. REVIEW C2 raised the possibility that the column was absent from
--    recent files. It is present; this is the coverage question, which is separate.
SELECT 'fein_coverage' AS check, fiscal_year, count() AS rows,
       countIf(employer_fein = '') AS missing_fein,
       round(100 * countIf(employer_fein = '') / count(), 1) AS missing_pct
FROM lca_filings GROUP BY fiscal_year ORDER BY fiscal_year;

-- 7. Scope of the certified filter, so the exclusion of 'Certified - Withdrawn' stays
--    visible rather than buried in a view definition.
SELECT 'certified_scope' AS check,
       countIf(case_status_norm = 'CERTIFIED')             AS included,
       countIf(case_status_norm = 'CERTIFIED - WITHDRAWN') AS excluded_withdrawn,
       countIf(case_status_norm NOT IN ('CERTIFIED','CERTIFIED - WITHDRAWN')) AS other
FROM lca_filings;

-- 8. Rows per source file, so a partial load is visible.
SELECT 'load_coverage' AS check, source_file, fiscal_year, count() AS rows,
       min(received_date) AS earliest, max(received_date) AS latest
FROM lca_filings GROUP BY source_file, fiscal_year ORDER BY fiscal_year;

-- 9. The materialized views must not be empty. If they are, they were created after
--    the load and saw no inserts. See docs/REVIEW.md A5.
SELECT 'mv_populated' AS check,
       (SELECT count() FROM wage_baselines)    AS wage_baselines,
       (SELECT count() FROM wage_histogram)    AS wage_histogram,
       (SELECT count() FROM wage_levels)       AS wage_levels,
       (SELECT count() FROM employer_profiles) AS employer_profiles;

-- 10. Occupation coverage. The LCA corpus is H-1B labour condition applications,
--     which are concentrated in technical occupations. It cannot answer a wage
--     question for a home health aide, and the API says so rather than estimating.
--     See docs/REVIEW.md C8.
SELECT 'occupation_coverage' AS check,
       soc_code_norm, any(soc_title) AS title, count() AS filings
FROM lca_filings WHERE case_status_norm = 'CERTIFIED'
GROUP BY soc_code_norm ORDER BY filings DESC LIMIT 8;
