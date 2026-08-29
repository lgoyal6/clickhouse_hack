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
import re
import time

from fastapi import Cookie, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg import errors as pgerrors

from engine import ENGINE_VERSION
from engine.evaluate import change_reason, evaluate
from . import clickhouse as ch
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

# Wording lives here, in every supported language. The engine returns codes.
#
# English is the DEFAULT. The user's stored locale is a preference surfaced in intake,
# not something that silently decides what a visitor sees; the switcher decides, and
# it defaults to English. Answering in someone's language is the product working, but
# guessing at it is how a demo opens in a language the room does not read.
LOCALES = {"en": "English", "es": "Español", "hi": "हिन्दी"}
DEFAULT_LOCALE = "en"

# Who the demo sessions are, for the UI. Names, not cookie values.
DEMO_PEOPLE = {
    "sess_maria": {
        "name": "Maria O.",
        "summary": {"en": "Home health aide · STEM OPT · H-1B pending, in cap-gap",
                    "es": "Auxiliar de salud a domicilio · STEM OPT · H-1B pendiente, en cap-gap",
                    "hi": "गृह स्वास्थ्य सहायक · STEM OPT · H-1B लंबित, कैप-गैप में"},
    },
    "sess_daniel": {
        "name": "Daniel R.",
        "summary": {"en": "Adjunct instructor · H-1B year five · nothing filed",
                    "es": "Profesor adjunto · quinto año de H-1B · nada presentado",
                    "hi": "सहायक प्राध्यापक · H-1B पाँचवाँ वर्ष · कुछ भी दायर नहीं"},
    },
}

LABELS = {
    "opt_unemployment":  {"en": "Unemployment days",
                          "es": "Días de desempleo",
                          "hi": "बेरोज़गारी के दिन"},
    "cap_gap_window":    {"en": "Cap-gap window",
                          "es": "Periodo cap-gap",
                          "hi": "कैप-गैप अवधि"},
    "h1b_grace_period":  {"en": "H-1B grace period",
                          "es": "Periodo de gracia H-1B",
                          "hi": "H-1B रियायती अवधि"},
    "ac21_365":          {"en": "AC21 365-day threshold",
                          "es": "Umbral de 365 días AC21",
                          "hi": "AC21 365-दिन सीमा"},
    "i485_portability":  {"en": "I-485 portability",
                          "es": "Portabilidad I-485",
                          "hi": "I-485 पोर्टेबिलिटी"},
    "h1b_max_stay":      {"en": "H-1B maximum stay",
                          "es": "Estancia máxima H-1B",
                          "hi": "H-1B अधिकतम अवधि"},
    "opt_filing_window": {"en": "OPT filing window",
                          "es": "Ventana de solicitud OPT",
                          "hi": "OPT आवेदन अवधि"},
}

# Why a clock is not running. "Not in H-1B status, so the six-year meter has not
# started" is an answer; a zero is not.
REASONS = {
    "no_opt_period":     {"en": "No OPT or STEM OPT period on file",
                          "es": "No hay periodo de OPT o STEM OPT registrado",
                          "hi": "कोई OPT या STEM OPT अवधि दर्ज नहीं है"},
    "no_ead_start":      {"en": "OPT start date not known. Add your EAD.",
                          "es": "No se conoce la fecha de inicio del OPT. Agregue su EAD.",
                          "hi": "OPT प्रारंभ तिथि ज्ञात नहीं है। अपना EAD जोड़ें।"},
    "no_cap_gap":        {"en": "No cap-gap period on file. Needs a pending cap-subject H-1B petition.",
                          "es": "No hay periodo cap-gap registrado. Requiere una petición H-1B sujeta al cupo pendiente.",
                          "hi": "कोई कैप-गैप अवधि दर्ज नहीं है। एक लंबित कैप-अधीन H-1B याचिका आवश्यक है।"},
    "not_h1b":           {"en": "Not in H-1B status, so the six-year meter has not started",
                          "es": "No está en estatus H-1B, así que el contador de seis años no ha empezado",
                          "hi": "H-1B स्थिति में नहीं हैं, इसलिए छह-वर्षीय गणना शुरू नहीं हुई है"},
    "already_filed":     {"en": "A PERM or I-140 is already on file",
                          "es": "Ya hay un PERM o I-140 presentado",
                          "hi": "एक PERM या I-140 पहले से दायर है"},
    "currently_employed": {"en": "Currently employed, so the grace period has not started",
                          "es": "Actualmente empleado, así que el periodo de gracia no ha empezado",
                          "hi": "वर्तमान में कार्यरत हैं, इसलिए रियायती अवधि शुरू नहीं हुई है"},
    "no_i485":           {"en": "No I-485 on file, so portability has not started",
                          "es": "No hay I-485 presentado, así que la portabilidad no ha empezado",
                          "hi": "कोई I-485 दायर नहीं है, इसलिए पोर्टेबिलिटी शुरू नहीं हुई है"},
    "no_program_end":    {"en": "No program end date on file. Add your I-20.",
                          "es": "No hay fecha de fin de programa registrada. Agregue su I-20.",
                          "hi": "कोई कार्यक्रम समाप्ति तिथि दर्ज नहीं है। अपना I-20 जोड़ें।"},
    "opt_authorised":    {"en": "OPT is already authorised, so the filing window has closed",
                          "es": "El OPT ya está autorizado, así que la ventana de solicitud se cerró",
                          "hi": "OPT पहले से अधिकृत है, इसलिए आवेदन अवधि बंद हो चुकी है"},
}

