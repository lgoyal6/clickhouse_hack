# Document fixtures

`specimen-program-dates.png` is a synthetic document for testing the extraction path:
upload it in Ask and the agent reads dates off it and offers to record them.

It is a **fictional college letter**, not a mock I-20 or receipt notice. That is
deliberate. Testing "can the model read dates off an image" does not require
producing something that imitates a United States government form, and a project
whose whole argument is that other people's paperwork is unreliable has no business
manufacturing official-looking paperwork. The banner and the footer both say what it
is, the institution does not exist, and the student is the seeded demo persona.

The dates match `db/seeds/030_personas.sql`, so the agent's extraction can be checked
against a known record rather than eyeballed.

## What it exercises

    upload  ->  model reads the dates
            ->  reports them and asks for confirmation before writing
            ->  record_fact kind=h1b_petition, receipt_date 2026-04-02
            ->  cap-gap period opens the day after the OPT authorization ends
            ->  get_my_clocks now returns the cap-gap window, 216 days,
                ending 2027-04-01 under the 2025 rule, 183 days later than
                the rule it superseded

## Verified behaviour

On an earlier run the receipt date was cut off by the screenshot boundary. The agent
said so and refused to guess the missing digits rather than filling them in, which is
the intake contract working. It also noticed the 15 hours per week on the OPT
authorization and flagged it as below the 20-hour threshold, unprompted.

To reset between runs: `make -f Makefile.data reseed`.
