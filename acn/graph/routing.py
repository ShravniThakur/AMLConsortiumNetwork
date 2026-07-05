"""Targeted alert routing.

An alert reveals that specific accounts — and therefore specific institutions — are under
suspicion. Broadcasting it would tell uninvolved banks that *someone* has at-risk accounts,
leaking exactly what the system protects. So an alert is delivered **only** to the institutions
whose accounts appear in its evidence subgraph.

This module is pure (no Kafka/Neo4j) so the "who is involved" computation — the load-bearing,
must-be-correct step calls out — is unit-testable in isolation. ``institutions`` on a
candidate is the set of non-null ``institution_id`` on its evidence nodes; a node with no known
owner (a hash only ever seen as a *destination*, never published as a sender) contributes no
recipient, which is correct — no institution has claimed it.
"""

from __future__ import annotations


def involved_institutions(candidate: dict) -> list[str]:
    """The institutions whose accounts appear in the candidate's evidence (sorted, unique)."""
    return sorted(set(candidate.get("institutions", [])))


def route(candidate: dict) -> list[str]:
    """Recipients for this candidate's alert — its involved institutions and no one else."""
    recipients = involved_institutions(candidate)
    assert_targeted(recipients, candidate)
    return recipients


def assert_targeted(recipients: list[str], candidate: dict) -> None:
    """Fail loudly if routing would deliver to an institution not present in the evidence.

    A broadcast (or any superset of the involved set) is a privacy violation, so this
    is a stop-the-line guard, not a warning. An empty recipient set is also refused: an alert
    nobody can act on means the evidence has no owned account and should not have been raised.
    """
    involved = set(involved_institutions(candidate))
    extra = set(recipients) - involved
    if extra:
        raise ValueError(f"alert routed to uninvolved institutions (broadcast leak): {extra}")
    if not recipients:
        raise ValueError("alert has no involved institution — refusing to route it")
