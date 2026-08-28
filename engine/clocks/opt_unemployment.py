"""OPT unemployment days.

Two corrections to docs/BUILD_SPEC.md 5 clock 1, both of which change the number:

  A9. Hours aggregate across concurrent employers. Concurrent employment is legal
      on OPT, so two 15-hour jobs is 30 hours a week and is not unemployment. The
      spec tests each episode against the threshold individually, which counts that
      person as unemployed for the entire overlap. The test is per DAY over the SUM
      of hours, which is a different shape of code.

  A10. The count is bounded to the OPT authorization window. The 90 days are days of
      unemployment during the post-completion OPT period, which begins on the EAD
      start date. The spec walks the person's whole employment history, so anyone
      with a normal F-1 study period and no job starts out over the ceiling.
"""
from __future__ import annotations

import datetime as dt

CLOCK_KEY = "opt_unemployment"
KIND = "consumption"


def applies(state, as_of: dt.date) -> tuple[bool, str]:
    period = _opt_period(state)
    if period is None:
        return False, "no_opt_period"
    if period.ead_start is None:
        return False, "no_ead_start"
    return True, ""


def _opt_period(state):
    # Prefer STEM OPT: its ceiling is the aggregate one.
    for st in ("STEM_OPT", "OPT"):
        p = state.period(st)
        if p is not None:
            return p
    return None


def _window(period, as_of: dt.date) -> tuple[dt.date, dt.date]:
    start = period.ead_start
    end = min(x for x in (period.ead_expiry, as_of) if x is not None)
    return start, max(start, end)


def hours_on(state, day: dt.date) -> int:
    """Total qualifying hours per week across every episode covering `day`."""
    return sum(
        e.hours_per_week or 0
        for e in state.employment
        if e.counts_as_employment
        and e.start_date <= day
        and (e.end_date is None or day <= e.end_date)
    )


def compute(state, as_of: dt.date, ruleset) -> dict:
    period = _opt_period(state)
    base = ruleset.governing("opt_unemployment_max", as_of)
    min_hours_rule = ruleset.governing("opt_min_hours", as_of)
    threshold = min_hours_rule.param("hours")

    denominator = base.param("days")
    if period.is_stem or period.status_type == "STEM_OPT":
        add = ruleset.governing("stem_opt_unemployment_add", as_of)
        denominator += add.param("days")

    start, end = _window(period, as_of)
    consumed = 0
    day = start
    one = dt.timedelta(days=1)
    while day <= end:
        if hours_on(state, day) < threshold:
            consumed += 1
        day += one

    remaining = denominator - consumed
    if remaining <= 0:
        severity = "critical"
    elif remaining <= 21:
        severity = "critical"
    elif remaining <= 45:
        severity = "warn"
    else:
        severity = "clear"

    return {
        "kind": KIND,
        "days_consumed": consumed,
        "denominator": denominator,
        "days_remaining": remaining,
        "window_start": start,
        "window_end": period.ead_expiry,
        "window_days": None,
        "severity": severity,
        "rule": base,
        "derived": True,
        "derivation": (
            f"{base.param('days')} days under {base.citation}"
            + (
                f" plus {ruleset.governing('stem_opt_unemployment_add', as_of).param('days')}"
                " additional days for the STEM extension, aggregated across the whole"
                " OPT period"
                if denominator != base.param("days")
                else ""
            )
            + f". Counted only inside the OPT authorization window, and only on days"
            f" where total hours across all employers fell below {threshold}"
            f" ({min_hours_rule.citation})."
        ),
    }
