# LibreChat plus the toolchain its MCP servers need.
#
# The upstream image is Alpine on aarch64. PyPI manylinux wheels do not apply to
# musl, and there is no musllinux aarch64 wheel for lz4, so `uvx mcp-clickhouse`
# resolves clickhouse-connect -> lz4 and tries to compile it. The image has no `cc`,
# the build backend fails, and the ClickHouse MCP never connects:
#
#   error: [Errno 2] No such file or directory: 'cc'
#   hint: `lz4` was included because `mcp-clickhouse` depends on `clickhouse-connect`
#
# Five lines of build tooling is cheaper than replacing the official ClickHouse MCP,
# and it keeps the agent talking to ClickHouse through a server the ClickHouse project
# maintains rather than one we wrote the night before.

FROM ghcr.io/danny-avila/librechat-dev:latest

USER root
RUN apk add --no-cache build-base python3-dev linux-headers
USER node
