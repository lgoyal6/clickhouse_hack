#!/usr/bin/env python3
"""Validate the contract and every fixture. Run before you push.

    pip install pyyaml jsonschema
    python contracts/validate.py

Exits non-zero on the first failure. Both tracks depend on this passing.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(label)


def main() -> int:
    try:
        import yaml
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:
        print(f"missing dependency: {exc}. pip install pyyaml jsonschema")
        return 2

    spec = yaml.safe_load((HERE / "openapi.yaml").read_text())
    check("openapi.yaml parses", True, f"{len(spec['paths'])} paths")

    # Invariant: identity never travels as a parameter.
    leaked = [p for p, body in spec["paths"].items() if "user_id" in json.dumps(body)]
    check("no endpoint accepts a user id (REVIEW D1)", not leaked, str(leaked))

    schema = json.loads((HERE / "clock.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Invariant: provenance is required, not optional.
    required = set(schema["properties"]["provenance"]["required"])
    for field in ("citation", "authority", "effective_from", "verified"):
        check(f"provenance.{field} is required (REVIEW H2)", field in required)

    for path in sorted((HERE / "fixtures").glob("clocks_*.json")):
        doc = json.loads(path.read_text())
        for clock in doc["clocks"]:
            errors = sorted(validator.iter_errors(clock), key=lambda e: list(e.path))
            check(
                f"{path.name} :: {clock.get('clock_key')}",
                not errors,
                "; ".join(f"{list(e.path)} {e.message}" for e in errors),
            )

    # Negative check: a RUNNING clock without provenance must be REJECTED.
    # Without this, the conditional requirement is assumed rather than proven.
    uncited = {
        "clock_key": "opt_unemployment", "label": "Unemployment days",
        "kind": "consumption", "severity": "critical", "as_of": "2026-08-28",
        "applicable": True, "days_consumed": 131, "denominator": 150,
    }
    check(
        "a running clock with no provenance is rejected (REVIEW H2)",
        bool(list(validator.iter_errors(uncited))),
    )
    # And a non-applicable clock without provenance must be ACCEPTED, because a clock
    # that has not started has no governing rule to cite.
    not_running = {
        "clock_key": "ac21_365", "label": "AC21 365-day threshold",
        "kind": "deadline", "severity": "info", "as_of": "2026-08-28",
        "applicable": False,
        "not_applicable_reason": "not in H-1B status; the six-year meter has not started",
    }
    errs = list(validator.iter_errors(not_running))
    check(
        "a not-applicable clock needs no provenance (REVIEW B11)",
        not errs,
        "; ".join(e.message for e in errs),
    )

    # Every fixture must at least be well-formed JSON.
    for path in sorted((HERE / "fixtures").glob("*.json")):
        try:
            json.loads(path.read_text())
            check(f"{path.name} is valid JSON", True)
        except json.JSONDecodeError as exc:
            check(f"{path.name} is valid JSON", False, str(exc))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s)")
        return 1
    print("contract green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
