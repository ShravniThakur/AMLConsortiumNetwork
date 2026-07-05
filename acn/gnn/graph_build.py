"""Build a per-institution NetworkX training graph, with boundary edges.

Accounts are nodes, transactions are directed edges. Critically, the local graph is **not**
purely internal: it also includes the cross-institution edges this institution *originates*
(internal account → account owned by another institution), terminating in **boundary nodes**.
Boundary nodes carry only locally-computable features + an ``is_boundary`` flag and are
excluded from the labelled loss — their sole job is to give message passing the
boundary-crossing structure the model must score at inference.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from ..pseudonymise import buckets as _bkt

# Fixed amount-bucket boundaries. 10 buckets.
BUCKET_BOUNDARIES = [1e4, 2.5e4, 5e4, 1e5, 2.5e5, 5e5, 1e6, 2.5e6, 5e6]
N_BUCKETS = len(BUCKET_BOUNDARIES) + 1
BOUNDARY_LABEL = -1  # boundary nodes carry no local label → excluded from the loss


def _to_midpoints(amounts: np.ndarray) -> np.ndarray:
    """Map each amount to its fixed-bucket midpoint — the exact representation the graph engine
    scores on (raw amounts never reach it). Training with ``bucketize=True`` uses this so the
    model's train features match its inference features (no real-vs-bucket distribution shift).
    """
    return np.array(
        [_bkt.bucket_midpoint(_bkt.amount_bucket(float(a))) for a in amounts], dtype=float
    )


def _bucket_hist(amounts: np.ndarray) -> list[float]:
    """Normalised histogram of amounts over the 10 fixed buckets."""
    idx = np.digitize(amounts, BUCKET_BOUNDARIES)
    counts = np.bincount(idx, minlength=N_BUCKETS)[:N_BUCKETS].astype(float)
    total = counts.sum()
    return (counts / total).tolist() if total else counts.tolist()


def build_graph(
    partition: pd.DataFrame, institution: str, ref_ts: int, bucketize: bool = False
) -> nx.DiGraph:
    """Directed training graph for ``institution`` from its (sending) partition rows.

    Internal edges connect accounts this institution owns. A transaction to an account owned
    by *another* institution (``dst_institution != institution``) becomes a **boundary edge**
    into a boundary node (keyed by the destination's owning institution + account — the
    institution's own local knowledge, nothing new shared).

    ``bucketize=True`` replaces each amount with its fixed-bucket midpoint before computing any
    amount feature, so the model trains on the **same** representation the graph engine scores on
    (real amounts never reach it) — aligning train/inference features (the institution bucketises
    its own raw data locally, no privacy cost).
    """
    if bucketize:
        partition = partition.copy()
        partition["amount_paid"] = _to_midpoints(partition["amount_paid"].to_numpy())
    g = nx.DiGraph()

    def node_id(inst: str, acct: str) -> str:
        return f"{inst}:{acct}"

    # Total amount received per account (for flow-conservation): the hallmark of a layering
    # mule is out ≈ in (money passes straight through).
    incoming = partition.groupby("to_account")["amount_paid"].sum().to_dict()

    # Per-account (sender) aggregates for internal node features.
    for acct, grp in partition.groupby("from_account"):
        n = node_id(institution, str(acct))
        amounts = grp["amount_paid"].to_numpy(dtype=float)
        first_seen = int((pd.to_datetime(grp["timestamp"]).astype("int64") // 10**9).min())
        age_days = max(ref_ts - first_seen, 0) / 86400.0
        recipients = grp["to_account"].astype(str)
        out_amount = float(amounts.sum())
        in_amount = float(incoming.get(str(acct), 0.0))
        g.add_node(
            n,
            is_boundary=0,
            label=int(grp["is_laundering"].max()) if "is_laundering" in grp else 0,
            txn_count=len(grp),
            amount_mean=float(amounts.mean()),
            amount_std=float(amounts.std()),
            age_days=age_days,
            velocity_per_day=len(grp) / max(age_days, 1.0),
            new_counterparty_ratio=recipients.nunique() / len(grp),
            total_in=in_amount,
            flow_ratio=out_amount / (in_amount + 1.0),  # ≈1 for pass-through / layering
            in_degree=0,
            out_degree=0,
            bucket_hist=_bucket_hist(amounts),
        )

    # Edges (internal) + boundary nodes/edges (cross-institution, this-institution-originated).
    for row in partition.itertuples(index=False):
        src = node_id(institution, str(row.from_account))
        dst_inst = getattr(row, "dst_institution", institution)
        if dst_inst == institution:
            dst = node_id(institution, str(row.to_account))
            if dst not in g:  # a receiver never seen as a sender → minimal internal node
                _add_receiver_node(g, dst)
        else:
            dst = node_id(str(dst_inst), str(row.to_account))
            if dst not in g:
                _add_boundary_node(g, dst)
        g.add_edge(src, dst, amount=float(row.amount_paid), is_laundering=int(row.is_laundering))

    _set_degrees(g)
    _tag_laundering_chains(g)
    return g


def _minimal_node(g: nx.DiGraph, node: str, *, is_boundary: int, label: int) -> None:
    """A receiver-only / boundary node — no local sending history (defaults, never imputed)."""
    g.add_node(
        node,
        is_boundary=is_boundary,
        label=label,
        txn_count=0,
        amount_mean=0.0,
        amount_std=0.0,
        age_days=0.0,
        velocity_per_day=0.0,
        new_counterparty_ratio=0.0,
        total_in=0.0,
        flow_ratio=0.0,  # terminal / boundary node — not a pass-through
        in_degree=0,
        out_degree=0,
        bucket_hist=[0.0] * N_BUCKETS,
    )


def _add_receiver_node(g: nx.DiGraph, node: str) -> None:
    _minimal_node(g, node, is_boundary=0, label=0)


def _add_boundary_node(g: nx.DiGraph, node: str) -> None:
    _minimal_node(g, node, is_boundary=1, label=BOUNDARY_LABEL)


def _set_degrees(g: nx.DiGraph) -> None:
    """Fill in/out degree once all edges exist (structural signal for the GNN)."""
    for node in g.nodes():
        g.nodes[node]["in_degree"] = g.in_degree(node)
        g.nodes[node]["out_degree"] = g.out_degree(node)


def _tag_laundering_chains(g: nx.DiGraph) -> None:
    """Tag each node with a ``chain`` id: connected components over laundering edges (-1 = none)."""
    laundering = nx.Graph()
    for u, v, data in g.edges(data=True):
        if data.get("is_laundering") == 1:
            laundering.add_edge(u, v)
    nx.set_node_attributes(g, -1, "chain")
    for cid, comp in enumerate(nx.connected_components(laundering)):
        for node in comp:
            g.nodes[node]["chain"] = cid


# Feature columns in a fixed order (the model consumes this matrix).
_SCALAR_FEATURES = [
    "is_boundary",
    "txn_count",
    "amount_mean",
    "amount_std",
    "age_days",
    "velocity_per_day",
    "new_counterparty_ratio",
    "total_in",
    "flow_ratio",
    "in_degree",
    "out_degree",
]


def to_arrays(g: nx.DiGraph) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Flatten the graph to ``(nodes, features, labels, is_boundary_mask)`` for the model.

    ``features`` = scalar features + the 10 amount-bucket bins; ``labels`` uses -1 for
    boundary nodes (excluded from the loss); ``is_boundary_mask`` is a bool array.
    """
    nodes = list(g.nodes())
    rows, labels, boundary = [], [], []
    for n in nodes:
        a = g.nodes[n]
        rows.append([a[f] for f in _SCALAR_FEATURES] + list(a["bucket_hist"]))
        labels.append(a["label"])
        boundary.append(bool(a["is_boundary"]))
    return nodes, np.asarray(rows, dtype=float), np.asarray(labels, dtype=int), np.asarray(boundary)
