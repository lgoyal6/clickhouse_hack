"""I-485 portability: 180 days from filing, after which a same-or-similar job change
is permitted under INA 204(j).

Note the layer this depends on. A pending I-485 coexists with H-1B status, which is
why status_periods carries a layer discriminator and why the build spec's single
exclusion constraint over all rows would have made this clock unreachable. See
REVIEW A3.
"""
from __future__ import annotations

import datetime as dt

CLOCK_KEY = "i485_portability"
KIND = "deadline"


def applies(state, as_of: dt.date) -> tuple[bool, str]:
    if state.milestone_date("I485_FILED") is None:
        return False, "no_i485"
    return True, ""


def compute(state, as_of: dt.date, ruleset) -> dict:
    rule = ruleset.governing("i485_portability", as_of)
    days = rule.param("days")

    filed = state.milestone_date("I485_FILED")
    eligible_on = filed + dt.timedelta(days=days)
    consumed = (as_of - filed).days
    remaining = (eligible_on - as_of).days

    # This clock counts UP to a freedom, not down to a cliff, so it is never critical.
    severity = "clear" if remaining <= 0 else "info"

    return {
        "kind": KIND,
        "days_consumed": min(consumed, days),
        "denominator": days,
        "days_remaining": max(remaining, 0),
        "window_start": filed,
        "window_end": eligible_on,
        "window_days": days,
        "severity": severity,
        "rule": rule,
        "derived": True,
        "derivation": (
            f"You filed I-485 on {filed.isoformat()}. {rule.citation} permits a change "
            f"to a same or similar occupation once the application has been pending "
            f"{days} days, which is {eligible_on.isoformat()}."
            + ("" if remaining > 0 else " That date has passed; portability is available.")
        ),
    }
