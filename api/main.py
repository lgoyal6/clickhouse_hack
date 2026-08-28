"""Status Clock API.

Implements contracts/openapi.yaml. Skeleton: routes, identity handling and response
models are real; the database calls are marked TODO and currently serve the contract
fixtures so Person B is never blocked.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import time

from fastapi import Cookie, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from engine import ENGINE_VERSION

REPO = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = REPO / "contracts" / "fixtures"

app = FastAPI(
    title="Status Clock API",
    version="0.1.0",
    description="Every number carries its citation. Identity comes from the session.",
)

# Demo sessions. Two personas, two sessions, deliberately NOT one endpoint with a
# user_id parameter. See docs/REVIEW.md D1.
DEMO_SESSIONS = {
    "sess_maria": ("00000000-0000-4000-8000-00000000a001", "clocks_maria_stem_opt.json"),
    "sess_daniel": ("00000000-0000-4000-8000-00000000d001", "clocks_daniel_h1b.json"),
}


def subject(sc_session: str | None) -> tuple[str, str]:
    """Resolve the session to a subject. The ONLY source of identity in this API."""
    if not sc_session or sc_session not in DEMO_SESSIONS:
        raise HTTPException(status_code=401, detail="No session. Sign in to see your clocks.")
    return DEMO_SESSIONS[sc_session]


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@app.get("/v1/clocks")
def get_my_clocks(
    sc_session: str | None = Cookie(default=None),
    as_of: dt.date | None = Query(default=None),
    locale: str = Query(default="en"),
):
    _subject_id, fixture_name = subject(sc_session)
    # TODO: load UserState from Postgres with the subject GUC set, resolve the
    # RuleSet, call engine.evaluate.evaluate(), and read the previous day's row from
    # the outbox to fill change_reason. Serving the fixture until then so that the
    # interface track is never blocked on this file.
    payload = _fixture(fixture_name)
    if as_of:
        payload["_warning"] = (
            f"as_of={as_of.isoformat()} ignored: this response is a fixture, not a "
            f"computed evaluation. Do not demo a number from this path."
        )
    return payload


@app.get("/v1/rules/{rule_key}")
def explain_rule(rule_key: str, as_of: dt.date | None = Query(default=None)):
    if rule_key != "cap_gap_end":
        raise HTTPException(404, detail=f"No fixture for rule_key {rule_key!r} yet.")
    # TODO: SELECT the governing version and walk `supersedes` to build the chain.
    return _fixture("rule_chain_cap_gap.json")


@app.post("/v1/claims/check")
def check_claim(body: dict):
    if not body.get("text"):
        raise HTTPException(422, detail="text is required")
    # TODO: resolve the claim to a rule version (exact/alias match first, vector
    # search for the tail; see docs/REVIEW.md C5) and report when it was superseded.
    return _fixture("claim_check_capgap.json")


@app.get("/v1/corpus/wage-percentile")
def wage_percentile(
    soc_code: str,
    state: str,
    wage: float,
    fiscal_year: int | None = None,
):
    # TODO: run clickhouse/queries/wage_percentile.sql. Exact scan, not interpolated
    # from quantile states; see docs/REVIEW.md A6.
    payload = _fixture("wage_percentile.json")
    payload["_warning"] = (
        "PLACEHOLDER NUMBERS. This endpoint is not wired to ClickHouse yet. A "
        "fabricated percentile is the exact harm this product exists to prevent; do "
        "not show this on stage."
    )
    return JSONResponse(payload, status_code=200)


@app.post("/v1/scenarios/replay")
def replay(body: dict, sc_session: str | None = Cookie(default=None)):
    subject(sc_session)
    started = time.perf_counter()
    # TODO: run engine.evaluate.evaluate() twice for the same as_of, once with
    # scenario overrides, write both to the outbox, then run
    # clickhouse/queries/replay_diff.sql. Same code path as the what_if tool.
    payload = _fixture("replay_h1b_grace.json")
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    payload["_warning"] = "rows_scanned is 0 because nothing was scanned. Fill from a real run."
    return payload


@app.post("/v1/facts", status_code=201)
def record_fact(body: dict, sc_session: str | None = Cookie(default=None)):
    subject_id, _ = subject(sc_session)
    kind = body.get("kind")
    if kind not in {"status_period", "employment_episode", "gc_milestone", "document"}:
        raise HTTPException(422, detail=f"unknown kind {kind!r}")
    # TODO: INSERT with the subject GUC set so RLS applies, then SELECT the row back
    # and return exactly what landed. Translate a 23P01 exclusion violation into the
    # 409 shape in the contract, with user-facing copy.
    return {
        "id": "00000000-0000-4000-8000-000000000000",
        "kind": kind,
        "written": body.get("payload", {}),
        "needs_confirmation": body.get("confidence", "inferred") != "document_verified",
        "_warning": "Not persisted. This route is a stub.",
    }


@app.get("/healthz")
def healthz():
    return {"ok": True, "engine_version": ENGINE_VERSION}
