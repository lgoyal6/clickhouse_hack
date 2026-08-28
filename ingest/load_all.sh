#!/usr/bin/env bash
# Convert and load every LCA file in data/, from scratch.
#
# The quarterly files are NOT cumulative: FY2025 Q4 holds decisions from
# 2025-07-01 to 2025-09-30 only. A fiscal year is four files. Loading Q4 alone gives
# you a quarter and labels it a year, which is how the first pass understated every
# occupation's sample size by roughly 4x.
#
#   ./ingest/load_all.sh            # convert what is missing, then load everything
#
# Truncates first, so it is safe to re-run and cannot double-count.
set -euo pipefail
cd "$(dirname "$0")/.."

CH="docker compose -f infra/data.compose.yml exec -T clickhouse clickhouse-client --password ${CLICKHOUSE_PASSWORD:-devonly}"
PY="${PYTHON:-python}"

echo "== truncating lca_filings and its views (an MV's rows live in its own table) =="
for t in lca_filings wage_baselines wage_histogram wage_levels employer_profiles; do
  $CH --query "TRUNCATE TABLE IF EXISTS $t"
done

shopt -s nullglob
for x in data/LCA_Disclosure_Data_FY*.xlsx; do
  csv="${x%.xlsx}.csv"
  [ -f "$csv" ] || { echo "== converting $(basename "$x") =="; $PY -m ingest.convert "$x"; }
done

total=0
for csv in data/LCA_Disclosure_Data_FY*.csv; do
  base=$(basename "$csv" .csv)
  fy=$(echo "$base" | sed -E 's/.*FY([0-9]{4}).*/\1/')
  echo "== loading $base (FY$fy) =="
  $PY -m ingest.load --fiscal-year "$fy" "$csv" | tail -2
done

echo
$CH --query "SELECT fiscal_year, count() AS rows, countIf(case_status_norm='CERTIFIED') AS certified,
             uniqExact(soc_code_norm) AS occupations, uniqExact(employer_name_norm) AS employers
             FROM lca_filings GROUP BY fiscal_year ORDER BY fiscal_year FORMAT PrettyCompactMonoBlock"
$CH --query "SELECT count() AS total_rows, uniqExact(source_file) AS files FROM lca_filings FORMAT PrettyCompactMonoBlock"
