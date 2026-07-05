"""GNN detector tests: graph/feature construction, metrics, GraphSAGE, training.

The model trains on the pseudonymised merged graph. These tests cover the graph/feature builder,
eval metrics, the model forward pass, and a small transductive training sanity check.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from acn.gnn import graph_build, metrics


def _partition():
    rows = [
        ("A1", "A2", 5_000.0, "2022-09-01", 1, "INST_A"),  # laundering chain A1->A2->A3
        ("A2", "A3", 4_800.0, "2022-09-01", 1, "INST_A"),
        ("A1", "B1", 9_000.0, "2022-09-02", 0, "INST_B"),  # cross-institution -> boundary node
        ("A4", "A5", 200.0, "2022-09-03", 0, "INST_A"),  # background internal edge
    ]
    cols = [
        "from_account",
        "to_account",
        "amount_paid",
        "timestamp",
        "is_laundering",
        "dst_institution",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


# ------------------------------------------------------------------- graph build


def test_boundary_node_created_and_excluded_from_labels():
    ref_ts = int(pd.Timestamp("2022-09-11").timestamp())
    g = graph_build.build_graph(_partition(), "INST_A", ref_ts)
    assert "INST_B:B1" in g  # cross-institution destination became a boundary node
    b = g.nodes["INST_B:B1"]
    assert b["is_boundary"] == 1
    assert b["label"] == graph_build.BOUNDARY_LABEL
    assert g.nodes["INST_A:A1"]["is_boundary"] == 0


def test_laundering_chain_tagged_and_arrays_shape():
    ref_ts = int(pd.Timestamp("2022-09-11").timestamp())
    g = graph_build.build_graph(_partition(), "INST_A", ref_ts)
    chains = {g.nodes[n]["chain"] for n in ("INST_A:A1", "INST_A:A2", "INST_A:A3")}
    assert chains == {next(iter(chains))} and next(iter(chains)) >= 0

    nodes, feats, labels, boundary = graph_build.to_arrays(g)
    assert feats.shape == (len(nodes), len(graph_build._SCALAR_FEATURES) + graph_build.N_BUCKETS)
    assert boundary.sum() == 1
    assert labels[boundary].tolist() == [graph_build.BOUNDARY_LABEL]


def test_bucketize_uses_midpoints():
    # With bucketize on, amount features come from fixed-bucket midpoints (match graph-engine).
    ref_ts = int(pd.Timestamp("2022-09-11").timestamp())
    g = graph_build.build_graph(_partition(), "INST_A", ref_ts, bucketize=True)
    from acn.pseudonymise import buckets

    # A1 sent 5,000 (bucket_1) and 9,000 (bucket_1) → both map to the bucket_1 midpoint.
    assert g.nodes["INST_A:A1"]["amount_mean"] == pytest.approx(buckets.bucket_midpoint("bucket_1"))


# ---------------------------------------------------------------------- metrics


def test_recall_at_fpr_and_auc():
    y = [0, 0, 0, 0, 1, 1]
    perfect = [0.1, 0.2, 0.3, 0.4, 0.9, 0.95]
    assert metrics.recall_at_fpr(y, perfect, fpr=0.05) == 1.0
    assert metrics.auc_roc(y, perfect) == 1.0
    assert metrics.recall_at_fpr([0, 0, 0], [0.1, 0.2, 0.3]) == 0.0
    assert metrics.auc_roc([1, 1, 1], [0.1, 0.2, 0.3]) == 0.5


# ---------------------------------------------------------------- model + training


def test_graphsage_forward_shape():
    torch = pytest.importorskip("torch")
    pytest.importorskip("torch_geometric")
    from acn.gnn.model import IN_DIM, GraphSAGE

    net = GraphSAGE(in_dim=IN_DIM)
    x = torch.randn(6, IN_DIM)
    ei = torch.tensor([[0, 1, 2, 3], [1, 2, 3, 4]], dtype=torch.long)
    out = net(x, ei)
    assert out.shape == (6,)  # one logit per node


def test_centralized_training_learns_a_separable_signal():
    torch = pytest.importorskip("torch")
    pytest.importorskip("torch_geometric")
    from acn.gnn.model import IN_DIM, GraphSAGE, weighted_bce

    # A tiny transductive graph where a feature perfectly predicts the label — training on the
    # merged graph (with a train mask) should push train-set probabilities the right way.
    torch.manual_seed(0)
    n = 40
    y = (torch.arange(n) % 2).float()
    x = torch.zeros(n, IN_DIM)
    x[:, 1] = y * 5 + torch.randn(n) * 0.1  # signal in one feature column
    ei = torch.stack([torch.arange(n - 1), torch.arange(1, n)])
    mask = torch.zeros(n, dtype=torch.bool)
    mask[: n // 2] = True

    net = GraphSAGE(in_dim=IN_DIM)
    opt = torch.optim.Adam(net.parameters(), lr=0.05)
    for _ in range(60):
        opt.zero_grad()
        loss = weighted_bce(net(x, ei)[mask], y[mask])
        loss.backward()
        opt.step()
    with torch.no_grad():
        p = torch.sigmoid(net(x, ei))[mask]
    # positives should score higher than negatives on the train set (it learned the signal)
    assert p[y[mask] == 1].mean() > p[y[mask] == 0].mean()
    assert np.isfinite(loss.item())
