-- Data quality gates. The loader runs these and refuses to proceed on a surprise.
-- Silent-wrong is the worst failure mode this product has. See docs/REVIEW.md A8.

-- 1. wage_unit must be a closed set you have enumerated. Anything new means the
--    annualisation is wrong for those rows and they are excluded rather than
--    silently mixed in.
SELECT 'unknown_wage_units' AS check, wage_unit, count() AS n
FROM lca_filings
WHERE wage_unit NOT IN ('Year','YR','Annual','Hour','HR','Hourly',
                        'Month','MTH','Monthly','Week','WK','Weekly',
                        'Bi-Weekly','BI')
GROUP BY wage_unit
ORDER BY n DESC;

-- 2. How much of the corpus is unusable for wage analysis, and why.
SELECT 'wage_usability' AS check,
       count()                                          AS total,
       countIf(annualized_wage IS NULL)                 AS unannualisable,
       countIf(wage_suspect = 1)                        AS suspect,
       round(100 * countIf(wage_suspect = 1) / count(), 2) AS suspect_pct
FROM lca_filings;

-- 3. Is employer_fein actually present? If this is mostly null, every design that
--    keys on it is wrong. Check before building on it. See docs/REVIEW.md C2.
SELECT 'fein_coverage' AS check,
       fiscal_year,
       count()                                            AS rows,
       countIf(employer_fein IS NULL OR employer_fein = '') AS missing_fein,
       round(100 * countIf(employer_fein IS NULL OR employer_fein = '') / count(), 1) AS missing_pct
FROM lca_filings
GROUP BY fiscal_year
ORDER BY fiscal_year;

-- 4. Same question for worksite_msa. See docs/REVIEW.md C3.
SELECT 'msa_coverage' AS check,
       fiscal_year,
       round(100 * countIf(worksite_msa IS NULL OR worksite_msa = '') / count(), 1) AS missing_pct
FROM lca_filings
GROUP BY fiscal_year
ORDER BY fiscal_year;

-- 5. Row counts per source file, so a partially-loaded file is visible.
SELECT 'load_coverage' AS check, source_file, fiscal_year, count() AS rows
FROM lca_filings
GROUP BY source_file, fiscal_year
ORDER BY fiscal_year, source_file;

-- 6. The materialized views must not be empty. If they are, they were created
--    after the load and saw no inserts. See docs/REVIEW.md A5.
SELECT 'mv_populated' AS check,
       (SELECT count() FROM wage_baselines)  AS wage_baselines_rows,
       (SELECT count() FROM wage_histogram)  AS wage_histogram_rows,
       (SELECT count() FROM employer_profiles) AS employer_profiles_rows;
