"""API tests that need no database.

Kept separate from test_integration.py so the fast checks always run. These live
here rather than in engine/tests because the engine must stay free of any
dependency on the API or on Postgres.
"""
import pathlib
import sys
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from api.main import DEMO_SESSIONS, KINDS, LABELS, REQUIRED_PROVENANCE, serialise
from engine.clocks import ALL_CLOCK_KEYS


def test_demo_sessions_hold_real_uuids():
    """These strings reach Postgres as UUID.

    They were originally written with 'ma01'/'da01' suffixes, which are not hex, so
    every insert failed the first time the migrations ran against a real database.
    Python never parsed them, so the suite passed and the defect was invisible.
    """
    for session, subject_id in DEMO_SESSIONS.items():
        assert str(uuid.UUID(subject_id)) == subject_id, session


def test_every_clock_has_a_label_and_a_kind():
    """The engine and the UI read one canonical list. REVIEW B8."""
    for key in ALL_CLOCK_KEYS:
        assert key in LABELS, f"{key} has no label"
        assert "en" in LABELS[key], f"{key} has no English label"
        assert key in KINDS, f"{key} has no kind"


def test_serialise_refuses_a_running_clock_without_provenance():
    """A 500 is correct here. An uncited number is not. REVIEW H2."""
    import datetime as dt
    from fastapi import HTTPException

    broken = {
        "clock_key": "opt_unemployment", "applicable": True, "severity": "critical",
        "as_of": dt.date(2026, 8, 28), "engine_version": "0.1.0",
        "days_consumed": 131, "denominator": 150,
        "provenance": {f: None for f in REQUIRED_PROVENANCE},
    }
    with pytest.raises(HTTPException) as exc:
        serialise(broken, "en")
    assert exc.value.status_code == 500
    assert "without provenance" in exc.value.detail


def test_serialise_allows_a_not_applicable_clock_without_provenance():
    import datetime as dt

    out = serialise(
        {
            "clock_key": "ac21_365", "applicable": False,
            "not_applicable_reason": "not in H-1B status",
            "as_of": dt.date(2026, 8, 28), "engine_version": "0.1.0",
        },
        "en",
    )
    assert out["applicable"] is False
    assert "provenance" not in out
    assert out["label"] == "AC21 365-day threshold"


def test_labels_are_localised_with_an_english_fallback():
    import datetime as dt

    base = {
        "clock_key": "opt_unemployment", "applicable": False,
        "not_applicable_reason": "x", "as_of": dt.date(2026, 8, 28),
        "engine_version": "0.1.0",
    }
    assert serialise(base, "es")["label"] == "Días de desempleo"
    assert serialise(base, "en")["label"] == "Unemployment days"
    assert serialise(base, "tl")["label"] == "Unemployment days"   # fallback, not a crash
