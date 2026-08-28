"""MCP server wrapping Person A's API.

    python -m agents.mcp.status_clock

Holds the session cookie. Tools take no identity parameter, so there is no argument
the model can vary to read another person's data. See docs/REVIEW.md D1.

This is a skeleton: the tool list and the dispatch table are real, the HTTP calls are
marked TODO. It exists so the tool contract is reviewable before either side is wired.
"""
from __future__ import annotations

import os

from .tool_schemas import TOOLS

API = os.environ.get("STATUS_CLOCK_API", "http://localhost:8000")
SESSION = os.environ.get("STATUS_CLOCK_SESSION", "sess_maria")

ROUTES = {
    "get_my_clocks":   ("GET",  "/v1/clocks"),
    "explain_rule":    ("GET",  "/v1/rules/{rule_key}"),
    "check_claim":     ("POST", "/v1/claims/check"),
    "wage_percentile": ("GET",  "/v1/corpus/wage-percentile"),
    "what_if":         ("POST", "/v1/scenarios/replay"),
    "record_fact":     ("POST", "/v1/facts"),
}


def list_tools() -> list[dict]:
    return TOOLS


def call_tool(name: str, arguments: dict) -> dict:
    if name not in ROUTES:
        raise ValueError(f"unknown tool {name!r}")
    # TODO: httpx call to API with cookie {'sc_session': SESSION}, then validate the
    # response against the tool's outputSchema before returning it. Validate rather
    # than trust: if provenance is missing, raise, so the model never receives a
    # number it could repeat uncited.
    raise NotImplementedError(
        f"{name} is not wired yet. Route is {ROUTES[name][0]} {API}{ROUTES[name][1]}."
    )


if __name__ == "__main__":
    import json
    print(json.dumps({"tools": [t["name"] for t in list_tools()]}, indent=2))
