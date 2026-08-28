#!/usr/bin/env bash
# Move the corpus to a ClickHouse Cloud service.
#
#   export CH_CLOUD_HOST=xxxx.us-west-2.aws.clickhouse.cloud
#   export CH_CLOUD_PASSWORD='...'
#   ./clickhouse/cloud/migrate.sh
#
# What moves and what does not:
#
#   lca_filings   1.16M rows   real DOL data      MOVES
#   perm_filings  239K rows    real DOL data      MOVES
#   clock_evaluations  127.8M  SYNTHETIC benchmark data
#
# The evaluations are deliberately NOT moved by default. They are generated rows that
# exist to benchmark the replay query, and pushing 3.68 GiB of synthetic data into a
# hosted service to make a row count look bigger is the kind of thing this project is
# supposed to be against. Pass --with-evaluations if you want them anyway; the real
# ones replicate from Postgres through api/replicate.py in seconds.
set -euo pipefail
cd "$(dirname "$0")/../.."

: "${CH_CLOUD_HOST:?set CH_CLOUD_HOST}"
: "${CH_CLOUD_PASSWORD:?set CH_CLOUD_PASSWORD}"
CH_CLOUD_USER="${CH_CLOUD_USER:-default}"
WITH_EVALS="${1:-}"

LOCAL="docker compose -f infra/data.compose.yml exec -T clickhouse clickhouse-client --password ${CLICKHOUSE_PASSWORD:-devonly}"

cloud() {
  curl -sS --fail-with-body \
    --user "${CH_CLOUD_USER}:${CH_CLOUD_PASSWORD}" \
    "https://${CH_CLOUD_HOST}:8443/" --data-binary @-
}

echo "== 1. schema =="
for f in clickhouse/ddl/010_corpus.sql clickhouse/ddl/015_perm.sql \
         clickhouse/ddl/020_evaluations.sql clickhouse/ddl/030_views.sql; do
  echo "   $f"
  # Cloud runs SharedMergeTree; the plain MergeTree in these files is accepted and
  # substituted automatically, so the DDL needs no fork.
  cloud < "$f" >/dev/null
done

echo "== 2. corpus =="
for t in lca_filings perm_filings; do
  n=$($LOCAL --query "SELECT count() FROM $t")
  echo "   $t: $n rows"
  $LOCAL --query "SELECT * FROM $t FORMAT Native" \
    | curl -sS --fail-with-body --user "${CH_CLOUD_USER}:${CH_CLOUD_PASSWORD}" \
        "https://${CH_CLOUD_HOST}:8443/?query=INSERT%20INTO%20${t}%20FORMAT%20Native" \
        --data-binary @- >/dev/null
done

if [ "$WITH_EVALS" = "--with-evaluations" ]; then
  echo "== 3. synthetic evaluations (3.68 GiB) =="
  $LOCAL --query "SELECT * FROM clock_evaluations FORMAT Native" \
    | curl -sS --fail-with-body --user "${CH_CLOUD_USER}:${CH_CLOUD_PASSWORD}" \
        "https://${CH_CLOUD_HOST}:8443/?query=INSERT%20INTO%20clock_evaluations%20FORMAT%20Native" \
        --data-binary @- >/dev/null
else
  echo "== 3. skipping synthetic evaluations. Real ones replicate from Postgres:"
  echo "      CLICKHOUSE_HOST=$CH_CLOUD_HOST CLICKHOUSE_PORT=8443 python -m api.replicate"
fi

echo "== 4. read-only user for the LibreChat MCP =="
sed "s/{{CH_READONLY_PASSWORD}}/${CH_READONLY_PASSWORD:-devonly-readonly}/" \
  clickhouse/ddl/090_readonly_user.sql | cloud >/dev/null || \
  echo "   (skipped: Cloud may manage users differently on your plan)"

echo
echo "== verify =="
echo "SELECT table, formatReadableQuantity(sum(rows)) FROM system.parts
      WHERE active AND database='default' AND table NOT LIKE '.inner%'
      GROUP BY table ORDER BY table FORMAT PrettyCompact" | cloud

cat <<'NEXT'

Point the app at Cloud:

  export CLICKHOUSE_HOST=$CH_CLOUD_HOST
  export CLICKHOUSE_PORT=8443
  export CLICKHOUSE_USER=default
  export CLICKHOUSE_PASSWORD=$CH_CLOUD_PASSWORD
  make -f Makefile.data api

api/clickhouse.py reads those four and speaks the HTTP interface, which Cloud serves
on 8443 over TLS. Nothing else changes.
NEXT
