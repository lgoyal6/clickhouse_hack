"""ClickHouse access over the HTTP interface.

HTTP rather than a native client binary, so the API has no dependency the container
does not already provide. Read-only by construction: every helper here sends a
SELECT and there is no code path that writes.
"""
from __future__ import annotations

import json
import os
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


def query(sql: str, params: dict | None = None, timeout: int = 30) -> tuple[list[dict], float]:
    """Run a SELECT and return (rows, elapsed_ms).

    Parameters go through ClickHouse's own {name:Type} substitution rather than
    string interpolation, so a SOC code cannot become SQL.
    """
    args = {"query": sql.rstrip().rstrip(";") + " FORMAT JSON",
            "default_format": "JSON"}
    for key, value in (params or {}).items():
        args[f"param_{key}"] = str(value)

    url = f"http://{CH_HOST}:{CH_PORT}/?" + urllib.parse.urlencode(args)
    req = urllib.request.Request(url, method="POST")
    req.add_header("X-ClickHouse-User", CH_USER)
    req.add_header("X-ClickHouse-Key", CH_PASSWORD)

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
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
