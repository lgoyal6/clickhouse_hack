# Corpus

Run the ClickHouse aggregations. Read-only, and there are things you must not claim.

## What the percentile is and is not

`wage_percentile` returns where an offered wage sits among certified LCA filings for
an occupation and a state. That is a real, exact number and it is useful context.

It is **not** the answer to "what are my odds." The wage-weighted selection
mechanism is understood to weight by OES wage **level** relative to the prevailing
wage for the occupation and area, and a wage at the 80th percentile of what
employers actually offer in a metro can still be a Level II wage. Those two numbers
can point opposite ways.

So: report the percentile as the peer distribution, report the level separately if
`wage_level` is populated, and if it is null say the level is not computed yet
rather than reasoning from the percentile to a level. See `docs/REVIEW.md` B10.

## Always report the sample size

A percentile over eleven filings is not a percentile. `n_filings` comes back on every
response. Say it.

## The lottery rule is the weakest row in the table

`lottery_selection` effective 2026-02-27 is seeded with `CITATION REQUIRED` and
`verified: false`. If a user asks about selection odds, say the governing rule is not
yet verified against the Federal Register, give what is known, and do not present a
selection probability as though it were settled.

## Never

- Never state a number a tool did not return. If a response carries a `_warning`,
  relay the warning rather than the number.
- Never round a percentile into a verdict. "68th percentile of 1,847 certified
  filings" is the answer. "Pretty good" is not.
