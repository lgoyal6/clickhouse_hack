"""Verification for the findings in docs/REVIEW.md that change a number.

Each test names the finding it locks down. These are the failing tests the fixes
were written against.
"""
import datetime as dt

import pytest

from engine.clocks import cap_gap_window, opt_unemployment, ac21_365, h1b_max_stay
from engine.evaluate import evaluate, change_reason
from engine.rules import RuleSet

D = dt.date


# ---------------------------------------------------------------- REVIEW A2 ----

def test_capgap_supersession_fires_on_the_demo_date(maria, as_of, ruleset):
    """The strikethrough must render. This is the demo beat."""
    r = cap_gap_window.compute(maria, as_of, ruleset)
    assert r["superseded"] is not None
    assert r["superseded"]["prior_value"] == "SEP 30 2026"
    assert r["superseded"]["superseded_on"] == D(2025, 1, 17)


def test_spec_one_year_lookback_would_not_fire(ruleset, as_of):
    """The build spec resolves the prior rule at as_of minus one year.

    That lands on 2025-08-28, which resolves to the SAME 2025 rule, so
    prior.id == rule.id, superseded is None, and the strikethrough never renders.
    This test documents the bug the chain walk replaces. See docs/REVIEW.md A2.
    """
    governing = ruleset.governing("cap_gap_end", as_of)
    spec_prior = ruleset.governing("cap_gap_end", as_of.replace(year=as_of.year - 1))
    assert spec_prior.rule_id == governing.rule_id      # the bug

    chain_prior = ruleset.prior(governing)              # the fix
    assert chain_prior is not None
    assert chain_prior.rule_id != governing.rule_id


def test_capgap_three_numbers_are_three_numbers(maria, as_of, ruleset):
    """216 remaining, 243-day window, 183 days gained. See docs/REVIEW.md F3."""
    r = cap_gap_window.compute(maria, as_of, ruleset)
    assert r["window_end"] == D(2027, 4, 1)
    assert r["days_remaining"] == 216
    assert r["window_days"] == 243
    assert r["superseded"]["delta_days"] == 183


# ---------------------------------------------------------------- REVIEW A9 ----

def test_concurrent_part_time_jobs_are_not_unemployment(maria, as_of, ruleset):
    """15 + 15 hours across two employers is 30 hours, not unemployment."""
    mid_job = D(2025, 6, 1)
    assert opt_unemployment.hours_on(maria, mid_job) == 30

    r = opt_unemployment.compute(maria, as_of, ruleset)
    # Employment ran 2024-09-03 to 2026-04-10. Unemployed days are the gap before
    # the job started and the gap after it ended, both inside the EAD window.
    before = (D(2024, 9, 3) - D(2024, 8, 12)).days
    after = (D(2026, 7, 31) - D(2026, 4, 10)).days
    assert r["days_consumed"] == before + after


def test_per_episode_test_would_have_overcounted(maria, as_of, ruleset):
    """What the spec's algorithm would have produced, for contrast."""
    per_episode_unemployed = sum(
        1
        for day in _days(D(2024, 8, 12), D(2026, 7, 31))
        if not any(
            (e.hours_per_week or 0) >= 20
            and e.start_date <= day
            and (e.end_date is None or day <= e.end_date)
            for e in maria.employment
        )
    )
    correct = opt_unemployment.compute(maria, as_of, ruleset)["days_consumed"]
    assert per_episode_unemployed > correct
    # The whole 585-day employed stretch would have been called unemployment.
    assert per_episode_unemployed - correct == (D(2026, 4, 10) - D(2024, 9, 3)).days + 1


# --------------------------------------------------------------- REVIEW A10 ----

def test_unemployment_is_bounded_to_the_authorization_window(maria, as_of, ruleset):
    """A pre-OPT gap must not count. Maria's F-1 study period had no employment."""
    r = opt_unemployment.compute(maria, as_of, ruleset)
    assert r["window_start"] == D(2024, 8, 12)
    # 2022-08-20 through 2024-08-11 was jobless and must contribute nothing.
    assert r["days_consumed"] < (as_of - D(2022, 8, 20)).days