UI_STRINGS = {
    "as_of":            {"en": "As of", "es": "Al", "hi": "तिथि"},
    "clocks":           {"en": "clocks", "es": "relojes", "hi": "काउंटडाउन"},
    "needs_attention":  {"en": "needs attention", "es": "requiere atención",
                         "hi": "ध्यान देने योग्य"},
    "not_running":      {"en": "Not running yet", "es": "Aún no activos",
                         "hi": "अभी सक्रिय नहीं"},
    "days_remaining":   {"en": "days remaining", "es": "días restantes", "hi": "दिन शेष"},
    "day_window":       {"en": "day window", "es": "días de duración", "hi": "दिन की अवधि"},
    "days_gained":      {"en": "days gained", "es": "días ganados", "hi": "दिन अतिरिक्त"},
    "unverified":       {"en": "Unverified against the primary source",
                         "es": "No verificado contra la fuente primaria",
                         "hi": "प्राथमिक स्रोत से असत्यापित"},
    "why":              {"en": "Why this number", "es": "Por qué este número",
                         "hi": "यह संख्या क्यों"},
    "supersedes":       {"en": "supersedes rule of", "es": "reemplaza la regla de",
                         "hi": "पूर्व नियम को प्रतिस्थापित करता है"},
    "disclaimer":       {"en": "This is information, not legal advice.",
                         "es": "Esto es información, no asesoría legal.",
                         "hi": "यह जानकारी है, कानूनी सलाह नहीं।"},
}


