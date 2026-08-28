-- The two demo personas.
--
-- They are separate people on purpose. The build spec's Clock Wall renders OPT and
-- H-1B clocks for one person, and nobody can be running both: someone in cap-gap is
-- in F-1 status with a pending petition, so the six-year meter has not started and
-- AC21 has nothing to extend. See docs/REVIEW.md B11.
--
-- Maria's history exercises the layer discriminator: cap-gap overlaps the STEM OPT
-- period, which the build spec's exclusion constraint would have rejected.

BEGIN;

DELETE FROM users WHERE id IN (
  '00000000-0000-4000-8000-00000000a001',
  '00000000-0000-4000-8000-00000000d001'
);

-- ---------- Maria O. Home health aide, STEM OPT, H-1B pending, in cap-gap ----------
INSERT INTO users (id, email, locale, country_chg) VALUES
  ('00000000-0000-4000-8000-00000000a001', 'maria@example.invalid', 'es', 'MEXICO');

INSERT INTO status_periods
  (user_id, status_type, layer, start_date, end_date, program_end, confidence)
VALUES
  ('00000000-0000-4000-8000-00000000a001', 'F1', 'primary',
   '2022-08-20', '2024-08-11', '2024-05-14', 'document_verified');

INSERT INTO status_periods
  (user_id, status_type, layer, start_date, end_date,
   ead_start, ead_expiry, is_stem, confidence)
VALUES
  ('00000000-0000-4000-8000-00000000a001', 'STEM_OPT', 'primary',
   '2024-08-12', '2026-07-31', '2024-08-12', '2026-07-31', true, 'document_verified');

-- Stacked on top of the OPT period, overlapping it. Legal, and the reason
-- no_overlapping_primary_status is scoped to layer = 'primary'.
INSERT INTO status_periods (user_id, status_type, layer, start_date, confidence)
VALUES ('00000000-0000-4000-8000-00000000a001', 'CAP_GAP', 'authorization',
        '2026-08-01', 'inferred');

-- Two concurrent part-time jobs: 15 + 15 = 30 hours a week, which is NOT
-- unemployment. The spec's per-episode test calls the whole overlap unemployment.
INSERT INTO employment_episodes
  (user_id, employer_name, start_date, end_date, hours_per_week,
   soc_code, worksite_state, offered_wage, wage_unit, employment_kind)
VALUES
  ('00000000-0000-4000-8000-00000000a001', 'Bayview Home Care',
   '2024-09-03', '2026-04-10', 15, '31-1120', 'CA', 31200, 'Year', 'paid'),
  ('00000000-0000-4000-8000-00000000a001', 'Sunset Senior Living',
   '2024-09-03', '2026-04-10', 15, '31-1120', 'CA', 31200, 'Year', 'paid');

-- ---------- Daniel R. Adjunct instructor, H-1B year five, nothing filed ----------
INSERT INTO users (id, email, locale, country_chg, h1b_first_entry) VALUES
  ('00000000-0000-4000-8000-00000000d001', 'daniel@example.invalid', 'en',
   'PHILIPPINES', '2021-10-01');

INSERT INTO status_periods (user_id, status_type, layer, start_date, confidence)
VALUES ('00000000-0000-4000-8000-00000000d001', 'H1B', 'primary',
        '2021-10-01', 'document_verified');

-- SOC 25-1071 (Health Specialties Teachers, Postsecondary) rather than 25-1199.
-- 25-1199 has ONE certified filing in California in the whole corpus; 25-1071 has 48
-- in FY2025. The Standing screen needs an occupation the corpus actually covers, and
-- a nursing-programme instructor is both realistic and adjacent to Maria's world.
-- See docs/REVIEW.md C8.
--
-- His offer is deliberately below the median. The honest number is the interesting
-- number: the corpus reflects who gets sponsored, which skews to full faculty, so an
-- adjunct lands low and the screen says so.
INSERT INTO employment_episodes
  (user_id, employer_name, start_date, hours_per_week,
   soc_code, worksite_state, offered_wage, wage_unit, employment_kind)
VALUES
  ('00000000-0000-4000-8000-00000000d001', 'Bay Area Community College',
   '2021-10-01', 40, '25-1071', 'CA', 92000, 'Year', 'paid');

-- Deliberately no gc_milestones for Daniel. That absence is what makes ac21_365
-- fire, and it is a deadline set by an employer's inaction he cannot see.

COMMIT;

SELECT u.email, u.locale,
       count(DISTINCT sp.id) AS periods,
       count(DISTINCT ee.id) AS jobs
FROM users u
LEFT JOIN status_periods sp ON sp.user_id = u.id
LEFT JOIN employment_episodes ee ON ee.user_id = u.id
GROUP BY u.email, u.locale ORDER BY u.email;
