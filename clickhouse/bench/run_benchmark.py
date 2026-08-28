#!/usr/bin/env python3
"""Measure the queries the architecture argument rests on.

    python clickhouse/bench/run_benchmark.py

Reports wall clock, rows read and bytes read for each query, taken from
system.query_log rather than from a stopwatch, and runs the marquee query both with
and without the by_clock projection so the access path is visible rather than
asserted.

Every number printed here is a PERFORMANCE number over synthetic evaluations. The
corpus (lca_filings, perm_filings) is real DOL data; clock_evaluations is not. See
clickhouse/bench/seed_evaluations.sql.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from api import clickhouse as ch  # noqa: E402

AS_OF = "2026-08-01"
REPO = pathlib.Path(__file__).resolve().parents[2]


def sql(path: str) -> str:
    text = (REPO / path).read_text()
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    return body.split(";")[0].strip()


def run(label: str, query: str, params: dict | None = None,
        settings: dict | None = None) -> dict:
    # Correlate by query_id, not by a comment. ClickHouse strips leading /* */
    # comments from the query text it logs, so a tagged query cannot be found again.
    qid = f"bench-{label}-{int(time.time() * 1000)}"
    q = query
    if settings:
        q += "\nSETTINGS " + ", ".join(f"{k}={v}" for k, v in settings.items())

    started = time.perf_counter()
    rows, _ = ch.query(q, params, timeout=600, query_id=qid)
    wall = (time.perf_counter() - started) * 1000

    # query_log is written asynchronously, so a fast query can finish before its own
    # row lands. Retry rather than reporting a zero, which would read as "free".
    m = {}
    for _ in range(10):
        ch.query("SYSTEM FLUSH LOGS")
        # Exclude the lookup itself. Parameter values are substituted into the
        # logged query text, so this SELECT contains the tag too and would otherwise
        # match as the most recent row: it reads a handful of rows and would report
        # a 127M-row scan as almost free.
        log, _ = ch.query(
            "SELECT read_rows, read_bytes, memory_usage, query_duration_ms "
            "FROM system.query_log "
            "WHERE type='QueryFinish' AND query_id = {q:String} "
            "ORDER BY event_time DESC LIMIT 1",
            {"q": qid})
        if log:
            m = log[0]
            break
        time.sleep(0.3)
    else:
        raise RuntimeError(f"no query_log row for {qid}; refusing to report a zero")
    return {
        "label": label,
        "result_rows": len(rows),
        "wall_ms": round(wall, 1),
        "server_ms": int(m.get("query_duration_ms") or 0),
        "read_rows": int(m.get("read_rows") or 0),
        "read_mb": round(int(m.get("read_bytes") or 0) / 1048576, 1),
        "mem_mb": round(int(m.get("memory_usage") or 0) / 1048576, 1),
        "sample": rows[:3],
    }


def show(r: dict) -> None:
    print(f"  {r['label']:<44} {r['server_ms']:>7,} ms   "
          f"{r['read_rows']:>13,} rows read   {r['read_mb']:>9,.1f} MB   "
          f"{r['result_rows']:>8,} out")


def main() -> int:
    if not ch.available():
        print("ClickHouse not reachable"); return 2

    size, _ = ch.query("""
        SELECT sum(rows) AS rows,
               formatReadableSize(sum(bytes_on_disk)) AS on_disk,
               formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed,
               round(sum(data_uncompressed_bytes) / sum(data_compressed_bytes), 1) AS ratio
        FROM system.parts WHERE table = 'clock_evaluations' AND active""")
    s = size[0]
    users, _ = ch.query("SELECT uniqExact(user_id) AS u, uniqExact(as_of) AS d "
                        "FROM clock_evaluations WHERE scenario_id='actual'")

    print("\nclock_evaluations")
    print(f"  {int(s['rows']):,} rows   {users[0]['u']:,} users   {users[0]['d']} days")
    print(f"  {s['on_disk']} on disk, {s['uncompressed']} uncompressed, {s['ratio']}x compression")

    results = []

    print("\n1. THE MARQUEE QUERY  rule-change replay across the whole population")
    print("   Who loses days if the H-1B grace period is eliminated?")
    replay = sql("clickhouse/queries/replay_diff.sql")
    p = {"clock": "h1b_grace_period", "scenario": "rule:h1b_grace_0d", "as_of": AS_OF}
    for label, st in (("replay, projection ON", {"optimize_use_projections": 1}),
                      ("replay, projection OFF", {"optimize_use_projections": 0})):
        r = run(label.replace(" ", "").replace(",", "-"), replay, p, st)
        r["label"] = label
        show(r); results.append(r)

    print("\n2. ONE PERSON'S HISTORY  what the Timeline screen reads")
    uid, _ = ch.query("SELECT any(user_id) AS u FROM clock_evaluations "
                      "WHERE scenario_id='actual'")
    r = run("user_history", """
        SELECT clock_key, as_of, days_remaining, severity
        FROM clock_evaluations
        WHERE user_id = {u:UUID} AND scenario_id = 'actual'
        ORDER BY clock_key, as_of""", {"u": uid[0]["u"]})
    r["label"] = "one user, every clock, every day"
    show(r); results.append(r)

    print("\n3. POPULATION RISK OVER TIME  the operator view")
    r = run("risk_series", """
        SELECT as_of, severity, uniqExact(user_id) AS users
        FROM clock_evaluations
        WHERE clock_key = 'ac21_365' AND scenario_id = 'actual'
        GROUP BY as_of, severity ORDER BY as_of""")
    r["label"] = "365-day risk series for one clock"
    show(r); results.append(r)

    r = run("risk_rollup", """
        SELECT as_of, severity, uniqMerge(users) AS users
        FROM risk_rollup
        WHERE clock_key = 'ac21_365' AND scenario_id = 'actual'
        GROUP BY as_of, severity ORDER BY as_of""")
    r["label"] = "  same, from the risk_rollup view"
    show(r); results.append(r)

    print("\n4. THE DAY YOUR RISK MOVED  full history scan, no filter")
    r = run("moved", """
        SELECT count() AS transitions
        FROM (
          SELECT user_id, clock_key, as_of, severity,
                 lagInFrame(severity) OVER (PARTITION BY user_id, clock_key
                                            ORDER BY as_of) AS prev
          FROM clock_evaluations WHERE scenario_id = 'actual'
        ) WHERE prev != '' AND prev != severity""")
    r["label"] = "every severity transition, whole corpus"
    show(r); results.append(r)

    print("\nheadline:")
    m = results[0]
    print(f"  {m['read_rows']:,} rows scanned in {m['server_ms']:,} ms "
          f"({m['read_rows'] / max(m['server_ms'], 1) / 1000:.1f}M rows/sec)")
    print(f"  {m['result_rows']:,} users would lose days under the proposed rule")
    print("\n  Synthetic evaluations. The corpus is real; the user base is not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
