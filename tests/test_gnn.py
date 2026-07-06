"""GNN detector tests: eval metrics and DirMultigraphSAGE model.

The model trains on the pseudonymised merged Neo4j graph (scripts/train_gnn.py).
These tests cover eval metrics and the model forward pass + a small transductive
training sanity check. Feature constants live in acn.gnn.features.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from acn.gnn import metrics



def test_recall_at_fpr_and_auc():
    y = [0, 0, 0, 0, 1, 1]
    perfect = [0.1, 0.2, 0.3, 0.4, 0.9, 0.95]
    assert metrics.recall_at_fpr(y, perfect, fpr=0.05) == 1.0
    assert metrics.auc_roc(y, perfect) == 1.0
    assert metrics.recall_at_fpr([0, 0, 0], [0.1, 0.2, 0.3]) == 0.0
    assert metrics.auc_roc([1, 1, 1], [0.1, 0.2, 0.3]) == 0.5


# ---------------------------------------------------------------- model + training


def test_multigraph_forward_shape():
    torch = pytest.importorskip("torch")
    pytest.importorskip("torch_geometric")
    from acn.gnn.model import EDGE_DIM, IN_DIM, DirMultigraphSAGE

    n_nodes, n_edges = 6, 4
    net = DirMultigraphSAGE(in_dim=IN_DIM, edge_dim=EDGE_DIM)
    x = torch.randn(n_nodes, IN_DIM)
    ei = torch.tensor([[0, 1, 2, 3], [1, 2, 3, 4]], dtype=torch.long)
    ea = torch.randn(n_edges, EDGE_DIM)
    out = net(x, ei, ea)
    assert out.shape == (n_nodes,)  # one logit per node


def test_centralized_training_learns_a_separable_signal():
    torch = pytest.importorskip("torch")
    pytest.importorskip("torch_geometric")
    from acn.gnn.model import EDGE_DIM, IN_DIM, DirMultigraphSAGE, weighted_bce

    # A tiny transductive graph where a feature perfectly predicts the label — training on the
    # merged graph (with a train mask) should push train-set probabilities the right way.
    torch.manual_seed(0)
    n = 40
    n_edges = n - 1
    y = (torch.arange(n) % 2).float()
    x = torch.zeros(n, IN_DIM)
    x[:, 1] = y * 5 + torch.randn(n) * 0.1  # signal in one feature column
    ei = torch.stack([torch.arange(n_edges), torch.arange(1, n)])
    ea = torch.zeros(n_edges, EDGE_DIM)       # zero edge features (neutral baseline)
    mask = torch.zeros(n, dtype=torch.bool)
    mask[: n // 2] = True

    net = DirMultigraphSAGE(in_dim=IN_DIM, edge_dim=EDGE_DIM)
    opt = torch.optim.Adam(net.parameters(), lr=0.05)
    for _ in range(60):
        opt.zero_grad()
        loss = weighted_bce(net(x, ei, ea)[mask], y[mask])
        loss.backward()
        opt.step()
    with torch.no_grad():
        p = torch.sigmoid(net(x, ei, ea))[mask]
    # positives should score higher than negatives on the train set (it learned the signal)
    assert p[y[mask] == 1].mean() > p[y[mask] == 0].mean()
    assert np.isfinite(loss.item())
