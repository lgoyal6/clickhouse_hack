"""Cap-gap window. This is the demo.

The supersession callout is driven by the `supersedes` chain, not by a fixed
lookback. See engine/rules.py and docs/REVIEW.md A2.

Three distinct numbers, three distinct labels. The build spec's Field Card mock
prints "216 days of work authorization", but 216 is days REMAINING from 2026-08-28;
the window is 243 days long and 183 of those days are the gain over the superseded
rule. All three verified. See docs/REVIEW.md F3.
"""
from __future__ import annotations

import datetime as dt

CLOCK_KEY = "cap_gap_window"
KIND = "window"


def applies(state, as_of: dt.date) -> tuple[bool, str]:
    if state.period("CAP_GAP") is None:
        return False, "no_cap_gap"
    return True, ""


def _end_date(end_rule: str, cap_gap_start: dt.date) -> dt.date:
    """Resolve an end_rule param to a date for this person's cap-gap.

    The H-1B fiscal year requested is the one beginning on the October 1 that
    follows the start of the cap-gap period.
    """
    fy_start_year = cap_gap_start.year if cap_gap_start.month < 10 else cap_gap_start.year + 1
    if end_rule == "SEPT_30":
        return dt.date(fy_start_year, 9, 30)
    if end_rule == "APRIL_1":
        return dt.date(fy_start_year + 1, 4, 1)
    raise ValueError(f"unknown cap_gap_end end_rule {end_rule!r}")


def compute(state, as_of: dt.date, ruleset) -> dict:
    period = state.period("CAP_GAP")
    rule = ruleset.governing("cap_gap_end", as_of)
    prior = ruleset.prior(rule)

    start = period.start_date
    end = _end_date(rule.param("end_rule"), start)
    remaining = (end - as_of).days

    superseded = None
    if prior is not None:
        prior_end = _end_date(prior.param("end_rule"), start)
        # Only surface it when the superseded version was actually in force during a
        # period relevant to this person. That is what makes it honest rather than
        # decorative: it fires for someone whose OPT window straddles the change and
        # not for someone who started afterwards.
        relevant = period.start_date <= rule.effective_from or prior.effective_from <= start
        if relevant or prior_end != end:
            superseded = {
                "rule_id": prior.rule_id,
                "citation": prior.citation,
                "effective_from": prior.effective_from,
                "superseded_on": rule.effective_from,
                "prior_value": prior_end.strftime("%b %d %Y").upper(),
                "delta_days": (end - prior_end).days,
            }

    return {
        "kind": KIND,
        "days_consumed": None,
        "denominator": None,
        "days_remaining": remaining,
        "window_start": start,
        "window_end": end,
        "window_days": (end - start).days,
        "severity": "clear" if remaining > 60 else ("warn" if remaining > 21 else "critical"),
        "rule": rule,
        "superseded": superseded,
        "derived": False,
        "derivation": None,
    }
