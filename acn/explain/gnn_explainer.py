"""GNNExplainer over the GraphSAGE model.

For an alerted node, answer **what drove its laundering score** — which incoming transactions
(edges) and which node features mattered most. We use PyG's GNNExplainer, *not* attention
weights: attention describes how the model *aggregated* neighbours, while GNNExplainer learns a
mask over the actual inputs, i.e. *causal influence*. When the output becomes evidence for a
regulatory filing, "what caused this score" must be an influence answer, not an aggregation
artefact (explainability ADR).

Because GraphSAGE is 2 layers, a node's score depends only on its 2-hop in-neighbourhood, so we
extract that k-hop subgraph and explain within it — faithful *and* cheap (never the 230k-node
graph). ``torch``/``torch_geometric`` are imported lazily so ``evidence.py`` and its tests stay
torch-free.
"""

from __future__ import annotations

import numpy as np

from ..gnn import graph_build
from ..graph import score as graph_score

DEFAULT_EPOCHS = 100  # GNNExplainer mask-optimisation steps (recorded in explain_report.md)
NUM_HOPS = 2  # matches the 2 SAGEConv layers — the node's full receptive field

# Human-facing feature names in the model's column order (scalars + the 10 amount-bucket bins).
FEATURE_NAMES = list(graph_score._FEATURES) + [
    f"amount_bucket_{i}" for i in range(1, graph_build.N_BUCKETS + 1)
]


def build_explainer(model, epochs: int = DEFAULT_EPOCHS):
    """Wrap a trained GraphSAGE model in a PyG ``Explainer`` for node-level binary output."""
    from torch_geometric.explain import Explainer, GNNExplainer

    return Explainer(
        model=model,
        algorithm=GNNExplainer(epochs=epochs),
        explanation_type="model",
        node_mask_type="attributes",
        edge_mask_type="object",
        model_config=dict(mode="binary_classification", task_level="node", return_type="raw"),
    )


def explain_node(
    explainer,
    feats: np.ndarray,
    edge_index: np.ndarray,
    target_idx: int,
    top_k_edges: int = 5,
    top_k_features: int = 5,
    num_hops: int = NUM_HOPS,
) -> dict:
    """Explain the score for one global node; return plain-Python edges + feature importances.

    ``feats``/``edge_index`` are the whole-graph arrays (from ``score.reconstruct_features``).
    We normalise features exactly as scoring did, pull the target's k-hop subgraph, run the
    explainer, and map masks back to **global** node indices so callers can resolve hashes.
    """
    import torch
    from torch_geometric.utils import k_hop_subgraph

    from ..gnn.model import normalise_features

    x = torch.tensor(normalise_features(feats), dtype=torch.float)
    ei = torch.tensor(edge_index, dtype=torch.long)

    subset, sub_ei, mapping, _ = k_hop_subgraph(int(target_idx), num_hops, ei, relabel_nodes=True)
    if sub_ei.numel() == 0:
        # Pure-source node: nothing flows in, so the model had no edges to attribute the score to.
        return {
            "target_idx": int(target_idx),
            "n_edges": 0,
            "top_edges": [],
            "feature_importance": [],
        }

    sub_x = x[subset]
    explanation = explainer(sub_x, sub_ei, index=int(mapping[0]))

    edge_mask = explanation.edge_mask.detach().cpu().numpy()
    subset_np = subset.detach().cpu().numpy()
    src_local = sub_ei[0].detach().cpu().numpy()
    dst_local = sub_ei[1].detach().cpu().numpy()
    order = np.argsort(edge_mask)[::-1][:top_k_edges]
    top_edges = [
        (int(subset_np[src_local[e]]), int(subset_np[dst_local[e]]), float(edge_mask[e]))
        for e in order
        if edge_mask[e] > 0
    ]

    node_mask = explanation.node_mask.detach().cpu().numpy()  # [sub_nodes, n_features]
    feat_imp = np.abs(node_mask).sum(axis=0)
    total = feat_imp.sum() or 1.0
    f_order = np.argsort(feat_imp)[::-1][:top_k_features]
    feature_importance = [
        (FEATURE_NAMES[c], float(feat_imp[c] / total)) for c in f_order if feat_imp[c] > 0
    ]

    return {
        "target_idx": int(target_idx),
        "n_edges": int(sub_ei.shape[1]),
        "top_edges": top_edges,
        "feature_importance": feature_importance,
    }
