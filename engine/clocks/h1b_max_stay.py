"""H-1B six-year maximum, minus recaptured time abroad.

docs/BUILD_SPEC.md 5 specifies this clock and its schema has no table of trips
abroad, so as specified the clock cannot be computed and silently ignores recapture.
The `absences` table exists for this reason. When no absence records are on file the
clock says so in its derivation rather than presenting a confident wrong date, which
is the failure mode this product is pitched against. See docs/REVIEW.md B7.
"""
from __future__ import annotations

import datetime as dt

CLOCK_KEY = "h1b_max_stay"
KIND = "deadline"


def applies(state, as_of: dt.date) -> tuple[bool, str]:
    if state.h1b_first_entry is None:
        return False, "not_h1b"
    return True, ""


def compute(state, as_of: dt.date, ruleset) -> dict:
    rule = ruleset.governing("h1b_max_stay", as_of)
    years = rule.param("years")

    base = _add_years(state.h1b_first_entry, years)
    recaptured = sum(
        ((a.returned_on or as_of) - a.departed_on).days
        for a in state.absences
        if a.departed_on >= state.h1b_first_entry
    )
    end = base + dt.timedelta(days=recaptured)
    remaining = (end - as_of).days
    total = (end - state.h1b_first_entry).days

    if state.absences:
        note = (
            f"{recaptured} days of recaptured time abroad are included, from "
            f"{len(state.absences)} absence record(s)."
        )
    else:
        note = (
            "Recaptured time abroad is NOT included: no absence records are on file. "
            "If you have spent time outside the US while on H-1B, this date moves later."
        )

    return {
        "kind": KIND,
        "days_consumed": (as_of - state.h1b_first_entry).days,
        "denominator": total,
        "days_remaining": remaining,
        "window_start": state.h1b_first_entry,
        "window_end": end,
        "window_days": None,
        "severity": "critical" if remaining <= 180 else ("warn" if remaining <= 540 else "clear"),
        "rule": rule,
        "derived": True,
        "derivation": (
            f"{years} years from first H-1B entry on "
            f"{state.h1b_first_entry.isoformat()}. {note}"
        ),
    }


def _add_years(d: dt.date, years: int) -> dt.date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)
