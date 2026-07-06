"""Directed-multigraph GraphSAGE laundering detector.

Replaces the symmetric SAGEConv baseline with ``DirMultigraphSAGE``, a two-layer
directed-multigraph message-passing network. Each message carries both the source
node's features **and the edge's own features** (amount bucket, structuring flag,
timing), and in-flow / out-flow are aggregated separately — matching three of the
adaptations from Egressy et al. AAAI 2024 ("Provably Powerful GNNs for Directed
Multigraphs") that are empirically most impactful on AML tasks.

Architecture:
  DirMultigraphConv (×2)
    msg(u→v)   = ReLU(Linear([h_u ‖ e_uv]))
    in_agg[v]  = mean{ msg(u→v) : all u→v }   # what flows IN
    out_agg[u] = mean{ msg(u→v) : all u→v }   # what flows OUT
    h_v'       = ReLU(Linear([h_v ‖ in_agg[v] ‖ out_agg[v]]))
  Linear head → one logit per node.

Loss: weighted BCE (~200× on laundering class) to counter the 0.052% base rate.
Feature schema lives in ``acn.gnn.features`` — single source of truth.
``torch``/``torch_geometric`` are imported only on the training/scoring path.
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from ..graph import chain_features
from . import features

# Input dimensions (node and edge feature widths).
IN_DIM = (
    len(features.SCALAR_FEATURES)
    + features.N_BUCKETS
    + chain_features.N_CHAIN_FEATURES
)
EDGE_DIM = features.N_EDGE_FEATURES  # 13
HIDDEN_DIM = 64
LAUNDERING_POS_WEIGHT = 200.0


# ---------------------------------------------------------------------------
# Low-level scatter helper (pure PyTorch — no torch_scatter dependency)
# ---------------------------------------------------------------------------


def _scatter_mean(src: torch.Tensor, index: torch.Tensor, dim_size: int) -> torch.Tensor:
    """Mean-aggregate rows of ``src`` grouped by ``index`` (pure PyTorch)."""
    out = torch.zeros(dim_size, src.size(1), dtype=src.dtype, device=src.device)
    cnt = torch.zeros(dim_size, 1, dtype=src.dtype, device=src.device)
    idx = index.unsqueeze(1).expand_as(src)
    ones = torch.ones(src.size(0), 1, dtype=src.dtype, device=src.device)
    out.scatter_add_(0, idx, src)
    cnt.scatter_add_(0, index.unsqueeze(1), ones)
    return out / cnt.clamp(min=1.0)


# ---------------------------------------------------------------------------
# DirMultigraphConv — one directed-multigraph message-passing layer
# ---------------------------------------------------------------------------


class DirMultigraphConv(nn.Module):
    """Edge-conditioned, direction-aware graph convolution for directed multigraphs.

    For every directed edge (u→v) with feature vector e:
      message = ReLU(Linear([h_u ‖ e]))

    Separate mean-pools over incoming/outgoing messages give each node independent
    signals for what flows *in* vs what flows *out* — a key AML discriminator (a
    pass-through mule has in ≈ out; a money source has high out and low in).
    """

    def __init__(self, in_channels: int, edge_channels: int, out_channels: int) -> None:
        super().__init__()
        # Message: concatenates source node embedding with the edge's own features.
        self.msg_lin = nn.Linear(in_channels + edge_channels, out_channels)
        # Update: combines the node's own embedding with both aggregation signals.
        self.update_lin = nn.Linear(in_channels + 2 * out_channels, out_channels)

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
    ) -> torch.Tensor:
        n = x.size(0)
        src, dst = edge_index[0], edge_index[1]

        # Build one message per directed edge: f(source embedding ‖ edge features)
        msgs = F.relu(self.msg_lin(torch.cat([x[src], edge_attr], dim=-1)))

        # Separate aggregation for in-neighbourhood (→ dst) and out-neighbourhood (src →)
        in_agg = _scatter_mean(msgs, dst, n)
        out_agg = _scatter_mean(msgs, src, n)

        return F.relu(self.update_lin(torch.cat([x, in_agg, out_agg], dim=-1)))


# ---------------------------------------------------------------------------
# DirMultigraphSAGE — full 2-layer model
# ---------------------------------------------------------------------------


class DirMultigraphSAGE(nn.Module):
    """2-layer directed-multigraph GNN → per-node laundering logit."""

    def __init__(
        self,
        in_dim: int = IN_DIM,
        edge_dim: int = EDGE_DIM,
        hidden: int = HIDDEN_DIM,
        layers: int = 2,
    ) -> None:
        super().__init__()
        self.convs = nn.ModuleList(
            DirMultigraphConv(in_dim if i == 0 else hidden, edge_dim, hidden)
            for i in range(layers)
        )
        self.head = nn.Linear(hidden, 1)

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
    ) -> torch.Tensor:
        for conv in self.convs:
            x = conv(x, edge_index, edge_attr)
        return self.head(x).squeeze(-1)  # logits, shape [num_nodes]


# ---------------------------------------------------------------------------
# Loss + normalisation helpers (unchanged from the GraphSAGE baseline)
# ---------------------------------------------------------------------------


def weighted_bce(
    logits: torch.Tensor,
    labels: torch.Tensor,
    pos_weight: float = LAUNDERING_POS_WEIGHT,
):
    """Weighted BCE-with-logits; ``pos_weight`` up-weights the rare laundering class."""
    return F.binary_cross_entropy_with_logits(
        logits, labels.float(), pos_weight=torch.tensor(pos_weight, device=logits.device)
    )


# Heavy-tailed node feature columns that need log-compression before z-scoring.
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

_SCALAR_FEATURES = features.SCALAR_FEATURES  # local alias for normalise_features indexing


def normalise_features(feats: np.ndarray) -> np.ndarray:
    """log-compress heavy-tailed node columns, then z-score every column (per graph).

    Operates on node features only — edge features are normalised inline in
    ``score.reconstruct_features`` so train and inference stay consistent.
    """
    f = feats.astype(float).copy()
    for name in _LOG_FEATURES:
        c = _SCALAR_FEATURES.index(name)
        f[:, c] = np.log1p(np.clip(f[:, c], 0.0, None))
    mu = f.mean(axis=0)
    sd = f.std(axis=0)
    sd[sd == 0] = 1.0
    return (f - mu) / sd