def test_stem_denominator_is_150_not_90(maria, as_of, ruleset):
    r = opt_unemployment.compute(maria, as_of, ruleset)
    assert r["denominator"] == 150


# ---------------------------------------------------------------- REVIEW B5 ----

def test_missing_param_raises_instead_of_coercing(ruleset, as_of):
    rule = ruleset.governing("opt_unemployment_max", as_of)
    with pytest.raises(KeyError, match="has no param 'nope'"):
        rule.param("nope")


def test_rule_gap_raises_instead_of_rendering_empty(as_of):
    empty = RuleSet([])
    with pytest.raises(LookupError, match="no rule version governs"):
        empty.governing("cap_gap_end", as_of)


# ---------------------------------------------------------------- REVIEW B6 ----

def test_inputs_hash_ignores_the_calendar(maria):
    """The hash must not change because a day passed, or the signal is gone."""
    a = maria.inputs_hash()
    b = maria.inputs_hash()
    assert a == b


def test_inputs_hash_changes_when_facts_change(maria):
    from engine.state import EmploymentEpisode
    before = maria.inputs_hash()
    changed = type(maria)(**{**maria.__dict__,
                             "employment": maria.employment + (
                                 EmploymentEpisode("New Job", D(2026, 8, 1), None, 40),)})
    assert changed.inputs_hash() != before


def test_change_reason_distinguishes_three_cases(maria, daniel, as_of, ruleset):
    today = {"inputs_hash": "aaa", "provenance": {"rule_id": "r1"}}
    assert change_reason(today, {"inputs_hash": "bbb", "provenance": {"rule_id": "r1"}}) == "facts_changed"
    assert change_reason(today, {"inputs_hash": "aaa", "provenance": {"rule_id": "r0"}}) == "law_changed"
    assert change_reason(today, {"inputs_hash": "aaa", "provenance": {"rule_id": "r1"}}) == "time_passed"


# ---------------------------------------------------------------- REVIEW B7 ----

def test_h1b_max_says_so_when_recapture_data_is_missing(daniel, as_of, ruleset):
    r = h1b_max_stay.compute(daniel, as_of, ruleset)
    assert r["window_end"] == D(2027, 10, 1)
    assert r["days_remaining"] == 399
    assert "no absence records are on file" in r["derivation"]


def test_h1b_max_recaptures_absences(daniel, as_of, ruleset):
    from engine.state import Absence
    travelled = type(daniel)(**{**daniel.__dict__,
                                "absences": (Absence(D(2023, 6, 1), D(2023, 7, 1)),)})
    r = h1b_max_stay.compute(travelled, as_of, ruleset)
    assert r["window_end"] == D(2027, 10, 31)          # 30 days recaptured
    assert "30 days of recaptured time abroad" in r["derivation"]


# --------------------------------------------------------------- REVIEW B11 ----

def test_stem_opt_person_does_not_get_h1b_clocks(maria, as_of, ruleset):
    """The Clock Wall mock renders OPT and H-1B clocks for one person.

    Reasons are CODES here, not sentences: the engine must stay language-free so the
    API can render them in English, Spanish or Hindi.

    Nobody can be running both: someone in cap-gap is in F-1 status with a pending
    petition, so the six-year meter has not started and AC21 has nothing to extend.
    """
    clocks = evaluate(maria, as_of, ruleset)
    running = {c["clock_key"] for c in clocks if c["applicable"]}
    assert running == {"opt_unemployment", "cap_gap_window"}

    not_running = {c["clock_key"]: c["not_applicable_reason"]
                   for c in clocks if not c["applicable"]}
    assert "ac21_365" in not_running
    assert not_running["ac21_365"] == "not_h1b"


def test_h1b_person_does_not_get_opt_clocks(daniel, as_of, ruleset):
    clocks = evaluate(daniel, as_of, ruleset)
    running = {c["clock_key"] for c in clocks if c["applicable"]}
    assert running == {"ac21_365", "h1b_max_stay"}


