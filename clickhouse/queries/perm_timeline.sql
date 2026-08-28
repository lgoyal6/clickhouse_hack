-- How long PERM actually takes, from the real corpus.
--
-- This is the number the ac21_365 clock is really about. AC21 Sec. 106(a) allows
-- one-year extensions past the sixth year when a PERM or I-140 has been PENDING 365
-- days or more. The clock derives a filing deadline from that: six-year mark minus
-- 365 days.
--
-- The corpus says the median certified PERM takes 483 days end to end. So a person
-- who files exactly at the derived deadline has a filing that is still pending at the
-- six-year mark, which is what the statute needs, but they have zero margin: the p90
-- is 512 days. Telling someone "file by 2026-10-01" without telling them that the
-- process itself runs 16 months is a true number that leaves out the part that
-- matters.
--
-- Parameters: {fy:UInt16}

SELECT
    count()                                       AS n,
    round(quantileExact(0.50)(days_to_decision))  AS median_days,
    round(quantileExact(0.75)(days_to_decision))  AS p75_days,
    round(quantileExact(0.90)(days_to_decision))  AS p90_days,
    round(min(days_to_decision))                  AS fastest_days
FROM perm_filings
WHERE case_status_norm LIKE 'CERTIFIED%'
  AND fiscal_year = {fy:UInt16}
  AND days_to_decision BETWEEN 0 AND 2000;
