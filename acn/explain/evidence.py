"""Turn a GNNExplainer result into investigator-ready evidence.

Produces a structured object **and** a plain-language sentence citing the specific hops, amount
buckets, threshold flags, and node features that drove the score — the raw material for the STR
draft and a case-detail view. Pure (no torch/Neo4j) so it is deterministic
and unit-testable.

Security: references only **pseudonymised** hashes (shortened for readability), fixed amount
buckets, and the threshold-proximity flag — never a raw account id or amount.
"""

from __future__ import annotations

# What each detection pattern means, in one plain clause.
_PATTERN_DESC = {
    "sliding_window": "funds moved in and back out of an account within a short window",
    "path_tracker": "a multi-hop transfer chain spanning institutions",
    "round_trip": "funds left an account and returned to it through intermediaries",
    "flow_conservation": "an account forwarded almost exactly what it received (pass-through)",
    "coordinated_new_accounts": "a cluster of newly-seen accounts moved funds in concert",
}

# Model feature names → friendly phrasing for the sentence.
_FRIENDLY = {
    "flow_ratio": "money-out-to-money-in ratio",
    "txn_count": "number of transactions sent",
    "amount_mean": "typical transaction size",
    "amount_std": "variability of transaction size",
    "velocity_per_day": "transactions per day",
    "new_counterparty_ratio": "share of new counterparties",
    "total_in": "total money received",
    "in_degree": "number of distinct senders",
    "out_degree": "number of distinct recipients",
    "age_days": "account age",
    "is_boundary": "cross-institution position",
}


def short(h: str) -> str:
    """First 8 hex chars of a hash — enough to identify a node in evidence without the full key."""
    return str(h)[:8]


def _friendly(feature: str) -> str:
    if feature.startswith("amount_bucket_"):
        return f"activity in amount band {feature.rsplit('_', 1)[1]}"
    return _FRIENDLY.get(feature, feature)


def build_evidence(candidate: dict, explanation: dict, nodes: list[str], edge_attrs: dict) -> dict:
    """Assemble structured + plain-language evidence for one alerted candidate.

    ``nodes`` maps a global index → account hash; ``edge_attrs`` maps ``(src_hash, dst_hash)`` →
    ``(amount_bucket, threshold_proximity)``. Returns a dict with ``has_evidence`` (False when the
    explanation is empty — we flag it rather than emit a vacuous string) and a ``text`` summary.
    """
    pattern = candidate.get("pattern", "unknown")
    target_hash = nodes[explanation["target_idx"]] if nodes else None

    responsible_edges = []
    for src_i, dst_i, weight in explanation.get("top_edges", []):
        sh, dh = nodes[src_i], nodes[dst_i]
        bucket, prox = edge_attrs.get((sh, dh), (None, None))
        responsible_edges.append(
            {
                "src": sh,
                "dst": dh,
                "amount_bucket": bucket,
                "threshold_proximity": prox,
                "influence": round(float(weight), 3),
            }
        )

    responsible_features = [
        {"feature": f, "importance": round(float(w), 3)}
        for f, w in explanation.get("feature_importance", [])
    ]

    structured = {
        "pattern": pattern,
        "target_account": target_hash,
        "score": round(float(candidate.get("score", 0.0)), 4),
        "institutions": candidate.get("institutions", []),
        "responsible_edges": responsible_edges,
        "responsible_features": responsible_features,
        "n_edges_considered": explanation.get("n_edges", 0),
        "has_evidence": bool(responsible_edges),
    }
    structured["text"] = _render(structured)
    return structured


def _render(s: dict) -> str:
    """Compose the plain-language evidence sentence from the structured object."""
    desc = _PATTERN_DESC.get(s["pattern"], s["pattern"])
    target = short(s["target_account"]) if s["target_account"] else "?"
    insts = ", ".join(s["institutions"]) if s["institutions"] else "one institution"
    head = (
        f"Account {target} was flagged for {s['pattern'].replace('_', ' ')} "
        f"(laundering score {s['score']:.2f}), i.e. {desc}. "
        f"Institutions involved: {insts}."
    )

    if not s["has_evidence"]:
        return (
            head
            + " No incoming transactions drove the score (structural/first-seen signal only) — "
            "treat as low-confidence evidence pending review."
        )

    hops = []
    for e in s["responsible_edges"]:
        bit = f"{short(e['src'])}→{short(e['dst'])}"
        if e["amount_bucket"]:
            bit += f" ({e['amount_bucket']}"
            if e["threshold_proximity"] == "high":
                bit += ", near reporting threshold"
            bit += ")"
        hops.append(bit)
    edges_txt = " The transactions most responsible for the score: " + "; ".join(hops) + "."

    feats_txt = ""
    if s["responsible_features"]:
        names = [_friendly(f["feature"]) for f in s["responsible_features"][:3]]
        feats_txt = " Most influential account features: " + ", ".join(names) + "."

    return head + edges_txt + feats_txt
