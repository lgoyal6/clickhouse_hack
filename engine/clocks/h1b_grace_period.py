"""H-1B grace period: 60 days from the end of employment.

The clock the replay scenario targets. Elimination is proposed under RIN 1615-AD22,
which is exactly why replay has to be a write: no evaluation exists under a rule that
has not taken effect, so reading history back tells you nothing. See REVIEW A1.
"""
from __future__ import annotations

import datetime as dt

CLOCK_KEY = "h1b_grace_period"
KIND = "consumption"


def _last_job_end(state) -> dt.date | None:
    """The end of the most recent employment, if nothing is currently open."""
    if any(e.end_date is None for e in state.employment):
        return None
    ends = [e.end_date for e in state.employment if e.end_date]
    return max(ends) if ends else None


def applies(state, as_of: dt.date) -> tuple[bool, str]:
    if state.h1b_first_entry is None:
        return False, "not in H-1B status"
    if _last_job_end(state) is None:
        return False, "currently employed; the grace period has not started"
    return True, ""


def compute(state, as_of: dt.date, ruleset) -> dict:
    rule = ruleset.governing("h1b_grace_period", as_of)
    days = rule.param("days")

    ended = _last_job_end(state)
    consumed = max(0, (as_of - ended).days)
    remaining = days - consumed
    end = ended + dt.timedelta(days=days)

    if remaining <= 0:
        severity = "critical"
    elif remaining <= 14:
        severity = "critical"
    elif remaining <= 30:
        severity = "warn"
    else:
        severity = "info"

    return {
        "kind": KIND,
        "days_consumed": consumed,
        "denominator": days,
        "days_remaining": remaining,
        "window_start": ended,
        "window_end": end,
        "window_days": days,
        "severity": severity,
        "rule": rule,
        "derived": False,
        "derivation": None,
    }
