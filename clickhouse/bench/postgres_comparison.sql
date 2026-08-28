-- The same query in Postgres, at one tenth the scale.
--
-- docs/BUILD_SPEC.md 2.2 claims the population replay "runs in seconds in ClickHouse
-- and is a multi-hour disaster anywhere else." That is an adjective. This makes it a
-- number.
--
-- Built at 12,775,000 rows rather than 127,750,000 because 127M rows of this shape is
-- roughly 15 GB in Postgres heap plus indexes, which does not fit the demo machine.
-- Report the measured figure and the scale it was measured at; extrapolate explicitly
-- or not at all.
--
-- This is NOT a criticism of Postgres. It is the point of the architecture: Postgres
-- holds the person and enforces that her history is coherent, which ClickHouse cannot
-- do at all, and ClickHouse holds every evaluation ever made, which Postgres is not
-- shaped for. Each is being asked to do the thing it is for.

DROP TABLE IF EXISTS bench_evaluations;

CREATE TABLE bench_evaluations (
  as_of           DATE        NOT NULL,
  user_id         UUID        NOT NULL,
  clock_key       TEXT        NOT NULL,
  scenario_id     TEXT        NOT NULL,
  applicable      BOOLEAN     NOT NULL,
  days_remaining  INTEGER,
  days_consumed   INTEGER,
  denominator     INTEGER,
  severity        TEXT        NOT NULL,
  inputs_hash     TEXT        NOT NULL,
  engine_version  TEXT        NOT NULL
);

-- 5,000 users x 7 clocks x 365 days = 12,775,000
INSERT INTO bench_evaluations
SELECT
  DATE '2025-08-29' + d                                              AS as_of,
  ('00000000-0000-4000-9000-' || lpad(to_hex(u), 12, '0'))::uuid     AS user_id,
  ck                                                                 AS clock_key,
  'actual'                                                           AS scenario_id,
  true,
  den - ((u * 7 + c + d) % den)                                      AS days_remaining,
  (u * 7 + c + d) % den                                              AS days_consumed,
  den,
  CASE WHEN den - ((u * 7 + c + d) % den) <= 14  THEN 'critical'
       WHEN den - ((u * 7 + c + d) % den) <= 45  THEN 'warn'
       WHEN den - ((u * 7 + c + d) % den) <= 120 THEN 'info'
       ELSE 'clear' END                                              AS severity,
  md5(u::text), '0.1.0'
FROM generate_series(0, 4999) u,
     generate_series(0, 364)  d,
     LATERAL (
       SELECT c, ck, den FROM (VALUES
         (0,'opt_unemployment',150),(1,'cap_gap_window',243),(2,'h1b_grace_period',60),
         (3,'ac21_365',365),(4,'i485_portability',180),(5,'h1b_max_stay',2191),
         (6,'opt_filing_window',150)
       ) AS t(c, ck, den)
     ) clocks;

-- The counterfactual half.
INSERT INTO bench_evaluations
SELECT as_of, user_id, clock_key, 'rule:h1b_grace_0d', applicable,
       0, days_consumed, 0, 'critical', inputs_hash, engine_version
FROM bench_evaluations
WHERE clock_key = 'h1b_grace_period' AND scenario_id = 'actual'
  AND as_of = DATE '2026-08-01';

CREATE INDEX bench_by_clock ON bench_evaluations (clock_key, scenario_id, as_of);
ANALYZE bench_evaluations;
