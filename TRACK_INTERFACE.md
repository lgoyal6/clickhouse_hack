# track/interface — Person B

You own `web/`, `librechat/`, `agents/`, `Makefile.chat`, and this file. Nothing
else. See `docs/OWNERSHIP.md`.

## First thing

```bash
make -f Makefile.chat verify     # 8 tool-contract tests + the contract check
make -f Makefile.chat web        # then open http://localhost:5173/web/
```

The Clock Wall renders right now, with two personas, no backend, no build step. It
reads `contracts/fixtures/` directly. You are not blocked on Person A at any point.

When A's API is up: set `BASE = 'http://localhost:8000'` in `web/index.html` and
delete the fixture map. That is the only change.

## What is already true

**8 tool-contract tests pass**, and they are the interesting part of this track:

- no tool accepts a `user_id`, `email`, or `subject` argument, and every input
  schema is `additionalProperties: false`, so identity cannot be smuggled in. The
  spec's `get_my_clocks(user_id)` hands a language model the ability to read any
  person's immigration status, employer, and wage (REVIEW D1)
- every rule-bearing tool's output schema requires `citation`, `authority`,
  `effective_from`, `source_url`, and `verified`, so the model physically cannot
  receive an uncited number (REVIEW H2)
- `wage_percentile` requires `n_filings` and `source`, because a percentile over
  eleven filings is not a percentile
- its description states outright that a percentile is not selection odds
  (REVIEW B10)

**Contrast is measured, not eyeballed.** `web/src/styles/tokens.css` carries the
computed ratio for every token in a comment. Two additions were forced by the
measurement: `--rule-text` (#666D62, 4.78:1) for the citation line, because `--rule`
measures 2.90:1 and the spec sets the citation at 11px in it; and `--clear-text`
(#2F6244, 6.37:1) for small tags, because `--clear` is large-text only.

## What is NOT verified

The LibreChat container has never been started. `librechat.yaml` is unrun, the MCP
server in `agents/mcp/status_clock.py` raises `NotImplementedError` on every call,
and the model id needs checking against the current list before you pin it
(REVIEW H1).

## Then, in order

1. **Wire the MCP server.** `agents/mcp/status_clock.py` has the routes and the
   session handling; add the HTTP calls, and **validate each response against the
   tool's own `outputSchema` before returning it**. Validate rather than trust: if
   provenance is missing, raise. That is what makes the contract structural instead
   of aspirational.
2. **Start LibreChat and confirm both MCP servers connect.** The ClickHouse one needs
   `CH_READONLY_PASSWORD` from Person A.
3. **Build Ask.** Full height, reachable from the top nav, not a corner bubble. For
   many users it is the primary interface.
4. **Alert copy as reviewed templates, not runtime translation.** Person A's schema
   has `alert_templates (template_key, locale, headline, detail, reviewed_by)`. Write
   the Spanish for the fixed set and have a person read it. Runtime LLM translation
   is right for open conversation and wrong for the sentence that tells someone a
   deadline is approaching (REVIEW G).
5. **Read the primary sources for E1 and E5.** They are yours because they surface in
   agent copy and on the Standing screen, and whoever writes the sentence should be
   the one who read the source. E1 is the lottery rule, seeded as
   `CITATION REQUIRED`. E5 is whether AC21 §106(a) supports a deadline or only an
   eligibility condition.

## Do not build yet

Timeline, Standing, Rule Detail, and Intake-as-a-screen are deferred. Standing is
blocked on B10: whether the lottery statistic is a wage percentile or a wage level.
Do not draw a screen that makes a numeric claim about someone's odds until that is
settled with Person A.

## Your review findings

F1-F5, H1, H2, G (the translation half), E1, E5.

B8, B9, B10 need a joint decision with Person A first: the canonical clock list,
whether the visa bulletin becomes a clock, and the lottery statistic.
