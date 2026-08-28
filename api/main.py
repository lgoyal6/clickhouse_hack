"""Status Clock API.

Implements contracts/openapi.yaml.

Identity comes from the session cookie and nothing else. There is no route that
accepts a user id, and the subject is bound to the transaction with SET LOCAL so
Postgres RLS enforces the same boundary a second time. See docs/REVIEW.md D1.

No response lets a number travel without its provenance. `serialise` refuses to
emit a running clock whose provenance is incomplete, so a missing citation is a
500 rather than an uncited number in front of a user. See docs/REVIEW.md H2.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import time

from fastapi import Cookie, FastAPI, HTTPException, Query, Response
from psycopg import errors as pgerrors

from engine import ENGINE_VERSION
from engine.evaluate import change_reason, evaluate
from . import repository as repo

REPO = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = REPO / "contracts" / "fixtures"

DISCLAIMER = "This is information, not legal advice."

app = FastAPI(
    title="Status Clock API",
    version="0.1.0",
    description="Every number carries its citation. Identity comes from the session.",
)

# Demo sessions. Two personas, two sessions, deliberately NOT one route with a
# user_id parameter. In production this is a session store; the shape is the same.
DEMO_SESSIONS = {
    "sess_maria":  "00000000-0000-4000-8000-00000000a001",
    "sess_daniel": "00000000-0000-4000-8000-00000000d001",
}

LABELS = {
    "opt_unemployment":   {"en": "Unemployment days",        "es": "Días de desempleo"},
    "cap_gap_window":     {"en": "Cap-gap window",           "es": "Periodo cap-gap"},
    "ac21_365":           {"en": "AC21 365-day threshold",   "es": "Umbral de 365 días AC21"},
    "h1b_max_stay":       {"en": "H-1B maximum stay",        "es": "Estancia máxima H-1B"},
    "h1b_grace_period":   {"en": "H-1B grace period",        "es": "Periodo de gracia H-1B"},
    "i485_portability":   {"en": "I-485 portability",        "es": "Portabilidad I-485"},
    "opt_filing_window":  {"en": "OPT filing window",        "es": "Ventana de solicitud OPT"},
}

KINDS = {
    "opt_unemployment": "consumption", "cap_gap_window": "window",
    "ac21_365": "deadline", "h1b_max_stay": "deadline",
    "h1b_grace_period": "consumption", "i485_portability": "deadline",
    "opt_filing_window": "window",
}

REQUIRED_PROVENANCE = ("rule_id", "rule_key", "citation", "authority",
                       "effective_from", "source_url", "verified")


def subject(sc_session: str | None) -> str:
    """The ONLY source of identity in this API."""
    if not sc_session or sc_session not in DEMO_SESSIONS:
        raise HTTPException(status_code=401, detail="No session. Sign in to see your clocks.")
    return DEMO_SESSIONS[sc_session]


def _iso(v):
    return v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v


def serialise(clock: dict, locale: str) -> dict:
    """Engine result -> contract shape.

    Refuses to emit a running clock without complete provenance. A 500 is the
    correct outcome; an uncited number is not.
    """
    key = clock["clock_key"]
    label = LABELS.get(key, {}).get(locale) or LABELS.get(key, {}).get("en") or key

    if not clock["applicable"]:
        return {
            "clock_key": key, "label": label, "kind": KINDS.get(key, "deadline"),
            "severity": "info", "as_of": _iso(clock["as_of"]),
            "applicable": False,
            "not_applicable_reason": clock["not_applicable_reason"],
            "engine_version": clock["engine_version"],
        }

    prov = {k: _iso(v) for k, v in clock["provenance"].items()}
    missing = [f for f in REQUIRED_PROVENANCE if prov.get(f) is None and f != "effective_to"]
    if missing:
        raise HTTPException(
            500,
            detail=(f"refusing to return {key} without provenance: missing "
                    f"{', '.join(missing)}. An uncited number is worse than no number."),
        )

    sup = clock.get("superseded")
    if sup:
        sup = {k: _iso(v) for k, v in sup.items()}

    return {
        "clock_key": key, "label": label, "kind": KINDS.get(key, "deadline"),
        "severity": clock["severity"], "as_of": _iso(clock["as_of"]),
        "applicable": True, "not_applicable_reason": None,
        "days_consumed": clock.get("days_consumed"),
        "denominator": clock.get("denominator"),
        "days_remaining": clock.get("days_remaining"),
        "window_start": _iso(clock.get("window_start")),
        "window_end": _iso(clock.get("window_end")),
        "window_days": clock.get("window_days"),
        "derived": clock.get("derived", False),
        "derivation": clock.get("derivation"),
        "provenance": prov,
        "superseded": sup,
        "change_reason": clock.get("change_reason"),
        "engine_version": clock["engine_version"],
    }


# ------------------------------------------------------------------ routes ----

@app.get("/v1/clocks")
def get_my_clocks(
    sc_session: str | None = Cookie(default=None),
    as_of: dt.date | None = Query(default=None),
    locale: str | None = Query(default=None),
):
    subject_id = subject(sc_session)
    day = as_of or dt.date.today()

    with repo.subject_tx(subject_id) as conn:
        state = repo.load_user_state(conn, subject_id)
        ruleset = repo.load_ruleset(conn)
        clocks = evaluate(state, day, ruleset)

        # Three cases, not two: facts changed, law changed, only time passed.
        for c in clocks:
            if c["applicable"]:
                prev = repo.previous_evaluation(conn, c["clock_key"], day)
                c["change_reason"] = change_reason(c, prev) if prev else None

        repo.write_outbox(conn, subject_id, clocks, day)

    lang = locale or state.locale
    out = [serialise(c, lang) for c in clocks]
    running = [c for c in out if c["applicable"]]

    return {
        "as_of": day.isoformat(),
        "clocks": out,
        "needs_attention": sum(1 for c in running if c["severity"] in ("warn", "critical")),
        "disclaimer": DISCLAIMER,
    }


@app.get("/v1/rules/{rule_key}")
def explain_rule(rule_key: str, as_of: dt.date | None = Query(default=None)):
    day = as_of or dt.date.today()
    with repo.reference_tx() as conn:
        ruleset = repo.load_ruleset(conn)
    try:
        chain = ruleset.chain(rule_key, day)
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from None

    def version(r):
        return {
            "rule_id": r.rule_id, "rule_key": r.rule_key,
            "effective_from": _iso(r.effective_from),
            "effective_to": _iso(r.effective_to),
            "params": r.params, "citation": r.citation, "authority": r.authority,
            "source_url": r.source_url, "supersedes": r.supersedes, "note": r.note,
            "verified": r.verified, "verified_by": r.verified_by,
            "verified_at": _iso(r.verified_at),
        }

    return {"rule_key": rule_key, "governing": version(chain[0]),
            "chain": [version(r) for r in chain]}


@app.post("/v1/scenarios/replay")
def replay(body: dict, sc_session: str | None = Cookie(default=None)):
    """Run the engine twice for the same as_of and diff.

    Same code path as the agent's what_if tool. Because the scenario is a WRITE,
    this works for a rule change that has not taken effect, which is the case the
    spec's read-only query returns nothing for. See docs/REVIEW.md A1.
    """
    subject_id = subject(sc_session)
    scenario_id = body.get("scenario_id")
    clock_key = body.get("clock_key")
    overrides = body.get("overrides")
    if not scenario_id or not clock_key or overrides is None:
        raise HTTPException(422, detail="scenario_id, clock_key and overrides are required")
    if scenario_id == "actual":
        raise HTTPException(422, detail="scenario_id 'actual' is reserved for the nightly run")

    day = dt.date.fromisoformat(body["as_of"]) if body.get("as_of") else dt.date.today()
    started = time.perf_counter()

    with repo.subject_tx(subject_id) as conn:
        state = repo.load_user_state(conn, subject_id)
        actual = evaluate(state, day, repo.load_ruleset(conn))
        scenario = evaluate(state, day, repo.load_ruleset(conn, overrides=overrides),
                            scenario_id=scenario_id)
        repo.write_outbox(conn, subject_id, actual, day)
        repo.write_outbox(conn, subject_id, scenario, day)

    a = {c["clock_key"]: c for c in actual if c["applicable"]}
    s = {c["clock_key"]: c for c in scenario if c["applicable"]}

    diffs = []
    for key in sorted(set(a) & set(s)):
        if clock_key not in ("*", key):
            continue
        av, sv = a[key]["days_remaining"], s[key]["days_remaining"]
        if av is None or sv is None or sv >= av:
            continue
        diffs.append({
            "subject_ref": f"sub_{subject_id[-4:]}",
            "clock_key": key,
            "under_actual": av, "under_scenario": sv, "days_lost": av - sv,
            "newly_critical": s[key]["severity"] == "critical"
                              and a[key]["severity"] != "critical",
        })

    return {
        "scenario_id": scenario_id, "clock_key": clock_key, "as_of": day.isoformat(),
        "rows_scanned": len(actual) + len(scenario),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "diffs": sorted(diffs, key=lambda d: -d["days_lost"]),
    }


@app.post("/v1/facts", status_code=201)
def record_fact(body: dict, response: Response, sc_session: str | None = Cookie(default=None)):
    subject_id = subject(sc_session)
    kind = body.get("kind")
    payload = body.get("payload") or {}
    if kind != "status_period":
        raise HTTPException(422, detail=f"kind {kind!r} is not wired yet")

    cols = ("status_type", "layer", "start_date", "end_date", "ead_start",
            "ead_expiry", "program_end", "is_stem")
    values = {k: payload.get(k) for k in cols if k in payload}
    values.setdefault("layer", "primary")
    values["user_id"] = subject_id
    values["confidence"] = body.get("confidence", "inferred")

    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    try:
        with repo.subject_tx(subject_id) as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO status_periods ({names}) VALUES ({marks}) "
                f"RETURNING id::text, status_type, layer, start_date, end_date, confidence",
                list(values.values()),
            )
            written = cur.fetchone()
    except pgerrors.ExclusionViolation as exc:
        # User-facing copy, per the spec's copy rules: what went wrong and what to do.
        response.status_code = 409
        return {
            "error": "overlapping_status",
            "message": ("These dates overlap an existing status period. Adjust one of "
                        "them, or record this as a stacked authorization "
                        "(layer 'authorization') if it is a cap-gap or grace period."),
            "conflicting_id": None,
            "detail": str(exc.diag.message_detail or "")[:300],
        }
    except (pgerrors.CheckViolation, pgerrors.InvalidTextRepresentation) as exc:
        raise HTTPException(422, detail=str(exc).split("\n")[0]) from None

    return {
        "id": written["id"], "kind": kind,
        "written": {k: _iso(v) for k, v in written.items()},
        "needs_confirmation": written["confidence"] != "document_verified",
    }


@app.post("/v1/claims/check")
def check_claim(body: dict):
    if not body.get("text"):
        raise HTTPException(422, detail="text is required")
    # TODO: exact/alias match first, vector search for the tail (REVIEW C5).
    payload = json.loads((FIXTURES / "claim_check_capgap.json").read_text())
    payload["_warning"] = "Claim matching is not implemented. This is a fixture."
    return payload


@app.get("/v1/corpus/wage-percentile")
def wage_percentile(soc_code: str, state: str, wage: float, fiscal_year: int | None = None):
    # TODO: clickhouse/queries/wage_percentile.sql. Exact scan (REVIEW A6).
    payload = json.loads((FIXTURES / "wage_percentile.json").read_text())
    payload["_warning"] = (
        "PLACEHOLDER NUMBERS. Not wired to ClickHouse. A fabricated percentile is the "
        "exact harm this product exists to prevent; do not show this on stage."
    )
    return payload


@app.get("/healthz")
def healthz():
    return {"ok": True, "engine_version": ENGINE_VERSION}
