"""Score candidate subgraphs with the DirMultigraphSAGE model.

Detection-time feature reconstruction mirrors training exactly:
  - Node features rebuilt from bucket midpoints + graph structure (same as training).
  - Edge features built per directed edge (amount bucket → midpoint + one-hot,
    threshold_proximity flag, time-delta from window start) — **all parallel edges
    kept** so the multigraph structure the model was trained on is preserved.
  - One forward pass over the whole detect graph (matching training's per-graph
    z-scoring); a candidate's score is max laundering probability over its nodes.

``torch`` is imported lazily so the pure reconstruction helpers stay testable without it.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from ..gnn import features as feat_schema
from ..pseudonymise import buckets

CHECKPOINT = "acn-data/models/gnn/multigraph_final.pt"

_FEATURES = feat_schema.SCALAR_FEATURES   # fixed node feature column order
_N_BUCKETS = buckets.N_BUCKETS            # 10

# log1p(bucket_10_midpoint) ≈ log1p(7_500_000) ≈ 15.83 — divisor for edge midpoint normalisation.
_LOG_MID_SCALE = math.log1p(buckets.bucket_midpoint("bucket_10"))


# ---------------------------------------------------------------------------- graph fetch


def fetch_graph(driver, window_start: int, window_end: int) -> dict:
    """Pull the detect-window graph from Neo4j into plain Python for feature reconstruction.

    Returns ``{"nodes": [...], "meta": {hash: {...}}, "edges": [(src, dst, bucket, prox, ts)],
    "window_start": window_start}`` — only pseudonymised fields (privacy boundary intact).
    ``window_start`` is stored so edge time-delta features are consistent between
    training (wide window) and detection (narrow window).
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
            "e.threshold_proximity AS p, e.timestamp AS t, e.is_round_amount AS r",
            ws=window_start,
            we=window_end,
        ).data()
    meta = {n["h"]: {"institution_id": n["inst"], "first_seen_ts": n["fs"]} for n in nodes}
    return {
        "nodes": [n["h"] for n in nodes],
        "meta": meta,
        "edges": [(e["s"], e["d"], e["b"], e["p"], e["t"], e.get("r", False)) for e in edges],
        "window_start": window_start,
    }


# ---------------------------------------------------------------- edge feature helpers


def _edge_features(
    bucket: str,
    proximity: str,
    ts: int,
    window_start: int,
    time_since_prev_days: float,
    is_night: float,
    is_weekend: float,
    is_round_amount: float,
) -> list[float]:
    """Construct the DirMultigraphSAGE edge feature vector.

    All values are in [0, 1] or small positive floats — normalised inline here so
    training and detection share exactly the same representation without a separate
    normalisation step for edge features.
    """
    mid = buckets.bucket_midpoint(bucket)
    bucket_mid_norm = math.log1p(mid) / _LOG_MID_SCALE          # ∈ (0, 1]
    near_threshold = 1.0 if proximity == "high" else 0.0
    time_delta = max(ts - window_start, 0) / 86400.0 / 365.0    # ∈ [0, ~1] over a year

    # One-hot over the 10 fixed buckets: bucket_N → index N-1.
    try:
        bucket_idx = int(bucket.split("_")[1]) - 1  # 0-indexed
    except (IndexError, ValueError):
        bucket_idx = -1
    onehot = [1.0 if i == bucket_idx else 0.0 for i in range(_N_BUCKETS)]

    return [
        bucket_mid_norm,
        near_threshold,
        time_delta,
        time_since_prev_days,
        is_night,
        is_weekend,
        is_round_amount,
    ] + onehot


# ---------------------------------------------------------------- pure feature reconstruction


