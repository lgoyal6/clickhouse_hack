"""Integration tests. These need Postgres up:

    make -f Makefile.data up migrate seed

They assert the things unit tests cannot: that RLS actually isolates, that the
routes return contract-valid shapes, and that the numbers coming out of the API
match the numbers the engine tests pin down.
"""
import datetime as dt
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

psycopg = pytest.importorskip("psycopg")
from fastapi.testclient import TestClient  # noqa: E402
from jsonschema import Draft202012Validator, FormatChecker  # noqa: E402

from api.main import app  # noqa: E402
from api import repository as repo  # noqa: E402

AS_OF = "2026-08-28"
MARIA = "00000000-0000-4000-8000-00000000a001"
DANIEL = "00000000-0000-4000-8000-00000000d001"


def _db_up() -> bool:
    try:
        with psycopg.connect(repo.DSN, connect_timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_up(), reason=f"Postgres not reachable at {repo.DSN}; run make -f Makefile.data up"
)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def schema():
    path = ROOT / "contracts" / "clock.schema.json"
    return Draft202012Validator(json.loads(path.read_text()), format_checker=FormatChecker())


def clocks(client, session, **params):
    r = client.get("/v1/clocks", cookies={"sc_session": session},
                   params={"as_of": AS_OF, **params})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------- identity -------

def test_no_session_is_401(client):
    assert client.get("/v1/clocks").status_code == 401


def test_unknown_session_is_401(client):
    assert client.get("/v1/clocks", cookies={"sc_session": "sess_whoever"}).status_code == 401


def test_no_route_accepts_a_user_id(client):
    """Passing a user id must not change whose clocks come back."""
    mine = clocks(client, "sess_maria")
    spoofed = clocks(client, "sess_maria", user_id=DANIEL, subject=DANIEL)
    assert [c["clock_key"] for c in mine["clocks"]] == \
           [c["clock_key"] for c in spoofed["clocks"]]


def test_rls_isolates_rows_not_just_queries():
    """The repository omits WHERE user_id on purpose. RLS has to be doing the work.

    If the policy were missing, or the role could bypass it, this would see both
    people's periods and fail.
    """
    with repo.subject_tx(MARIA) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM status_periods")
        assert cur.fetchone()["n"] == 3            # Maria's F1 + STEM_OPT + CAP_GAP
        cur.execute("SELECT count(*) AS n FROM users")
        assert cur.fetchone()["n"] == 1
        # Even naming the other subject explicitly returns nothing.
        cur.execute("SELECT count(*) AS n FROM status_periods WHERE user_id = %s", (DANIEL,))
        assert cur.fetchone()["n"] == 0

    with repo.subject_tx(DANIEL) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM status_periods")
        assert cur.fetchone()["n"] == 1


def test_the_app_role_cannot_bypass_rls():
    with repo.reference_tx() as conn, conn.cursor() as cur:
        cur.execute("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user")
        row = cur.fetchone()
        assert row["rolbypassrls"] is False
        assert row["rolsuper"] is False


