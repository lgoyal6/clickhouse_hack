"""Drain the evaluation outbox into ClickHouse.

    python -m api.replicate            # one pass
    python -m api.replicate --watch 5  # poll every 5s

This is the CDC path. Evaluations land in Postgres inside the same transaction as the
alerts (see db/migrations/0005), so the retained history and the alert set cannot
disagree, and this carries them onward. PeerDB is a faster version of exactly this
loop, not a different architecture. See docs/REVIEW.md B3 and C6.

Two properties that matter:

  * At-least-once, and idempotent at the destination. Rows are stamped
    `replicated_at` only after ClickHouse acknowledges, so a crash mid-flight resends
    rather than loses. The destination key is (user_id, clock_key, scenario_id, as_of),
    and re-sending the same evaluation writes an identical row.
  * It reads the outbox with a superuser connection, deliberately. Replication is the
    one job that must see every subject's rows, and it is a background process rather
    than a request, so no session identity exists to scope it to. Every OTHER path
    goes through repository.subject_tx and RLS.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import psycopg
from psycopg.rows import dict_row

from . import clickhouse as ch

# Superuser, not status_clock_app: this job must cross subjects by design.
ADMIN_DSN = os.environ.get(
    "STATUS_CLOCK_ADMIN_DSN",
    "postgresql://postgres:devonly@localhost:5432/status_clock",
)

BATCH = 5000

# The outbox has no eval_date: it is the date the row was computed ON, derived here
# from evaluated_at, while as_of is the date it was computed FOR. Keeping the two
# column lists separate is what stops that difference becoming a runtime error.
PG_COLS = ("evaluated_at", "as_of", "user_id", "clock_key", "scenario_id",
           "applicable", "not_applicable_reason", "days_remaining", "days_consumed",
           "denominator", "severity", "rule_id", "rule_key", "rule_effective_from",
           "inputs_hash", "engine_version")

CH_COLS = ("evaluated_at", "as_of", "eval_date", "user_id", "clock_key", "scenario_id",
           "applicable", "not_applicable_reason", "days_remaining", "days_consumed",
           "denominator", "severity", "rule_id", "rule_key", "rule_effective_from",
           "inputs_hash", "engine_version")


def _tsv(rows: list[dict]) -> str:
    out = []
    for r in rows:
        out.append("\t".join([
            r["evaluated_at"].strftime("%Y-%m-%d %H:%M:%S"),
            r["as_of"].isoformat(),
            r["evaluated_at"].date().isoformat(),
            str(r["user_id"]),
            r["clock_key"],
            r["scenario_id"],
            "1" if r["applicable"] else "0",
            (r["not_applicable_reason"] or "").replace("\t", " "),
            _n(r["days_remaining"]), _n(r["days_consumed"]), _n(r["denominator"]),
            r["severity"],
            # A not-applicable evaluation has no governing rule. ClickHouse UUID is
            # not nullable here, so the zero UUID stands for "no rule", and
            # applicable=0 is what tells a reader to ignore it.
            str(r["rule_id"] or "00000000-0000-0000-0000-000000000000"),
            r["rule_key"] or "",
            (r["rule_effective_from"] or r["as_of"]).isoformat(),
            r["inputs_hash"],
            r["engine_version"],
        ]))
    return "\n".join(out) + "\n"


def _n(v) -> str:
    return "\\N" if v is None else str(v)


def drain_once(verbose: bool = True) -> int:
    total = 0
    with psycopg.connect(ADMIN_DSN, row_factory=dict_row) as conn:
        while True:
            with conn.transaction():
                with conn.cursor() as cur:
                    # FOR UPDATE SKIP LOCKED so two drainers can run side by side.
                    cur.execute(
                        f"""
                        SELECT id, {', '.join(PG_COLS)}
                        FROM clock_evaluation_outbox
                        WHERE replicated_at IS NULL
                        ORDER BY id
                        LIMIT {BATCH}
                        FOR UPDATE SKIP LOCKED
                        """
                    )
                    rows = cur.fetchall()
                    if not rows:
                        return total

                    # Send BEFORE stamping. A crash here resends; a crash after
                    # stamping would lose the batch silently.
                    ch.query(
                        f"INSERT INTO clock_evaluations ({', '.join(CH_COLS)}) "
                        f"FORMAT TabSeparated",
                        body=_tsv(rows),
                    )
                    cur.execute(
                        "UPDATE clock_evaluation_outbox SET replicated_at = now() "
                        "WHERE id = ANY(%s)",
                        ([r["id"] for r in rows],),
                    )
            total += len(rows)
            if verbose:
                print(f"  replicated {total}", flush=True)


def lag() -> dict:
    with psycopg.connect(ADMIN_DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS pending, min(evaluated_at) AS oldest "
            "FROM clock_evaluation_outbox WHERE replicated_at IS NULL")
        return cur.fetchone()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--watch", type=int, default=0,
                    help="seconds between passes; 0 means one pass and exit")
    args = ap.parse_args(argv)

    while True:
        n = drain_once()
        print(f"replicated {n} row(s); {lag()['pending']} pending")
        if not args.watch:
            return 0
        time.sleep(args.watch)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