def test_ac21_disappears_once_something_is_filed(daniel, as_of, ruleset):
    from engine.state import Milestone
    filed = type(daniel)(**{**daniel.__dict__,
                            "milestones": (Milestone("PERM_FILED", D(2026, 3, 1)),)})
    ok, reason = ac21_365.applies(filed, as_of)
    assert not ok and reason == "already_filed"


def test_ac21_is_marked_derived_and_shows_its_arithmetic(daniel, as_of, ruleset):
    r = ac21_365.compute(daniel, as_of, ruleset)
    assert r["derived"] is True
    assert r["days_remaining"] == 34            # 2026-10-01 minus 2026-08-28
    assert "our arithmetic" in r["derivation"]
    assert r["severity"] == "critical"


# ---------------------------------------------------------------- REVIEW A1 ----

def test_replay_is_a_write_and_produces_a_real_diff(daniel, as_of, ruleset):
    """Same engine, two scenarios, one diff.

    The scenario run overrides rule params rather than reading old rows back, so it
    works for a rule change that has NOT taken effect, which is the case the demo
    uses and the case the spec's query returns nothing for.
    """
    from engine.tests.conftest import SEED

    actual = evaluate(daniel, as_of, ruleset, scenario_id="actual")
    scenario = evaluate(
        daniel, as_of,
        RuleSet(SEED, overrides={"h1b_max_stay": {"years": 5}}),
        scenario_id="rule:h1b_max_5y",
    )

    a = {c["clock_key"]: c for c in actual if c["applicable"]}
    s = {c["clock_key"]: c for c in scenario if c["applicable"]}

    assert a["h1b_max_stay"]["days_remaining"] == 399
    assert s["h1b_max_stay"]["days_remaining"] == 34      # a full year lost
    assert s["h1b_max_stay"]["days_remaining"] < a["h1b_max_stay"]["days_remaining"]
    assert s["h1b_max_stay"]["scenario_id"] == "rule:h1b_max_5y"
    # And the diff is computed for the SAME as_of on both sides, so the difference
    # is the rule and nothing else.
    assert a["h1b_max_stay"]["as_of"] == s["h1b_max_stay"]["as_of"]


# ------------------------------------------------------------- provenance ------

def test_every_running_clock_carries_full_provenance(maria, daniel, as_of, ruleset):
    for state in (maria, daniel):
        for c in evaluate(state, as_of, ruleset):
            if not c["applicable"]:
                continue
            p = c["provenance"]
            for field in ("rule_id", "citation", "authority", "effective_from",
                          "source_url", "verified"):
                assert field in p, f"{c['clock_key']} is missing provenance.{field}"
            assert p["verified"] is False, "seeded rules must render the warning band"


def test_critical_sorts_first(daniel, as_of, ruleset):
    clocks = [c for c in evaluate(daniel, as_of, ruleset) if c["applicable"]]
    assert clocks[0]["severity"] == "critical"


def test_rule_chain_walks_to_the_oldest_version(ruleset, as_of):
    chain = ruleset.chain("cap_gap_end", as_of)
    assert [r.effective_from for r in chain] == [D(2025, 1, 17), D(2008, 4, 8)]


def _days(a, b):
    import datetime
    d = a
    while d <= b:
        yield d
        d += datetime.timedelta(days=1)


# ------------------------------------------------------- regression -----------

def test_demo_user_ids_are_real_uuids(maria, daniel):
    """These strings reach Postgres as UUID.

    They were originally written with 'ma01'/'da01' suffixes, which are not hex, so
    every insert failed with 'invalid input syntax for type uuid' the first time the
    migrations were run against a real database. Python never parsed them, so the
    tests passed and the defect was invisible until the SQL executed.
    """
    import uuid
    for state in (maria, daniel):
        assert str(uuid.UUID(state.user_id)) == state.user_id


# --------------------------------------------------- the last three clocks -----

