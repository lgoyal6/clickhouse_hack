# ingest/

## The pipeline, verified end to end

```bash
# 1. download (data/ is gitignored)
curl -o data/LCA_Disclosure_Data_FY2025_Q4.xlsx \
  https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx

# 2. look at the real headers before trusting any map
python -m ingest.headers data/LCA_Disclosure_Data_FY2025_Q4.xlsx

# 3. convert once. 75 MB of xlsx takes minutes; the CSV loads in seconds.
python -m ingest.convert data/LCA_Disclosure_Data_FY2025_Q4.xlsx

# 4. audit the wage units without inserting anything
python -m ingest.load --fiscal-year 2025 --dry-run data/LCA_Disclosure_Data_FY2025_Q4.csv

# 5. load, then gate
python -m ingest.load --fiscal-year 2025 data/LCA_Disclosure_Data_FY2025_Q4.csv
make -f Makefile.data quality
```

Currently loaded: **239,477 rows**, FY2024 Q4 and FY2025 Q4, 216,775 certified.

## What the real files taught us

The maps in `column_maps.py` are verified against FY2024 Q4 and FY2025 Q4: 98
columns, identical headers. Four things the data settled, three of which were bugs
that produce a confident wrong answer rather than an error:

**`case_status` is `'Certified'`, not `'CERTIFIED'`.** The build spec's filter matches
zero rows. Every materialized view would have been empty and nothing would have
raised. `case_status_norm` normalises at write time; `data_quality.sql` reports every
distinct spelling so a change in the source is visible.

**SOC codes come in two spellings.** 236,886 rows carry the O\*NET detail suffix
(`15-1252.00`) and 2,591 are bare (`15-1252`). For Software Developers that is 74,504
against 547. Querying the raw column returned `n=29` for California where the truth is
`n=5,991`. Normalise on both sides: the column *and* the caller's input.

**`PW_UNIT_OF_PAY` is a separate column** from `WAGE_UNIT_OF_PAY`, and they differ on
real rows. Comparing a raw prevailing wage against an annualised offered wage is out
by roughly 2,080.

**The spreadsheets are mostly empty.** FY2025 Q4 declares 563,689 rows and holds
118,580. `convert.py` skips blank rows; without it every distribution is computed over
mostly nothing.

Also: `EMPLOYER_FEIN` **is** present and 100% populated, so the concern in
`docs/REVIEW.md` C2 was unfounded. There is **no** MSA column at all, confirming C3.
State is the contract.

## Order of operations is enforced, not documented

A ClickHouse materialized view is a trigger over inserts, so it only sees rows that
arrive **after** it is created. Load 8M rows and then create `wage_baselines` and it
is empty, the Standing screen shows nothing, and the failure is silent.

`load.py` refuses to insert until `wage_baselines`, `wage_histogram` and
`employer_profiles` exist. Run `make -f Makefile.data ch-ddl` first.

## The wage-unit gate

A file where more than 0.5% of rows carry a unit that cannot be annualised is refused
outright, and the distribution is printed either way. On the real files the closed set
is complete: Year 109,568, Hour 8,612, Month 252, Week 79, Bi-Weekly 69, zero
unrecognised.

Unrecognised units annualise to `NULL` and are excluded from `wage_baselines` rather
than coerced. The alternative is a $52.00 hourly wage entering the distribution as an
annual salary, which quietly collapses the p50 for an occupation.

## What the corpus does and does not cover

It is H-1B labour condition applications, so it is overwhelmingly technical
occupations. Home Health Aides have **one** certified filing across both fiscal years.
`/v1/corpus/wage-percentile` returns `insufficient_data` with a reason rather than a
percentile over single digits. See `docs/REVIEW.md` C8, which matters for the demo
script.

## Adding a fiscal year

FY2020 through FY2026 are the same vintage and should work, but they are marked
unverified in `LCA_MAPS`. Run `ingest.headers` on the file first. FY2019 and earlier
are a different vintage and have not been checked at all.
