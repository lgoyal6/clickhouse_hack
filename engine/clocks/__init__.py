"""One module per clock. Each exposes `applies(state, as_of)` and `compute(...)`.

`applies` returns `(bool, code)` where code is a stable slug, never a sentence. The
API owns the wording and translates it. An English string baked in here cannot be
localised, and answering in the user's language without losing citation fidelity is
the point of the product, not a nice-to-have.

Applicability is explicit. docs/BUILD_SPEC.md 5 says "for each applicable clock_key"
and never defines applicable, and the Clock Wall mock then renders OPT clocks and
H-1B clocks for one person, which no single person can be running: someone in
cap-gap is in F-1 status with a pending petition, so the six-year meter has not
started and AC21 has nothing to extend. See docs/REVIEW.md B11.
"""
from . import (opt_unemployment, cap_gap_window, ac21_365, h1b_max_stay,
               h1b_grace_period, i485_portability, opt_filing_window)

REGISTRY = {
    m.CLOCK_KEY: m
    for m in (opt_unemployment, cap_gap_window, ac21_365, h1b_max_stay,
              h1b_grace_period, i485_portability, opt_filing_window)
}

# The canonical clock list. The engine and the UI both read this, which is what
# stops §5 and §7 disagreeing about what the product computes. See REVIEW B8.
ALL_CLOCK_KEYS = (
    "opt_unemployment",
    "cap_gap_window",
    "h1b_grace_period",
    "ac21_365",
    "i485_portability",
    "h1b_max_stay",
    "opt_filing_window",
)

NOT_YET_IMPLEMENTED = tuple(k for k in ALL_CLOCK_KEYS if k not in REGISTRY)
