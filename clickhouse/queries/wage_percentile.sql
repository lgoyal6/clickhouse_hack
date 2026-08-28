-- Exact position of one wage in the certified LCA distribution.
--
-- wage_baselines stores quantileState aggregates, which give value-at-quantile.
-- This product asks the inverse. Interpolating between five stored cut points is a
-- guess with a citation attached. This is a scan, it is what ClickHouse is for, and
-- it is exact. See docs/REVIEW.md A6.
--
-- Parameters: {soc:String} {state:String} {wage:Decimal(14,2)} {fy:UInt16}

SELECT
    {soc:String}                            AS soc_code,
    {state:String}                          AS state,
    {fy:UInt16}                             AS fiscal_year,
    {wage:Decimal(14,2)}                    AS wage,
    count()                                 AS n_filings,
    round(100 * countIf(annualized_wage <= {wage:Decimal(14,2)}) / count(), 1) AS percentile,
    quantileExact(0.10)(annualized_wage)    AS p10,
    quantileExact(0.25)(annualized_wage)    AS p25,
    quantileExact(0.50)(annualized_wage)    AS p50,
    quantileExact(0.75)(annualized_wage)    AS p75,
    quantileExact(0.90)(annualized_wage)    AS p90
FROM lca_filings
WHERE case_status = 'CERTIFIED'
  AND soc_code       = {soc:String}
  AND worksite_state = {state:String}
  AND fiscal_year    = {fy:UInt16}
  AND wage_suspect   = 0;

-- Render n_filings alongside the percentile, always. A percentile over eleven
-- filings is not a percentile, and this product does not get to hide a sample size.
--
-- The percentile is CONTEXT, not the answer to "what are my odds". The
-- wage-weighted selection mechanism is believed to weight by OES wage LEVEL
-- relative to the prevailing wage for the occupation and area, which is a different
-- number and can point the opposite way: a wage at the 80th percentile of what
-- employers actually offer in a metro can still be a Level II wage. Resolve this
-- before screen 6 makes a numeric claim about anyone's odds.
-- See docs/REVIEW.md B10.
