-- The loop.
--
-- Append-only. Every clock, every user, every day, plus every replay scenario.
--
-- scenario_id is the column that turns the rule-change diff into an actual
-- counterfactual. The spec's marquee query reads historical rows and labels the
-- pre-cutover ones "under the old rule", which returns nothing for a rule that has
-- not taken effect yet, and that is the exact case the demo uses. It also subtracts
-- days-remaining values measured from different calendar days. See REVIEW A1.

CREATE TABLE IF NOT EXISTS clock_evaluations (
  evaluated_at        DateTime,
  as_of               Date,               -- the date the clock was computed FOR
  eval_date           Date,               -- the date it was computed ON
  user_id             UUID,
  clock_key           LowCardinality(String),
  scenario_id         LowCardinality(String) DEFAULT 'actual',
  applicable          UInt8,              -- REVIEW B11: not every clock runs for everyone
  not_applicable_reason LowCardinality(String) DEFAULT '',
  days_remaining      Nullable(Int32),
  days_consumed       Nullable(Int32),
  denominator         Nullable(Int32),
  severity            LowCardinality(String),
  rule_id             UUID,
  rule_key            LowCardinality(String),
  rule_effective_from Date,
  inputs_hash         String,             -- facts only; excludes as_of and rule params
  engine_version      LowCardinality(String)
) ENGINE = MergeTree
PARTITION BY toYYYYMM(as_of)
ORDER BY (user_id, clock_key, scenario_id, as_of);

-- The population query filters on clock_key across every user, so the primary
-- index above cannot help it. Rather than choosing one ordering, keep both and
-- benchmark them. The timings belong on the architecture slide. See REVIEW B1.
ALTER TABLE clock_evaluations ADD PROJECTION IF NOT EXISTS by_clock (
  SELECT * ORDER BY (clock_key, scenario_id, as_of, user_id)
);

CREATE TABLE IF NOT EXISTS soc_embeddings (
  soc_code    LowCardinality(String),
  soc_title   String,
  variant     String,
  source      LowCardinality(String),     -- 'soc_title' | 'onet_alt' | 'lca_job_title'
  embedding   Array(Float32)
) ENGINE = MergeTree
ORDER BY soc_code;
