"""Layer 4 — flow conservation (pass-through mule).

A mule forwards almost exactly what it receives: money-in ≈ money-out. This layer only works
because every institution used the **same fixed amount buckets** — so we can compare
in- vs out-flow across institutions using a shared per-bucket midpoint (``buckets.bucket_midpoint``)
as the amount proxy. Raw amounts never reach Neo4j; the midpoint is a fixed stand-in, and the
comparison is a ratio, so the approximation cancels on both sides.

A node is flagged with enough in/out flow in the window and ``|out - in| <= tolerance * in``.
"""

from __future__ import annotations

from ...pseudonymise import buckets

PATTERN = "flow_conservation"

DEFAULT_TOLERANCE = 0.15  # out within ±15% of in
DEFAULT_MIN_TXNS = 2

# bucket label -> representative amount, passed to Cypher so the sum happens in-database.
_MIDS = {
    f"bucket_{i}": buckets.bucket_midpoint(f"bucket_{i}") for i in range(1, buckets.N_BUCKETS + 1)
}

CYPHER = """
MATCH (src:Account)-[i:SENT]->(mid:Account)
WHERE i.timestamp >= $window_start AND i.timestamp <= $window_end
WITH mid, sum($mids[i.amount_bucket]) AS in_amt, count(i) AS in_cnt, collect(DISTINCT src) AS srcs
MATCH (mid)-[o:SENT]->(dst:Account)
WHERE o.timestamp >= $window_start AND o.timestamp <= $window_end
WITH mid, in_amt, in_cnt, srcs,
     sum($mids[o.amount_bucket]) AS out_amt, count(o) AS out_cnt, collect(DISTINCT dst) AS dsts
WHERE in_cnt >= $min_txns AND out_cnt >= $min_txns AND in_amt > 0
  AND abs(out_amt - in_amt) <= $tolerance * in_amt
WITH [mid] + srcs + dsts AS ns, mid, in_amt, out_amt, in_cnt + out_cnt AS fan
RETURN [n IN ns | n.hash] AS nodes,
       [n IN ns WHERE n.institution_id IS NOT NULL | n.institution_id] AS insts,
       mid.hash AS focus, in_amt AS in_amt, out_amt AS out_amt, fan AS fan
ORDER BY fan DESC
LIMIT $limit
"""


def detect(
    driver,
    window_start: int,
    window_end: int,
    tolerance: float = DEFAULT_TOLERANCE,
    min_txns: int = DEFAULT_MIN_TXNS,
    limit: int = 500,
    **_,
) -> list[dict]:
    """Return pass-through candidates where money-in ≈ money-out within the window."""
    with driver.session() as session:
        rows = session.run(
            CYPHER,
            window_start=window_start,
            window_end=window_end,
            tolerance=tolerance,
            min_txns=min_txns,
            mids=_MIDS,
            limit=limit,
        ).data()
    return [
        {
            "pattern": PATTERN,
            "nodes": r["nodes"],
            "institutions": sorted(set(r["insts"])),
            "meta": {"focus": r["focus"], "in_amt": r["in_amt"], "out_amt": r["out_amt"]},
        }
        for r in rows
    ]
