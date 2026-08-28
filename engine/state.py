"""User state. Plain data, loaded from Postgres by the caller.

Kept free of any database dependency so that every clock is testable in isolation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field, asdict


@dataclass(frozen=True)
class StatusPeriod:
    status_type: str
    layer: str
    start_date: dt.date
    end_date: dt.date | None = None
    ead_start: dt.date | None = None
    ead_expiry: dt.date | None = None
    program_end: dt.date | None = None
    is_stem: bool = False
    i94_expiry: dt.date | None = None


@dataclass(frozen=True)
class EmploymentEpisode:
    employer_name: str
    start_date: dt.date
    end_date: dt.date | None = None
    hours_per_week: int | None = None
    counts_as_employment: bool = True


@dataclass(frozen=True)
class Milestone:
    milestone: str
    event_date: dt.date


@dataclass(frozen=True)
class Absence:
    departed_on: dt.date
    returned_on: dt.date | None = None


@dataclass(frozen=True)
class UserState:
    user_id: str
    locale: str = "en"
    h1b_first_entry: dt.date | None = None
    status_periods: tuple[StatusPeriod, ...] = field(default_factory=tuple)
    employment: tuple[EmploymentEpisode, ...] = field(default_factory=tuple)
    milestones: tuple[Milestone, ...] = field(default_factory=tuple)
    absences: tuple[Absence, ...] = field(default_factory=tuple)

    # ---- helpers ----

    def primary_on(self, day: dt.date) -> StatusPeriod | None:
        for p in self.status_periods:
            if p.layer != "primary":
                continue
            if p.start_date <= day and (p.end_date is None or day < p.end_date):
                return p
        return None

    def period(self, status_type: str) -> StatusPeriod | None:
        for p in self.status_periods:
            if p.status_type == status_type:
                return p
        return None

    def has_milestone(self, *names: str) -> bool:
        return any(m.milestone in names for m in self.milestones)

    def milestone_date(self, name: str) -> dt.date | None:
        hits = sorted(m.event_date for m in self.milestones if m.milestone == name)
        return hits[0] if hits else None

    def inputs_hash(self) -> str:
        """Hash of FACTS ONLY.

        Deliberately excludes as_of and excludes rule params. If as_of were included
        the hash would change every night purely because the calendar advanced, and
        the signal it exists to carry would be gone. Combined with rule_id this makes
        three cases distinguishable rather than two: facts changed, law changed, only
        time passed. See docs/REVIEW.md B6.
        """
        payload = {
            "user_id": self.user_id,
            "h1b_first_entry": _iso(self.h1b_first_entry),
            "status_periods": [_norm(asdict(p)) for p in sorted(
                self.status_periods, key=lambda p: (p.start_date, p.status_type))],
            "employment": [_norm(asdict(e)) for e in sorted(
                self.employment, key=lambda e: (e.start_date, e.employer_name))],
            "milestones": [_norm(asdict(m)) for m in sorted(
                self.milestones, key=lambda m: (m.event_date, m.milestone))],
            "absences": [_norm(asdict(a)) for a in sorted(
                self.absences, key=lambda a: a.departed_on)],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:32]


def _iso(d: dt.date | None) -> str | None:
    return d.isoformat() if d else None


def _norm(d: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in sorted(d.items())}