def reconstruct_features(
    graph: dict, ref_ts: int
) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Rebuild the model's feature matrices from pseudonymised data (pure; no torch/Neo4j).

    Returns ``(nodes, node_feats[N, 21], edge_index[2, E], edge_attr[E, 13])``.

    All parallel edges are preserved as separate rows — the multigraph structure the
    model was trained on. Node features use the same scalar columns and bucket-midpoint
    amounts as training (``_SCALAR_FEATURES`` + 10 bucket bins). Edge features are built
    per directed edge via ``_edge_features`` and are already normalised inline.
    """
    nodes = graph["nodes"]
    idx = {h: i for i, h in enumerate(nodes)}
    window_start = graph.get("window_start", ref_ts)

    out_amts: dict[int, list[float]] = {}
    out_dst: dict[int, set[int]] = {}
    out_hist: dict[int, np.ndarray] = {}
    in_amt_sum: dict[int, float] = {}
    in_deg: dict[int, int] = {}
    edge_pairs: list[tuple[int, int]] = []
    edge_feats: list[list[float]] = []

    # Sort edges chronologically so we can compute rolling temporal features
    sorted_edges = sorted(graph["edges"], key=lambda e: e[4])
    last_tx_ts: dict[int, int] = {}

    for edge in sorted_edges:
        # edge len is 5 in old tests, 6 with is_round_amount
        s, d, b, p, ts = edge[0], edge[1], edge[2], edge[3], int(edge[4])
        is_round = bool(edge[5]) if len(edge) > 5 else False

        if s not in idx or d not in idx:
            continue
        si, di = idx[s], idx[d]

        # Temporal features
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        is_night = 1.0 if dt.hour < 6 or dt.hour > 22 else 0.0
        is_weekend = 1.0 if dt.weekday() >= 5 else 0.0

        prev_ts = last_tx_ts.get(si, ts)
        time_since_prev_days = max(ts - prev_ts, 0) / 86400.0
        last_tx_ts[si] = ts

        edge_pairs.append((si, di))
        edge_feats.append(
            _edge_features(
                b,
                p,
                ts,
                window_start,
                time_since_prev_days,
                is_night,
                is_weekend,
                1.0 if is_round else 0.0,
            )
        )

        amt = buckets.bucket_midpoint(b)
        out_amts.setdefault(si, []).append(amt)
        out_dst.setdefault(si, set()).add(di)
        # bucket histogram: accumulate per-bucket counts (may have multiple edges)
        if si not in out_hist:
            out_hist[si] = np.zeros(_N_BUCKETS)
        try:
            out_hist[si][int(b.split("_")[1]) - 1] += 1
        except (IndexError, ValueError):
            pass
        in_amt_sum[di] = in_amt_sum.get(di, 0.0) + amt
        in_deg[di] = in_deg.get(di, 0) + 1

    # Node feature matrix
    col = {name: i for i, name in enumerate(_FEATURES)}
    rows = np.zeros((len(nodes), len(_FEATURES) + _N_BUCKETS), dtype=float)
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
            rows[i, len(_FEATURES):] = out_hist[i]

    # Edge index and edge attributes
    if edge_pairs:
        edge_index = np.asarray(edge_pairs, dtype=np.int64).T          # [2, E]
        edge_attr = np.asarray(edge_feats, dtype=float)                 # [E, 13]
    else:
        edge_index = np.zeros((2, 0), dtype=np.int64)
        edge_attr = np.zeros((0, feat_schema.N_EDGE_FEATURES), dtype=float)

    return nodes, rows, edge_index, edge_attr


# ---------------------------------------------------------------------------- model scoring


def load_model(path: str = CHECKPOINT, device: str = "cpu"):
    """Load the DirMultigraphSAGE checkpoint for inference (weights only, eval mode)."""
    import torch

    from ..gnn.model import EDGE_DIM, IN_DIM, DirMultigraphSAGE

    model = DirMultigraphSAGE(in_dim=IN_DIM, edge_dim=EDGE_DIM).to(device)
    state = torch.load(path, map_location=device)
    model.load_state_dict(state.get("model_state", state) if isinstance(state, dict) else state)
    model.eval()
    return model


def score_graph(
    model,
    feats: np.ndarray,
    edge_index: np.ndarray,
    edge_attr: np.ndarray,
    device: str = "cpu",
) -> np.ndarray:
    """One forward pass over the whole graph → per-node laundering probability [0, 1]."""
    import torch

    from ..gnn.model import normalise_features

    if feats.shape[0] == 0:
        return np.zeros(0)
    x = torch.tensor(normalise_features(feats), dtype=torch.float, device=device)
    ei = torch.tensor(edge_index, dtype=torch.long, device=device)
    ea = torch.tensor(edge_attr, dtype=torch.float, device=device)
    with torch.no_grad():
        logits = model(x, ei, ea)
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