def test_app_role_cannot_write_rules():
    """Rules change by migration with a human in the loop, never by a request."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repo.reference_tx() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO rules (rule_key, effective_from, params, citation, "
                "source_url, authority) VALUES "
                "('opt_min_hours','2031-01-01','{\"hours\":1}','x','https://x.invalid','8 CFR')"
            )


# ------------------------------------------------------------- contract -------

def test_every_clock_validates_against_the_contract(client, schema):
    for session in ("sess_maria", "sess_daniel"):
        for c in clocks(client, session)["clocks"]:
            errors = sorted(schema.iter_errors(c), key=lambda e: list(e.path))
            assert not errors, \
                f"{session} {c['clock_key']}: " + \
                "; ".join(f"{list(e.path)} {e.message}" for e in errors)


def test_every_running_clock_carries_complete_provenance(client):
    for session in ("sess_maria", "sess_daniel"):
        for c in clocks(client, session)["clocks"]:
            if not c["applicable"]:
                continue
            p = c["provenance"]
            assert p["citation"]
            assert p["source_url"].startswith("http")
            assert isinstance(p["verified"], bool)
            if p["verified"]:
                assert p["verified_by"], "verified with no signature is worse than unverified"


def test_verification_is_atomic_and_exactly_one_rule_is_flagged():
    """12 of 13 rules are signed off. lottery_selection is deliberately not.

    The build spec cites it as "Final Rule 2025-12-29" with no Federal Register
    number, and it powers the most quantitative screen in the product. Exactly one
    flagged card is the thesis working; thirteen would read as unfinished.
    See docs/REVIEW.md E1.
    """
    with repo.reference_tx() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT rule_key, effective_from, verified_by, verified_at FROM rules "
            "WHERE verified_by IS NULL OR verified_at IS NULL")
        unverified = cur.fetchall()
    assert len(unverified) == 1, [r["rule_key"] for r in unverified]
    assert unverified[0]["rule_key"] == "lottery_selection"
    assert unverified[0]["verified_by"] is None
    assert unverified[0]["verified_at"] is None      # the CHECK keeps these together


def test_disclaimer_is_present_once(client):
    body = clocks(client, "sess_maria")
    assert body["disclaimer"] == "This is information, not legal advice."


# --------------------------------------------------- the numbers, from the API -

def test_maria_gets_opt_clocks_and_not_h1b_clocks(client):
    body = clocks(client, "sess_maria")
    running = {c["clock_key"] for c in body["clocks"] if c["applicable"]}
    assert running == {"opt_unemployment", "cap_gap_window"}

    not_running = {c["clock_key"]: c["not_applicable_reason"]
                   for c in body["clocks"] if not c["applicable"]}
    assert "six-year meter has not started" in not_running["ac21_365"]


def test_cap_gap_returns_three_distinct_numbers(client):
    body = clocks(client, "sess_maria")
    cap = next(c for c in body["clocks"] if c["clock_key"] == "cap_gap_window")
    assert cap["window_end"] == "2027-04-01"
    assert cap["days_remaining"] == 216
    assert cap["window_days"] == 243
    assert cap["superseded"]["delta_days"] == 183
    assert cap["superseded"]["prior_value"] == "SEP 30 2026"


def test_maria_unemployment_reflects_aggregated_hours(client):
    body = clocks(client, "sess_maria")
    unemp = next(c for c in body["clocks"] if c["clock_key"] == "opt_unemployment")
    assert unemp["denominator"] == 150               # STEM, not 90
    # Two 15-hour jobs ran 2024-09-03..2026-04-10 and are NOT unemployment.
    before = (dt.date(2024, 9, 3) - dt.date(2024, 8, 12)).days
    after = (dt.date(2026, 7, 31) - dt.date(2026, 4, 10)).days
    assert unemp["days_consumed"] == before + after


def test_daniel_ac21_is_derived_and_shows_its_arithmetic(client):
    body = clocks(client, "sess_daniel")
    ac21 = next(c for c in body["clocks"] if c["clock_key"] == "ac21_365")
    assert ac21["applicable"] is True
    assert ac21["derived"] is True
    assert ac21["days_remaining"] == 34
    assert ac21["severity"] == "critical"
    assert "our arithmetic" in ac21["derivation"]


def test_locale_follows_the_person(client):
    assert next(c for c in clocks(client, "sess_maria")["clocks"]
                if c["clock_key"] == "opt_unemployment")["label"] == "Días de desempleo"
    assert next(c for c in clocks(client, "sess_daniel")["clocks"]
                if c["clock_key"] == "ac21_365")["label"] == "AC21 365-day threshold"


def test_critical_sorts_first(client):
    running = [c for c in clocks(client, "sess_daniel")["clocks"] if c["applicable"]]
    assert running[0]["severity"] == "critical"


# ------------------------------------------------------------- the outbox -----

def test_evaluations_land_in_the_outbox(client):
    clocks(client, "sess_maria")
    with repo.subject_tx(MARIA) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT clock_key, scenario_id, applicable, days_remaining "
            "FROM clock_evaluation_outbox WHERE as_of = %s ORDER BY clock_key",
            (AS_OF,),
        )
        rows = cur.fetchall()
    assert rows, "the outbox is the CDC source; nothing was written"
    assert {r["scenario_id"] for r in rows} == {"actual"}
    assert any(r["clock_key"] == "cap_gap_window" and r["days_remaining"] == 216
               for r in rows)


def test_reevaluating_the_same_day_does_not_double_count(client):
    """A nightly job that runs twice must not inflate the population. REVIEW B2."""
    clocks(client, "sess_maria")
    with repo.subject_tx(MARIA) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM clock_evaluation_outbox WHERE as_of = %s",
                    (AS_OF,))
        first = cur.fetchone()["n"]
    clocks(client, "sess_maria")
    with repo.subject_tx(MARIA) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM clock_evaluation_outbox WHERE as_of = %s",
                    (AS_OF,))
        assert cur.fetchone()["n"] == first


# ------------------------------------------------------------- replay ---------

def test_replay_produces_a_diff_for_a_rule_that_has_not_taken_effect(client):
    r = client.post(
        "/v1/scenarios/replay",
        cookies={"sc_session": "sess_daniel"},
        json={"scenario_id": "rule:h1b_max_5y", "clock_key": "h1b_max_stay",
              "overrides": {"h1b_max_stay": {"years": 5}}, "as_of": AS_OF},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    diff = next(d for d in body["diffs"] if d["clock_key"] == "h1b_max_stay")
    assert diff["under_actual"] == 399
    assert diff["under_scenario"] == 34
    assert diff["days_lost"] == 365
    assert body["elapsed_ms"] > 0
    assert not diff["subject_ref"].startswith("00000000"), "do not leak the raw subject id"


def test_replay_writes_both_scenarios(client):
    client.post(
        "/v1/scenarios/replay",
        cookies={"sc_session": "sess_daniel"},
        json={"scenario_id": "rule:h1b_max_5y", "clock_key": "h1b_max_stay",
              "overrides": {"h1b_max_stay": {"years": 5}}, "as_of": AS_OF},
    )
    with repo.subject_tx(DANIEL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT scenario_id FROM clock_evaluation_outbox WHERE as_of = %s "
            "ORDER BY scenario_id", (AS_OF,))
        seen = {r["scenario_id"] for r in cur.fetchall()}
    # Subset, not equality: other scenarios may have been run against this database,
    # and asserting the exact set makes the test order-dependent on other tests.
    assert {"actual", "rule:h1b_max_5y"} <= seen


def test_actual_is_a_reserved_scenario_id(client):
    r = client.post("/v1/scenarios/replay", cookies={"sc_session": "sess_daniel"},
                    json={"scenario_id": "actual", "clock_key": "h1b_max_stay",
                          "overrides": {}})
    assert r.status_code == 422


# ------------------------------------------------------------- writes ---------

def test_overlapping_primary_status_returns_409_with_usable_copy(client):
    r = client.post(
        "/v1/facts", cookies={"sc_session": "sess_maria"},
        json={"kind": "status_period", "confidence": "user_stated",
              "payload": {"status_type": "H1B", "layer": "primary",
                          "start_date": "2025-01-01", "end_date": "2025-06-01"}},
    )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["error"] == "overlapping_status"
    assert "Adjust one of them" in body["message"]


def test_a_stacked_authorization_is_accepted_then_cleaned_up(client):
    r = client.post(
        "/v1/facts", cookies={"sc_session": "sess_maria"},
        json={"kind": "status_period", "confidence": "user_stated",
              "payload": {"status_type": "GRACE", "layer": "authorization",
                          "start_date": "2026-08-05", "end_date": "2026-08-20"}},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["needs_confirmation"] is True
    with repo.subject_tx(MARIA) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM status_periods WHERE id = %s", (body["id"],))


# ------------------------------------------------------------- rules ----------

def test_rule_chain_walks_to_the_oldest_version(client):
    r = client.get("/v1/rules/cap_gap_end", params={"as_of": AS_OF})
    assert r.status_code == 200
    body = r.json()
    assert [v["effective_from"] for v in body["chain"]] == ["2025-01-17", "2008-04-08"]
    assert body["governing"]["params"] == {"end_rule": "APRIL_1"}
    assert body["chain"][1]["effective_to"] == "2025-01-17"


def test_unknown_rule_is_404(client):
    assert client.get("/v1/rules/not_a_rule").status_code == 404
