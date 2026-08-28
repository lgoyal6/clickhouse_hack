"""MCP server wrapping Person A's API.

    python -m agents.mcp.status_clock

Holds the session cookie. Tools take no identity parameter, so there is no argument
the model can vary to read another person's data. See docs/REVIEW.md D1.
"""
from __future__ import annotations

import os

import httpx
import jsonschema

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

_SCHEMAS = {t["name"]: t["outputSchema"] for t in TOOLS}


def list_tools() -> list[dict]:
    return TOOLS


def call_tool(name: str, arguments: dict) -> dict:
    if name not in ROUTES:
        raise ValueError(f"unknown tool {name!r}")
    method, path = ROUTES[name]

    # rule_key is the only path parameter; whatever's left goes in the query/body.
    path_params = {k: v for k, v in arguments.items() if "{" + k + "}" in path}
    body_params = {k: v for k, v in arguments.items() if k not in path_params}
    path = path.format(**path_params)

    with httpx.Client(base_url=API, cookies={"sc_session": SESSION}, timeout=10.0) as client:
        if method == "GET":
            resp = client.get(path, params=body_params)
        else:
            resp = client.post(path, json=body_params)
    resp.raise_for_status()
    data = resp.json()

    # Validate rather than trust: if provenance is missing, raise, so the model
    # never receives a number it could repeat uncited. See docs/REVIEW.md H2.
    jsonschema.validate(data, _SCHEMAS[name])
    return data


async def _serve() -> None:
    """Speak MCP over stdio. This is what librechat.yaml's `type: stdio` runs."""
    from mcp import stdio_server
    from mcp.server.lowlevel import Server
    from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent
    from mcp.types import Tool as MCPTool

    async def on_list_tools(ctx, params) -> ListToolsResult:
        return ListToolsResult(tools=[
            MCPTool(
                name=t["name"],
                description=t["description"],
                input_schema=t["inputSchema"],
                output_schema=t["outputSchema"],
            )
            for t in list_tools()
        ])

    async def on_call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
        try:
            result = call_tool(params.name, params.arguments or {})
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result))],
                structured_content=result,
            )
        except Exception as e:
            return CallToolResult(content=[TextContent(type="text", text=str(e))], is_error=True)

    server = Server("status-clock", on_list_tools=on_list_tools, on_call_tool=on_call_tool)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import json
    import sys

    if "--list" in sys.argv:
        print(json.dumps({"tools": [t["name"] for t in list_tools()]}, indent=2))
    else:
        import anyio
        anyio.run(_serve)
