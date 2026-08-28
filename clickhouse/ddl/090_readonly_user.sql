-- The read-only user for LibreChat's ClickHouse MCP connection.
--
-- Person A creates this and hands the connection string to Person B. The agent can
-- compose SQL; an agent that can compose SQL against a writable connection is a
-- hole, not a feature. See docs/OWNERSHIP.md.
--
-- Apply with:  make -f Makefile.data ch-user
--
-- Requires CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 on the server, which
-- infra/data.compose.yml sets. Without it the default user has no CREATE USER grant,
-- this file fails with ACCESS_DENIED, and the only way to give the agent ClickHouse
-- access is to hand it the admin credentials. That is the hole this file exists to
-- close, so the failure mode is worth naming.
--
-- Verified after creation: chat_readonly can SELECT lca_filings, perm_filings and
-- wage_baselines, and is DENIED on clock_evaluations, on INSERT, on DROP, and on
-- system.users.

CREATE USER IF NOT EXISTS chat_readonly
  IDENTIFIED WITH sha256_password BY '{{CH_READONLY_PASSWORD}}'
  SETTINGS
    readonly = 1,
    max_result_rows = 10000,
    max_execution_time = 20,
    max_memory_usage = 2000000000;

GRANT SELECT ON default.lca_filings     TO chat_readonly;
GRANT SELECT ON default.perm_filings    TO chat_readonly;
GRANT SELECT ON default.visa_bulletin   TO chat_readonly;
GRANT SELECT ON default.wage_baselines  TO chat_readonly;
GRANT SELECT ON default.wage_histogram  TO chat_readonly;
GRANT SELECT ON default.employer_profiles TO chat_readonly;

-- Deliberately NOT granted: clock_evaluations and soc_embeddings.
-- clock_evaluations is per-person data and must be reached only through the API,
-- where identity comes from the session. Granting it here would reintroduce the
-- IDOR that docs/REVIEW.md D1 exists to close.
