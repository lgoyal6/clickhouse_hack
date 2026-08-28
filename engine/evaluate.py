"""evaluate(state, as_of, ruleset) -> list[Clock]

Pure. No side effects. The caller writes the results to the outbox inside the same
Postgres transaction as the alerts, which is what keeps the retained history and the
alert set from disagreeing. See docs/REVIEW.md B3.

Passing `overrides` to the RuleSet and a non-default `scenario_id` gives the replay
run. That is the same code path as the `what_if` tool and as the population
rule-change diff: one engine, two scenarios, one diff. See docs/REVIEW.md A1.
"""
from __future__ import annotations

import datetime as dt

from . import ENGINE_VERSION
from .clocks import REGISTRY, ALL_CLOCK_KEYS, NOT_YET_IMPLEMENTED

SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2, "clear": 3}


def evaluate(state, as_of: dt.date, ruleset, scenario_id: str = "actual") -> list[dict]:
    out: list[dict] = []

    for clock_key in ALL_CLOCK_KEYS:
        module = REGISTRY.get(clock_key)
        if module is None:
            continue                    # not built yet; see clocks.NOT_YET_IMPLEMENTED

        ok, reason = module.applies(state, as_of)
        if not ok:
            out.append({
                "clock_key": clock_key,
                "scenario_id": scenario_id,
                "applicable": False,
                "not_applicable_reason": reason,
                "as_of": as_of,
                "engine_version": ENGINE_VERSION,
                "inputs_hash": state.inputs_hash(),
            })
            continue

        result = module.compute(state, as_of, ruleset)
        rule = result.pop("rule")
        superseded = result.pop("superseded", None)

        out.append({
            "clock_key": clock_key,
            "scenario_id": scenario_id,
            "applicable": True,
            "not_applicable_reason": None,
            "as_of": as_of,
            "engine_version": ENGINE_VERSION,
            "inputs_hash": state.inputs_hash(),
            "provenance": {
                "rule_id": rule.rule_id,
                "rule_key": rule.rule_key,
                "citation": rule.citation,
                "authority": rule.authority,
                "effective_from": rule.effective_from,
                "effective_to": rule.effective_to,
                "source_url": rule.source_url,
                "verified": rule.verified,
                "verified_by": rule.verified_by,
                "verified_at": rule.verified_at,
            },
            "superseded": superseded,
            **result,
        })

    running = [c for c in out if c["applicable"]]
    running.sort(key=lambda c: (SEVERITY_ORDER.get(c["severity"], 9),
                                c.get("days_remaining") if c.get("days_remaining") is not None else 10**6))
    not_running = [c for c in out if not c["applicable"]]
    return running + not_running


def change_reason(today: dict, yesterday: dict | None) -> str | None:
    """Three cases, not two. See docs/REVIEW.md B6."""
    if yesterday is None:
        return None
    if today["inputs_hash"] != yesterday["inputs_hash"]:
        return "facts_changed"
    if today.get("provenance", {}).get("rule_id") != yesterday.get("provenance", {}).get("rule_id"):
        return "law_changed"
    return "time_passed"
