"""Layer 6 — fan-out / scatter dispersion.

One of the AMLSim laundering topologies the other five layers don't cover: an account **receives**
illicit funds and then **scatters** them out to many distinct destinations in a short window — the
classic dispersion step that breaks one traceable flow into many small ones. It is the mirror of
``coordinated_new_accounts`` (fan-in / gather): here a single source fans *out*.

To separate laundering dispersion from an ordinary high-out-degree account (payroll, a merchant
paying suppliers), the source must **also have received** funds in the window — i.e. it is passing
received money onward, not originating its own payments. Bounded by the ``sent_timestamp`` index and
``LIMIT`` like the other layers.
"""

from __future__ import annotations

PATTERN = "fan_out"

DEFAULT_MIN_FANOUT = 5  # scatter to at least this many distinct destinations

CYPHER = """
MATCH (src:Account)-[out:SENT]->(dst:Account)
WHERE out.timestamp >= $window_start AND out.timestamp <= $window_end
WITH src, collect(DISTINCT dst) AS dsts
WHERE size(dsts) >= $min_fanout
MATCH (funder:Account)-[in:SENT]->(src)
WHERE in.timestamp >= $window_start AND in.timestamp <= $window_end
WITH src, dsts, count(DISTINCT funder) AS n_funders
WHERE n_funders >= 1
WITH [src] + dsts AS ns, src, size(dsts) AS fanout, n_funders
RETURN [n IN ns | n.hash] AS nodes,
       [n IN ns WHERE n.institution_id IS NOT NULL | n.institution_id] AS insts,
       src.hash AS focus, fanout AS fanout, n_funders AS n_funders
ORDER BY fanout DESC
LIMIT $limit
"""


def detect(
    driver,
    window_start: int,
    window_end: int,
    min_fanout: int = DEFAULT_MIN_FANOUT,
    limit: int = 300,
    **_,
) -> list[dict]:
    """Return sources that received funds and then scattered them to many distinct destinations."""
    with driver.session() as session:
        rows = session.run(
            CYPHER,
            window_start=window_start,
            window_end=window_end,
            min_fanout=min_fanout,
            limit=limit,
        ).data()
    return [
        {
            "pattern": PATTERN,
            "nodes": r["nodes"],
            "institutions": sorted(set(r["insts"])),
            "meta": {"focus": r["focus"], "fanout": r["fanout"], "n_funders": r["n_funders"]},
        }
        for r in rows
    ]
