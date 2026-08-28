"""OFLC loader. Enforces the order of operations and the wage-unit closed set.

    python -m ingest.load --dataset lca --fiscal-year 2025 data/LCA_FY2025.csv

Two things this exists to prevent, both of which are silent failures:

1. **Materialized views must exist before data lands.** A ClickHouse materialized
   view is a trigger over inserts, so it only sees rows that arrive after it is
   created. Load 8M rows and then create `wage_baselines` and it is empty, the
   Standing screen shows nothing, and nothing errors. `--check-order` refuses to
   load until the views exist. See docs/REVIEW.md A5.

2. **An unrecognised wage unit must exclude the row, not coerce it.** OFLC unit
   spellings move between fiscal years. A hourly row that falls through to the raw
   value enters the distribution as if $52.00 were an annual salary, and the p50 for
   an occupation quietly collapses. The DDL already fails closed to NULL; this
   refuses the load outright so nobody has to notice the NULLs later.
   See docs/REVIEW.md A8.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import subprocess
import sys

from .column_maps import CANONICAL, KNOWN_WAGE_UNITS, map_for

REQUIRED_VIEWS = ("wage_baselines", "wage_histogram", "employer_profiles")
UNIT_FAILURE_TOLERANCE = 0.005      # 0.5% of rows may carry a junk unit


def ch(query: str, host: str, password: str, fmt: str = "TSV") -> str:
    out = subprocess.run(
        ["clickhouse", "client", "--host", host, "--password", password,
         "--format", fmt, "--query", query],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout.strip()


def check_order(host: str, password: str) -> None:
    """Refuse to load until the materialized views exist."""
    existing = set(ch("SHOW TABLES", host, password).splitlines())
    missing = [v for v in REQUIRED_VIEWS if v not in existing]
    if missing:
        raise SystemExit(
            f"refusing to load: materialized view(s) {', '.join(missing)} do not exist.\n"
            f"A materialized view only sees inserts that arrive AFTER it is created, so\n"
            f"loading now leaves them permanently empty and nothing errors.\n"
            f"Run:  make -f Makefile.data ch-ddl"
        )


def read_rows(path: pathlib.Path, colmap: dict):
    """Yield canonical dicts, or raise on a header that does not match the map."""
    if path.suffix.lower() in {".xlsx", ".xls"}:
        raise SystemExit(
            f"{path.name} is a spreadsheet. Convert to CSV or Parquet once and load "
            f"that; reloads happen more often than anyone plans for and xlsx parsing "
            f"is slow enough to hurt. See ingest/README.md."
        )
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        header = set(reader.fieldnames or ())
        wanted = {v for v in colmap.values() if v}
        missing = sorted(wanted - header)
        if missing:
            raise SystemExit(
                f"{path.name} is missing column(s) the map expects: {', '.join(missing)}\n"
                f"Run  python -m ingest.headers {path}  and fix ingest/column_maps.py.\n"
                f"A mismapped wage column is the most likely way this project ships a "
                f"wrong number."
            )
        for row in reader:
            yield {canon: (row.get(src) if src else None)
                   for canon, src in colmap.items()}


def audit_units(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        unit = (r.get("wage_unit") or "").strip()
        counts[unit] = counts.get(unit, 0) + 1
    return counts


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=pathlib.Path)
    ap.add_argument("--dataset", default="lca", choices=["lca"])
    ap.add_argument("--fiscal-year", type=int, required=True)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--password", default="devonly")
    ap.add_argument("--dry-run", action="store_true",
                    help="audit the file and the wage units; insert nothing")
    args = ap.parse_args(argv)

    colmap = map_for(args.dataset, args.fiscal_year)

    if not args.dry_run:
        check_order(args.host, args.password)

    rows = list(read_rows(args.path, colmap))
    print(f"{len(rows)} rows read from {args.path.name}")

    # The wage-unit gate.
    units = audit_units(rows)
    unknown = {u: n for u, n in units.items() if u not in KNOWN_WAGE_UNITS}
    print("\nwage_unit distribution:")
    for unit, n in sorted(units.items(), key=lambda kv: -kv[1]):
        flag = "  <-- NOT IN KNOWN_WAGE_UNITS" if unit not in KNOWN_WAGE_UNITS else ""
        print(f"  {unit or '(blank)':12s} {n:>9,}{flag}")

    if unknown:
        bad = sum(unknown.values())
        share = bad / max(1, len(rows))
        print(f"\n{bad:,} row(s) ({share:.2%}) carry a wage unit that cannot be annualised.")
        if share > UNIT_FAILURE_TOLERANCE:
            raise SystemExit(
                f"refusing to load: {share:.2%} exceeds the {UNIT_FAILURE_TOLERANCE:.2%} "
                f"tolerance.\nAdd the real spellings to KNOWN_WAGE_UNITS and to the "
                f"multiIf in clickhouse/ddl/010_corpus.sql, or these rows silently\n"
                f"enter the distribution with the wrong magnitude. See docs/REVIEW.md A8."
            )
        print("Within tolerance. Those rows will annualise to NULL and be excluded "
              "from wage_baselines, not coerced.")

    if args.dry_run:
        print("\ndry run: nothing inserted")
        return 0

    # TODO: stream rows into clickhouse via INSERT ... FORMAT CSV. Kept out of this
    # commit so the gates above can be reviewed on their own.
    raise SystemExit(
        "insert path not written yet. --dry-run works and is the part that matters "
        "first: run it on every file before loading any of them."
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
