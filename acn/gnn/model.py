"""GraphSAGE laundering detector.

Two SAGEConv layers (a 2-hop neighbourhood, kept shallow to avoid over-smoothing) and a linear
head producing one logit per node. A 2-hop receptive field alone can't see long layering chains,
so the input carries a **chain-aware block** (``graph.chain_features``): the Cypher layers' path
findings as per-node features, giving the model the long-range structure message passing can't
reach. Loss is weighted BCE with the laundering class up-weighted (~200x) to counter the 0.052%
base rate — without it the model collapses to predicting "clean" everywhere.

Trained on the **pseudonymised merged graph** — the graph engine's own graph + bucket features,
so train and inference use the same representation. Privacy holds because the merged graph carries
only hashes + buckets (no raw identity/amount ever leaves a bank). ``torch``/``torch_geometric``
are imported only on the training/scoring path, never in the pure/tested code.
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn
from torch_geometric.data import Data
from torch_geometric.nn import SAGEConv

from ..graph import chain_features
from . import graph_build

# Feature width = scalar features + the 10 amount-bucket bins (graph_build.to_arrays) + the
# chain-aware block (chain_features): the Cypher layers' path findings, so the model can see
# long-range chain structure its 2-hop receptive field can't reach.
IN_DIM = len(graph_build._SCALAR_FEATURES) + graph_build.N_BUCKETS + chain_features.N_CHAIN_FEATURES
HIDDEN_DIM = 64
LAUNDERING_POS_WEIGHT = 200.0


class GraphSAGE(nn.Module):
    """2-layer GraphSAGE → per-node laundering logit."""

    def __init__(self, in_dim: int = IN_DIM, hidden: int = HIDDEN_DIM, layers: int = 2):
        super().__init__()
        self.convs = nn.ModuleList(
            SAGEConv(in_dim if i == 0 else hidden, hidden) for i in range(layers)
        )
        self.head = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        for conv in self.convs:
            x = F.relu(conv(x, edge_index))
        return self.head(x).squeeze(-1)  # logits, shape [num_nodes]


def weighted_bce(
    logits: torch.Tensor, labels: torch.Tensor, pos_weight: float = LAUNDERING_POS_WEIGHT
):
    """Weighted BCE-with-logits; ``pos_weight`` up-weights the rare laundering class."""
    return F.binary_cross_entropy_with_logits(
        logits, labels.float(), pos_weight=torch.tensor(pos_weight, device=logits.device)
    )


# Heavy-tailed feature columns (spanning orders of magnitude) that need log-compression
# before z-scoring, else a GraphSAGE with raw ₹-millions features simply cannot learn.
_LOG_FEATURES = [
    "txn_count",
    "amount_mean",
    "amount_std",
    "age_days",
    "velocity_per_day",
    "total_in",
    "in_degree",
    "out_degree",
]


def normalise_features(feats: np.ndarray) -> np.ndarray:
    """log-compress the heavy-tailed columns, then z-score every column (per graph).

    Standardisation is per graph — without it the giant amount columns swamp the binary/ratio
    features and training collapses.
    """
    f = feats.astype(float).copy()
    for name in _LOG_FEATURES:
        c = graph_build._SCALAR_FEATURES.index(name)
        f[:, c] = np.log1p(np.clip(f[:, c], 0.0, None))
    mu = f.mean(axis=0)
    sd = f.std(axis=0)
    sd[sd == 0] = 1.0
    return (f - mu) / sd


def nx_to_pyg(g) -> Data:
    """Convert an nx training graph to a PyG ``Data`` with a labelled-node ``train_mask``.

    Node features are normalised (``normalise_features``). The mask is True only for
    labelled, non-boundary nodes — boundary nodes give message passing structure but are
    never loss targets.
    """
    nodes, feats, labels, boundary = graph_build.to_arrays(g)
    feats = normalise_features(feats)
    index = {n: i for i, n in enumerate(nodes)}
    if g.number_of_edges():
        edges = [(index[u], index[v]) for u, v in g.edges()]
        edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous()
    else:
        edge_index = torch.empty((2, 0), dtype=torch.long)
    mask = (~boundary) & (labels >= 0)
    return Data(
        x=torch.tensor(feats, dtype=torch.float),
        edge_index=edge_index,
        y=torch.tensor(np.clip(labels, 0, 1), dtype=torch.long),
        train_mask=torch.tensor(mask, dtype=torch.bool),
    )
