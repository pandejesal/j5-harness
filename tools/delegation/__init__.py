"""Advanced delegation engine (task 4.2).

Stdlib-only Python 3.12 package: decompose tasks into DAGs, track them
via an append-only JSONL ledger, route leaves through router fallback
chains, critique low-confidence leaves, fan out consensus, self-heal.

Shared Zen free-tier key: multi-model fan-out is serialized to
1 in-flight by default. Kilo traffic is excluded (own model).
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