def test_grace_period_does_not_run_while_employed(daniel, as_of, ruleset):
    from engine.clocks import h1b_grace_period
    ok, reason = h1b_grace_period.applies(daniel, as_of)
    assert not ok and reason == "currently_employed"


def test_grace_period_counts_from_the_last_day_worked(daniel, as_of, ruleset):
    from engine.clocks import h1b_grace_period
    from engine.state import EmploymentEpisode
    laid_off = type(daniel)(**{**daniel.__dict__, "employment": (
        EmploymentEpisode("Bay Area Community College", D(2021, 10, 1), D(2026, 8, 1), 40),)})
    r = h1b_grace_period.compute(laid_off, as_of, ruleset)
    assert r["days_consumed"] == 27               # 2026-08-01 -> 2026-08-28
    assert r["days_remaining"] == 33
    assert r["window_end"] == D(2026, 9, 30)
    assert r["severity"] == "info"


def test_grace_period_is_the_replay_target(daniel, as_of, ruleset):
    """Eliminating it must show up as 60 days lost, for someone not yet laid off's
    sake this uses the laid-off variant."""
    from engine.clocks import h1b_grace_period
    from engine.state import EmploymentEpisode
    from engine.tests.conftest import SEED
    laid_off = type(daniel)(**{**daniel.__dict__, "employment": (
        EmploymentEpisode("X", D(2021, 10, 1), D(2026, 8, 1), 40),)})
    actual = h1b_grace_period.compute(laid_off, as_of, ruleset)
    zeroed = h1b_grace_period.compute(
        laid_off, as_of, RuleSet(SEED, overrides={"h1b_grace_period": {"days": 0}}))
    assert actual["days_remaining"] == 33
    assert zeroed["days_remaining"] == -27
    assert zeroed["severity"] == "critical"


def test_portability_needs_an_i485(daniel, as_of, ruleset):
    from engine.clocks import i485_portability
    ok, reason = i485_portability.applies(daniel, as_of)
    assert not ok and reason == "no_i485"


def test_portability_counts_up_to_a_freedom(daniel, as_of, ruleset):
    from engine.clocks import i485_portability
    from engine.state import Milestone
    filed = type(daniel)(**{**daniel.__dict__,
                            "milestones": (Milestone("I485_FILED", D(2026, 6, 1)),)})
    r = i485_portability.compute(filed, as_of, ruleset)
    assert r["window_end"] == D(2026, 11, 28)
    assert r["days_remaining"] == 92
    assert r["severity"] == "info", "counting up to a freedom is never critical"

    later = i485_portability.compute(filed, D(2027, 1, 1), ruleset)
    assert later["days_remaining"] == 0
    assert later["severity"] == "clear"
    assert "portability is available" in later["derivation"]


def test_filing_window_closes_once_opt_is_authorised(maria, as_of, ruleset):
    from engine.clocks import opt_filing_window
    ok, reason = opt_filing_window.applies(maria, as_of)
    assert not ok and reason == "opt_authorised"


def test_filing_window_spans_90_before_to_60_after(ruleset):
    from engine.clocks import opt_filing_window
    from engine.state import StatusPeriod, UserState
    student = UserState(
        user_id="00000000-0000-4000-8000-00000000f001",
        status_periods=(StatusPeriod("F1", "primary", D(2022, 8, 20), None,
                                     program_end=D(2026, 12, 18)),))
    ok, _ = opt_filing_window.applies(student, D(2026, 8, 28))
    assert ok
    r = opt_filing_window.compute(student, D(2026, 8, 28), ruleset)
    assert r["window_start"] == D(2026, 9, 19)     # 90 days before
    assert r["window_end"] == D(2027, 2, 16)       # 60 days after
    assert r["window_days"] == 150
    assert "runs independently" in r["derivation"], "the 30-day I-20 clock must be named"


def test_all_seven_clocks_are_implemented():
    from engine.clocks import REGISTRY, ALL_CLOCK_KEYS, NOT_YET_IMPLEMENTED
    assert NOT_YET_IMPLEMENTED == ()
    assert set(REGISTRY) == set(ALL_CLOCK_KEYS)
