"""Layer 3 — round-trip (funds return to origin).

Money that leaves an account and comes back to it through one or more intermediaries is a
strong laundering signal: the origin ends up whole while the trail is obscured. We look for a
cycle ``(a) -> ... -> (a)`` of 2–5 hops, forward in time, within the window. The origin is the
``focus``; every node on the loop is evidence.
"""

from __future__ import annotations

PATTERN = "round_trip"

DEFAULT_MIN_HOPS = 2
DEFAULT_MAX_HOPS = 5
DEFAULT_SPAN_SECONDS = 7 * 86400  # a returning loop that closes within a week

CYPHER = """
MATCH path = (a:Account)-[rels:SENT*{min_hops}..{max_hops}]->(a)
WHERE all(i IN range(0, size(rels) - 2)
          WHERE rels[i].timestamp <= rels[i + 1].timestamp)
  AND rels[0].timestamp >= $window_start
  AND rels[0].timestamp <= $window_end
  AND rels[size(rels) - 1].timestamp - rels[0].timestamp <= $span_seconds
WITH a, nodes(path) AS ns, rels
RETURN [n IN ns | n.hash] AS nodes,
       [n IN ns WHERE n.institution_id IS NOT NULL | n.institution_id] AS insts,
       a.hash AS focus, size(ns) AS loop_len,
       toInteger((rels[size(rels) - 1].timestamp - rels[0].timestamp) / 86400.0) AS timespan_days
ORDER BY loop_len DESC
LIMIT $limit
"""


def detect(
    driver,
    window_start: int,
    window_end: int,
    min_hops: int = DEFAULT_MIN_HOPS,
    max_hops: int = DEFAULT_MAX_HOPS,
    span_seconds: int = DEFAULT_SPAN_SECONDS,
    limit: int = 300,
    **_,
) -> list[dict]:
    """Return round-trip cycle candidates (funds returning to origin within the window)."""
    cypher = CYPHER.format(min_hops=min_hops, max_hops=max_hops)
    with driver.session() as session:
        rows = session.run(
            cypher,
            window_start=window_start,
            window_end=window_end,
            span_seconds=span_seconds,
            limit=limit,
        ).data()
    return [
        {
            "pattern": PATTERN,
            "nodes": r["nodes"],
            "institutions": sorted(set(r["insts"])),
            "meta": {"focus": r["focus"], "hops": len(r["nodes"]) - 1},
        }
        for r in rows
    ]
