"""Chain-aware node features — the Cypher layers' path findings, fed to the model.

A 2-layer GraphSAGE only sees a node's 2-hop neighbourhood, so it misses the thin degree-1
pass-through mules whose only signal is *being a link in a long chain*. The Cypher detection layers
already traverse whole chains (``path_tracker`` walks 3–6 hop, ≤30-day, cross-institution paths;
``flow_conservation`` follows money through mules, etc.). This turns their findings into per-node
features so the model can key off long-range structure a local receptive field can't reach.

Crucially these are **label-free**: the layers select on graph *structure and timestamps*, never on
``is_laundering`` — so they are legitimate inputs, not leakage. Coverage is bounded by the layer
candidate caps: a node not in any returned chain gets an all-zero row (bottom of the distribution).
"""

from __future__ import annotations

import numpy as np

from .layers import ALL_LAYERS

# One flag per pattern (fixed order) + four chain-shape scalars. Order is the contract the model's
# feature matrix depends on, so append-only.
PATTERNS = (
    "path_tracker",
    "round_trip",
    "flow_conservation",
    "sliding_window",
    "coordinated_new_accounts",
    "fan_out",
)
FEATURE_NAMES = ("chain_count", "chain_max_hops", "chain_n_patterns", "chain_n_insts") + tuple(
    f"in_{p}" for p in PATTERNS
)
N_CHAIN_FEATURES = len(FEATURE_NAMES)


def compute(
    driver, window_start: int, window_end: int, limit: int = 5000
) -> dict[str, list[float]]:
    """Run every Cypher layer and aggregate its findings into a per-account chain-feature vector.

    Returns ``{account_hash: [chain_count, max_hops, n_patterns, n_insts, in_<pattern>...]}`` for
    accounts that appear in at least one detected chain. ``limit`` caps candidates per layer (higher
    = wider coverage, slower). Deterministic (the layers ``ORDER BY`` + ``LIMIT``).
    """
    counts: dict[str, int] = {}
    max_hops: dict[str, int] = {}
    patterns: dict[str, set[str]] = {}
    max_insts: dict[str, int] = {}

    for layer in ALL_LAYERS:
        try:
            hits = layer.detect(driver, window_start, window_end, limit=limit)
        except TypeError:  # a layer that doesn't take limit
            hits = layer.detect(driver, window_start, window_end)
        for cand in hits:
            hops = cand.get("meta", {}).get("hops", len(cand["nodes"]) - 1)
            n_inst = len(set(cand.get("institutions", [])))
            for h in cand["nodes"]:
                counts[h] = counts.get(h, 0) + 1
                max_hops[h] = max(max_hops.get(h, 0), hops)
                patterns.setdefault(h, set()).add(cand["pattern"])
                max_insts[h] = max(max_insts.get(h, 0), n_inst)

    out: dict[str, list[float]] = {}
    for h, ps in patterns.items():
        out[h] = [
            float(counts[h]),
            float(max_hops[h]),
            float(len(ps)),
            float(max_insts[h]),
            *(1.0 if p in ps else 0.0 for p in PATTERNS),
        ]
    return out


def matrix(nodes: list[str], chain_by_hash: dict[str, list[float]]) -> np.ndarray:
    """Align the per-account chain features to ``nodes`` order; zeros for uncovered accounts."""
    m = np.zeros((len(nodes), N_CHAIN_FEATURES), dtype=float)
    for i, h in enumerate(nodes):
        row = chain_by_hash.get(h)
        if row is not None:
            m[i] = row
    return m


def append(
    nodes: list[str], feats: np.ndarray, chain_by_hash: dict[str, list[float]]
) -> np.ndarray:
    """Concatenate the chain-feature block onto a base feature matrix (as trailing columns)."""
    return np.concatenate([feats, matrix(nodes, chain_by_hash)], axis=1)
