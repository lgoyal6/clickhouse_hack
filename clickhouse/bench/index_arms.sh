#!/usr/bin/env bash
#
# What the partition key buys, and what a data-skipping index does not.
#
# clickhouse/queries/replay_diff.sql has told anyone reading it to run
# `EXPLAIN indexes = 1` since the file was written. RESULTS.md measured rows
# read, which is the outcome; this measures the plan, which is the reason.
#
# Four arms over the same 127.75M rows:
#
#   C  no index at all        ce_skipidx, use_skip_indexes = 0
#   B  minmax skip index      ce_skipidx, use_skip_indexes = 1
#   A  partition key          clock_evaluations, optimize_use_projections = 0
#   A+ partition + projection clock_evaluations, defaults
#
# B exists because it is the obvious alternative to partitioning and it is the
# one that does not work. Keeping it in the harness is the point: an index
# decision with only the winning arm measured is a preference with a number
# stapled to it.
#
# Usage: clickhouse/bench/index_arms.sh [container]

set -uo pipefail
CONTAINER=${1:-infra-clickhouse-1}
CH() { docker exec -i "$CONTAINER" clickhouse-client "$@"; }

CLOCK=h1b_grace_period
AS_OF=2026-08-28

# The scan half of the marquee replay query: one clock, one scenario, one day.
read -r -d '' QUERY <<'SQL' || true
SELECT count(), sum(days_remaining)
FROM %s
WHERE clock_key = '%s' AND scenario_id = 'actual'
  AND as_of = '%s' AND applicable = 1
SETTINGS %s
SQL

plan() {
  local table="$1" settings="$2"
  CH -q "EXPLAIN indexes = 1 $(printf "$QUERY" "$table" "$CLOCK" "$AS_OF" "$settings")"
}

# Best of three. Rows read is deterministic; the millisecond figure on a
# laptop sharing a machine with other containers is not, and the arms were
# first measured in an order that made the losing arm look 2.4x worse than a
# re-run in the opposite order showed. Order is varied and the minimum kept.
timed() {
  local label="$1" table="$2" settings="$3" best=999999 rows= bytes=
  for i in 1 2 3; do
    local qid="arm-${label// /_}-$i-$$"
    CH --query_id "$qid" -q "$(printf "$QUERY" "$table" "$CLOCK" "$AS_OF" "$settings")" >/dev/null 2>&1
    CH -q "SYSTEM FLUSH LOGS" >/dev/null 2>&1
    local row
    row=$(CH -q "SELECT read_rows, read_bytes, query_duration_ms FROM system.query_log WHERE query_id = '$qid' AND type = 'QueryFinish' LIMIT 1")
    [ -z "$row" ] && { echo "no query_log row for $qid" >&2; return 1; }
    rows=$(echo "$row" | cut -f1); bytes=$(echo "$row" | cut -f2)
    local d; d=$(echo "$row" | cut -f3)
    [ "$d" -lt "$best" ] && best=$d
  done
  printf "%-26s %14s %14s %8s\n" "$label" "$rows" "$bytes" "${best}ms"
}

echo "# index arms, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
CH -q "SELECT 'rows: ' || formatReadableQuantity(count()) FROM clock_evaluations"
echo
echo "## storage at steady state (run OPTIMIZE ... FINAL first for a fair read)"
CH -q "SELECT table, count() AS parts, formatReadableSize(sum(bytes_on_disk)) AS on_disk FROM system.parts WHERE table IN ('clock_evaluations','ce_skipidx') AND active GROUP BY table ORDER BY table FORMAT PrettyCompactMonoBlock"
CH -q "SELECT table, name, formatReadableSize(sum(bytes_on_disk)) AS on_disk FROM system.projection_parts WHERE table = 'clock_evaluations' AND active GROUP BY table, name FORMAT PrettyCompactMonoBlock"
echo
echo "## executed"
printf "%-26s %14s %14s %8s\n" "arm (best of 3)" "rows read" "bytes read" "time"
timed "C no index at all"   ce_skipidx        "use_skip_indexes = 0"
timed "B minmax skip index" ce_skipidx        "use_skip_indexes = 1"
timed "A partition key"     clock_evaluations "optimize_use_projections = 0"
timed "A+ projection"       clock_evaluations "optimize_use_projections = 1"
echo
for arm in "C:ce_skipidx:use_skip_indexes = 0" \
           "B:ce_skipidx:use_skip_indexes = 1" \
           "A:clock_evaluations:optimize_use_projections = 0" \
           "A+:clock_evaluations:optimize_use_projections = 1"; do
  IFS=: read -r label table settings <<<"$arm"
  echo "## plan, arm $label"
  plan "$table" "$settings" | grep -E "ReadFromMergeTree|Parts:|Granules:|Min-Max|Partition$|PrimaryKey|Skip$|Name:|Description:|Search Algorithm" 
  echo
done
