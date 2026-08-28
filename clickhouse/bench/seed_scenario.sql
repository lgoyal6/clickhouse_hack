-- The counterfactual half of the replay.
--
-- One clock, one as_of, every user, evaluated under a rule that has NOT taken effect:
-- the proposed elimination of the H-1B 60-day grace period, RIN 1615-AD22.
--
-- This is the half the build spec's query cannot produce. Its argMaxIf reads history
-- back, and no history exists under a rule that has not happened, so it returns zero
-- rows for exactly the case it was written for. See docs/REVIEW.md A1.
--
-- Parameters: {as_of:Date}

INSERT INTO clock_evaluations
  (evaluated_at, as_of, eval_date, user_id, clock_key, scenario_id, applicable,
   not_applicable_reason, days_remaining, days_consumed, denominator, severity,
   rule_id, rule_key, rule_effective_from, inputs_hash, engine_version)
SELECT
    evaluated_at + toIntervalMinute(5)          AS evaluated_at,
    as_of, eval_date, user_id, clock_key,
    'rule:h1b_grace_0d'                         AS scenario_id,
    applicable, not_applicable_reason,
    0                                           AS days_remaining,   -- grace eliminated
    days_consumed, 0                            AS denominator,
    'critical'                                  AS severity,
    rule_id, rule_key, rule_effective_from, inputs_hash, engine_version
FROM clock_evaluations
WHERE clock_key = 'h1b_grace_period'
  AND scenario_id = 'actual'
  AND as_of = {as_of:Date};
