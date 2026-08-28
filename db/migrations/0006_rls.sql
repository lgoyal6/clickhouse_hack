-- Row level security.
--
-- The build spec's tool signature is get_my_clocks(user_id), which hands a language
-- model a parameter that reads any person's immigration status, employer and wage.
-- In the demo that is how personas get switched, which means there is no
-- authorization boundary to accidentally leave in place; there is simply none.
--
-- The API sets a session GUC and the database enforces the rest, so the boundary
-- exists in two places and neither of them is a prompt. See docs/REVIEW.md D1.

CREATE OR REPLACE FUNCTION current_subject() RETURNS UUID AS $$
  SELECT NULLIF(current_setting('status_clock.subject', true), '')::uuid;
$$ LANGUAGE sql STABLE;

DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['status_periods','employment_episodes','absences',
                           'gc_milestones','documents','alerts',
                           'clock_evaluation_outbox']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY subject_isolation ON %I USING (user_id = current_subject())
         WITH CHECK (user_id = current_subject())', t);
  END LOOP;
END $$;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY subject_isolation ON users USING (id = current_subject());

-- rules, alert_templates and rule_param_shapes are public reference data: readable
-- by everyone, writable only by the migration role.
GRANT SELECT ON rules, alert_templates, rule_param_shapes TO PUBLIC;
