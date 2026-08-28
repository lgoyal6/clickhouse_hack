"""AC21 365-day threshold.

The most emotionally effective card on the wall: a deadline set by an employer's
inaction that the person cannot see from inside their own life.

Marked derived=true. AC21 Sec. 106(a) states an ELIGIBILITY condition (a PERM or
I-140 pending 365 days or more permits one-year extensions past the sixth year).
Reframing that as a filing deadline is our arithmetic, and the provenance contract
has to distinguish "this number is in the statute" from "this number is our
arithmetic over a statute". See docs/REVIEW.md E5.
"""
from __future__ import annotations

import datetime as dt

CLOCK_KEY = "ac21_365"
KIND = "deadline"

FILED = ("PERM_FILED", "I140_FILED", "I140_APPROVED", "PERM_APPROVED")


def applies(state, as_of: dt.date) -> tuple[bool, str]:
    if state.h1b_first_entry is None:
        return False, "not in H-1B status; the six-year meter has not started"
    if state.has_milestone(*FILED):
        return False, "a PERM or I-140 is already on file"
    return True, ""


def compute(state, as_of: dt.date, ruleset) -> dict:
    rule = ruleset.governing("ac21_extension_threshold", as_of)
    max_rule = ruleset.governing("h1b_max_stay", as_of)
    threshold = rule.param("days")
    years = max_rule.param("years")

    six_year = _add_years(state.h1b_first_entry, years)
    gate = six_year - dt.timedelta(days=threshold)
    remaining = (gate - as_of).days

    return {
        "kind": KIND,
        "days_consumed": None,
        "denominator": None,
        "days_remaining": remaining,
        "window_start": None,
        "window_end": gate,
        "window_days": None,
        "severity": "critical" if remaining <= 90 else ("warn" if remaining <= 270 else "clear"),
        "rule": rule,
        "derived": True,
        "derivation": (
            f"Your {years}-year maximum falls on {six_year.isoformat()}. {rule.citation} "
            f"allows one-year extensions past that point only if a PERM or I-140 has "
            f"been pending {threshold} days or more, so a filing has to exist by "
            f"{gate.isoformat()}. Nothing is on file. This date is our arithmetic, not "
            f"a date stated in the statute."
        ),
    }


def _add_years(d: dt.date, years: int) -> dt.date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:          # 29 Feb
        return d.replace(year=d.year + years, day=28)
