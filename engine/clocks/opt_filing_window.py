"""OPT filing window.

Three separate constraints in one rule, and the third is the one people miss: USCIS
must RECEIVE the application within 30 days of the DSO's I-20 recommendation, which
runs independently of the 90-before / 60-after window around program end.
"""
from __future__ import annotations

import datetime as dt

CLOCK_KEY = "opt_filing_window"
KIND = "window"


def _program_end(state) -> dt.date | None:
    for p in state.status_periods:
        if p.program_end:
            return p.program_end
    return None


def applies(state, as_of: dt.date) -> tuple[bool, str]:
    end = _program_end(state)
    if end is None:
        return False, "no program end date on file; add your I-20"
    # Once OPT is authorised the filing window is history.
    if state.period("OPT") or state.period("STEM_OPT"):
        return False, "OPT already authorised; the filing window has closed"
    return True, ""


def compute(state, as_of: dt.date, ruleset) -> dict:
    rule = ruleset.governing("opt_filing_window", as_of)
    before, after = rule.param("before"), rule.param("after")

    end = _program_end(state)
    opens = end - dt.timedelta(days=before)
    closes = end + dt.timedelta(days=after)
    remaining = (closes - as_of).days

    if as_of < opens:
        severity = "info"
    elif remaining <= 14:
        severity = "critical"
    elif remaining <= 30:
        severity = "warn"
    else:
        severity = "clear"

    return {
        "kind": KIND,
        "days_consumed": None,
        "denominator": None,
        "days_remaining": remaining,
        "window_start": opens,
        "window_end": closes,
        "window_days": (closes - opens).days,
        "severity": severity,
        "rule": rule,
        "derived": True,
        "derivation": (
            f"Your program end date is {end.isoformat()}. {rule.citation} allows filing "
            f"from {before} days before it ({opens.isoformat()}) to {after} days after "
            f"({closes.isoformat()}). Separately, USCIS must RECEIVE your application "
            f"within {rule.param('i20_days')} days of your DSO's I-20 recommendation, "
            f"and that clock runs independently of this one."
        ),
    }