def t(table: dict, key: str, locale: str) -> str:
    """Translate, falling back to English rather than to a key name."""
    entry = table.get(key) or {}
    return entry.get(locale) or entry.get("en") or key


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
    label = t(LABELS, key, locale)

    if not clock["applicable"]:
        return {
            "clock_key": key, "label": label, "kind": KINDS.get(key, "deadline"),
            "severity": "info", "as_of": _iso(clock["as_of"]),
            "applicable": False,
            "not_applicable_reason": t(REASONS, clock["not_applicable_reason"], locale),
            "not_applicable_code": clock["not_applicable_reason"],
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

# The UI is served by the API on purpose.
#
# Same origin means the session cookie is sent on every fetch with no CORS dance and
# no cross-site cookie rules to fight. One port, one URL, nothing to configure:
#
#     http://localhost:8000/ui
#
# CORS is still enabled for localhost so the page can also be served from a separate
# dev server if someone prefers that.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root(sc_session: str | None = Cookie(default=None)):
    """Entry point. Establishes a demo session if there is not one already.

    Without this, opening the app cold gives a 401 and an empty wall, which looks
    like a broken build rather than a missing sign-in.
    """
    if sc_session in DEMO_SESSIONS:
        return RedirectResponse("/ui/", status_code=303)
    return RedirectResponse("/session/sess_maria", status_code=303)


@app.get("/lang/{code}")
def switch_language(code: str):
    """Set the display language and return to the wall."""
    if code not in LOCALES:
        raise HTTPException(404, detail=f"unsupported locale {code!r}")
    r = RedirectResponse("/ui/", status_code=303)
    r.set_cookie("sc_lang", code, httponly=False, samesite="lax", path="/", max_age=31536000)
    return r


@app.get("/session/{name}")
def switch_session(name: str):
    """Set the demo session cookie and return to the wall.

    Persona switching is two sessions, never a user id in a query string. This is the
    whole reason no endpoint accepts an identity parameter. See docs/REVIEW.md D1.
    """
    if name not in DEMO_SESSIONS:
        raise HTTPException(404, detail=f"unknown session {name!r}")
    r = RedirectResponse("/ui/", status_code=303)
    r.set_cookie("sc_session", name, httponly=False, samesite="lax", path="/")
    return r


@app.get("/v1/locales")
def locales():
    """What the UI offers in its switcher."""
    return {"default": DEFAULT_LOCALE,
            "available": [{"code": c, "name": n} for c, n in LOCALES.items()]}


def resolve_locale(param: str | None, cookie: str | None) -> str:
    """Explicit choice, then the switcher's cookie, then English.

    Deliberately NOT the user's stored locale. That is a preference captured during
    intake and shown back to them; letting it silently pick the language means the
    demo can open in a language the room does not read. The switcher decides.
    """
    for candidate in (param, cookie):
        if candidate in LOCALES:
            return candidate
    return DEFAULT_LOCALE


@app.get("/v1/clocks")
def get_my_clocks(
    sc_session: str | None = Cookie(default=None),
    sc_lang: str | None = Cookie(default=None),
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

    lang = resolve_locale(locale, sc_lang)
    out = [serialise(c, lang) for c in clocks]

    # Corpus context for the one clock where the statute's number and the real-world
    # number differ enough to change what someone should do.
    for c in out:
        if c["clock_key"] == "ac21_365" and c["applicable"]:
            ctx = perm_context(lang)
            if ctx:
                c["corpus_context"] = ctx
    running = [c for c in out if c["applicable"]]

    return {
        "as_of": day.isoformat(),
        "locale": lang,
        "locales": [{"code": c, "name": n} for c, n in LOCALES.items()],
        "person": {
            "name": DEMO_PEOPLE.get(sc_session, {}).get("name", ""),
            "summary": t(
                {"s": DEMO_PEOPLE.get(sc_session, {}).get("summary", {})}, "s", lang),
            "preferred_locale": state.locale,
        },
        "strings": {k: t(UI_STRINGS, k, lang) for k in UI_STRINGS},
        "clocks": out,
        "needs_attention": sum(1 for c in running if c["severity"] in ("warn", "critical")),
        "disclaimer": t(UI_STRINGS, "disclaimer", lang),
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
    """Write one extracted fact and read it straight back for confirmation.

    This is the write half of the product. Someone says "I was laid off on 1 August",
    or uploads an I-20 and the agent reads a date off it, and the clocks move. Reading
    the row back rather than echoing the request means the user confirms what the
    database actually holds, not what was asked for.
    """
    subject_id = subject(sc_session)
    kind = body.get("kind")
    payload_early = body.get("payload") or {}

    # "My job ended on 1 August" corrects an existing record; it does not add one.
    # Inserting a second, closed episode would leave the original open one in place,
    # the person would still read as employed, and the grace period would never
    # start. Correcting history rather than appending to it is the whole reason the
    # system of record is Postgres.
    if kind == "employment_end":
        if not payload_early.get("end_date"):
            raise HTTPException(422, detail="end_date is required")
        with repo.subject_tx(subject_id) as conn:
            row = repo.end_employment(conn, payload_early["end_date"],
                                      payload_early.get("employer_name"))
        if row is None:
            raise HTTPException(
                404, detail="No open employment to end. Add the job first.")
        return {
            "id": row["id"], "kind": kind,
            "written": {k: _iso(v) for k, v in row.items()},
            "needs_confirmation": True,
            "next": "Call get_my_clocks again; the countdowns have been recomputed.",
        }

    if kind not in repo.WRITABLE:
        raise HTTPException(
            422, detail=f"kind must be employment_end or one of {sorted(repo.WRITABLE)}")

    payload = body.get("payload") or {}
    confidence = body.get("confidence", "inferred")
    if confidence not in ("document_verified", "user_stated", "inferred"):
        raise HTTPException(422, detail=f"unknown confidence {confidence!r}")

    try:
        with repo.subject_tx(subject_id) as conn:
            written = repo.write_fact(conn, subject_id, kind, payload, confidence)
    except pgerrors.ExclusionViolation as exc:
        # User-facing copy: what went wrong and what to do about it.
        response.status_code = 409
        return {
            "error": "overlapping_status",
            "message": ("These dates overlap a status period you already have. Adjust "
                        "one of them, or record this as a stacked authorization "
                        "(layer 'authorization') if it is a cap-gap or grace period."),
            "detail": str(exc.diag.message_detail or "")[:300],
        }
    except pgerrors.UniqueViolation:
        response.status_code = 409
        return {"error": "duplicate", "message": "You already have that on file."}
    except (pgerrors.CheckViolation, pgerrors.InvalidTextRepresentation,
            pgerrors.InvalidDatetimeFormat, pgerrors.NotNullViolation) as exc:
        raise HTTPException(422, detail=str(exc).split("\n")[0]) from None

    return {
        "id": written["id"],
        "kind": kind,
        "written": {k: _iso(v) for k, v in written.items()},
        "needs_confirmation": confidence != "document_verified",
        "next": "Call get_my_clocks again; the countdowns have been recomputed.",
    }


CORPUS_COVERAGE = "DOL OFLC LCA disclosure, FY2024 and FY2025 (all quarters), CERTIFIED only"

# Below this, refuse outright rather than flag. A percentile over three filings is not
# a percentile with a caveat, it is noise with a decimal point. Between the floor and
# 30 the number is returned with insufficient_data set, because there the shape is
# real even if the precision is not. See docs/REVIEW.md C8.
MIN_FOR_PERCENTILE = 10
SMALL_SAMPLE = 30

PERCENTILE_SQL = (REPO / "clickhouse" / "queries" / "wage_percentile.sql").read_text()
LEVEL_SQL = (REPO / "clickhouse" / "queries" / "wage_level.sql").read_text()
PERM_SQL = (REPO / "clickhouse" / "queries" / "perm_timeline.sql").read_text()


def _sql(text: str) -> str:
    """Extract the statement from a commented .sql file.

    Comments are stripped BEFORE splitting on the first semicolon. Doing it the other
    way round breaks the moment prose in the header contains a semicolon, which
    silently yields an empty query and a 503 that looks like ClickHouse being down.
    """
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    stmt = body.split(";")[0].strip()
    if not stmt.upper().lstrip().startswith(("SELECT", "WITH")):
        raise RuntimeError(f"refusing to run a non-SELECT: {stmt[:80]!r}")
    return stmt


PERM_NOTE = {
    "en": ("The median certified PERM took {median} days end to end across {n} "
           "filings, and {p90} days at the 90th percentile. The 365 days in AC21 is "
           "how long a filing must have been PENDING, not how long the process takes. "
           "Filing at this deadline leaves no margin."),
    "es": ("El PERM certificado mediano tardó {median} días en total sobre {n} "
           "solicitudes, y {p90} días en el percentil 90. Los 365 días de AC21 son el "
           "tiempo que una solicitud debe llevar PENDIENTE, no lo que tarda el "
           "proceso. Presentar en esta fecha no deja margen."),
    "hi": ("{n} आवेदनों में औसत प्रमाणित PERM को आरंभ से अंत तक {median} दिन लगे, और 90वें "
           "पर्सेंटाइल पर {p90} दिन। AC21 के 365 दिन यह हैं कि आवेदन कितने समय से लंबित "
           "है, न कि प्रक्रिया में कितना समय लगता है। इस तिथि पर आवेदन करने से कोई "
           "मार्जिन नहीं बचता।"),
}


def perm_context(locale: str = DEFAULT_LOCALE) -> dict | None:
    """How long PERM actually takes, from the corpus, in the caller's language.

    Attached to ac21_365 because the clock alone is a true number that omits the part
    that matters. AC21 needs a filing PENDING 365 days, so the clock derives a filing
    deadline of six-year-mark minus 365. The corpus says the median certified PERM
    runs well past that end to end, so filing at the derived deadline satisfies the
    statute with zero margin.

    Spans the WHOLE loaded corpus rather than one fiscal year, so this figure and the
    one quoted on the landing page cannot contradict each other.

    Returns None rather than guessing if the corpus is not loaded.
    """
    try:
        rows, _ = ch.query(_sql(PERM_SQL))
    except (ch.ClickHouseError, RuntimeError):
        return None
    if not rows or not int(rows[0].get("n") or 0):
        return None
    r = rows[0]
    median, p90, n = int(r["median_days"]), int(r["p90_days"]), int(r["n"])
    return {
        "median_days": median,
        "p90_days": p90,
        "n_filings": n,
        "source": {"dataset": "DOL OFLC PERM Disclosure Data",
                   "coverage": "FY2024 and FY2025, CERTIFIED only",
                   "retrieved_at": "2026-08-28"},
        "note": (PERM_NOTE.get(locale) or PERM_NOTE["en"]).format(
            median=median, p90=p90, n=f"{n:,}"),
    }


# Words that point at a rule. Deliberately a small hand-written map rather than an
# embedding lookup: the vocabulary here is tiny and fixed, and a wrong match sends
# someone a confident answer about the wrong rule. See docs/REVIEW.md C5 for the
# vector-search version and why exact matching comes first.
CLAIM_KEYWORDS = {
    "cap_gap_end": ("cap-gap", "cap gap", "capgap", "september 30", "sept 30",
                    "april 1", "work authorization ends"),
    "opt_unemployment_max": ("unemployment", "unemployed", "90 days", "150 days",
                             "120 days", "out of work"),
    "stem_opt_unemployment_add": ("stem", "24-month", "extension"),
    "h1b_grace_period": ("grace period", "60 days", "60-day", "laid off", "layoff"),
    "ac21_extension_threshold": ("ac21", "365", "seventh year", "beyond six"),
    "i485_portability": ("portability", "180 days", "same or similar", "change jobs"),
    "h1b_max_stay": ("six year", "six-year", "6 year", "maximum stay"),
    "opt_filing_window": ("filing window", "90 days before", "60 days after"),
    "opt_min_hours": ("20 hours", "part time", "part-time"),
    "lottery_selection": ("lottery", "selection", "wage-weighted", "random"),
}


def _claim_matches(text: str, params: dict) -> bool:
    """Does the claim assert the value this rule version carries?"""
    low = text.lower()
    for value in params.values():
        v = str(value).lower()
        if v in low:
            return True
        if v == "sept_30" and ("september 30" in low or "sept 30" in low or "sep 30" in low):
            return True
        if v == "april_1" and ("april 1" in low or "apr 1" in low):
            return True
        if v.isdigit() and re.search(rf"\b{v}\b", low):
            return True
    return False


@app.post("/v1/claims/check")
def check_claim(body: dict, sc_session: str | None = Cookie(default=None),
                sc_lang: str | None = Cookie(default=None)):
    """Check something someone was told against the rule version table.

    The useful answer is almost never true or false. It is "that was true until this
    date". Matching is keyword plus value comparison, and it says `no_match` rather
    than reaching for the nearest rule, because a confident answer about the wrong
    rule is worse than no answer.
    """
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(422, detail="text is required")

    hint = body.get("rule_key")
    low = text.lower()
    candidates = [hint] if hint else [
        key for key, words in CLAIM_KEYWORDS.items() if any(w in low for w in words)
    ]

    with repo.reference_tx() as conn:
        versions = repo.rule_versions(conn)

    def shape(r):
        return {
            "rule_id": r["rule_id"], "rule_key": r["rule_key"],
            "effective_from": _iso(r["effective_from"]),
            "effective_to": _iso(r["effective_to"]),
            "params": r["params"], "citation": r["citation"],
            "authority": r["authority"], "source_url": r["source_url"],
            "verified": r["verified_by"] is not None,
            "verified_by": r["verified_by"], "note": r["note"],
        }

    if not candidates:
        return {"verdict": "no_match", "matched_version": None,
                "governing_version": None, "superseded_on": None,
                "match_confidence": 0.0,
                "message": ("I cannot place that against any rule I hold. Tell me which "
                            "deadline you mean and I will show you its version history.")}

    today = dt.date.today()
    for key in candidates:
        vs = [v for v in versions if v["rule_key"] == key]
        if not vs:
            continue
        governing = next(
            (v for v in vs if v["effective_from"] <= today
             and (v["effective_to"] is None or v["effective_to"] > today)), vs[0])
        matched = next((v for v in vs if _claim_matches(text, v["params"])), None)
        if matched is None:
            continue
        if matched["rule_id"] == governing["rule_id"]:
            verdict, superseded_on = "current", None
        else:
            verdict = "superseded"
            superseded_on = _iso(matched["effective_to"] or governing["effective_from"])
        return {
            "verdict": verdict,
            "matched_version": shape(matched),
            "governing_version": shape(governing),
            "superseded_on": superseded_on,
            "match_confidence": 0.9 if hint else 0.75,
        }

    key = candidates[0]
    vs = [v for v in versions if v["rule_key"] == key]
    governing = vs[0] if vs else None
    return {
        "verdict": "no_match" if governing is None else "never_correct",
        "matched_version": None,
        "governing_version": shape(governing) if governing else None,
        "superseded_on": None,
        "match_confidence": 0.4,
        "message": ("That does not match any version of this rule I hold, including "
                    "superseded ones. Check the wording, or it may never have been "
                    "correct."),
    }


@app.get("/v1/corpus/wage-percentile")
def wage_percentile(soc_code: str, state: str, wage: float,
                    fiscal_year: int | None = None):
    """Where an offered wage sits among certified LCA filings.

    An exact scan, not an interpolation between stored quantile states
    (docs/REVIEW.md A6). The SOC code is normalised on the way in, because the corpus
    carries both '15-1252.00' and bare '15-1252' for the same occupation and a
    caller-supplied suffix would otherwise return nothing.

    The percentile is peer-distribution CONTEXT. `wage_level` is the statistic the
    selection mechanism is understood to use, and the two can disagree
    (docs/REVIEW.md B10). Both are returned; neither is presented as odds.
    """
    fy = fiscal_year or 2025
    soc = ch.normalise_soc(soc_code)
    params = {"soc": soc, "state": state.upper(), "wage": wage, "fy": fy}

    try:
        rows, elapsed = ch.query(_sql(PERCENTILE_SQL), params)
    except ch.ClickHouseError as exc:
        raise HTTPException(503, detail=f"corpus unavailable: {exc}") from None

    row = rows[0] if rows else {}
    n = int(row.get("n_filings") or 0)
    # soc_code, state, fiscal_year and wage are echoed from the request here rather
    # than from the SQL. Echoing a parameter back under a column's own name inside
    # the query creates an alias that WHERE then resolves against, which silently
    # removes the filter. See the header of wage_percentile.sql.

    if n < MIN_FOR_PERCENTILE:
        # An empty result is an answer, and it must not look like a working query.
        # Home health aides have single-digit filings in the entire corpus: the LCA
        # corpus covers H-1B occupations, which are overwhelmingly technical. Saying
        # so is the honest answer. See docs/REVIEW.md C8.
        return {
            "soc_code": soc, "soc_title": None, "state": state.upper(),
            "fiscal_year": fy, "wage": wage,
            "percentile": None, "n_filings": n,
            "quantiles": None, "wage_level": None, "next_level_wage": None,
            "insufficient_data": True,
            "message": (
                (f"No certified LCA filings for {soc} in {state.upper()} in FY{fy}."
                 if n == 0 else
                 f"Only {n} certified LCA filing(s) for {soc} in {state.upper()} in "
                 f"FY{fy}, below the floor of {MIN_FOR_PERCENTILE}.")
                + " This corpus covers H-1B labour condition applications, which are "
                  "concentrated in technical occupations. A percentile cannot be "
                  "computed and will not be estimated."
            ),
            "source": {"dataset": "DOL OFLC LCA Disclosure Data",
                       "coverage": CORPUS_COVERAGE, "retrieved_at": "2026-08-28"},
            "elapsed_ms": elapsed,
        }

    try:
        levels, level_ms = ch.query(_sql(LEVEL_SQL), params)
    except ch.ClickHouseError:
        levels, level_ms = [], 0.0

    # Which level does this offer clear? The highest whose median it meets.
    order = ["I", "II", "III", "IV"]
    cleared, next_wage = None, None
    by_level = {str(l["pw_level"]): float(l["prevailing_median"]) for l in levels
                if l.get("prevailing_median") is not None}
    for name in order:
        median = by_level.get(name)
        if median is None:
            continue
        if wage >= median:
            cleared = order.index(name) + 1
        elif next_wage is None:
            next_wage = median

    return {
        "soc_code": soc, "soc_title": row.get("soc_title"),
        "state": state.upper(), "fiscal_year": fy, "wage": wage,
        "percentile": float(row["percentile"]),
        "n_filings": n,
        "quantiles": {k: float(row[k]) for k in ("p10", "p25", "p50", "p75", "p90")},
        "wage_level": cleared,
        "next_level_wage": next_wage,
        "level_bands": [
            {"level": str(l["pw_level"]), "n": int(l["n"]),
             "prevailing_median": float(l["prevailing_median"])}
            for l in levels
        ],
        "insufficient_data": n < SMALL_SAMPLE,
        "message": (
            f"Percentile computed over {n:,} certified filings. This is where the "
            f"offer sits among peer filings; it is not a selection probability. The "
            f"wage-weighted mechanism is understood to weight by OES wage level, "
            f"which is the level_bands field."
            + ("" if n >= SMALL_SAMPLE else
               f" Fewer than {SMALL_SAMPLE} filings: treat this percentile as "
               f"indicative only.")
        ),
        "source": {"dataset": "DOL OFLC LCA Disclosure Data",
                   "coverage": CORPUS_COVERAGE, "retrieved_at": "2026-08-28"},
        "elapsed_ms": round(elapsed + level_ms, 2),
    }


@app.get("/v1/standing")
def standing(sc_session: str | None = Cookie(default=None),
             fiscal_year: int | None = Query(default=None)):
    """Screen 6, for the signed-in person, with no parameters to get wrong.

    Reads the person's own occupation, state and offered wage from Postgres (scoped
    by RLS), then asks the corpus where that wage sits. The build spec has the agent
    assembling these arguments itself, which is three chances to hallucinate a SOC
    code; here the facts come from the record and the model just reads the answer.
    """
    subject_id = subject(sc_session)
    with repo.subject_tx(subject_id) as conn:
        job = repo.current_employment(conn)

    if job is None:
        return {"has_employment": False,
                "message": "No employment on file. Add your first job to see where "
                           "your wage sits."}
    if not job["soc_code"] or not job["worksite_state"] or job["offered_wage"] is None:
        missing = [k for k in ("soc_code", "worksite_state", "offered_wage")
                   if not job[k]]
        return {"has_employment": True, "employer": job["employer_name"],
                "incomplete": missing,
                "message": f"Missing {', '.join(missing)} for this job. "
                           f"Add it to see where your wage sits."}

    wage = float(job["offered_wage"])
    if (job["wage_unit"] or "Year") == "Hour":
        wage *= 2080

    corpus = wage_percentile(soc_code=job["soc_code"], state=job["worksite_state"],
                             wage=wage, fiscal_year=fiscal_year)

    # The rule that makes the wage question meaningful at all, with its provenance.
    #
    # This is the one rule in the table left unverified, and this is where its warning
    # band renders. The build spec cites it as "Final Rule 2025-12-29" with no Federal
    # Register number. Surfacing that on the screen it governs is the thesis working:
    # the product tells you which of its own numbers it cannot stand behind.
    # See docs/REVIEW.md E1.
    with repo.reference_tx() as conn:
        ruleset = repo.load_ruleset(conn)
    selection = ruleset.governing("lottery_selection", dt.date.today())

    return {
        "has_employment": True,
        "employer": job["employer_name"],
        "job": {"soc_code": job["soc_code"], "state": job["worksite_state"],
                "annual_wage": wage, "hours_per_week": job["hours_per_week"]},
        "corpus": corpus,
        "selection_rule": {
            "rule_id": selection.rule_id,
            "rule_key": selection.rule_key,
            "method": selection.param("method"),
            "citation": selection.citation,
            "authority": selection.authority,
            "effective_from": _iso(selection.effective_from),
            "source_url": selection.source_url,
            "verified": selection.verified,
            "verified_by": selection.verified_by,
            "note": selection.note,
        },
        "disclaimer": DISCLAIMER,
    }


app.mount("/ui", StaticFiles(directory=REPO / "web", html=True), name="ui")


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "engine_version": ENGINE_VERSION,
        "corpus": "up" if ch.available() else "down",
    }
