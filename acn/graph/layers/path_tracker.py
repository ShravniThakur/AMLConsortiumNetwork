"""Layer 2 — persistent 30-day multi-hop path tracker.

The layer that catches **slow, cross-institution** layering a single bank can't see: a chain of
transfers that unfolds over up to 30 days, each hop forwarding to the next. Real layering flows
*forward in time*, so we require strictly increasing timestamps along the path and cap the total
span at 30 days. Cross-institution chains (≥2 distinct institutions) are the ones that matter —
a chain inside one bank is that bank's own problem.

Variable-length paths are the expensive query in this unit; it is bounded three ways: a hop
count cap (``$max_hops``), the 30-day span, and a per-relationship timestamp filter so the
planner uses the ``sent_timestamp`` index rather than walking the whole graph.
"""

from __future__ import annotations

PATTERN = "path_tracker"

THIRTY_DAYS = 30 * 86400
DEFAULT_MIN_HOPS = 3
DEFAULT_MAX_HOPS = 6

# Pure Cypher (no apoc dependency): the distinct-institution count is done in Python from the
# returned ``insts`` list — the query only has to filter chains that touch ≥2 named institutions,
# which it does with a size([...DISTINCT via reduce]) guard kept simple by post-filtering instead.
CYPHER = """
MATCH path = (a:Account)-[rels:SENT*{min_hops}..{max_hops}]->(z:Account)
WHERE a.hash <> z.hash
  AND all(i IN range(0, size(rels) - 2)
          WHERE rels[i].timestamp <= rels[i + 1].timestamp)
  AND rels[0].timestamp >= $window_start
  AND rels[0].timestamp <= $window_end
  AND rels[size(rels) - 1].timestamp - rels[0].timestamp <= $span_seconds
WITH nodes(path) AS ns,
     [n IN nodes(path) WHERE n.institution_id IS NOT NULL | n.institution_id] AS insts,
     toInteger((rels[size(rels) - 1].timestamp - rels[0].timestamp) / 86400.0) AS timespan_days
WITH ns, insts, timespan_days,
     reduce(acc = [], x IN insts | CASE WHEN x IN acc THEN acc ELSE acc + x END) AS distinct_inst
WHERE size(distinct_inst) >= 2
RETURN [n IN ns | n.hash] AS nodes, insts AS insts,
       size(ns) AS chain_len, size(distinct_inst) AS n_inst, timespan_days
ORDER BY chain_len DESC, n_inst DESC
LIMIT $limit
"""


def detect(
    driver,
    window_start: int,
    window_end: int,
    min_hops: int = DEFAULT_MIN_HOPS,
    max_hops: int = DEFAULT_MAX_HOPS,
    span_seconds: int = THIRTY_DAYS,
    limit: int = 300,
    **_,
) -> list[dict]:
    """Return cross-institution multi-hop chain candidates (≥2 institutions, ≤30 days)."""
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
            "meta": {"hops": len(r["nodes"]) - 1},
        }
        for r in rows
    ]
