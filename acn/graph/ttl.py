"""TTL pruning to keep the graph bounded.

Detection queries stay under the performance budget only if the graph doesn't grow without
limit, so edges and orphaned accounts inactive past the TTL are pruned. Two hard exceptions,
enforced here: an account ``under_investigation`` and its edges are **never** pruned (that would
destroy live evidence), and nothing is pruned inside the
window still being detected on. This is a scheduled batch job, not a per-write hook.
"""

from __future__ import annotations

NINETY_DAYS = 90 * 86400


# Delete SENT edges older than the cutoff, but keep any edge touching an account still under
# investigation — its evidence subgraph must survive until an officer closes the case.
_PRUNE_EDGES = """
MATCH (s:Account)-[e:SENT]->(d:Account)
WHERE e.timestamp < $cutoff
  AND coalesce(s.under_investigation, false) = false
  AND coalesce(d.under_investigation, false) = false
WITH e LIMIT $batch
DELETE e
RETURN count(e) AS n
"""

# Remove accounts left with no edges, first seen before the cutoff, not under investigation.
_PRUNE_ORPHANS = """
MATCH (a:Account)
WHERE NOT (a)-[:SENT]-()
  AND coalesce(a.first_seen_ts, 0) < $cutoff
  AND coalesce(a.under_investigation, false) = false
WITH a LIMIT $batch
DELETE a
RETURN count(a) AS n
"""


def _drain(session, cypher: str, **params) -> int:
    """Run a batched delete repeatedly until it stops removing rows; return the total."""
    total = 0
    while True:
        n = session.run(cypher, **params).single()["n"]
        total += n
        if n == 0:
            break
    return total


def prune(driver, now_ts: int, ttl_seconds: int = NINETY_DAYS, batch: int = 5000) -> dict:
    """Prune edges/orphans older than ``now_ts - ttl_seconds``; return the counts removed."""
    cutoff = now_ts - ttl_seconds
    with driver.session() as session:
        edges = _drain(session, _PRUNE_EDGES, cutoff=cutoff, batch=batch)
        orphans = _drain(session, _PRUNE_ORPHANS, cutoff=cutoff, batch=batch)
    return {"cutoff": cutoff, "edges_pruned": edges, "accounts_pruned": orphans}
