-- Synthetic evaluation history at the scale docs/BUILD_SPEC.md 2.2 claims.
--
--   50,000 users x 7 clocks x 365 days = 127,750,000 rows
--
-- That is the spec's own arithmetic, reproduced so the marquee query can be measured
-- rather than described. These are SYNTHETIC EVALUATIONS, not real people: §9 of the
-- spec is explicit that the corpus is real and the user base is not, and this is how
-- you show the query that would run at scale without pretending the scale exists.
--
-- The corpus in lca_filings and perm_filings is real DOL data. This table is not.
-- Any number quoted from here is a performance number, never a product number.
--
-- Users are deterministic: user index u maps to a stable UUID, so the same person
-- appears across all 365 days, which is what makes the per-user history query real.

INSERT INTO clock_evaluations
  (evaluated_at, as_of, eval_date, user_id, clock_key, scenario_id, applicable,
   not_applicable_reason, days_remaining, days_consumed, denominator, severity,
   rule_id, rule_key, rule_effective_from, inputs_hash, engine_version)
SELECT
    toDateTime(as_of) + toIntervalHour(3)                       AS evaluated_at,
    as_of,
    as_of                                                       AS eval_date,
    -- 9-variant prefix, so synthetic users can never collide with the real demo
    -- personas at ...-8000-...a001 / ...d001. u=40961 would otherwise reproduce
    -- Maria's UUID exactly.
    toUUID(concat('00000000-0000-4000-9000-', leftPad(hex(u), 12, '0'))) AS user_id,
    clock_key,
    'actual'                                                    AS scenario_id,
    1                                                           AS applicable,
    ''                                                          AS not_applicable_reason,
    days_remaining,
    denominator - days_remaining                                AS days_consumed,
    denominator,
    multiIf(days_remaining <= 14, 'critical',
            days_remaining <= 45, 'warn',
            days_remaining <= 120, 'info', 'clear')             AS severity,
    toUUID(concat('b1e1a5f2-0000-4000-8000-', leftPad(hex(clock_idx + 1), 12, '0'))) AS rule_id,
    clock_key                                                   AS rule_key,
    toDate('2008-04-08')                                        AS rule_effective_from,
    hex(cityHash64(u))                                          AS inputs_hash,
    '0.1.0'                                                     AS engine_version
FROM (
    SELECT
        number % {users:UInt64}                                 AS u,
        intDiv(number, {users:UInt64}) % 7                      AS clock_idx,
        intDiv(intDiv(number, {users:UInt64}), 7)               AS day_idx,
        toDate('2025-08-29') + day_idx                          AS as_of,
        ['opt_unemployment','cap_gap_window','h1b_grace_period','ac21_365',
         'i485_portability','h1b_max_stay','opt_filing_window'][clock_idx + 1] AS clock_key,
        [150, 243, 60, 365, 180, 2191, 150][clock_idx + 1]      AS denominator,
        -- Cycles through the clock's range rather than decreasing monotonically.
        --
        -- A monotonic countdown floors every user: a 60-day grace clock observed over
        -- 365 days puts all 50,000 people at the floor by day 100, every severity
        -- becomes 'critical', and the replay diff has nothing to compare because both
        -- sides are pinned. Cycling keeps a realistic spread of positions at any given
        -- as_of, which is what the population queries are meant to measure.
        toInt32(denominator - toInt64((cityHash64(u, clock_idx) + day_idx) % denominator))
                                                                AS days_remaining
    FROM numbers_mt({rows:UInt64})
);
