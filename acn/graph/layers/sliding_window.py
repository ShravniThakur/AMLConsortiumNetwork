# ruff: noqa: E501
"""Layer 1 — sliding-window layering hop.

A node that **receives then rapidly forwards** funds within a short window is the classic
single layering hop.
Bounded by ``timestamp`` (index) and a max in→out gap; aggregated per intermediary so each
candidate is one hop's evidence subgraph {senders} → mid → {receivers}.
"""

from __future__ import annotations

PATTERN = "sliding_window"

# Default max seconds between the inbound and outbound leg (2 hours) — a "rapid" forward.
DEFAULT_WINDOW_SECONDS = 2 * 3600

CYPHER = """
MATCH (src:Account)-[s:SENT]->(mid:Account)-[r:SENT]->(dst:Account)
WHERE s.timestamp >= $window_start AND s.timestamp <= $window_end
  AND r.timestamp >= s.timestamp
  AND r.timestamp - s.timestamp <= $window_seconds
  AND src.hash <> dst.hash AND src.hash <> mid.hash AND mid.hash <> dst.hash
WITH mid, collect(DISTINCT src) AS srcs, collect(DISTINCT dst) AS dsts, min(s.timestamp) AS min_ts, max(r.timestamp) AS max_ts  # noqa: E501
WITH [mid] + srcs + dsts AS ns, mid, size(srcs) + size(dsts) AS fan, min_ts, max_ts
RETURN [n IN ns | n.hash] AS nodes,
       [n IN ns WHERE n.institution_id IS NOT NULL | n.institution_id] AS insts,
       mid.hash AS focus, fan AS fan, toInteger((max_ts - min_ts) / 86400.0) AS timespan_days
ORDER BY fan DESC
LIMIT $limit
"""


def detect(
    driver,
    window_start: int,
    window_end: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    limit: int = 500,
    **_,
) -> list[dict]:
    """Return sliding-window hop candidates in ``[window_start, window_end]``."""
    with driver.session() as session:
        rows = session.run(
            CYPHER,
            window_start=window_start,
            window_end=window_end,
            window_seconds=window_seconds,
            limit=limit,
        ).data()
    return [
        {
            "pattern": PATTERN,
            "nodes": r["nodes"],
            "institutions": sorted(set(r["insts"])),
            "meta": {"focus": r["focus"]},
        }
        for r in rows
    ]
