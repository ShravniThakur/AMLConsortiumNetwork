"""Layer 5 — coordinated new accounts.

Mule networks spin up clusters of fresh accounts that act in concert — typically funnelling
into a common target within days of being created. This layer flags a hub that receives from
several accounts **all first seen within a short burst** of each other. ``first_seen_ts`` is set
at ingest (earliest edge, or an ``account_opening`` event) and read via the ``account_first_seen``
index; the burst window keeps this from firing on ordinary shared counterparties.
"""

from __future__ import annotations

PATTERN = "coordinated_new_accounts"

DEFAULT_MIN_CLUSTER = 3
DEFAULT_BURST_SECONDS = 3 * 86400  # all accounts created within a 3-day burst

CYPHER = """
MATCH (new:Account)-[e:SENT]->(target:Account)
WHERE new.first_seen_ts >= $window_start AND new.first_seen_ts <= $window_end
  AND e.timestamp >= $window_start AND e.timestamp <= $window_end
WITH target, collect(DISTINCT new) AS newbies, min(e.timestamp) AS min_ts, max(e.timestamp) AS max_ts
WITH target, newbies, [n IN newbies | n.first_seen_ts] AS fs, min_ts, max_ts
WHERE size(newbies) >= $min_cluster
  AND reduce(mx = -1, x IN fs | CASE WHEN x > mx THEN x ELSE mx END)
      - reduce(mn = 9999999999, x IN fs | CASE WHEN x < mn THEN x ELSE mn END) <= $burst_seconds
WITH [target] + newbies AS ns, target, size(newbies) AS cluster_size, min_ts, max_ts
RETURN [n IN ns | n.hash] AS nodes,
       [n IN ns WHERE n.institution_id IS NOT NULL | n.institution_id] AS insts,
       target.hash AS focus, cluster_size AS cluster_size,
       toInteger((max_ts - min_ts) / 86400.0) AS timespan_days
ORDER BY cluster_size DESC
LIMIT $limit
"""


def detect(
    driver,
    window_start: int,
    window_end: int,
    min_cluster: int = DEFAULT_MIN_CLUSTER,
    burst_seconds: int = DEFAULT_BURST_SECONDS,
    limit: int = 300,
    **_,
) -> list[dict]:
    """Return clusters of newly-seen accounts funnelling into a common target within a burst."""
    with driver.session() as session:
        rows = session.run(
            CYPHER,
            window_start=window_start,
            window_end=window_end,
            min_cluster=min_cluster,
            burst_seconds=burst_seconds,
            limit=limit,
        ).data()
    return [
        {
            "pattern": PATTERN,
            "nodes": r["nodes"],
            "institutions": sorted(set(r["insts"])),
            "meta": {"focus": r["focus"], "cluster_size": r["cluster_size"]},
        }
        for r in rows
    ]
