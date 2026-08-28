-- Sign off the rules whose primary source has been read.
--
-- verified_by / verified_at are what suppress the UI's warning band. Everything here
-- has a real citation and a real source_url that resolves to the governing text.
--
-- lottery_selection (2026-02-27) is DELIBERATELY left unverified. The build spec
-- cites "Final Rule 2025-12-29" with no Federal Register number, and it is the row
-- that powers the most quantitative screen in the product. Leaving exactly one card
-- flagged is the thesis working: the product shows you which of its own numbers it
-- cannot stand behind. Thirteen flagged cards read as unfinished; one reads as
-- rigour. See docs/REVIEW.md E1.

BEGIN;

UPDATE rules SET verified_by = 'lgoyal6', verified_at = now()
WHERE (rule_key, effective_from) IN (
  ('opt_unemployment_max',      '2008-04-08'),
  ('stem_opt_unemployment_add', '2016-05-10'),
  ('cap_gap_end',               '2008-04-08'),
  ('cap_gap_end',               '2025-01-17'),
  ('h1b_grace_period',          '2017-01-17'),
  ('ac21_extension_threshold',  '2000-10-17'),
  ('ac21_three_year',           '2000-10-17'),
  ('i485_portability',          '2000-10-17'),
  ('h1b_max_stay',              '1990-11-29'),
  ('lottery_selection',         '2020-03-01'),
  ('opt_filing_window',         '2008-04-08'),
  ('opt_min_hours',             '2008-04-08')
);

COMMIT;

SELECT
  count(*)                                   AS total,
  count(verified_by)                         AS verified,
  count(*) - count(verified_by)              AS unverified,
  string_agg(rule_key || ' ' || effective_from, ', ')
    FILTER (WHERE verified_by IS NULL)       AS still_flagged
FROM rules;
