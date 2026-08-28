-- Seed rules.
--
-- EVERY ROW HERE IS UNVERIFIED. verified_by and verified_at are deliberately null,
-- which makes the API return verified:false and the UI render its warning band.
-- Do not fill them without opening the primary source and reading it.
--
-- The two-step shape for superseded rules is not stylistic. no_overlapping_rule_windows
-- (0004) rejects a successor while the predecessor is still open-ended, so closing
-- the predecessor and inserting the successor happen in one transaction. In the
-- build spec's seed table the predecessors are marked "superseded" in a note column
-- and left open-ended, which makes effective_to decorative. See docs/REVIEW.md B4.

BEGIN;

-- ---------- OPT unemployment ----------
INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority, note)
VALUES ('opt_unemployment_max', '2008-04-08', '{"days":90}',
        '8 CFR 214.2(f)(10)',
        'https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/part-214/section-214.2',
        '8 CFR',
        'Standard post-completion OPT unemployment ceiling.');

INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority, note)
VALUES ('stem_opt_unemployment_add', '2016-05-10', '{"days":60}',
        '81 FR 13040 (STEM OPT Final Rule)',
        'https://www.federalregister.gov/documents/2016/03/11/2016-04828/improving-and-expanding-training-opportunities-for-f-1-nonimmigrant-students-with-stem-degrees-and',
        'Federal Register',
        'Additional 60 days, for an aggregate of 150 across the entire OPT period '
        'including the 24-month extension. The aggregate does NOT reset when the '
        'extension starts. Some published sources print 120; read the rule text '
        'and the SEVP STEM OPT guidance before signing this off. REVIEW E2.');

-- ---------- Cap-gap: the demo ----------
INSERT INTO rules (rule_key, effective_from, effective_to, params, citation, source_url, authority, note)
VALUES ('cap_gap_end', '2008-04-08', '2025-01-17', '{"end_rule":"SEPT_30"}',
        '8 CFR 214.2(f)(5)(vi) (pre-2025)',
        'https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/part-214/section-214.2',
        '8 CFR',
        'Prior cap-gap end rule. This is the version most published guidance and '
        'many DSO handouts still show.');

INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority,
                   supersedes, note)
SELECT 'cap_gap_end', '2025-01-17', '{"end_rule":"APRIL_1"}',
       'H-1B Modernization Final Rule',
       'https://www.federalregister.gov/documents/2024/12/18/2024-29354/modernizing-h-1b-requirements-providing-flexibility-in-the-f-1-program-and-program-improvements',
       'Federal Register',
       id,
       'Extends cap-gap to April 1 of the fiscal year for which H-1B status is '
       'requested. Confirm the exact FR citation and effective date.'
FROM rules WHERE rule_key = 'cap_gap_end' AND effective_from = '2008-04-08';

-- ---------- H-1B grace ----------
INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority, note)
VALUES ('h1b_grace_period', '2017-01-17', '{"days":60}',
        '8 CFR 214.1(l)(2)',
        'https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/part-214/section-214.1',
        '8 CFR',
        'Elimination proposed under RIN 1615-AD22. This is the rule the replay '
        'scenario rule:h1b_grace_0d tests. Because the change has not taken '
        'effect, no evaluation exists under the new rule, which is exactly why '
        'replay has to be a write. REVIEW A1.');

-- ---------- AC21 ----------
INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority, note)
VALUES ('ac21_extension_threshold', '2000-10-17', '{"days":365}',
        'AC21 Sec. 106(a)',
        'https://www.congress.gov/bill/106th-congress/senate-bill/2045/text',
        'INA',
        'Eligibility condition, not a deadline. The ac21_365 clock reframes it as '
        'a deadline, which is useful and is our arithmetic. The clock must be '
        'marked derived and show its working. REVIEW E5.');

INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority, note)
VALUES ('ac21_three_year', '2000-10-17', '{"basis":"I140_APPROVED_PD_NOT_CURRENT"}',
        'AC21 Sec. 104(c)',
        'https://www.congress.gov/bill/106th-congress/senate-bill/2045/text',
        'INA', NULL);

INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority, note)
VALUES ('i485_portability', '2000-10-17', '{"days":180}',
        'INA Sec. 204(j)',
        'https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title8-section1154',
        'INA',
        'Same or similar occupational classification.');

INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority, note)
VALUES ('h1b_max_stay', '1990-11-29', '{"years":6}',
        'INA Sec. 214(g)(4)',
        'https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title8-section1184',
        'INA',
        'Recapture of time abroad is allowed, which is why the absences table '
        'exists. Without absence records this clock is systematically wrong. '
        'REVIEW B7.');

-- ---------- Lottery ----------
INSERT INTO rules (rule_key, effective_from, effective_to, params, citation, source_url, authority, note)
VALUES ('lottery_selection', '2020-03-01', '2026-02-27', '{"method":"RANDOM"}',
        '85 FR 82 (H-1B registration)',
        'https://www.federalregister.gov/documents/2019/01/31/2019-00302/registration-requirement-for-petitioners-seeking-to-file-h-1b-petitions-on-behalf-of-cap-subject',
        'Federal Register',
        'Random selection among registrations.');

INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority,
                   supersedes, note)
SELECT 'lottery_selection', '2026-02-27', '{"method":"WAGE_WEIGHTED"}',
       'CITATION REQUIRED',
       'https://www.federalregister.gov/',
       'Federal Register',
       id,
       'THE WEAKEST ROW IN THIS TABLE. The build spec cites "Final Rule 2025-12-29" '
       'with no FR number and no URL, and asserts a first run in March 2026 which '
       'is already in the past. Every other row cites a CFR section or a named rule. '
       'This is also the row that powers the most quantitative screen. Get the FR '
       'citation and the exact effective date, or leave it unverified and let the '
       'UI show its warning band on stage. REVIEW E1. Note also that the mechanism '
       'is believed to weight by OES wage LEVEL, not by percentile among peer LCA '
       'filings, which are different numbers that can point opposite ways. REVIEW B10.'
FROM rules WHERE rule_key = 'lottery_selection' AND effective_from = '2020-03-01';

-- ---------- OPT mechanics ----------
INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority, note)
VALUES ('opt_filing_window', '2008-04-08', '{"before":90,"after":60,"i20_days":30}',
        '8 CFR 214.2(f)(11)',
        'https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/part-214/section-214.2',
        '8 CFR', NULL);

INSERT INTO rules (rule_key, effective_from, params, citation, source_url, authority, note)
VALUES ('opt_min_hours', '2008-04-08', '{"hours":20}',
        'SEVP Policy Guidance, post-completion OPT',
        'https://studyinthestates.dhs.gov/students/training-opportunities-in-the-united-states/optional-practical-training',
        'ICE SEVP Guidance',
        'The 20-hour minimum comes from SEVP policy guidance rather than the '
        'regulation text, so this is the weakest-sourced rule that gates the '
        'flagship clock. Hours aggregate across concurrent employers. REVIEW E3, A9.');

COMMIT;

-- Sanity: no rule should be verified yet, and every chain should be walkable.
DO $$
DECLARE n INT;
BEGIN
  SELECT count(*) INTO n FROM rules WHERE verified_by IS NOT NULL;
  IF n > 0 THEN RAISE NOTICE '% rule(s) marked verified. Confirm someone actually read the source.', n; END IF;
  SELECT count(*) INTO n FROM rules r WHERE r.supersedes IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM rules p WHERE p.id = r.supersedes);
  IF n > 0 THEN RAISE EXCEPTION 'broken supersedes chain'; END IF;
END $$;
