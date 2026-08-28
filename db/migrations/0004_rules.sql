-- The provenance backbone.
--
-- docs/BUILD_SPEC.md 2.1 argues that an unbroken version chain is what makes
-- provenance verifiable. The spec's DDL then enforces nothing but a unique key,
-- so the chain can fork, overlap, or leave a gap in which rule resolution
-- silently returns no row and a clock renders empty. See docs/REVIEW.md B4.

CREATE TABLE rules (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_key       TEXT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to   DATE,
  params         JSONB NOT NULL,
  citation       TEXT NOT NULL,
  source_url     TEXT NOT NULL,
  -- Widened from the spec's three values. opt_min_hours is sourced to SEVP policy
  -- guidance, which the spec's own comment excludes, leaving the weakest-sourced
  -- rule in the product with the least legible provenance. See docs/REVIEW.md E3.
  authority      TEXT NOT NULL
                 CHECK (authority IN ('Federal Register','8 CFR','INA',
                                      'USCIS Policy Manual','ICE SEVP Guidance')),
  supersedes     UUID REFERENCES rules(id),
  note           TEXT,
  verified_by    TEXT,
  verified_at    TIMESTAMPTZ,

  UNIQUE (rule_key, effective_from),
  CONSTRAINT sane_window CHECK (effective_to IS NULL OR effective_to > effective_from),
  -- verified_by and verified_at travel together or not at all. A half-filled
  -- verification is worse than none, because the UI keys its warning band on it.
  CONSTRAINT verification_is_atomic
    CHECK ((verified_by IS NULL) = (verified_at IS NULL))
);

-- A rule has at most one successor. Two rows superseding the same predecessor is a
-- forked chain, and provenance cannot be walked through a fork.
ALTER TABLE rules ADD CONSTRAINT one_successor_per_rule UNIQUE (supersedes);

-- No two versions of the same rule may be in force at the same time. This is also
-- what forces effective_to to be set on the predecessor when a successor lands,
-- which in the spec's seed table is left null and therefore decorative.
ALTER TABLE rules ADD CONSTRAINT no_overlapping_rule_windows
EXCLUDE USING gist (
  rule_key WITH =,
  daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)') WITH &&
);

CREATE INDEX rules_key_from_idx ON rules (rule_key, effective_from DESC);

-- A rule may only supersede another version of the same rule_key.
CREATE OR REPLACE FUNCTION rules_supersedes_same_key() RETURNS trigger AS $$
DECLARE prior_key TEXT;
BEGIN
  IF NEW.supersedes IS NULL THEN RETURN NEW; END IF;
  SELECT rule_key INTO prior_key FROM rules WHERE id = NEW.supersedes;
  IF prior_key IS DISTINCT FROM NEW.rule_key THEN
    RAISE EXCEPTION 'rule % cannot supersede a different rule_key (%)',
      NEW.rule_key, prior_key;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER rules_supersedes_same_key_trg
  BEFORE INSERT OR UPDATE ON rules
  FOR EACH ROW EXECUTE FUNCTION rules_supersedes_same_key();

-- Params shape validation. A typo in {"days":90} reads back as NULL and the engine
-- computes a wrong countdown instead of failing. In this product a wrong countdown
-- is the harm. See docs/REVIEW.md B5.
CREATE TABLE rule_param_shapes (
  rule_key   TEXT PRIMARY KEY,
  required   TEXT[] NOT NULL,
  types      JSONB NOT NULL   -- {"days": "number", "end_rule": "string"}
);

CREATE OR REPLACE FUNCTION rules_validate_params() RETURNS trigger AS $$
DECLARE
  shape RECORD;
  k TEXT;
  want TEXT;
  got TEXT;
BEGIN
  SELECT * INTO shape FROM rule_param_shapes WHERE rule_key = NEW.rule_key;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'no param shape registered for rule_key %; add one to rule_param_shapes', NEW.rule_key;
  END IF;
  FOREACH k IN ARRAY shape.required LOOP
    IF NOT (NEW.params ? k) THEN
      RAISE EXCEPTION 'rule % is missing required param %', NEW.rule_key, k;
    END IF;
    want := shape.types->>k;
    got  := jsonb_typeof(NEW.params->k);
    IF want IS NOT NULL AND got <> want THEN
      RAISE EXCEPTION 'rule % param % should be % but is %', NEW.rule_key, k, want, got;
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER rules_validate_params_trg
  BEFORE INSERT OR UPDATE ON rules
  FOR EACH ROW EXECUTE FUNCTION rules_validate_params();
