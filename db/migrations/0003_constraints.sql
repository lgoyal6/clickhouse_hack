-- Temporal exclusion constraints.
--
-- Split out from table creation so the demo can show them being added, and so a
-- failing seed points at exactly one file.

-- Overlap is forbidden within the primary layer, where two simultaneous statuses
-- are genuinely impossible. It is permitted across layers, because cap-gap stacks
-- on F-1/OPT and a pending I-485 stacks on H-1B. The build spec's single
-- constraint over all rows rejects both of those and therefore rejects the demo
-- persona. See docs/REVIEW.md A3.
ALTER TABLE status_periods ADD CONSTRAINT no_overlapping_primary_status
EXCLUDE USING gist (
  user_id WITH =,
  daterange(start_date, COALESCE(end_date, 'infinity'::date), '[)') WITH &&
) WHERE (layer = 'primary');

-- Two cap-gap periods, or two grace periods, cannot overlap either.
ALTER TABLE status_periods ADD CONSTRAINT no_overlapping_same_authorization
EXCLUDE USING gist (
  user_id WITH =,
  status_type WITH =,
  daterange(start_date, COALESCE(end_date, 'infinity'::date), '[)') WITH &&
) WHERE (layer <> 'primary');

-- You cannot be in two places at once.
ALTER TABLE absences ADD CONSTRAINT no_overlapping_absences
EXCLUDE USING gist (
  user_id WITH =,
  daterange(departed_on, COALESCE(returned_on, 'infinity'::date), '[)') WITH &&
);
