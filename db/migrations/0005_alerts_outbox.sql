-- Alerts, and the evaluation outbox.

-- Alert copy is a template key plus params, not a stored English sentence.
--
-- The build spec routes localisation through a Translation agent at read time.
-- For explanatory prose that is right. For the sentence that tells someone a
-- deadline is approaching, it means nobody has ever reviewed the Spanish a user
-- actually receives. Dates and counts interpolate; the sentence is reviewed once
-- by a human. See docs/REVIEW.md G.
CREATE TABLE alert_templates (
  template_key  TEXT NOT NULL,
  locale        TEXT NOT NULL,
  headline      TEXT NOT NULL,
  detail        TEXT,
  reviewed_by   TEXT,
  reviewed_at   TIMESTAMPTZ,
  PRIMARY KEY (template_key, locale)
);

CREATE TABLE alerts (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  clock_key     TEXT NOT NULL,
  fires_on      DATE NOT NULL,
  severity      TEXT NOT NULL CHECK (severity IN ('info','warn','critical')),
  template_key  TEXT NOT NULL,
  params        JSONB NOT NULL DEFAULT '{}'::jsonb,
  rule_id       UUID REFERENCES rules(id),
  acknowledged_at TIMESTAMPTZ,
  -- Delivery. The spec has no channel at all, which is a problem for a product
  -- whose thesis is that the user is not looking. See docs/REVIEW.md H3.
  delivered_at  TIMESTAMPTZ,
  delivery_channel TEXT CHECK (delivery_channel IN ('email','sms','none')),
  UNIQUE (user_id, clock_key, fires_on)
);

CREATE INDEX alerts_due_idx ON alerts (fires_on) WHERE delivered_at IS NULL;

-- The evaluation outbox.
--
-- The spec has the engine write alerts to Postgres in a transaction and append
-- evaluations straight to ClickHouse. There is no transaction spanning both, so a
-- partial failure leaves the retained history disagreeing with the alerts, and the
-- spec's own argument is that a stale alert is active harm.
--
-- Instead: evaluations land here inside the same transaction as the alerts, and CDC
-- carries them to ClickHouse. Postgres stays the system of record for anything the
-- UI treats as authoritative. See docs/REVIEW.md B3.
CREATE TABLE clock_evaluation_outbox (
  id                  BIGSERIAL PRIMARY KEY,
  evaluated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  as_of               DATE NOT NULL,
  user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  clock_key           TEXT NOT NULL,
  -- 'actual' for the nightly run; anything else is a replay. This column is what
  -- makes the rule-change diff a real counterfactual instead of a read of history.
  -- See docs/REVIEW.md A1.
  scenario_id         TEXT NOT NULL DEFAULT 'actual',
  applicable          BOOLEAN NOT NULL,
  not_applicable_reason TEXT,
  days_remaining      INTEGER,
  days_consumed       INTEGER,
  denominator         INTEGER,
  severity            TEXT NOT NULL,
  rule_id             UUID REFERENCES rules(id),
  rule_key            TEXT,
  rule_effective_from DATE,
  -- Facts only. Excludes as_of and excludes rule params, or it changes every night
  -- purely because the calendar advanced and the signal is gone. Combined with
  -- rule_id this gives three distinguishable cases: facts changed, law changed,
  -- only time passed. See docs/REVIEW.md B6.
  inputs_hash         TEXT NOT NULL,
  engine_version      TEXT NOT NULL,
  replicated_at       TIMESTAMPTZ,

  UNIQUE (user_id, clock_key, as_of, scenario_id)
);

CREATE INDEX outbox_unreplicated_idx ON clock_evaluation_outbox (id)
  WHERE replicated_at IS NULL;
