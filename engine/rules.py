"""Rule resolution.

The governing version is resolved by effective window. The PRIOR version is
resolved by walking `supersedes`, not by looking back a fixed interval.

docs/BUILD_SPEC.md 5 uses `resolve_rule(clock_key, as_of - 1 year)` for the
stale-advice callout. With as_of = 2026-08-28 that lands on 2025-08-28, which
resolves to the same cap_gap_end row effective 2025-01-17, so `prior.id ==
rule.id`, `superseded` is None, and the strikethrough never renders. That is the
demo beat. Verified arithmetic. See docs/REVIEW.md A2.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    rule_key: str
    effective_from: dt.date
    effective_to: dt.date | None
    params: dict
    citation: str
    authority: str
    source_url: str
    supersedes: str | None = None
    note: str | None = None
    verified_by: str | None = None
    verified_at: dt.datetime | None = None

    @property
    def verified(self) -> bool:
        return self.verified_by is not None

    def param(self, key: str):
        """Raise rather than coerce a missing param.

        A typo in {"days":90} would otherwise read back as None and the engine would
        compute a wrong countdown instead of failing. Here a wrong countdown is the
        harm. See docs/REVIEW.md B5.
        """
        if key not in self.params:
            raise KeyError(
                f"rule {self.rule_key} (effective {self.effective_from}) has no param "
                f"{key!r}; params are {sorted(self.params)}"
            )
        return self.params[key]


class RuleSet:
    """All versions of all rules, indexed. Loaded once per evaluation run."""

    def __init__(self, rules: list[Rule], overrides: dict[str, dict] | None = None):
        self._by_key: dict[str, list[Rule]] = {}
        self._by_id: dict[str, Rule] = {}
        for r in rules:
            self._by_key.setdefault(r.rule_key, []).append(r)
            self._by_id[r.rule_id] = r
        for versions in self._by_key.values():
            versions.sort(key=lambda r: r.effective_from, reverse=True)
        # Scenario overrides: substitute params for a replay run. This is what makes
        # the rule-change diff a counterfactual. See docs/REVIEW.md A1.
        self._overrides = overrides or {}

    def governing(self, rule_key: str, as_of: dt.date) -> Rule:
        for r in self._by_key.get(rule_key, []):
            if r.effective_from <= as_of and (r.effective_to is None or r.effective_to > as_of):
                if rule_key in self._overrides:
                    return Rule(**{**r.__dict__, "params": {**r.params, **self._overrides[rule_key]}})
                return r
        raise LookupError(
            f"no rule version governs {rule_key!r} on {as_of}. A gap in the effective "
            f"windows renders an empty clock rather than an error. See docs/REVIEW.md B4."
        )

    def prior(self, rule: Rule) -> Rule | None:
        """The version this one superseded. Chain-driven, not time-window-driven."""
        if rule.supersedes is None:
            return None
        prev = self._by_id.get(rule.supersedes)
        if prev is None:
            raise LookupError(
                f"rule {rule.rule_key} claims to supersede {rule.supersedes} which is "
                f"not loaded. A broken chain makes provenance unverifiable."
            )
        return prev

    def chain(self, rule_key: str, as_of: dt.date) -> list[Rule]:
        out, cur = [], self.governing(rule_key, as_of)
        while cur is not None:
            out.append(cur)
            cur = self.prior(cur)
        return out
