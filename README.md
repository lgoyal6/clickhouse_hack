# Status Clock

Every person on a US work or student visa is running countdowns they cannot see.
Unemployment days. Grace periods. Cap-gap. The 365-day AC21 threshold. The six-year
maximum. Miss one and you lose status, which means losing the job, the apartment, and
often the ability to come back.

The rules move faster than the information about them. Cap-gap moved from September 30
to April 1 under a rule effective 2025-01-17, and a year and a half later most
published guidance still shows the old date.

**Status Clock computes your countdowns against rules that carry effective dates,
shows which version governs your case, and flags the moment the advice you were given
stopped being true.**

The product promise, which is also the design constraint: every number on the screen
traces to a citation and a date.

ClickHouse × Postgres hackathon, KOHO SF. Open track. LibreChat bonus.

---

## Start here

| Read | For |
|---|---|
| [docs/BUILD_SPEC.md](docs/BUILD_SPEC.md) | The design intent of record, as authored. |
| [docs/REVIEW.md](docs/REVIEW.md) | What breaks, in order, with fixes. **Read A1 through A10 before writing code.** |
| [docs/OWNERSHIP.md](docs/OWNERSHIP.md) | Who owns which directories, and why nothing conflicts. |
| [contracts/](contracts/) | The seam. A implements `openapi.yaml`, B consumes it. |

## The split

Two people, two branches, disjoint trees.

```
main                 docs/  contracts/  README.md          both, by agreement only
track/data           db/  clickhouse/  engine/  ingest/  api/      Person A
track/interface      web/  librechat/  agents/                     Person B
```

Person B builds against `contracts/fixtures/` from minute one and never waits for a
database. When A's API comes up, B changes one base URL. Full rules in
[docs/OWNERSHIP.md](docs/OWNERSHIP.md).

```bash
git checkout track/data        # Person A
git checkout track/interface   # Person B
```

## Before you push

```bash
pip install pyyaml jsonschema
python contracts/validate.py
```

Must print `contract green`. It checks that every fixture matches the schema, that
provenance stays required, and that no endpoint has grown a caller-supplied user id.

## Three things not to relitigate

1. **Identity comes from the session, never from a parameter.** A tool signature of
   `get_my_clocks(user_id)` hands a language model the ability to read anyone's
   immigration status. See [docs/REVIEW.md](docs/REVIEW.md) D1.
2. **Provenance is enforced in the tool and response schemas, not in a system
   prompt.** Prompt-level contracts leak, and here a leak means an uncited number in
   front of someone making a decision about staying in the country. See H2.
3. **Replay is a write, not a read.** The rule-change diff needs the engine run twice
   under two rule sets and stamped with a `scenario_id`. Reading old rows back and
   labelling them "under the old rule" returns nothing for a rule that has not taken
   effect yet, which is the exact case the demo uses. See A1.

## Numbers to never invent

`rows_scanned`, `elapsed_ms`, and any wage percentile. The fixtures ship these as
zeroes and placeholders with a `_fixture_note` attached. Fill them from a real run.
A product whose entire pitch is that other people's numbers are stale cannot show a
made-up number on stage.

Unverified rules must render their warning band. `verified` is `false` on every seeded
rule until someone reads the primary source and signs `verified_by`.

## Not legal advice

Stated once in the UI and once in the agent contract. Not repeated, because repetition
reads as fear.
