-- Param shapes must exist before any rule is inserted; the trigger in 0004
-- refuses a rule_key it does not recognise.
INSERT INTO rule_param_shapes (rule_key, required, types) VALUES
  ('opt_unemployment_max',       ARRAY['days'],   '{"days":"number"}'),
  ('stem_opt_unemployment_add',  ARRAY['days'],   '{"days":"number"}'),
  ('cap_gap_end',                ARRAY['end_rule'], '{"end_rule":"string"}'),
  ('h1b_grace_period',           ARRAY['days'],   '{"days":"number"}'),
  ('ac21_extension_threshold',   ARRAY['days'],   '{"days":"number"}'),
  ('ac21_three_year',            ARRAY['basis'],  '{"basis":"string"}'),
  ('i485_portability',           ARRAY['days'],   '{"days":"number"}'),
  ('h1b_max_stay',               ARRAY['years'],  '{"years":"number"}'),
  ('lottery_selection',          ARRAY['method'], '{"method":"string"}'),
  ('opt_filing_window',          ARRAY['before','after','i20_days'],
     '{"before":"number","after":"number","i20_days":"number"}'),
  ('opt_min_hours',              ARRAY['hours'],  '{"hours":"number"}');
