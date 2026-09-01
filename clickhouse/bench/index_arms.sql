-- The comparison table for clickhouse/bench/index_arms.sh.
--
-- Same 127.75M rows, same ORDER BY, no partition key, and a minmax
-- data-skipping index on as_of instead. It exists to be the losing arm: a
-- skip index is the obvious alternative to partitioning, and measuring only
-- the option that worked would make the partition key a preference with a
-- number stapled to it.
--
-- Written out in full rather than with CREATE TABLE ... AS clock_evaluations.
-- That form silently carries over the source's PARTITION BY *and* its
-- PROJECTION even when a different ENGINE and ORDER BY are supplied, so the
-- first version of this experiment compared the partitioned table against
-- itself and reported a difference that did not exist. SHOW CREATE TABLE is
-- the check.

DROP TABLE IF EXISTS ce_skipidx;

CREATE TABLE ce_skipidx (
  evaluated_at        DateTime,
  as_of               Date,
  eval_date           Date,
  user_id             UUID,
  clock_key           LowCardinality(String),
  scenario_id         LowCardinality(String) DEFAULT 'actual',
  applicable          UInt8,
  not_applicable_reason LowCardinality(String) DEFAULT '',
  days_remaining      Nullable(Int32),
  days_consumed       Nullable(Int32),
  denominator         Nullable(Int32),
  severity            LowCardinality(String),
  rule_id             UUID,
  rule_key            LowCardinality(String),
  rule_effective_from Date,
  inputs_hash         String,
  engine_version      LowCardinality(String),
  INDEX as_of_mm as_of TYPE minmax GRANULARITY 1
) ENGINE = MergeTree
ORDER BY (user_id, clock_key, scenario_id, as_of);

INSERT INTO ce_skipidx
SELECT evaluated_at, as_of, eval_date, user_id, clock_key, scenario_id,
       applicable, not_applicable_reason, days_remaining, days_consumed,
       denominator, severity, rule_id, rule_key, rule_effective_from,
       inputs_hash, engine_version
FROM clock_evaluations
SETTINGS max_insert_threads = 4;

-- Both tables to their maximally merged state before reading storage or rows.
-- Not cosmetic: before merging, the day this query asks for happened to sit in
-- two small parts and the query read 987,694 rows. After merging it reads
-- 9,850,336, because the primary key cannot prune inside a part and a bigger
-- part means more of the month to scan. The pre-merge figure was an artifact
-- of insert order; the post-merge one is what the table actually costs.
OPTIMIZE TABLE ce_skipidx FINAL;
OPTIMIZE TABLE clock_evaluations FINAL;
