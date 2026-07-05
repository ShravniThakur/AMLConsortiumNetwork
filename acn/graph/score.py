"""Score candidate subgraphs with the GraphSAGE model.

The trained checkpoint is an *inference* artefact here (never retrained). It was trained on
raw-amount node features, but raw amounts legitimately never reach the graph engine — only fixed
buckets do (the privacy point). So detection-time features are **reconstructed from bucket
midpoints** + graph structure + timestamps + the chain-aware block. To keep normalisation stable,
we run **one forward pass over the whole detect graph** (matching training's per-graph z-scoring)
rather than normalising each candidate subgraph in isolation; a candidate's score is then the max
laundering probability over its nodes.

``torch`` is imported lazily so the pure reconstruction helpers stay importable/testable without it.
"""

from __future__ import annotations

import numpy as np

from ..gnn import graph_build
from ..pseudonymise import buckets

CHECKPOINT = "acn-data/models/gnn/graphsage_final.pt"

_FEATURES = graph_build._SCALAR_FEATURES  # fixed order the model consumes
_N_BUCKETS = buckets.N_BUCKETS


# ---------------------------------------------------------------------------- graph fetch


def fetch_graph(driver, window_start: int, window_end: int) -> dict:
    """Pull the detect-window graph from Neo4j into plain Python for feature reconstruction.

    Returns ``{"nodes": [...], "meta": {hash: {...}}, "edges": [(src, dst, bucket), ...]}`` — only
    pseudonymised fields, so this stays inside the privacy boundary.
    """
    with driver.session() as session:
        nodes = session.run(
            "MATCH (a:Account) WHERE a.first_seen_ts <= $we "
            "RETURN a.hash AS h, a.institution_id AS inst, a.first_seen_ts AS fs",
            we=window_end,
        ).data()
        edges = session.run(
            "MATCH (s:Account)-[e:SENT]->(d:Account) "
            "WHERE e.timestamp >= $ws AND e.timestamp <= $we "
            "RETURN s.hash AS s, d.hash AS d, e.amount_bucket AS b, "
            "e.threshold_proximity AS p, e.timestamp AS t",
            ws=window_start,
            we=window_end,
        ).data()
    meta = {n["h"]: {"institution_id": n["inst"], "first_seen_ts": n["fs"]} for n in nodes}
    return {
        "nodes": [n["h"] for n in nodes],
        "meta": meta,
        # (src, dst, amount_bucket, threshold_proximity, timestamp); reconstruct uses the first 3.
        "edges": [(e["s"], e["d"], e["b"], e["p"], e["t"]) for e in edges],
    }


# ---------------------------------------------------------------- pure feature reconstruction


def reconstruct_features(graph: dict, ref_ts: int) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Rebuild the model's feature matrix from pseudonymised data (pure; no torch/Neo4j).

    Returns ``(nodes, feature_matrix[N,21], edge_index[2,E])`` in the exact column order the
    checkpoint expects (``_SCALAR_FEATURES`` + 10 bucket bins). Per-node scalars are derived from
    a node's **outgoing** edges (as training used sending transactions), amounts via bucket
    midpoints; ``total_in``/``flow_ratio`` use incoming midpoints.
    """
    nodes = graph["nodes"]
    idx = {h: i for i, h in enumerate(nodes)}

    out_amts: dict[int, list[float]] = {}
    out_dst: dict[int, set[int]] = {}
    out_hist: dict[int, np.ndarray] = {}
    in_amt_sum: dict[int, float] = {}
    in_deg: dict[int, int] = {}
    edge_pairs: list[tuple[int, int]] = []

    for edge in graph["edges"]:
        s, d, b = edge[0], edge[1], edge[2]  # tolerant of a 4- or 5-field edge tuple
        if s not in idx or d not in idx:
            continue
        si, di = idx[s], idx[d]
        edge_pairs.append((si, di))
        amt = buckets.bucket_midpoint(b)
        out_amts.setdefault(si, []).append(amt)
        out_dst.setdefault(si, set()).add(di)
        out_hist.setdefault(si, np.zeros(_N_BUCKETS))[int(b.split("_")[1]) - 1] += 1
        in_amt_sum[di] = in_amt_sum.get(di, 0.0) + amt
        in_deg[di] = in_deg.get(di, 0) + 1

    rows = np.zeros((len(nodes), len(_FEATURES) + _N_BUCKETS), dtype=float)
    col = {name: i for i, name in enumerate(_FEATURES)}
    for i, h in enumerate(nodes):
        amts = out_amts.get(i, [])
        txn_count = len(amts)
        first_seen = graph["meta"].get(h, {}).get("first_seen_ts") or ref_ts
        age_days = max(ref_ts - first_seen, 0) / 86400.0
        out_amount = float(sum(amts))
        in_amount = in_amt_sum.get(i, 0.0)

        rows[i, col["is_boundary"]] = 0.0
        rows[i, col["txn_count"]] = txn_count
        rows[i, col["amount_mean"]] = float(np.mean(amts)) if amts else 0.0
        rows[i, col["amount_std"]] = float(np.std(amts)) if len(amts) > 1 else 0.0
        rows[i, col["age_days"]] = age_days
        rows[i, col["velocity_per_day"]] = txn_count / max(age_days, 1.0)
        rows[i, col["new_counterparty_ratio"]] = (
            len(out_dst.get(i, set())) / txn_count if txn_count else 0.0
        )
        rows[i, col["total_in"]] = in_amount
        rows[i, col["flow_ratio"]] = out_amount / (in_amount + 1.0)
        rows[i, col["in_degree"]] = in_deg.get(i, 0)
        rows[i, col["out_degree"]] = txn_count
        if i in out_hist:
            rows[i, len(_FEATURES) :] = out_hist[i]

    if edge_pairs:
        edge_index = np.asarray(edge_pairs, dtype=np.int64).T
    else:
        edge_index = np.zeros((2, 0), dtype=np.int64)
    return nodes, rows, edge_index


# ---------------------------------------------------------------------------- GraphSAGE scoring


def load_model(path: str = CHECKPOINT, device: str = "cpu"):
    """Load the GraphSAGE checkpoint for inference (weights only, eval mode)."""
    import torch

    from ..gnn.model import IN_DIM, GraphSAGE

    model = GraphSAGE(in_dim=IN_DIM).to(device)
    state = torch.load(path, map_location=device)
    model.load_state_dict(state.get("model_state", state) if isinstance(state, dict) else state)
    model.eval()
    return model


def score_graph(
    model, feats: np.ndarray, edge_index: np.ndarray, device: str = "cpu"
) -> np.ndarray:
    """One forward pass over the whole graph → per-node laundering probability [0,1]."""
    import torch

    from ..gnn.model import normalise_features

    if feats.shape[0] == 0:
        return np.zeros(0)
    x = torch.tensor(normalise_features(feats), dtype=torch.float, device=device)
    ei = torch.tensor(edge_index, dtype=torch.long, device=device)
    with torch.no_grad():
        logits = model(x, ei)
        probs = torch.sigmoid(logits).cpu().numpy()
    return probs


def score_candidates(
    candidates: list[dict], nodes: list[str], node_probs: np.ndarray
) -> list[dict]:
    """Attach ``score`` = max node laundering probability over a candidate's evidence nodes."""
    prob = {h: float(node_probs[i]) for i, h in enumerate(nodes)}
    for c in candidates:
        c_nodes = c.get("nodes", [])
        c["score"] = max((prob.get(h, 0.0) for h in c_nodes), default=0.0)
    return candidates
