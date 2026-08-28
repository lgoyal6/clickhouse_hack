"""Status Clock engine.

A pure function over user state plus a resolved rule set. The only side effect is
an append to the evaluation outbox, which happens in the caller, not here, so the
whole engine is testable without a database.
"""

ENGINE_VERSION = "0.1.0"
