-- Exact position of one wage in the certified LCA distribution.
--
-- A SCAN, not an interpolation. wage_baselines stores quantile states, which give
-- value-at-quantile; the product asks the inverse. Interpolating between five stored
-- cut points is a guess with a citation attached, which is the sin this product
-- exists to oppose. See docs/REVIEW.md A6.
--
-- Keys on soc_code_norm. The corpus carries both '15-1252.00' and bare '15-1252' for
-- the same occupation, 74,504 rows against 547, so querying the raw column returns a
-- confident percentile computed over 1% of the data.
--
-- Filters case_status_norm, because the source value is 'Certified' and not
-- 'CERTIFIED'. The uppercase comparison in the build spec matches zero rows.
--
-- Parameters: {soc:String} {state:String} {wage:Decimal(16,2)} {fy:UInt16}

-- DO NOT echo a parameter back under a column's own name. ClickHouse resolves
-- SELECT aliases inside WHERE, so `{fy:UInt16} AS fiscal_year` made the predicate
-- `WHERE fiscal_year = {fy:UInt16}` compare the parameter to itself: always true,
-- filter silently gone, percentile computed across every fiscal year while claiming
-- one. The same shadowing bug bit employer_profiles at create time and wage_level at
-- query time. The API already knows what it asked for; SQL returns only results.
SELECT
    any(soc_title)                          AS soc_title,
    count()                                 AS n_filings,
    round(100 * countIf(annualized_wage <= {wage:Decimal(16,2)}) / count(), 1) AS percentile,
    round(quantileExact(0.10)(annualized_wage)) AS p10,
    round(quantileExact(0.25)(annualized_wage)) AS p25,
    round(quantileExact(0.50)(annualized_wage)) AS p50,
    round(quantileExact(0.75)(annualized_wage)) AS p75,
    round(quantileExact(0.90)(annualized_wage)) AS p90
FROM lca_filings
WHERE case_status_norm = 'CERTIFIED'
  AND soc_code_norm  = {soc:String}
  AND worksite_state = {state:String}
  AND fiscal_year    = {fy:UInt16}
  AND wage_suspect   = 0;

-- Render n_filings alongside the percentile, ALWAYS. A percentile over eleven
-- filings is not a percentile, and this product does not get to hide a sample size.
--
-- The percentile is CONTEXT, not the answer to "what are my odds". The wage-weighted
-- selection mechanism is understood to weight by OES wage LEVEL relative to the
-- prevailing wage for the occupation and area, which is a different number and can
-- point the opposite way. Use clickhouse/queries/wage_level.sql for that.
-- See docs/REVIEW.md B10.
