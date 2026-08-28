-- The application role.
--
-- RLS is pointless if the API connects as a superuser: superusers bypass row
-- security unconditionally, so the policies in 0006 would exist and never fire.
-- The API connects as this role, which has no BYPASSRLS, so the isolation in
-- 0006 is actually load-bearing rather than decorative. See docs/REVIEW.md D1.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'status_clock_app') THEN
    CREATE ROLE status_clock_app LOGIN PASSWORD 'devonly' NOBYPASSRLS;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO status_clock_app;

-- Per-person tables: full DML, and every row filtered by the subject_isolation
-- policy on each one.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  users, status_periods, employment_episodes, absences,
  gc_milestones, documents, alerts, clock_evaluation_outbox
TO status_clock_app;

GRANT USAGE, SELECT ON SEQUENCE clock_evaluation_outbox_id_seq TO status_clock_app;

-- Reference data is readable and not writable by the app. Rules are changed by a
-- migration with a human in the loop, never by a request.
GRANT SELECT ON rules, alert_templates, rule_param_shapes TO status_clock_app;

-- The GUC the policies read. Set per transaction by the API, never by a caller.
COMMENT ON FUNCTION current_subject() IS
  'Reads status_clock.subject, set per transaction from the session cookie. '
  'No request parameter reaches this. See docs/REVIEW.md D1.';
