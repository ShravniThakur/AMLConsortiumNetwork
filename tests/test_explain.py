"""Explainability tests.

- **Pure** (always): evidence-string assembly — structured fields, plain-language content, the
  empty-explanation guard (no vacuous string), pseudonymised-only output.
- **Torch** (skipped if torch/PyG absent): GNNExplainer on a planted chain highlights the
  laundering hops and returns non-empty feature importances.
"""

from __future__ import annotations

import pytest

from acn.explain import evidence

BASE_TS = 1_726_000_000
DAY = 86400


# ------------------------------------------------------------------------------- pure evidence


def _candidate():
    return {
        "pattern": "round_trip",
        "nodes": ["aaaaaaaa11", "bbbbbbbb22", "cccccccc33"],
        "institutions": ["INST_A", "INST_B"],
        "score": 0.97,
    }


def test_evidence_structure_and_text():
    explanation = {
        "target_idx": 0,
        "n_edges": 3,
        "top_edges": [(1, 0, 0.8), (2, 1, 0.4)],
        "feature_importance": [("flow_ratio", 0.5), ("txn_count", 0.3)],
    }
    nodes = ["aaaaaaaa11", "bbbbbbbb22", "cccccccc33"]
    edge_attrs = {
        ("bbbbbbbb22", "aaaaaaaa11"): ("bucket_7", "high"),
        ("cccccccc33", "bbbbbbbb22"): ("bucket_4", "low"),
    }
    ev = evidence.build_evidence(_candidate(), explanation, nodes, edge_attrs)

    assert ev["has_evidence"] is True
    assert ev["pattern"] == "round_trip"
    assert ev["target_account"] == "aaaaaaaa11"
    assert len(ev["responsible_edges"]) == 2
    # top edge resolved to hashes + its bucket/flag
    assert ev["responsible_edges"][0]["amount_bucket"] == "bucket_7"
    assert ev["responsible_edges"][0]["threshold_proximity"] == "high"
    # text cites the pattern, short hashes, bucket, and the threshold note
    assert "round trip" in ev["text"]
    assert "bbbbbbbb" in ev["text"] and "aaaaaaaa" in ev["text"]
    assert "near reporting threshold" in ev["text"]


def test_evidence_only_pseudonymised():
    explanation = {
        "target_idx": 0,
        "n_edges": 1,
        "top_edges": [(1, 0, 0.9)],
        "feature_importance": [("amount_mean", 0.6)],
    }
    nodes = ["aaaaaaaa11", "bbbbbbbb22", "cccccccc33"]
    ev = evidence.build_evidence(
        _candidate(), explanation, nodes, {("bbbbbbbb22", "aaaaaaaa11"): ("bucket_3", "low")}
    )
    # no raw ids/amounts — only hashes (shown truncated), bucket labels, flags
    assert "₹" not in ev["text"] and "amount=" not in ev["text"]
    # short() truncates the hash to 8 chars in the sentence
    assert "aaaaaaaa" in ev["text"]


def test_empty_explanation_is_not_vacuous():
    explanation = {"target_idx": 0, "n_edges": 0, "top_edges": [], "feature_importance": []}
    ev = evidence.build_evidence(_candidate(), explanation, ["aaaaaaaa11"], {})
    assert ev["has_evidence"] is False
    assert "low-confidence" in ev["text"]
    assert ev["responsible_edges"] == []


def test_short_hash_helper():
    assert evidence.short("0123456789abcdef") == "01234567"


# ------------------------------------------------------------------------- torch: real explainer


def test_gnnexplainer_highlights_laundering_hops():
    pytest.importorskip("torch")
    pytest.importorskip("torch_geometric")
    import torch

    from acn.explain import gnn_explainer as gx
    from acn.gnn.model import GraphSAGE
    from acn.graph import score as gs

    torch.manual_seed(0)
    # a -> mid -> b -> c ; explain the chain end (c). Its 2-hop receptive field = {mid->b, b->c}.
    graph = {
        "nodes": ["a", "mid", "b", "c"],
        "meta": {
            h: {"institution_id": i, "first_seen_ts": BASE_TS - DAY}
            for h, i in [("a", "INST_A"), ("mid", "INST_B"), ("b", "INST_C"), ("c", "INST_A")]
        },
        "edges": [
            ("a", "mid", "bucket_7", "high", BASE_TS),
            ("mid", "b", "bucket_7", "high", BASE_TS + 100),
            ("b", "c", "bucket_7", "high", BASE_TS + 200),
        ],
    }
    nodes, feats, ei = gs.reconstruct_features(graph, ref_ts=BASE_TS + DAY)
    model = GraphSAGE(in_dim=feats.shape[1])  # base reconstruct width (no Cypher chain block here)
    model.eval()
    explainer = gx.build_explainer(model, epochs=50)

    res = gx.explain_node(explainer, feats, ei, nodes.index("c"))
    assert res["n_edges"] == 2  # only the two edges feeding c's 2-hop field
    assert res["top_edges"]  # non-empty
    assert res["feature_importance"]  # non-empty
    # every attributed edge is a real chain hop (endpoints are known nodes), not spurious
    known = set(range(len(nodes)))
    for src_i, dst_i, _w in res["top_edges"]:
        assert src_i in known and dst_i in known

    # full evidence string builds from it
    edge_attrs = {(e[0], e[1]): (e[2], e[3]) for e in graph["edges"]}
    cand = {"pattern": "path_tracker", "nodes": nodes, "institutions": ["INST_A"], "score": 0.98}
    ev = evidence.build_evidence(cand, res, nodes, edge_attrs)
    assert ev["has_evidence"] is True
    assert "bucket_7" in ev["text"]
