#!/usr/bin/env python3
"""Move the schema and the real corpus to a ClickHouse Cloud service.

    set -a; . infra/.env.cloud; set +a
    python clickhouse/cloud/migrate.py            # schema + corpus
    python clickhouse/cloud/migrate.py --with-evaluations

Cloud's HTTP endpoint refuses multi-statement SQL ("Multi-statements are not
allowed"), so the DDL files cannot be posted whole the way they can to a local
server over the native protocol. This splits them on semicolons, after stripping
comments, and posts one statement at a time.

What moves and what does not:

    lca_filings    1.16M rows   real DOL data     moves
    perm_filings    239K rows   real DOL data     moves
    clock_evaluations  127.8M   SYNTHETIC         skipped unless asked

The evaluations are generated rows that exist to benchmark the replay query. Pushing
3.68 GiB of synthetic data into a hosted service to make a row count look bigger is
the kind of thing this project argues against. The real evaluations replicate from
Postgres through api/replicate.py in seconds.
"""
from __future__ import annotations

import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]

HOST = os.environ.get("CH_CLOUD_HOST", "")
USER = os.environ.get("CH_CLOUD_USER", "default")
PASSWORD = os.environ.get("CH_CLOUD_PASSWORD", "")

LOCAL_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
LOCAL_PORT = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
LOCAL_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "devonly")

DDL = ["clickhouse/ddl/010_corpus.sql", "clickhouse/ddl/015_perm.sql",
       "clickhouse/ddl/020_evaluations.sql", "clickhouse/ddl/030_views.sql"]
CORPUS = ["lca_filings", "perm_filings"]
CHUNK = 200_000


def statements(sql: str) -> list[str]:
    """Split a .sql file into individual statements.

    ALL comments are stripped before splitting, INLINE ones included. Stripping only
    full-line comments is not enough: a trailing `-- facts only; excludes as_of`
    inside a CREATE TABLE carries a semicolon, and splitting on it cuts the statement
    in half. That produced a syntax error pointing at a parenthesis 46 characters in,
    which tells you nothing about the real cause.

    These files use `--` only for comments, never inside a string literal.
    """
    out = []
    for line in sql.splitlines():
        cut = line.find("--")
        out.append(line if cut < 0 else line[:cut])
    body = "\n".join(out)
    return [s.strip() for s in body.split(";") if s.strip()]


def cloud(query: str, body: bytes | None = None, timeout: int = 900) -> str:
    url = f"https://{HOST}:8443/?" + urllib.parse.urlencode({"query": query})
    req = urllib.request.Request(url, data=body or b"", method="POST")
    req.add_header("X-ClickHouse-User", USER)
    req.add_header("X-ClickHouse-Key", PASSWORD)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode()[:600]) from None


def local(query: str, timeout: int = 900) -> bytes:
    url = f"http://{LOCAL_HOST}:{LOCAL_PORT}/?" + urllib.parse.urlencode({"query": query})
    req = urllib.request.Request(url, method="POST")
    req.add_header("X-ClickHouse-User", "default")
    req.add_header("X-ClickHouse-Key", LOCAL_PASSWORD)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main(argv: list[str]) -> int:
    if not HOST or not PASSWORD:
        print("set CH_CLOUD_HOST and CH_CLOUD_PASSWORD (see infra/.env.cloud)")
        return 2

    print(f"target: {HOST}")
    print("  " + cloud("SELECT version()").strip())

    print("\n== schema ==")
    for path in DDL:
        stmts = statements((REPO / path).read_text())
        ok = 0
        for n, st in enumerate(stmts, 1):
            try:
                cloud(st)
                ok += 1
            except RuntimeError as exc:
                # IF NOT EXISTS on a view that already exists is fine; anything else
                # is worth seeing rather than swallowing.
                if "already exists" in str(exc):
                    ok += 1
                else:
                    print(f"  {pathlib.Path(path).name}: FAILED on statement {n} "
                          f"({st.split(chr(10))[0][:60]}...)")
                    print("      " + str(exc).split("\n")[0][:180])
        print(f"  {pathlib.Path(path).name:24s} {ok}/{len(stmts)} statements")

    print("\n== corpus ==")
    for table in CORPUS:
        # No "already loaded, skipping" check on purpose. clickhouse/ddl/010_corpus.sql
        # and 015_perm.sql both begin with DROP TABLE, so re-running this script
        # recreates the tables empty and reloads them. That makes the result
        # deterministic rather than additive: run it twice and you get the same row
        # count, not double. It also means the script is destructive on the target,
        # which is fine for a corpus rebuilt from files and would not be for anything
        # else.
        total = int(local(f"SELECT count() FROM {table}").decode().strip())
        print(f"  {table:16s} {total:,} rows", flush=True)
        sent, t0 = 0, time.time()
        while sent < total:
            data = local(f"SELECT * FROM {table} ORDER BY tuple() "
                         f"LIMIT {CHUNK} OFFSET {sent} FORMAT Native")
            if not data:
                break
            cloud(f"INSERT INTO {table} FORMAT Native", body=data)
            sent += CHUNK
            print(f"      {min(sent, total):,}/{total:,} "
                  f"({time.time() - t0:.0f}s)", flush=True)

    if "--with-evaluations" in argv:
        print("\n== synthetic evaluations ==")
        total = int(local("SELECT count() FROM clock_evaluations").decode().strip())
        sent = 0
        while sent < total:
            data = local(f"SELECT * FROM clock_evaluations ORDER BY tuple() "
                         f"LIMIT {CHUNK} OFFSET {sent} FORMAT Native")
            if not data:
                break
            cloud("INSERT INTO clock_evaluations FORMAT Native", body=data)
            sent += CHUNK
            print(f"      {min(sent, total):,}/{total:,}", flush=True)
    else:
        print("\n== evaluations: skipped (synthetic benchmark data) ==")
        print("   real ones replicate from Postgres:")
        print("   CLICKHOUSE_HOST=$CH_CLOUD_HOST CLICKHOUSE_PORT=8443 \\")
        print("     CLICKHOUSE_PASSWORD=$CH_CLOUD_PASSWORD python -m api.replicate")

    print("\n== verify ==")
    print(cloud("SELECT table, formatReadableQuantity(sum(rows)) AS rows "
                "FROM system.parts WHERE active AND database='default' "
                "AND table NOT LIKE '.inner%' GROUP BY table ORDER BY table "
                "FORMAT PrettyCompactMonoBlock"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
