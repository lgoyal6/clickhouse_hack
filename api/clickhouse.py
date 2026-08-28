"""ClickHouse access over the HTTP interface.

HTTP rather than a native client binary, so the API has no dependency the container
does not already provide. Read-only by construction: every helper here sends a
SELECT and there is no code path that writes.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

CH_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
CH_USER = os.environ.get("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "devonly")


class ClickHouseError(RuntimeError):
    pass


def query(sql: str, params: dict | None = None, timeout: int = 30,
          body: str | None = None, query_id: str | None = None) -> tuple[list[dict], float]:
    """Run a SELECT and return (rows, elapsed_ms).

    Parameters go through ClickHouse's own {name:Type} substitution rather than
    string interpolation, so a SOC code cannot become SQL.
    """
    # An INSERT ... FORMAT TabSeparated carries its rows in the request body and must
    # NOT have FORMAT JSON appended.
    stmt = sql.rstrip().rstrip(";")
    # Strip leading /* */ comments and blank lines before deciding, or a tagged query
    # like "/* bench_x */ SELECT ..." is misread as a non-SELECT and comes back as raw
    # TSV that will not parse as JSON.
    probe = re.sub(r"^\s*(/\*.*?\*/\s*)*", "", stmt, flags=re.S).lstrip().upper()
    returns_rows = probe.startswith(("SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN"))
    if body is not None or not returns_rows:
        # INSERT ... FORMAT TabSeparated carries rows in the body, and statements like
        # SYSTEM FLUSH LOGS return nothing. Appending FORMAT JSON to either is a
        # syntax error.
        args = {"query": stmt}
    else:
        args = {"query": stmt + " FORMAT JSON", "default_format": "JSON"}
    if query_id:
        # The only reliable way to correlate a query with its system.query_log row.
        # ClickHouse strips leading /* */ comments from the logged query text, so
        # tagging the SQL does not survive.
        args["query_id"] = query_id
    for key, value in (params or {}).items():
        args[f"param_{key}"] = str(value)

    url = f"http://{CH_HOST}:{CH_PORT}/?" + urllib.parse.urlencode(args)
    req = urllib.request.Request(url, data=(body or "").encode(), method="POST")
    req.add_header("X-ClickHouse-User", CH_USER)
    req.add_header("X-ClickHouse-Key", CH_PASSWORD)

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
        payload = json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raise ClickHouseError(exc.read().decode()[:1000]) from None
    except OSError as exc:
        raise ClickHouseError(f"cannot reach ClickHouse at {CH_HOST}:{CH_PORT}: {exc}") from None

    return payload.get("data", []), round((time.perf_counter() - started) * 1000, 2)


def normalise_soc(code: str) -> str:
    """'15-1252.00' and '15-1252' are the same occupation.

    The corpus carries both spellings, 74,504 rows against 547 for Software
    Developers. Normalising the caller's input is as important as normalising the
    column: a request for '15-1252.00' against a normalised column would otherwise
    return nothing at all.
    """
    return code.strip().split(".")[0]


def available(timeout: int = 3) -> bool:
    try:
        query("SELECT 1", timeout=timeout)
        return True
    except ClickHouseError:
        return False
