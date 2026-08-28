# Status Clock

Status Clock turns immigration rules and personal dates into visible, cited countdowns.
It answers questions such as:

- How many unemployment days remain during OPT or STEM OPT?
- When does cap-gap work authorization end under the rule that governs this case?
- When must an employer start a PERM or I-140 process for an AC21 extension to remain possible?
- How would a proposed rule change alter a person's clocks?
- Where does an offered wage sit in the real DOL filing corpus, and what OES wage level does it clear?

The product has one hard rule: **every number shown to a user must carry its source,
authority, effective date, and verification state.** If the system cannot support a
number, it returns a warning or no number at all.

Status Clock was built for the ClickHouse x Postgres hackathon at KOHO SF, with
LibreChat used for the conversational interface.

> Status Clock provides information, not legal advice.

## Table of contents

- [Purpose](#purpose)
- [The solution](#the-solution)
- [What the demo shows](#what-the-demo-shows)
- [Architecture](#architecture)
- [How each sponsor is used](#how-each-sponsor-is-used)
  - [Postgres](#postgres)
  - [ClickHouse](#clickhouse)
  - [LibreChat](#librechat)
- [How a clock request works](#how-a-clock-request-works)
- [The seven clocks](#the-seven-clocks)
- [API reference](#api-reference)
- [Agent tools](#agent-tools)
- [Data and provenance model](#data-and-provenance-model)
- [Security model](#security-model)
- [Repository layout](#repository-layout)
- [Quick start: run the Clock Wall](#quick-start-run-the-clock-wall)
- [Run the data stack](#run-the-data-stack)
- [Load the DOL corpus](#load-the-dol-corpus)
- [Run the API and demo](#run-the-api-and-demo)
- [Run LibreChat and Ask](#run-librechat-and-ask)
- [Connect the web UI to the API](#connect-the-web-ui-to-the-api)
- [Verification](#verification)
- [Measured results](#measured-results)
- [Known limits](#known-limits)
- [Development model](#development-model)
- [Further documentation](#further-documentation)
- [Glossary](#glossary)

## Purpose

People on US work and student visas live with deadlines that are easy to miss and
hard to calculate. The inputs are spread across I-20s, EADs, I-797s, I-94 records,
employment history, and government rules. The governing rules also change over time.
A handout can have been correct when it was written and wrong for a case today.

Most existing tools act like disposable calculators. They compute a number from the
facts entered today and discard the history. That makes three important questions
difficult to answer:

1. Did the user's facts change, did the law change, or did one day simply pass?
2. Which version of a rule produced a number?
3. Who becomes newly at risk if a proposed rule takes effect?

Status Clock treats rules, rule versions, citations, effective dates, and prior
evaluations as first-class data. The result is not only a countdown. It is a record
of how that countdown was produced and how it changed.

## The solution

Status Clock combines four pieces:

1. **An effective-dated rule store.** Each rule version has a citation, source URL,
   authority, effective window, typed parameters, verification record, and a link to
   the version it supersedes.
2. **A deterministic clock engine.** Seven clock modules decide whether they apply,
   compute their result, attach provenance, and explain derived arithmetic.
3. **A retained evaluation history.** Actual and hypothetical evaluations are copied
   into ClickHouse with a `scenario_id`, which makes rule-change replay a real
   counterfactual comparison for the same date.
4. **Two user interfaces.** The Clock Wall shows active deadlines and their sources.
   LibreChat guides document intake, answers questions, checks stale advice, and
   queries the wage corpus through constrained tools.

The web track can run against contract fixtures while the data track is offline.
When the API is available, the web client changes one base URL and keeps the same
response shape.

## What the demo shows

The repository includes two separate demo sessions because one person cannot be on
STEM OPT in cap-gap and simultaneously be running H-1B clocks.

| Session | Persona | What it demonstrates |
|---|---|---|
| `sess_maria` | Spanish-speaking STEM OPT worker with a pending H-1B petition | Aggregated hours across concurrent jobs, the unemployment ceiling, cap-gap supersession, localized labels, and clocks that correctly report that they have not started |
| `sess_daniel` | H-1B worker in year five with no PERM or I-140 filing | The derived AC21 filing threshold, H-1B maximum stay, wage standing, and hypothetical rule replay |

The main demo beats are:

- A cap-gap card strikes out the old September 30 date and shows the newer April 1
  date, the supersession date, and 183 days gained.
- Two simultaneous 15-hour jobs count as 30 hours of employment. The engine totals
  hours per day instead of incorrectly treating both jobs as unemployment.
- A proposed reduction in a rule is evaluated by running the same engine twice for
  the same `as_of` date, once as actual and once as a named scenario.
- A wage can be near the middle of peer filings and still clear OES Level III. The
  product keeps peer percentile and wage level separate because they answer
  different questions.
- An unverified lottery rule remains visibly flagged instead of presenting a weak
  citation as settled fact.

## Architecture

```text
                                      +-------------------------+
                                      | DOL OFLC spreadsheets   |
                                      +------------+------------+
                                                   |
                                                   v
+---------------+     +----------------+    +------+-------+
| Clock Wall    |     | LibreChat Ask  |    | Ingest tools |
| web/*.html    |     | localhost:3080 |    +------+-------+
+-------+-------+     +-------+--------+           |
        |                     |                    v
        |                     +-----------> +-----+------+
        |                                  | ClickHouse |
        |                                  | corpus and |
        |                                  | history    |
        |                                  +-----+------+
        |                                        ^
        v                                        |
+-------+-----------------------------------------+------+
| FastAPI                                                     |
| Session identity -> Postgres transaction -> clock engine    |
| -> contract response -> Postgres evaluation outbox          |
+----------------------+---------------------------+-----------+
                       |                           |
                       v                           v
                +------+-------+             +-----+----------+
                | Postgres     |             | Outbox drainer |
                | facts, rules,|             | at-least-once  |
                | alerts, RLS  |             | replication    |
                +--------------+             +----------------+
```

The clock engine does not know about databases. `api/repository.py` converts
Postgres rows into `UserState` and `RuleSet` values, then passes those values to the
engine. This keeps the arithmetic easy to test without running infrastructure.

The API writes clock evaluations to a Postgres outbox in the request transaction.
`api.replicate` drains the outbox into ClickHouse after Postgres commits. This avoids
pretending that one transaction can atomically span Postgres and ClickHouse.

## How each sponsor is used

### Postgres

Postgres is the system of record for facts that can be corrected and facts that must
remain internally consistent.

It stores:

- users and locale preferences;
- uploaded document metadata and confirmed extractions;
- status periods, stacked authorizations, employment episodes, absences, and green
  card milestones;
- effective-dated rule versions and their typed parameter shapes;
- alert templates and alerts;
- the clock evaluation outbox used for replication.

Postgres is used for correctness, not only storage:

- GiST exclusion constraints reject overlapping primary status periods while still
  allowing legal stacked layers such as cap-gap or a pending I-485.
- Foreign keys and uniqueness rules keep the supersession chain from forking.
- A trigger checks that each rule carries the parameters and JSON types registered
  for its `rule_key`.
- Row-level security, abbreviated RLS, limits each application transaction to the
  person resolved from the session cookie.
- The application role is `NOBYPASSRLS`, so the policies are active rather than
  decorative.
- The outbox lands in the same transaction as authoritative application writes.
  Replication can retry without losing an evaluation.

The data stack uses Postgres 17 in `infra/data.compose.yml`.

### ClickHouse

ClickHouse handles workloads that scan or retain many evaluations and filings.

It stores:

- `lca_filings`, the normalized DOL Labor Condition Application corpus;
- `perm_filings` and `visa_bulletin`, which are present but not yet loaded;
- `clock_evaluations`, including actual and hypothetical scenarios;
- `soc_embeddings`, reserved for occupation matching and currently empty.

It also maintains materialized views for:

- wage quantiles by occupation, state, and fiscal year;
- an invertible wage histogram;
- OES wage-level bands based on prevailing wages;
- employer filing profiles;
- population risk counts by date, clock, scenario, and severity.

ClickHouse powers two concrete product features:

1. **Wage standing.** The API runs an exact scan to locate an offer in the certified
   filing distribution, returns the sample size, then compares the offer with
   prevailing-wage level bands.
2. **Rule-change replay.** Actual and scenario evaluations for the same person and
   date are joined by `user_id`. The result shows days lost and newly critical users.

The schema normalizes case status, SOC code spellings, offered-wage units, and
prevailing-wage units at load time. Unknown units fail closed to `NULL` and are
excluded. Twelve data-quality queries make silent failures visible before the API
uses the corpus.

LibreChat receives a separate ClickHouse user named `chat_readonly`. That user can
query aggregate and corpus tables, has row and time limits, and cannot read private
`clock_evaluations`.

### LibreChat

LibreChat is the conversational product surface. It is not used as a decorative
chat bubble.

The configuration provides:

- a full-height Ask experience at `web/ask.html`;
- multi-file upload support for I-20s, EADs, I-797s, I-94 records, PDFs, and images;
- a Supervisor prompt that routes work to Intake, Clock, Corpus, or Verify;
- the Status Clock MCP server for session-scoped API calls;
- the official ClickHouse MCP server through a read-only database account;
- MongoDB for LibreChat state and Meilisearch for its own search features.

MCP means Model Context Protocol. The local Status Clock MCP server exposes six
closed-schema tools. It keeps the session cookie itself, so the model cannot choose a
different `user_id`. Every API response is validated against the tool's output
schema before the model receives it.

The agent prompts divide work by failure mode:

- **Intake** extracts and confirms dates one question at a time.
- **Clock** reports computed evaluations and never performs its own legal arithmetic.
- **Corpus** reports exact database results, sample size, and the limits of each
  statistic.
- **Verify** matches something a user was told to the rule version chain.
- **Supervisor** chooses one of those agents and enforces citation behavior on the
  final answer.

## How a clock request works

1. The browser or MCP server calls `GET /v1/clocks` with the `sc_session` cookie.
2. FastAPI resolves the cookie to a subject. No caller-supplied user identifier is
   accepted.
3. `subject_tx()` starts a Postgres transaction and sets the transaction-local
   `status_clock.subject` setting.
4. Postgres RLS limits every person-owned table to that subject.
5. The repository builds `UserState` and loads the complete effective-dated
   `RuleSet`.
6. The engine calls `applies()` and `compute()` for all seven clocks.
7. Each running clock receives its governing rule, provenance, input hash, engine
   version, severity, and optional derivation.
8. The API compares the result with the previous evaluation to distinguish
   `facts_changed`, `law_changed`, and `time_passed`.
9. All evaluations, including not-applicable clocks, are written to the Postgres
   outbox.
10. The API serializes the contract response. A running clock with incomplete
    provenance becomes a server error instead of an uncited number.
11. The outbox drainer copies committed evaluations to ClickHouse and only then
    stamps them as replicated.

## The seven clocks

Every module exposes `applies(state, as_of)` and `compute(state, as_of, ruleset)`.

| Clock key | Question answered | Important inputs |
|---|---|---|
| `opt_unemployment` | How many unemployment days have been consumed and how many remain? | EAD window, STEM status, employment dates, total hours across employers, 90-day rule, 60-day STEM addition |
| `cap_gap_window` | When does cap-gap authorization end under the governing rule? | Cap-gap status, fiscal-year boundary, current and prior `cap_gap_end` rules |
| `h1b_grace_period` | How much of the post-employment grace period remains? | H-1B status, final employment date, grace-period rule |
| `ac21_365` | By what derived date must a qualifying process have started for the 365-day threshold? | H-1B first entry, existing PERM or I-140 milestones, AC21 threshold |
| `i485_portability` | When does an I-485 become portable under the configured threshold? | I-485 filing milestone and portability rule |
| `h1b_max_stay` | When does the six-year H-1B maximum end? | First H-1B entry, recorded absences, maximum-stay rule |
| `opt_filing_window` | When does the OPT filing window open and close? | Program end date, before/after offsets, separate I-20 recommendation window |

Not-applicable clocks remain in the API response with a reason. The UI renders them
in a quiet secondary list instead of displaying zero, which would mean something
different.

## API reference

The data branch exposes eight routes. The six `/v1` routes defined in
`contracts/openapi.yaml` form the shared Person A and Person B contract.

| Method | Path | Purpose | Current state |
|---|---|---|---|
| `GET` | `/v1/clocks` | Compute all clocks for the signed-in person | Implemented end to end |
| `GET` | `/v1/rules/{rule_key}` | Return the governing rule and full version chain | Implemented |
| `POST` | `/v1/scenarios/replay` | Run actual and hypothetical rule sets for the same date | Implemented for one signed-in subject |
| `POST` | `/v1/facts` | Write a confirmed intake fact | Only `status_period` is wired |
| `POST` | `/v1/claims/check` | Compare advice with the rule version table | Returns a fixture with an explicit warning |
| `GET` | `/v1/corpus/wage-percentile` | Return exact peer percentile, sample size, and wage-level context | Implemented against ClickHouse |
| `GET` | `/v1/standing` | Read the signed-in person's job under RLS and compute wage standing | Implemented in the API; still needs addition to the shared OpenAPI file |
| `GET` | `/healthz` | Report API and corpus availability | Implemented in the API; operational route, not part of the product contract |

Authentication in the demo uses the `sc_session` cookie. The two recognized values
are `sess_maria` and `sess_daniel`.

## Agent tools

The Status Clock MCP server maps six tools to the shared API.

| Tool | API route | Use |
|---|---|---|
| `get_my_clocks` | `GET /v1/clocks` | Read the signed-in person's clocks |
| `explain_rule` | `GET /v1/rules/{rule_key}` | Read one governing rule and its prior versions |
| `check_claim` | `POST /v1/claims/check` | Check stale or conflicting advice |
| `wage_percentile` | `GET /v1/corpus/wage-percentile` | Query peer wage distribution and wage-level context |
| `what_if` | `POST /v1/scenarios/replay` | Re-run clocks under hypothetical rule parameters |
| `record_fact` | `POST /v1/facts` | Store a confirmed intake fact |

The input schemas are closed with `additionalProperties: false`. No tool accepts
`user_id`, email, or another subject selector. Numeric rule-bearing responses require
provenance fields in their schemas.

## Data and provenance model

### Personal facts

Postgres keeps personal records in separate tables instead of one untyped JSON blob.
That allows constraints to reject impossible states while still representing legal
overlap.

`status_periods.layer` has three values:

- `primary` for statuses such as F-1, STEM OPT, and H-1B;
- `authorization` for stacked periods such as cap-gap and grace;
- `pending` for a filing such as adjustment of status.

Employment hours are summed across concurrent episodes per day. Absences are stored
because H-1B maximum-stay calculations can recapture time spent outside the country.

### Rules

A rule version contains:

- `rule_key` and typed `params`;
- `effective_from` and optional `effective_to`;
- `citation`, `source_url`, and `authority`;
- `supersedes`, pointing to the prior version;
- `verified_by` and `verified_at`, which must be filled together.

Rule parameter shapes are registered separately and validated by a trigger. A rule
with a missing or wrongly typed parameter is rejected during migration or update.

### Evaluations

Every evaluation records:

- the date it was computed for and the time it was computed;
- person, clock, and `scenario_id`;
- applicability and the reason a clock is not running;
- days remaining or consumed, denominator, and severity;
- rule identity and effective date;
- an input hash containing facts but not calendar time or rule parameters;
- engine version.

Keeping the fact hash separate from the rule identity is what lets the API tell
whether facts changed, law changed, or time passed.

### Derived values

Some useful deadlines do not appear verbatim in a regulation. The AC21 clock is the
clearest example. In those cases, the response sets `derived: true`, shows the
arithmetic in `derivation`, and cites the underlying rule for the input rather than
claiming that the final date was printed in the source.

## Security model

The repository treats immigration status, employer, and wage as sensitive personal
data.

The main controls are:

- Identity comes from the session, never from a model-controlled parameter.
- FastAPI binds the subject to a transaction-local Postgres setting.
- Postgres RLS enforces the subject boundary on users, documents, statuses,
  employment, absences, milestones, alerts, and the outbox.
- The API connects as a role that cannot bypass RLS and cannot modify rules.
- Rules and tool responses require provenance in code and schemas.
- The MCP server validates API output before returning it to LibreChat.
- LibreChat's ClickHouse account is read-only and cannot access private evaluation
  history.
- Query parameters use ClickHouse typed substitution instead of SQL string
  interpolation.
- Fixture identities are invalid external identities and use `.invalid` email
  addresses.

The demo session map is not a production authentication system. It shows the shape
of session-derived identity while keeping user selection out of tool arguments.

## Repository layout

```text
.
|-- agents/                 Status Clock MCP server, tool schemas, and tests
|-- api/                    FastAPI routes, Postgres repository, ClickHouse client,
|                           and outbox replication
|-- clickhouse/
|   |-- ddl/                Corpus, evaluation, view, projection, and user DDL
|   `-- queries/            Exact percentile, wage level, replay, and quality SQL
|-- contracts/              OpenAPI contract, clock JSON Schema, fixtures, validator
|-- db/
|   |-- migrations/         Postgres tables, constraints, rule checks, RLS, app role
|   `-- seeds/              Rule shapes, rules, demo personas, verification sign-off
|-- docs/                   Build intent, review findings, and ownership rules
|-- engine/                 Database-free rule resolution and seven clock modules
|-- ingest/                 DOL header audit, spreadsheet conversion, and loader
|-- infra/                  Postgres and ClickHouse Docker Compose stack
|-- librechat/              LibreChat config, agent prompts, and chat Compose stack
|-- web/                    Clock Wall, Ask page, design tokens, and card styles
|-- Makefile.data           Person A commands
|-- Makefile.chat           Person B commands
|-- TRACK_DATA.md           Data-track status and measured results
`-- TRACK_INTERFACE.md      Interface-track status and remaining work
```

The project began on two branches with disjoint ownership so both tracks could move
without merge conflicts. The final main branch is expected to contain both trees.

## Quick start: run the Clock Wall

The fastest visible result uses checked-in fixtures and needs no database or build
step.

```bash
make -f Makefile.chat web
```

Open [http://localhost:5173/web/](http://localhost:5173/web/). Switch between
`sess_maria` and `sess_daniel` to see different applicable clocks.

If `make` is unavailable, run the underlying command from the repository root:

```bash
python3 -m http.server 5173
```

## Run the data stack

### Prerequisites

- Docker with Docker Compose
- Python 3 and `pip`
- GNU Make
- `psql`
- `curl` for corpus downloads

Install Python dependencies and start Postgres and ClickHouse:

```bash
make -f Makefile.data deps
make -f Makefile.data up
make -f Makefile.data migrate
make -f Makefile.data seed
make -f Makefile.data ch-ddl
```

The default local passwords are `devonly`. Copy `infra/.env.example` to
`infra/.env` before changing them.

Before applying `clickhouse/ddl/090_readonly_user.sql`, replace
`{{CH_READONLY_PASSWORD}}` with the password that LibreChat will use. Store the same
value as `CH_READONLY_PASSWORD` in `librechat/.env`.

The order matters. ClickHouse materialized views only receive rows inserted after
the views exist, so `ch-ddl` must run before `load` or `corpus`.

## Load the DOL corpus

The full convenience target downloads, converts, loads, and checks FY2024 Q4 and
FY2025 Q4 LCA disclosure files:

```bash
make -f Makefile.data corpus
```

Expect a download of roughly 155 MB and several minutes of conversion time.

To inspect one fiscal year step by step:

```bash
make -f Makefile.data fetch FY=2025
make -f Makefile.data convert FY=2025
make -f Makefile.data load FY=2025
make -f Makefile.data quality
```

The loader performs a dry run before insertion. It checks headers, prints the wage
unit distribution, refuses files with too many unknown units, and refuses to load if
the required materialized views do not exist.

## Run the API and demo

Start FastAPI:

```bash
make -f Makefile.data api
```

The API listens on [http://localhost:8000](http://localhost:8000). Check health:

```bash
curl http://localhost:8000/healthz
```

Print both demo personas directly from the API:

```bash
make -f Makefile.data demo
```

Generate evaluations, then copy the committed outbox rows into ClickHouse:

```bash
make -f Makefile.data replicate
```

For a polling drainer instead of a single pass:

```bash
python -m api.replicate --watch 5
```

## Run LibreChat and Ask

Install the interface dependencies:

```bash
pip install -r agents/requirements.txt
```

Create the local environment file:

```bash
cp librechat/.env.example librechat/.env
```

Fill in:

- `ANTHROPIC_API_KEY` for the configured model provider;
- `CH_READONLY_PASSWORD`, matching the ClickHouse `chat_readonly` account;
- `MEILI_MASTER_KEY`, which defaults to `devonly` for local work.

Start LibreChat, MongoDB, and Meilisearch:

```bash
make -f Makefile.chat up
```

Open [http://localhost:3080](http://localhost:3080), or serve the web directory and
visit [http://localhost:5173/web/ask.html](http://localhost:5173/web/ask.html).

`ask.html` embeds LibreChat in a full-height frame. Whether a particular LibreChat
image permits framing depends on its response headers. The page includes a direct
link to port 3080 as a fallback.

## Connect the web UI to the API

`web/index.html` runs in fixture mode by default:

```js
const BASE = null;
```

After FastAPI is running, change it to:

```js
const BASE = 'http://localhost:8000';
```

Then remove the fixture map. The UI already consumes the contract response shape,
so the rendering path does not otherwise change. If the UI and API run on different
origins, configure CORS in FastAPI before making browser requests.

## Verification

### Shared contract

```bash
python contracts/validate.py
```

Expected output:

```text
contract green
```

The validator checks fixture compatibility, required provenance, and the absence of
caller-supplied identity parameters.

### Data and API track

After `up`, `migrate`, `seed`, and `ch-ddl`:

```bash
make -f Makefile.data verify
make -f Makefile.data quality
```

Run only the database-free engine tests with:

```bash
make -f Makefile.data test
```

### Interface and agent track

```bash
pip install -r agents/requirements.txt
make -f Makefile.chat verify
python -m agents.mcp.status_clock --list
```

The tool-contract tests check closed input schemas, session-only identity,
provenance requirements, sample size for wage statistics, and route coverage.

## Measured results

The latest data-track verification record reports:

| Check | Recorded result |
|---|---|
| Postgres migrations | `0001` through `0007` applied cleanly on Postgres 17 |
| Rule data | 13 versions, 2 supersession chains, 12 verified and 1 deliberately flagged |
| Clock engine | All 7 clocks implemented |
| DOL corpus | 239,477 loaded rows, 216,775 certified, FY2024 Q4 and FY2025 Q4 |
| Software Developer example | 5,991 California filings in FY2025 |
| Exact wage scan | About 20 to 45 ms in the recorded local run |
| Evaluation history | 56 rows across 3 dates and 3 scenarios in the recorded demo |
| Engine tests | 39 passing in the data-track record |
| API tests | 47 passing against real Postgres, ClickHouse, and routes |
| Interface tests | 8 tool-contract tests defined on the interface track |
| Data-quality checks | 12 SQL gates recorded as passing |

These values describe the recorded hackathon environment. Re-run the commands above
before presenting them as results from another machine.

## Known limits

The repository states these limits directly so a demo does not imply more than the
code supports:

- `/v1/claims/check` still returns a fixture and an explicit warning.
- Population replay has not been measured at the proposed 50,000-user scale. The
  current route reports a real one-person timing, not a population benchmark.
- The outbox drainer provides change data capture behavior. PeerDB has not been
  attempted.
- Alerts have tables and delivery fields, but generation and delivery are not wired.
- PERM filings and Visa Bulletin tables exist but are empty.
- `soc_embeddings` exists but no embedding job has run.
- The corpus contains only Q4 files for two fiscal years.
- The 2026 wage-weighted lottery rule remains unverified because its seeded citation
  is incomplete. The warning is intentional.
- `record_fact` currently writes only `status_period` facts.
- The Standing and health routes are implemented but not yet represented in the
  shared OpenAPI contract.
- The Clock Wall still defaults to fixtures until `BASE` is changed.
- The LibreChat container, MCP connections, and Ask iframe must be verified in the
  final merged environment.
- The demo session map is not production authentication.
- Status Clock is informational software, not a substitute for legal advice.

## Development model

The hackathon work was split by directory ownership:

| Branch | Owner | Directories |
|---|---|---|
| `track/data` | Person A | `db/`, `clickhouse/`, `engine/`, `ingest/`, `api/`, and `infra/data.compose.yml` |
| `track/interface` | Person B | `web/`, `librechat/`, `agents/`, and `Makefile.chat` |
| `main` | Shared by agreement | `docs/`, `contracts/`, and this README |

The shared contract allowed Person B to build against fixtures without waiting for
Person A's services. The two Docker Compose stacks do not share files, networks, or
volumes. LibreChat reaches the API and read-only ClickHouse user through the host.

Before changing an API or clock response:

1. Update `contracts/openapi.yaml` or `contracts/clock.schema.json`.
2. Update or add a fixture.
3. Run `python contracts/validate.py`.
4. Update the implementing API and consuming interface.
5. Run both track verification commands.

## Further documentation

| Document | Purpose |
|---|---|
| [`docs/BUILD_SPEC.md`](docs/BUILD_SPEC.md) | Original product and architecture intent |
| [`docs/REVIEW.md`](docs/REVIEW.md) | Correctness, security, data, design, and scope findings |
| [`docs/OWNERSHIP.md`](docs/OWNERSHIP.md) | Branch boundaries and integration contract |
| [`contracts/README.md`](contracts/README.md) | Shared schema and fixture workflow |
| [`contracts/openapi.yaml`](contracts/openapi.yaml) | HTTP contract |
| [`contracts/clock.schema.json`](contracts/clock.schema.json) | Clock response schema |
| [`TRACK_DATA.md`](TRACK_DATA.md) | Data-track status, measurements, and remaining work |
| [`TRACK_INTERFACE.md`](TRACK_INTERFACE.md) | Interface-track status and remaining work |
| [`api/README.md`](api/README.md) | API invariants and run command |
| [`ingest/README.md`](ingest/README.md) | DOL corpus pipeline and verified source quirks |
| [`web/README.md`](web/README.md) | Clock Wall behavior and accessibility choices |

## Glossary

| Term | Meaning in this project |
|---|---|
| AC21 | The American Competitiveness in the Twenty-First Century Act, used here for extension and portability thresholds |
| CDC | Change data capture, the process that copies committed Postgres changes into ClickHouse |
| EAD | Employment Authorization Document |
| LCA | Labor Condition Application disclosure data published by the US Department of Labor |
| MCP | Model Context Protocol, used to expose constrained tools to LibreChat |
| OES wage level | A prevailing-wage tier from I through IV; distinct from a percentile among peer offers |
| OPT | Optional Practical Training for eligible F-1 students |
| Provenance | The citation, authority, effective dates, source URL, and verification state behind a result |
| Replay | A second engine run for the same date with different rule parameters and a distinct `scenario_id` |
| RLS | Postgres row-level security, used to restrict each transaction to one signed-in subject |
| SOC code | Standard Occupational Classification code used to group occupations in the wage corpus |
