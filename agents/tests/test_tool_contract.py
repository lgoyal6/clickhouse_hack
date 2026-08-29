"""The citation contract, as tests.

If these fail, a tool can hand the model a number with no provenance, which is the
one failure this product cannot absorb. See docs/REVIEW.md H2 and D1.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agents.mcp.tool_schemas import TOOLS, PROVENANCE

NUMERIC_TOOLS = {"get_my_clocks", "explain_rule", "check_claim"}


def _flatten(node):
    """Yield every dict in a schema tree."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _flatten(v)
    elif isinstance(node, list):
        for v in node:
            yield from _flatten(v)


def test_no_tool_accepts_a_user_id():
    """Identity comes from the session. There must be no argument to vary."""
    for tool in TOOLS:
        props = tool["inputSchema"].get("properties", {})
        for banned in ("user_id", "userId", "subject", "subject_id", "email"):
            assert banned not in props, f"{tool['name']} accepts {banned}"


def test_every_input_schema_is_closed():
    """additionalProperties: false, so an identity field cannot be smuggled in."""
    for tool in TOOLS:
        assert tool["inputSchema"].get("additionalProperties") is False, tool["name"]


def test_provenance_fields_are_required():
    for field in ("citation", "authority", "effective_from", "source_url", "verified"):
        assert field in PROVENANCE["required"], field


def test_rule_bearing_tools_require_provenance_somewhere():
    for tool in TOOLS:
        if tool["name"] not in NUMERIC_TOOLS:
            continue
        found = any(
            node.get("required") and set(PROVENANCE["required"]).issubset(set(node["required"]))
            for node in _flatten(tool["outputSchema"])
        )
        assert found, f"{tool['name']} can return a rule without provenance"


def test_wage_tool_requires_its_sample_size_and_source():
    tool = next(t for t in TOOLS if t["name"] == "wage_percentile")
    required = tool["outputSchema"]["required"]
    assert "n_filings" in required, "a percentile without a sample size is not a percentile"
    assert "source" in required
    src = tool["outputSchema"]["properties"]["source"]["required"]
    assert {"dataset", "coverage", "retrieved_at"}.issubset(set(src))


def test_wage_tool_description_separates_percentile_from_odds():
    """REVIEW B10: the percentile is context, not selection odds."""
    tool = next(t for t in TOOLS if t["name"] == "wage_percentile")
    assert "wage level" in tool["description"]
    assert "not selection odds" in tool["description"]


def test_record_fact_forces_a_confidence_choice():
    tool = next(t for t in TOOLS if t["name"] == "record_fact")
    conf = tool["inputSchema"]["properties"]["confidence"]["enum"]
    assert set(conf) == {"document_verified", "user_stated", "inferred"}
    assert "needs_confirmation" in tool["outputSchema"]["required"]


def test_every_tool_has_a_route():
    from agents.mcp.status_clock import ROUTES
    assert {t["name"] for t in TOOLS} == set(ROUTES)


def test_provenance_is_required_only_for_running_clocks():
    """Regression: the agent refused a valid response because of this.

    Requiring provenance on EVERY clock meant a non-applicable entry, which has no
    governing rule to cite, failed validation. The agent saw a data-integrity error,
    correctly declined to vouch for the payload, and reported no clocks at all. The
    contract was right; the schema was too strict.
    """
    from jsonschema import Draft202012Validator

    tool = next(t for t in TOOLS if t["name"] == "get_my_clocks")
    item = tool["outputSchema"]["properties"]["clocks"]["items"]
    v = Draft202012Validator(item)

    running = {"clock_key": "opt_unemployment", "label": "Unemployment days",
               "severity": "critical", "applicable": True,
               "provenance": {"rule_id": "r", "rule_key": "k", "citation": "8 CFR",
                              "authority": "8 CFR", "effective_from": "2008-04-08",
                              "source_url": "https://x.invalid", "verified": False}}
    assert not list(v.iter_errors(running))

    not_running = {"clock_key": "ac21_365", "label": "AC21 365-day threshold",
                   "severity": "info", "applicable": False,
                   "not_applicable_reason": "Not in H-1B status"}
    assert not list(v.iter_errors(not_running)), "a clock that has not started needs no citation"

    uncited = {"clock_key": "opt_unemployment", "label": "Unemployment days",
               "severity": "critical", "applicable": True}
    assert list(v.iter_errors(uncited)), "a RUNNING clock with no provenance must still fail"
