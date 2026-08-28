import datetime as dt
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from engine.rules import Rule, RuleSet
from engine.state import (UserState, StatusPeriod, EmploymentEpisode, Milestone, Absence)

D = dt.date


def _r(rid, key, frm, params, citation, authority="8 CFR", to=None, supersedes=None):
    return Rule(rule_id=rid, rule_key=key, effective_from=frm, effective_to=to,
                params=params, citation=citation, authority=authority,
                source_url="https://example.invalid/source", supersedes=supersedes)


SEED = [
    _r("r-opt-90", "opt_unemployment_max", D(2008, 4, 8), {"days": 90},
       "8 CFR 214.2(f)(10)"),
    _r("r-stem-60", "stem_opt_unemployment_add", D(2016, 5, 10), {"days": 60},
       "81 FR 13040", "Federal Register"),
    _r("r-capgap-2008", "cap_gap_end", D(2008, 4, 8), {"end_rule": "SEPT_30"},
       "8 CFR 214.2(f)(5)(vi) (pre-2025)", to=D(2025, 1, 17)),
    _r("r-capgap-2025", "cap_gap_end", D(2025, 1, 17), {"end_rule": "APRIL_1"},
       "H-1B Modernization Final Rule", "Federal Register", supersedes="r-capgap-2008"),
    _r("r-ac21-365", "ac21_extension_threshold", D(2000, 10, 17), {"days": 365},
       "AC21 Sec. 106(a)", "INA"),
    _r("r-h1bmax", "h1b_max_stay", D(1990, 11, 29), {"years": 6},
       "INA Sec. 214(g)(4)", "INA"),
    _r("r-minhours", "opt_min_hours", D(2008, 4, 8), {"hours": 20},
       "SEVP Policy Guidance", "ICE SEVP Guidance"),
    _r("r-grace-60", "h1b_grace_period", D(2017, 1, 17), {"days": 60},
       "8 CFR 214.1(l)(2)"),
    _r("r-port-180", "i485_portability", D(2000, 10, 17), {"days": 180},
       "INA Sec. 204(j)", "INA"),
    _r("r-optwindow", "opt_filing_window", D(2008, 4, 8),
       {"before": 90, "after": 60, "i20_days": 30}, "8 CFR 214.2(f)(11)"),
]


@pytest.fixture
def ruleset():
    return RuleSet(SEED)


@pytest.fixture
def as_of():
    return D(2026, 8, 28)


@pytest.fixture
def maria():
    """Home health aide, STEM OPT, H-1B petition pending, in cap-gap.

    Cap-gap stacks on the OPT period rather than replacing it, which is why the
    layer discriminator exists. See docs/REVIEW.md A3.
    """
    return UserState(
        user_id="00000000-0000-4000-8000-00000000a001",
        locale="es",
        h1b_first_entry=None,
        status_periods=(
            StatusPeriod("F1", "primary", D(2022, 8, 20), D(2024, 5, 14),
                         program_end=D(2024, 5, 14)),
            StatusPeriod("STEM_OPT", "primary", D(2024, 8, 12), D(2026, 7, 31),
                         ead_start=D(2024, 8, 12), ead_expiry=D(2026, 7, 31),
                         is_stem=True),
            StatusPeriod("CAP_GAP", "authorization", D(2026, 8, 1), None),
        ),
        employment=(
            # Two concurrent part-time jobs. 15 + 15 = 30 hours a week, which is NOT
            # unemployment. The build spec's per-episode test calls both of these
            # unemployment. See docs/REVIEW.md A9.
            EmploymentEpisode("Bayview Home Care", D(2024, 9, 3), D(2026, 4, 10), 15),
            EmploymentEpisode("Sunset Senior Living", D(2024, 9, 3), D(2026, 4, 10), 15),
        ),
    )


@pytest.fixture
def daniel():
    """Adjunct instructor, H-1B year five, nothing filed."""
    return UserState(
        user_id="00000000-0000-4000-8000-00000000d001",
        h1b_first_entry=D(2021, 10, 1),
        status_periods=(
            StatusPeriod("H1B", "primary", D(2021, 10, 1), None),
        ),
        employment=(
            EmploymentEpisode("Bay Area Community College", D(2021, 10, 1), None, 40),
        ),
    )
