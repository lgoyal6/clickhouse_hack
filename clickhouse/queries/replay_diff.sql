-- The rule-change diff, done as a real counterfactual.
--
-- This is the query docs/BUILD_SPEC.md 2.2 says justifies the architecture. The
-- spec's version reads history and labels pre-cutover rows "under the old rule",
-- which:
--   * returns zero rows for a PENDING rule change, because no evaluation exists
--     under a rule that has not taken effect, and a pending change is the example
--     the spec itself uses;
--   * subtracts days-remaining values measured from different calendar days;
--   * silently drops any user who joined after the cutover.
--
-- Instead: the engine runs twice for the same as_of, once with scenario_id
-- 'actual' and once with the scenario's rule overrides, and this query joins the
-- two. Both sides were computed for the same day, so the difference is the rule and
-- nothing else. See docs/REVIEW.md A1.
--
-- Parameters: {clock:String} {scenario:String} {as_of:Date}

SELECT
    a.user_id,
    a.days_remaining                        AS under_actual,
    s.days_remaining                        AS under_scenario,
    a.days_remaining - s.days_remaining     AS days_lost,
    a.severity                              AS severity_actual,
    s.severity                              AS severity_scenario,
    s.severity = 'critical' AND a.severity != 'critical' AS newly_critical
FROM (
    SELECT user_id, days_remaining, severity
    FROM clock_evaluations
    WHERE clock_key = {clock:String} AND scenario_id = 'actual'
      AND as_of = {as_of:Date} AND applicable = 1
) AS a
INNER JOIN (
    SELECT user_id, days_remaining, severity
    FROM clock_evaluations
    WHERE clock_key = {clock:String} AND scenario_id = {scenario:String}
      AND as_of = {as_of:Date} AND applicable = 1
) AS s USING (user_id)
WHERE s.days_remaining < a.days_remaining
ORDER BY days_lost DESC;

-- Put the measured cost of this on the architecture slide, not the word "seconds":
--
--   SELECT count() FROM clock_evaluations;
--   EXPLAIN indexes = 1 SELECT ... (the query above)
--
-- and run it twice, once forcing the by_clock projection and once without, so you
-- can say which access path it takes and why. See docs/REVIEW.md B1.
