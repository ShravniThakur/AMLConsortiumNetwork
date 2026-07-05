"""The six Cypher detection layers.

Each layer is one **bounded** Cypher query over the pseudonymised Neo4j graph that surfaces a
known layering signature (mapped to the AMLSim laundering topologies the data is generated from):

1. ``sliding_window``           — rapid in→out through a node (a classic layering hop)
2. ``path_tracker``             — persistent multi-hop chains over up to 30 days, cross-bank (stack)
3. ``round_trip``               — funds returning to their origin via intermediaries (cycle)
4. ``flow_conservation``        — money-in ≈ money-out at a pass-through mule
5. ``coordinated_new_accounts`` — bursts of freshly-seen accounts acting in concert (fan-in/gather)
6. ``fan_out``                  — a funded account scattering to many destinations (fan-out/scatter)

Every layer returns the same candidate shape (a dict), so scoring/routing/alerting treat all
five uniformly::

    {"pattern": str, "nodes": [hash, ...], "institutions": [inst, ...], "meta": {...}}

``institutions`` is the set of non-null ``institution_id`` on the evidence nodes — the input to
targeted routing. Queries are bounded by ``timestamp`` (uses the ``sent_timestamp``
index) and ``LIMIT`` so they stay under the performance budget; they never scan the full graph.
"""

from __future__ import annotations

from . import (
    coordinated_new_accounts,
    fan_out,
    flow_conservation,
    path_tracker,
    round_trip,
    sliding_window,
)

# Ordered so callers can "run all" without hard-coding the list.
ALL_LAYERS = [
    sliding_window,
    path_tracker,
    round_trip,
    flow_conservation,
    coordinated_new_accounts,
    fan_out,
]


def run_all(driver, window_start: int, window_end: int, **kwargs) -> dict[str, list[dict]]:
    """Run every layer over ``[window_start, window_end]``; return ``{pattern: [candidates]}``."""
    out: dict[str, list[dict]] = {}
    for layer in ALL_LAYERS:
        out[layer.PATTERN] = layer.detect(driver, window_start, window_end, **kwargs)
    return out
