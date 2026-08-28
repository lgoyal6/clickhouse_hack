-- Core person and history tables.
--
-- Table order matters: documents comes before status_periods because
-- status_periods.source_doc_id references it. The build spec had these reversed,
-- which fails on first run. See docs/REVIEW.md A4.

CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT UNIQUE NOT NULL,
  locale        TEXT NOT NULL DEFAULT 'en',
  country_chg   TEXT,                    -- chargeability country, drives priority dates
  -- Moved here from status_periods. A person has exactly one date that starts the
  -- six-year meter; putting it on each period lets several periods disagree about
  -- it. See docs/REVIEW.md B7.
  h1b_first_entry DATE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  doc_type       TEXT NOT NULL
                 CHECK (doc_type IN ('I20','EAD','I797','I94','VISA','PERM_NOTICE')),
  uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  extracted      JSONB,                  -- what the intake agent pulled out
  user_confirmed BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE status_periods (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status_type   TEXT NOT NULL
                CHECK (status_type IN ('F1','OPT','STEM_OPT','H1B','H4','O1','L1',
                                       'TN','J1','AOS_PENDING','GRACE','CAP_GAP')),

  -- The layer discriminator. This is what lets the exclusion constraint in 0003
  -- forbid overlap where overlap is impossible while permitting the stacking the
  -- law actually does. Cap-gap is an extension of F-1 status that runs concurrently
  -- with the OPT period; a pending I-485 coexists with H-1B status, which is the
  -- entire premise of the portability clock. See docs/REVIEW.md A3.
  --
  --   primary       : F1, OPT, STEM_OPT, H1B, H4, O1, L1, TN, J1
  --   authorization : CAP_GAP, GRACE   (stacked on top of a primary status)
  --   pending       : AOS_PENDING      (a filing, not a status)
  layer         TEXT NOT NULL DEFAULT 'primary'
                CHECK (layer IN ('primary','authorization','pending')),

  start_date    DATE NOT NULL,
  end_date      DATE,
  i94_expiry    DATE,
  ead_expiry    DATE,
  ead_start     DATE,                    -- bounds the unemployment count; see REVIEW A10
  program_end   DATE,
  is_stem       BOOLEAN NOT NULL DEFAULT false,
  cap_exempt    BOOLEAN NOT NULL DEFAULT false,
  source_doc_id UUID REFERENCES documents(id),
  confidence    TEXT NOT NULL DEFAULT 'user_stated'
                CHECK (confidence IN ('document_verified','user_stated','inferred')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT sane_dates CHECK (end_date IS NULL OR end_date >= start_date),
  CONSTRAINT sane_ead   CHECK (ead_expiry IS NULL OR ead_start IS NULL
                               OR ead_expiry >= ead_start),
  -- Keep layer and status_type honest about each other.
  CONSTRAINT layer_matches_status CHECK (
    (layer = 'authorization' AND status_type IN ('CAP_GAP','GRACE'))
    OR (layer = 'pending' AND status_type = 'AOS_PENDING')
    OR (layer = 'primary' AND status_type NOT IN ('CAP_GAP','GRACE','AOS_PENDING'))
  )
);

CREATE TABLE employment_episodes (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  employer_name TEXT NOT NULL,
  -- Nullable and NOT a join key on its own. Recent OFLC disclosure files do not
  -- reliably publish FEIN; check the actual headers before depending on it.
  -- See docs/REVIEW.md C2.
  employer_fein TEXT,
  employer_ref  UUID,                    -- resolved employer identity, once we have one
  start_date    DATE NOT NULL,
  end_date      DATE,
  -- Concurrent employment is legal on OPT and hours aggregate across employers.
  -- The unemployment calculation sums this per day rather than testing each
  -- episode against the threshold. See docs/REVIEW.md A9.
  hours_per_week SMALLINT CHECK (hours_per_week IS NULL OR hours_per_week BETWEEN 0 AND 168),
  soc_code      TEXT,
  soc_confidence REAL CHECK (soc_confidence IS NULL OR soc_confidence BETWEEN 0 AND 1),
  worksite_state TEXT,
  worksite_msa  TEXT,
  offered_wage  NUMERIC(12,2),
  wage_unit     TEXT,
  wage_level    SMALLINT CHECK (wage_level IS NULL OR wage_level BETWEEN 1 AND 4),
  employment_kind TEXT
                CHECK (employment_kind IN ('paid','unpaid_training','self_employed',
                                           'volunteer','contract')),
  counts_as_employment BOOLEAN NOT NULL DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT sane_dates CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE INDEX employment_episodes_user_start_idx
  ON employment_episodes (user_id, start_date);

-- Trips abroad. Required by h1b_max_stay, which is "six years minus recaptured
-- time abroad" and cannot be computed without this. The build spec specifies the
-- clock and omits the table. See docs/REVIEW.md B7.
CREATE TABLE absences (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  departed_on   DATE NOT NULL,
  returned_on   DATE,
  evidence_doc_id UUID REFERENCES documents(id),
  confidence    TEXT NOT NULL DEFAULT 'user_stated'
                CHECK (confidence IN ('document_verified','user_stated','inferred')),

  CONSTRAINT sane_dates CHECK (returned_on IS NULL OR returned_on >= departed_on)
);

CREATE INDEX absences_user_idx ON absences (user_id, departed_on);

CREATE TABLE gc_milestones (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  milestone     TEXT NOT NULL
                CHECK (milestone IN ('PWD_FILED','PWD_ISSUED','RECRUITMENT_START',
                                     'PERM_FILED','PERM_APPROVED','I140_FILED',
                                     'I140_APPROVED','I485_FILED','AP_APPROVED')),
  event_date    DATE NOT NULL,
  priority_date DATE,
  category      TEXT CHECK (category IN ('EB1','EB2','EB3','EB2_NIW')),
  receipt_number TEXT,
  UNIQUE (user_id, milestone, event_date)
);
