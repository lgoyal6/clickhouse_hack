# Running the demo

Everything is local. Three terminals, or two if you leave the databases up.

## Cold start

```bash
# 1. databases (Postgres + ClickHouse)
make -f Makefile.data up migrate seed ch-ddl

# 2. corpus, ~10 min, downloads ~1.2 GB from DOL. Skip if data/ is already populated.
./ingest/load_all.sh

# 3. the API, which also serves the UI
make -f Makefile.data api

# 4. LibreChat
docker compose -f librechat/chat.compose.yml --env-file librechat/.env up -d
```

## What to open

| URL | What it is |
|---|---|
| **http://localhost:8000** | **Start here.** Sets a demo session and redirects to the Clock Wall. |
| http://localhost:8000/ui/ | Clock Wall, live from Postgres + the engine |
| http://localhost:8000/ui/ask.html | Ask, which links out to LibreChat |
| **http://localhost:3080** | LibreChat. Sign up with any email; registration is open locally. |
| http://localhost:8000/docs | Auto-generated API reference, clickable |

## The demo path

1. **http://localhost:8000** opens on Maria: home health aide, STEM OPT, in cap-gap.
   Two clocks running, five explained as not-yet-started rather than shown as zero.
   Labels are in Spanish because her `locale` is `es`.
2. **The cap-gap card is the beat.** `SEP 30 2026` struck through, `01 APR 2027`
   below it, and `216 days remaining · 243-day window · 183 days gained`. Three
   numbers, three labels. The citation and the supersession date sit inside the card.
3. **Click `sess_daniel`.** This changes the *session*, not a parameter: the URL is
   `/session/sess_daniel` and no endpoint anywhere accepts a user id. Daniel is an
   adjunct on H-1B with nothing filed, so AC21 is critical at 34 days, and the card
   carries the corpus finding that the median certified PERM takes 462 days.
4. **Standing**: `curl -b sc_session=sess_daniel localhost:8000/v1/standing`.
   14.6th percentile of real certified filings, OES Level I, and the wage that would
   move him a tier. The selection rule attached to it is the one rule left unverified,
   and its warning band is showing on purpose.
5. **Ask** at http://localhost:3080. Both MCP servers are connected, 9 tools.

## Personas

| session | who | clocks running |
|---|---|---|
| `sess_maria` | home health aide, STEM OPT, cap-gap, locale `es` | unemployment, cap-gap |
| `sess_daniel` | adjunct instructor, H-1B year five, nothing filed | AC21, H-1B max |

Switch with http://localhost:8000/session/sess_daniel.

## Health check

```bash
curl localhost:8000/healthz          # {"ok":true,"corpus":"up"}
make -f Makefile.data verify         # 99 tests + contract
make -f Makefile.data quality        # 12 corpus gates
docker compose -f librechat/chat.compose.yml logs librechat | grep "Initialized with"
```

The last one should say `2 configured servers and 9 tools`.

## Things that will bite you

**LibreChat needs an Anthropic key.** `librechat/.env`, `ANTHROPIC_API_KEY=`. Then
restart the librechat container. Everything else is already wired.

**Ask opens in its own tab.** LibreChat sends `X-Frame-Options: SAMEORIGIN` and the
UI is on a different port, so it cannot be embedded. Two tabs is fine.

**First LibreChat start compiles `lz4`** because Alpine on aarch64 has no wheel for
it. The uv cache is on the mounted volume so it happens once. If the ClickHouse MCP
times out on a cold machine, restart the container and it will connect.

**Hard-refresh after CSS edits.** The API serves `web/` with normal caching.

**`bench_evaluations` is 1.7 GB in Postgres** from the benchmark.
`DROP TABLE bench_evaluations;` to reclaim it. `clock_evaluations` in ClickHouse holds
127.8M synthetic rows at 3.68 GiB; `make -f Makefile.data reset-evals` rebuilds it
from the real outbox instead.

## What is real and what is not

Real: 1,396,903 rows of DOL OFLC LCA and PERM disclosure data, and every rule
citation. Synthetic: the two personas, and the 127.8M evaluation rows used to
benchmark. That split is deliberate and `clickhouse/bench/RESULTS.md` states it.
