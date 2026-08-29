"""Postgres access. The only place identity is bound to a connection.

Every read and write happens inside `subject_tx`, which sets
`status_clock.subject` with SET LOCAL. The RLS policies in
`db/migrations/0006_rls.sql` read that GUC, and the API connects as
`status_clock_app`, which has no BYPASSRLS. So a query cannot see another
person's rows even if the SQL forgets a WHERE clause.

The engine stays database-free: this module builds `engine.state.UserState` and
`engine.rules.RuleSet` and hands them over. See docs/REVIEW.md D1.
"""
from __future__ import annotations

import datetime as dt
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from engine.rules import Rule, RuleSet
from engine.state import (
    Absence,
    EmploymentEpisode,
    Milestone,
    StatusPeriod,
    UserState,
)

DSN = os.environ.get(
    "STATUS_CLOCK_DSN",
    "postgresql://status_clock_app:devonly@localhost:5432/status_clock",
)


@contextmanager
def subject_tx(subject_id: str):
    """A transaction scoped to one person.

    SET LOCAL, so the binding dies with the transaction and cannot leak into the
    next request on a pooled connection.
    """
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('status_clock.subject', %s, true)",
                            (subject_id,))
            yield conn


@contextmanager
def reference_tx():
    """For reference data only: rules, templates. No subject, so no per-person rows."""
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        with conn.transaction():
            yield conn


def load_ruleset(conn, overrides: dict[str, dict] | None = None) -> RuleSet:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text AS rule_id, rule_key, effective_from, effective_to,
                   params, citation, authority, source_url,
                   supersedes::text AS supersedes, note, verified_by, verified_at
            FROM rules
            """
        )
        rows = cur.fetchall()
    return RuleSet([Rule(**r) for r in rows], overrides=overrides)


def load_user_state(conn, subject_id: str) -> UserState:
    """Build UserState. Every query below relies on RLS, not on a WHERE clause.

    The absence of `WHERE user_id = ...` is deliberate and is the point: if the
    policy were missing or the role could bypass it, the integration tests would
    catch it immediately rather than the code silently over-reading.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id::text, email, locale, country_chg, h1b_first_entry FROM users")
        user = cur.fetchone()
        if user is None:
            raise LookupError(f"no visible user for subject {subject_id}")

        cur.execute(
            """
            SELECT status_type, layer, start_date, end_date, ead_start, ead_expiry,
                   program_end, is_stem, i94_expiry
            FROM status_periods ORDER BY start_date
            """
        )
        periods = tuple(StatusPeriod(**r) for r in cur.fetchall())

        cur.execute(
            """
            SELECT employer_name, start_date, end_date, hours_per_week,
                   counts_as_employment
            FROM employment_episodes ORDER BY start_date, employer_name
            """
        )
        employment = tuple(EmploymentEpisode(**r) for r in cur.fetchall())

        cur.execute("SELECT milestone, event_date FROM gc_milestones ORDER BY event_date")
        milestones = tuple(Milestone(**r) for r in cur.fetchall())

        cur.execute("SELECT departed_on, returned_on FROM absences ORDER BY departed_on")
        absences = tuple(Absence(**r) for r in cur.fetchall())

    return UserState(
        user_id=user["id"],
        locale=user["locale"],
        h1b_first_entry=user["h1b_first_entry"],
        status_periods=periods,
        employment=employment,
        milestones=milestones,
        absences=absences,
    )


