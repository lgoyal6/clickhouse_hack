-- Which OES wage level an offer lands in, and what crosses into the next one.
--
-- This is the statistic the selection mechanism is understood to use, as opposed to
-- the peer percentile, which is context. A wage at the 80th percentile of what
-- employers actually offer in a metro can still be a Level II wage. See REVIEW B10.
--
-- The prevailing wage is annualised with pw_unit, which is a SEPARATE column from
-- wage_unit in the source. Comparing a raw prevailing wage against an annualised
-- offered wage compares hourly to yearly.
--
-- Parameters: {soc:String} {state:String} {fy:UInt16} {wage:Decimal(16,2)}

-- Note the alias names. `round(quantileMerge(0.50)(pw_median)) AS pw_median` would
-- shadow the source column, and the next expression referencing pw_median then
-- resolves against a Decimal instead of an AggregateFunction and the query fails.
-- The same shadowing bug bit employer_profiles at create time.
SELECT
    pw_level,
    countMerge(filings)                        AS n,
    round(quantileMerge(0.50)(pw_median))      AS prevailing_median,
    round(minMerge(pw_min))                    AS prevailing_min,
    round(maxMerge(pw_max))                    AS prevailing_max,
    round(quantileMerge(0.50)(pw_median)) <= {wage:Decimal(16,2)} AS offer_clears_median
FROM wage_levels
WHERE soc_code       = {soc:String}
  AND worksite_state = {state:String}
  AND fiscal_year    = {fy:UInt16}
GROUP BY pw_level
ORDER BY pw_level;
