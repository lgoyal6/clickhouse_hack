# Ownership and the split

Two people, two branches, zero shared files after this commit.

The split is enforced by **directory ownership**, not by etiquette. Each track
creates its own top-level directories and never touches the other's. Because the two
branches add disjoint trees on top of the same trunk, they cannot conflict on merge,
and neither person is ever blocked waiting for the other's code to exist.

## Branches

| Branch | Owner | Owns these paths, and only these |
|---|---|---|
| `track/data` | Person A | `db/`, `clickhouse/`, `engine/`, `ingest/`, `api/`, `infra/`, `Makefile.data`, `TRACK_DATA.md` |
| `track/interface` | Person B | `web/`, `librechat/`, `agents/`, `Makefile.chat`, `TRACK_INTERFACE.md` |
| `main` | both, by agreement | `docs/`, `contracts/`, `README.md`, `.gitignore` |

Note the filenames. There is no shared `TRACK.md` and no shared `Makefile`, and the
two compose files live in separate trees (`infra/data.compose.yml` and
`librechat/chat.compose.yml`). Every path in the table above appears on exactly one
branch, which is what makes the merge trivial rather than merely likely to work.

Nothing on `main` is edited during normal work. If a contract has to change, that is
a deliberate commit on `main` touching only `contracts/`, made after both people
agree, and then both branches rebase onto it.

## The seam

The only coupling between the two tracks is `contracts/`:

- `contracts/openapi.yaml` is the HTTP surface. **A implements it. B consumes it.**
- `contracts/clock.schema.json` is the Clock object, including the required
  provenance fields. Every number the UI or the agent renders arrives in this shape.
- `contracts/fixtures/*.json` are real, complete, contract-valid responses for the
  two demo personas.

**B builds entirely against the fixtures from minute one.** No waiting for a
database. When A's API comes up, B flips one base URL and everything already works.
This is the whole reason the contract exists.

## The one shared credential

Person B's LibreChat instance talks to ClickHouse through the ClickHouse MCP server.
That needs a read-only ClickHouse user, which **A provisions** in
`clickhouse/ddl/090_readonly_user.sql` and hands to B as a connection string. That
user must be read-only with a row limit; the agent can compose SQL, and an agent that
can compose SQL against a writable connection is a hole, not a feature.

Everything else in Person B's stack reaches Person A's stack over HTTP at the base
URL in `contracts/openapi.yaml`. B writes no SQL against Postgres. All Postgres
access goes through A's API, which is what keeps identity enforcement (see
`docs/REVIEW.md` §D1) in exactly one place.

## Rules of engagement

1. **Never edit a path you do not own.** If you need something changed on the other
   side, open an issue or say so; do not reach across.
2. **Never edit `main` except to change a contract**, and then only `contracts/`.
3. Branch off your track branch for anything experimental; land back onto your track
   branch, not onto `main`, until integration.
4. Commit in logical units. One commit per meaningful change, each one buildable on
   its own. History on these branches survives the merge, so it should read.
5. When both tracks are green, merge `track/data` into `main` first, then
   `track/interface`. There is nothing to resolve because the trees are disjoint.

## Split of the review work

`docs/REVIEW.md` findings, assigned:

| Findings | Owner |
|---|---|
| A1, A3, A4, A5, A6, A7, A8, A9, A10 | A |
| B1, B2, B3, B4, B5, B6, B7 | A |
| C1 through C7 (all ingestion) | A |
| D1, D3 (identity enforcement lives in A's API) | A |
| A2 (rule resolution; engine side) | A |
| E1 through E5 (primary source verification) | **split: A takes E2, E3, E4; B takes E1, E5** |
| F1 through F5 (design, contrast, copy) | B |
| G (alert templates: schema is A, translations are B) | both, at the seam |
| H1, H2 (agent config and tool schemas) | B |
| B8, B9, B10 (clock inventory and the lottery statistic) | **decide together before either builds** |

E1 and E5 go to B because they are the two rules that surface in agent copy and on the
Standing screen, and because whoever writes the sentence should be the one who read
the source.
