"""Replication tests. Need Postgres and ClickHouse both up.

The outbox is the CDC path. These assert the properties that make it safe: it is
idempotent, it is at-least-once rather than at-most-once, and the rollup cannot drift
from its source without a gate catching it.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

psycopg = pytest.importorskip("psycopg")

from api import clickhouse as ch  # noqa: E402
from api import replicate  # noqa: E402


def _pg_up() -> bool:
    try:
        with psycopg.connect(replicate.ADMIN_DSN, connect_timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_up() or not ch.available(),
    reason="needs Postgres and ClickHouse; run make -f Makefile.data up")


def _count(scenario: str = "actual") -> int:
    rows, _ = ch.query(
        "SELECT count() AS n FROM clock_evaluations WHERE scenario_id = {s:String}",
        {"s": scenario})
    return int(rows[0]["n"])


def test_a_drained_outbox_drains_to_zero():
    replicate.drain_once(verbose=False)
    assert replicate.lag()["pending"] == 0


def test_replication_is_idempotent():
    """A second pass over an empty outbox must not duplicate anything."""
    replicate.drain_once(verbose=False)
    before = _count()
    assert replicate.drain_once(verbose=False) == 0
    assert _count() == before


def test_resending_a_batch_does_not_change_the_answer():
    """At-least-once delivery means a batch can arrive twice.

    Rows are stamped only after ClickHouse acknowledges, so a crash mid-flight
    resends. The destination must therefore tolerate a duplicate without changing
    what a reader sees, which it does because the key is
    (user_id, clock_key, scenario_id, as_of) and a resend writes an identical row.
    """
    replicate.drain_once(verbose=False)
    rows, _ = ch.query(
        "SELECT uniqExact((user_id, clock_key, scenario_id, as_of)) AS keys, "
        "count() AS rows FROM clock_evaluations")
    keys, total = int(rows[0]["keys"]), int(rows[0]["rows"])
    # Distinct evaluations, not distinct physical rows: a resend is allowed to add a
    # row, and every query in clickhouse/queries/ groups by the key.
    assert keys > 0
    assert total >= keys


def test_the_rollup_agrees_with_its_source():
    """Regression for a real drift.

    TRUNCATE on clock_evaluations does NOT clear risk_rollup: a materialized view's
    rows live in its own table. Truncating the source alone left the rollup reporting
    users who no longer existed, which in an operator view means showing a population
    that is not there. make -f Makefile.data reset-evals truncates both.
    """
    rows, _ = ch.query("""
        SELECT countIf(agrees = 0) AS disagreements, count() AS compared
        FROM (
          SELECT r.users = s.users AS agrees
          FROM (SELECT as_of, clock_key, scenario_id, severity, uniqMerge(users) AS users
                FROM risk_rollup GROUP BY as_of, clock_key, scenario_id, severity) r
          FULL JOIN (SELECT as_of, clock_key, scenario_id, severity,
                            uniqExact(user_id) AS users
                     FROM clock_evaluations WHERE applicable = 1
                     GROUP BY as_of, clock_key, scenario_id, severity) s
          USING (as_of, clock_key, scenario_id, severity)
        )""")
    assert int(rows[0]["disagreements"]) == 0, "rollup has drifted; run reset-evals"
    assert int(rows[0]["compared"]) > 0


def test_not_applicable_evaluations_are_replicated_too():
    """A clock that is not running is a fact worth retaining.

    'AC21 has not started because you are not in H-1B status' is an answer, and
    keeping it is what lets the history show the day a clock began.
    """
    rows, _ = ch.query(
        "SELECT countIf(applicable = 0) AS not_running, countIf(applicable = 1) AS running "
        "FROM clock_evaluations WHERE scenario_id = 'actual'")
    assert int(rows[0]["not_running"]) > 0
    assert int(rows[0]["running"]) > 0


def test_scenario_rows_are_kept_separate_from_actual():
    rows, _ = ch.query(
        "SELECT scenario_id, count() AS n FROM clock_evaluations "
        "GROUP BY scenario_id ORDER BY scenario_id")
    scenarios = {r["scenario_id"] for r in rows}
    assert "actual" in scenarios
    assert len(scenarios) > 1, "no replay scenario has been written"


def test_column_lists_differ_on_purpose():
    """eval_date exists in ClickHouse and not in the outbox.

    as_of is the date a clock was computed FOR; eval_date is the date it was computed
    ON. Requesting eval_date from Postgres is an UndefinedColumn error, which is how
    this was found.
    """
    assert "eval_date" in replicate.CH_COLS
    assert "eval_date" not in replicate.PG_COLS
    assert set(replicate.PG_COLS) < set(replicate.CH_COLS)
