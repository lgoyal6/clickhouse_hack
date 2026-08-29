"""Tool schemas for the Status Clock MCP server.

The citation contract is enforced HERE, in the response schemas, rather than in a
system prompt. docs/BUILD_SPEC.md 6 puts "never state a rule without citation,
authority, and effective date" in the prompt. Prompt-level contracts leak under
pressure, and here a leak means an uncited number reaching someone making a decision
about staying in the country.

Making provenance a required field of every response means the model physically
cannot receive a number without it, so it has nothing uncited to repeat. That is a
structural guarantee and it is one sentence on the architecture slide.
See docs/REVIEW.md H2.

Note what is NOT here: no tool takes a user id. Identity comes from the session that
the MCP server holds. See docs/REVIEW.md D1.
"""

PROVENANCE = {
    "type": "object",
    "required": ["rule_id", "rule_key", "citation", "authority",
                 "effective_from", "source_url", "verified"],
    "properties": {
        "rule_id": {"type": "string"},
        "rule_key": {"type": "string"},
        "citation": {"type": "string"},
        "authority": {"type": "string"},
        "effective_from": {"type": "string"},
        "effective_to": {"type": ["string", "null"]},
        "source_url": {"type": "string"},
        "verified": {
            "type": "boolean",
            "description": "When false, you MUST say the rule is unverified in the "
                           "same breath as the number.",
        },
        "verified_by": {"type": ["string", "null"]},
    },
}

TOOLS = [
    {
        "name": "get_my_clocks",
        "description": (
            "Every active countdown for the signed-in person, with provenance. Takes "
            "no arguments: identity comes from the session, and there is deliberately "
            "no way to ask about another person."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "as_of": {"type": "string", "description": "ISO date. Defaults to today."},
                "locale": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "required": ["as_of", "clocks", "disclaimer"],
            "properties": {
                "as_of": {"type": "string"},
                "clocks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        # provenance is required only for a RUNNING clock. A clock
                        # that has not started has no governing rule to cite, and
                        # requiring one anyway made the agent refuse an entire, valid
                        # response: it saw a non-applicable entry with no citation,
                        # correctly concluded it could not vouch for the payload, and
                        # reported a data-integrity error instead of the clocks. The
                        # contract was right and the schema was too strict.
                        # Mirrors contracts/clock.schema.json.
                        "required": ["clock_key", "label", "severity"],
                        "allOf": [{
                            "if": {"properties": {"applicable": {"const": True}},
                                   "required": ["applicable"]},
                            "then": {"required": ["provenance"]},
                        }],
                        "properties": {
                            "clock_key": {"type": "string"},
                            "label": {"type": "string"},
                            "severity": {"type": "string"},
                            "applicable": {"type": "boolean"},
                            "not_applicable_reason": {"type": ["string", "null"]},
                            "days_remaining": {"type": ["integer", "null"]},
                            "days_consumed": {"type": ["integer", "null"]},
                            "denominator": {"type": ["integer", "null"]},
                            "derived": {"type": "boolean"},
                            "derivation": {"type": ["string", "null"]},
                            "provenance": PROVENANCE,
                            "superseded": {"type": ["object", "null"]},
                        },
                    },
                },
                "disclaimer": {"type": "string"},
            },
        },
    },
    {
        "name": "explain_rule",
        "description": "The governing version of a rule plus its complete version chain.",
        "inputSchema": {
            "type": "object",
            "required": ["rule_key"],
            "properties": {
                "rule_key": {"type": "string"},
                "as_of": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "required": ["rule_key", "governing", "chain"],
            "properties": {
                "rule_key": {"type": "string"},
                "governing": PROVENANCE,
                "chain": {"type": "array", "items": PROVENANCE},
            },
        },
    },
    {
        "name": "check_claim",
        "description": (
            "Check something the user was told against the rule version table. The "
            "useful answer is usually not true or false but 'that was true until "
            "this date'."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["text"],
            "properties": {
                "text": {"type": "string"},
                "rule_key": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "required": ["verdict", "governing_version"],
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["current", "superseded", "never_correct", "no_match"],
                },
                "matched_version": {"type": ["object", "null"]},
                "governing_version": PROVENANCE,
                "superseded_on": {"type": ["string", "null"]},
                "match_confidence": {"type": "number"},
            },
        },
    },
    {
        "name": "wage_percentile",
        "description": (
            "Where an offered wage sits among certified LCA filings for an occupation "
            "and state. This is peer-distribution CONTEXT, not selection odds: the "
            "wage-weighted mechanism is understood to weight by OES wage level, which "
            "is a different number and can point the opposite way. Report n_filings "
            "with every answer."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["soc_code", "state", "wage"],
            "properties": {
                "soc_code": {"type": "string"},
                "state": {"type": "string"},
                "wage": {"type": "number"},
                "fiscal_year": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "required": ["percentile", "n_filings", "source"],
            "properties": {
                "percentile": {"type": "number"},
                "n_filings": {"type": "integer"},
                "quantiles": {"type": "object"},
                "wage_level": {"type": ["integer", "null"]},
                "next_level_wage": {"type": ["number", "null"]},
                "source": {
                    "type": "object",
                    "required": ["dataset", "coverage", "retrieved_at"],
                    "properties": {
                        "dataset": {"type": "string"},
                        "coverage": {"type": "string"},
                        "retrieved_at": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "what_if",
        "description": (
            "Re-run the clocks under a hypothetical rule set. Same code path as the "
            "population rule-change replay: one engine, two scenarios, one diff."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["scenario_id", "clock_key", "overrides"],
            "properties": {
                "scenario_id": {"type": "string"},
                "clock_key": {"type": "string"},
                "overrides": {"type": "object"},
                "as_of": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "required": ["scenario_id", "diffs"],
            "properties": {
                "scenario_id": {"type": "string"},
                "rows_scanned": {"type": "integer"},
                "elapsed_ms": {"type": "number"},
                "diffs": {"type": "array"},
            },
        },
    },
    {
        "name": "record_fact",
        "description": (
            "Write an extracted date and get it back for confirmation. Always show the "
            "user what was written. Never call this with a date they have not confirmed."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["kind", "payload"],
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["status_period", "employment_episode", "gc_milestone", "document"],
                },
                "payload": {"type": "object"},
                "confidence": {
                    "type": "string",
                    "enum": ["document_verified", "user_stated", "inferred"],
                },
                "source_doc_id": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "required": ["id", "kind", "written", "needs_confirmation"],
            "properties": {
                "id": {"type": "string"},
                "kind": {"type": "string"},
                "written": {"type": "object"},
                "needs_confirmation": {"type": "boolean"},
            },
        },
    },
]
