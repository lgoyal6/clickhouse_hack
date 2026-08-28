# web/

Six screens are specified in `docs/BUILD_SPEC.md` 7. Two of them carry the pitch:
**Clock Wall** and **Ask**. Build those first; `docs/REVIEW.md` I says why.

## Run it now

```bash
make -f Makefile.chat web
# then open http://localhost:5173/web/
```

No build step and no backend. `index.html` reads `contracts/fixtures/` directly, so
the Clock Wall renders with two personas before Person A's API exists. When the API
is up, set `BASE = 'http://localhost:8000'` in `index.html` and delete the fixture
map. Nothing else changes.

## Three things already decided by measurement

1. **The citation line uses `--rule-text` (#666D62, 4.78:1), not `--rule`
   (#8A9187, 2.90:1).** The spec sets the citation at 11px in `--rule`, which makes
   the one element it calls non-optional the least readable text on the screen.
   `--rule` is for hairlines only. See `docs/REVIEW.md` F1.
2. **`--clear` (#3F7D58, 4.39:1) is large-text only.** It clears the 3:1 threshold
   for the enormous counts and fails the 4.5:1 threshold for anything small. Small
   confidence tags use `--clear-text` (#2F6244, 6.37:1). See F2.
3. **The accessible name carries the final value and the citation from the start**,
   and the animated digits are `aria-hidden`. A screen reader must never read an
   intermediate number off a 400ms tick. A wrong number spoken aloud is the same
   harm as a wrong number displayed. See F4.

## Card copy

The cap-gap card shows three separate numbers with three separate labels: days
remaining, window length, days gained. The spec's mock prints "216 days of work
authorization", and 216 is days remaining. See `docs/REVIEW.md` F3.

Unverified rules always render the band. Do not add a way to suppress it.

## What not to build yet

Timeline, Standing, Rule Detail, and Intake-as-a-screen are all deferred in the
scope cut. Standing in particular is blocked on an open question: whether the
lottery statistic is a wage percentile or a wage level, which are different numbers
that can point opposite ways. Do not draw that screen until it is settled.
See `docs/REVIEW.md` B10.
