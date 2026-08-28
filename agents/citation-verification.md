# Citation verification — E1, E5

Person B's assigned findings from `docs/REVIEW.md`. Both were read against the
primary source, not summarized from a secondary one, per `TRACK_INTERFACE.md` item
5: whoever writes the sentence should be the one who read it.

## E1 — the H-1B wage-weighted lottery rule

**Confirmed.** Citation: **90 FR 60864** — "Weighted Selection Process for
Registrants and Petitioners Seeking To File Cap-Subject H-1B Petitions," DHS final
rule, published 2025-12-29, **effective 2026-02-27**.

Read directly from the Federal Register's own published text:
https://www.govinfo.gov/content/pkg/FR-2025-12-29/html/2025-23853.htm

This matches the effective date `librechat/agents/corpus.md` already states for
`lottery_selection`. Nothing in `librechat/` needs to change: `corpus.md`'s
instruction ("say the rule is not yet verified") is conditional on the seed data,
not hardcoded, so it's already correct and will resolve on its own once the seed
updates.

**Handoff to Person A:** the `rules` seed row for `lottery_selection`
(`db/seeds/020_rules.sql`, not my path to edit) can be updated from
`CITATION REQUIRED` / `verified: false` to:
```
citation: '90 FR 60864'
authority: 'DHS'
effective_from: '2026-02-27'
verified: true
verified_by: '<whoever seeds it>'
```

## E5 — does AC21 §106(a) support a deadline, or only an eligibility condition?

**Resolved: an eligibility condition, not a deadline — and it is not about I-485
portability.** Two distinct AC21 provisions get conflated in casual discussion:

- **§106(a)** — governs H-1B **extensions past the six-year cap**. It makes
  one-year extensions available if a labor certification or I-140 has been
  **pending 365 days or more** before the six-year mark. The statute states an
  eligibility condition (365 days pending), not a filing deadline.
- **§106(c)** — a separate provision governing **I-485 portability** (180 days
  pending, same-or-similar job classification). Unrelated to the 365-day figure.

Person A's own fixture already gets this right —
`contracts/fixtures/clocks_daniel_h1b.json`'s `ac21_365` entry derivation reads:
> "AC21 Sec. 106(a) allows one-year extensions past that point only if a PERM or
> I-140 has been pending 365 days or more, so a filing has to exist by
> 2026-10-01. ... This date is our arithmetic, not a date stated in the statute."

That's the correct framing: the *statute* states a 365-day eligibility threshold;
the *displayed date* (2026-10-01) is derived by working backward from the
six-year max, and is explicitly labeled as our arithmetic rather than a
statutory deadline. Nothing to fix there — confirming it so alert/chat copy that
touches `ac21_365` (see `alert-copy.md` in this directory) doesn't drift from it,
and so nothing built later re-introduces the "I-485 stays valid" framing (a
different provision, §106(c), that this clock does not evaluate).
