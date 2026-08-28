# api/

Implements `contracts/openapi.yaml`. This is the only thing Person B talks to.

Two invariants, both structural rather than conventional:

1. **Identity comes from the session cookie, never from a request parameter.** There
   is no route that accepts a user id. The middleware resolves the session to a
   subject UUID and sets the `status_clock.subject` GUC on the connection, so
   Postgres RLS (`db/migrations/0006_rls.sql`) enforces the same boundary a second
   time. See `docs/REVIEW.md` D1.
2. **No response shape lets a number travel without its provenance.** The response
   models make `citation`, `authority`, `effective_from`, and `verified` required.
   See `docs/REVIEW.md` H2.

## Run

```bash
make -f Makefile.data api
```

## Contract check

```bash
python contracts/validate.py
```