def write_outbox(conn, subject_id: str, clocks: list[dict], as_of: dt.date) -> int:
    """Append evaluations to the outbox, in the caller's transaction.

    This is the write path the build spec routed straight into ClickHouse. Landing
    it here means the evaluations share a transaction with the alerts, so the
    retained history and the alert set cannot disagree. CDC carries it onward.
    See docs/REVIEW.md B3.

    Idempotent per (user, clock, as_of, scenario) so a re-run or a backfill updates
    rather than double-counting. See docs/REVIEW.md B2.
    """
    rows = []
    for c in clocks:
        prov = c.get("provenance") or {}
        rows.append((
            as_of, subject_id, c["clock_key"], c["scenario_id"],
            c["applicable"], c.get("not_applicable_reason"),
            c.get("days_remaining"), c.get("days_consumed"), c.get("denominator"),
            c.get("severity", "info"),
            prov.get("rule_id"), prov.get("rule_key"), prov.get("effective_from"),
            c["inputs_hash"], c["engine_version"],
        ))
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO clock_evaluation_outbox
              (as_of, user_id, clock_key, scenario_id, applicable,
               not_applicable_reason, days_remaining, days_consumed, denominator,
               severity, rule_id, rule_key, rule_effective_from, inputs_hash,
               engine_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id, clock_key, as_of, scenario_id) DO UPDATE SET
              evaluated_at = now(),
              applicable = EXCLUDED.applicable,
              not_applicable_reason = EXCLUDED.not_applicable_reason,
              days_remaining = EXCLUDED.days_remaining,
              days_consumed = EXCLUDED.days_consumed,
              denominator = EXCLUDED.denominator,
              severity = EXCLUDED.severity,
              rule_id = EXCLUDED.rule_id,
              inputs_hash = EXCLUDED.inputs_hash,
              engine_version = EXCLUDED.engine_version,
              replicated_at = NULL
            """,
            rows,
        )
    return len(rows)


def previous_evaluation(conn, clock_key: str, before: dt.date) -> dict | None:
    """Yesterday's row, for change_reason. Three cases, not two. REVIEW B6."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT inputs_hash, rule_id::text AS rule_id, as_of
            FROM clock_evaluation_outbox
            WHERE clock_key = %s AND scenario_id = 'actual' AND as_of < %s
            ORDER BY as_of DESC LIMIT 1
            """,
            (clock_key, before),
        )
        return cur.fetchone()


def current_employment(conn) -> dict | None:
    """The person's live job, for the Standing screen.

    RLS scopes this; there is no user_id in the query. Returns the most recent open
    episode, or the latest closed one if nothing is open.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT employer_name, soc_code, worksite_state, offered_wage, wage_unit,
                   start_date, end_date, hours_per_week
            FROM employment_episodes
            ORDER BY (end_date IS NULL) DESC, start_date DESC
            LIMIT 1
            """
        )
        return cur.fetchone()


# Columns a caller may set, per fact kind. An allow-list rather than passing the
# payload through: the request comes from a language model reading a document, and
# "whatever keys it produced" is not a schema.
WRITABLE = {
    "status_period": ("status_type", "layer", "start_date", "end_date", "ead_start",
                      "ead_expiry", "program_end", "is_stem", "i94_expiry"),
    "employment_episode": ("employer_name", "start_date", "end_date", "hours_per_week",
                           "soc_code", "worksite_state", "offered_wage", "wage_unit",
                           "employment_kind", "counts_as_employment"),
    "gc_milestone": ("milestone", "event_date", "priority_date", "category",
                     "receipt_number"),
}

HAS_CONFIDENCE = {"status_period"}

TABLES = {
    "status_period": "status_periods",
    "employment_episode": "employment_episodes",
    "gc_milestone": "gc_milestones",
}

RETURNING = {
    "status_period": "id::text, status_type, layer, start_date, end_date, confidence",
    "employment_episode": "id::text, employer_name, start_date, end_date, hours_per_week",
    "gc_milestone": "id::text, milestone, event_date, category",
}


def write_fact(conn, subject_id: str, kind: str, payload: dict,
               confidence: str = "inferred") -> dict:
    """Insert one extracted fact and read it straight back.

    Reads back rather than echoing the request, so what the user confirms is what the
    database actually holds, including anything a default or a trigger changed.
    """
    cols = WRITABLE[kind]
    values = {k: payload[k] for k in cols if k in payload and payload[k] is not None}
    values["user_id"] = subject_id
    # Only status_periods carries a confidence column. employment_episodes and
    # gc_milestones do not, and adding it blindly raises UndefinedColumn.
    if kind in HAS_CONFIDENCE:
        values["confidence"] = confidence

    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {TABLES[kind]} ({names}) VALUES ({marks}) "
            f"RETURNING {RETURNING[kind]}",
            list(values.values()),
        )
        return cur.fetchone()


def rule_versions(conn, rule_key: str | None = None) -> list[dict]:
    """Every version of every rule, newest first. Backs claim checking."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text AS rule_id, rule_key, effective_from, effective_to,
                   params, citation, authority, source_url,
                   supersedes::text AS supersedes, note, verified_by, verified_at
            FROM rules
            -- Cast both: Postgres cannot infer the type of a bare NULL parameter
            -- and raises IndeterminateDatatype on $1.
            WHERE %s::text IS NULL OR rule_key = %s::text
            ORDER BY rule_key, effective_from DESC
            """,
            (rule_key, rule_key),
        )
        return cur.fetchall()


def end_employment(conn, end_date, employer_name: str | None = None) -> dict | None:
    """Close the open employment episode. "I was laid off on 1 August."

    This is an UPDATE, not an INSERT, and the distinction matters. Recording a layoff
    as a new closed episode leaves the original open one in place, so the person still
    reads as employed and the grace period never starts. Status history is corrected,
    not appended to; that is the argument for Postgres in the first place.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE employment_episodes SET end_date = %s
            WHERE end_date IS NULL
              AND (%s::text IS NULL OR employer_name ILIKE %s::text)
            RETURNING id::text, employer_name, start_date, end_date
            """,
            (end_date, employer_name, employer_name),
        )
        return cur.fetchone()


def record_h1b_petition(conn, receipt_date) -> dict:
    """Record a pending cap-subject H-1B petition, and open the cap-gap it creates.

    There was no way to express this, which is a hole in the middle of the product's
    own story: cap-gap exists BECAUSE a petition is pending, and the demo persona has
    a cap-gap period only because it was seeded by hand. Someone uploading a receipt
    notice had nowhere to put it.

    Cap-gap runs from the day after the OPT authorization ends. Its end date is left
    NULL deliberately: the cap_gap_end rule decides that, and hard-coding a date here
    would put a number in the database that no citation governs.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text, status_type, ead_expiry FROM status_periods
            WHERE status_type IN ('OPT','STEM_OPT') AND ead_expiry IS NOT NULL
            ORDER BY ead_expiry DESC LIMIT 1
            """
        )
        opt = cur.fetchone()
        if opt is None:
            raise LookupError(
                "No OPT period with an EAD end date on file. Add the OPT "
                "authorization first; cap-gap extends it and cannot exist without it.")

        cur.execute(
            """
            INSERT INTO status_periods
              (user_id, status_type, layer, start_date, confidence)
            VALUES (current_subject(), 'CAP_GAP', 'authorization',
                    %s::date + 1, 'document_verified')
            ON CONFLICT DO NOTHING
            RETURNING id::text, status_type, layer, start_date
            """,
            (opt["ead_expiry"],),
        )
        created = cur.fetchone()

    return {
        "receipt_date": str(receipt_date),
        "cap_gap": created,
        "extends": {"status_type": opt["status_type"], "ead_expiry": str(opt["ead_expiry"])},
    }
