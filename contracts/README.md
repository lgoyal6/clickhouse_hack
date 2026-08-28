# contracts/

The only coupling point between `track/data` and `track/interface`.

| File | What it is |
|---|---|
| `openapi.yaml` | The HTTP surface. Person A implements it, Person B consumes it. |
| `clock.schema.json` | The Clock object. Provenance fields are `required`, so a number cannot travel without its citation. |
| `fixtures/*.json` | Real, complete, contract-valid responses. Person B builds against these from minute one. |
| `validate.py` | Checks every fixture against the schema and parses the spec. Run it before you push. |

## Two invariants

**Identity never travels as a parameter.** No endpoint accepts a user id. The subject
comes from the session. `get_my_clocks(user_id)` as specified in the build spec is an
IDOR with a language model holding the argument; see `docs/REVIEW.md` D1. Persona
switching in the demo uses two sessions.

**Provenance is enforced by the schema, not by a prompt.** `citation`, `authority`,
`effective_from`, and `verified` are required on every clock. The agent cannot receive
an uncited number, so it has nothing uncited to repeat; see `docs/REVIEW.md` H2.

## Fixtures

Two personas, deliberately not merged into one screen (see `docs/REVIEW.md` B11):

- `clocks_maria_stem_opt.json` — home health aide, STEM OPT, H-1B petition pending, in
  cap-gap. Carries the superseded-rule strikethrough with `delta_days: 183`.
- `clocks_daniel_h1b.json` — adjunct instructor, H-1B year five, no PERM on file.
  Carries the AC21 card, marked `derived: true` with the arithmetic spelled out.
- `claim_check_capgap.json` — the stale-advice beat. Verdict `superseded`.
- `wage_percentile.json`, `replay_h1b_grace.json` — shapes only. Both carry a
  `_fixture_note` saying the numbers are placeholders. Replace them with real query
  output before any demo. A fabricated percentile in this product is the exact harm the
  product exists to prevent.

Every date in the clock fixtures is computed, not typed. Verified:

```
cap-gap remaining (2026-08-28 -> 2027-04-01) : 216 days
cap-gap window length (2026-08-01 -> 2027-04-01) : 243 days
days gained vs the superseded rule (2026-09-30 -> 2027-04-01) : 183 days
AC21 gate (2027-10-01 minus 365 days = 2026-10-01) : 34 days out
H-1B max remaining (2026-08-28 -> 2027-10-01) : 399 days
```

The build spec's mock says "216 days of work authorization" for cap-gap. 216 is days
remaining; the window is 243 days long and 183 of them are the gain from the rule
change. Three different numbers, three different labels. See `docs/REVIEW.md` F3.

## Changing a contract

A contract change is a deliberate commit on `main` touching only `contracts/`, made
after both people agree, followed by both branches rebasing onto it. Do not change it
from inside a track branch.
