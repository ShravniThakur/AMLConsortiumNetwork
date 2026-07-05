"""Train GraphSAGE on the pseudonymised merged graph.

Trains on the graph engine's **own** merged graph — the same pseudonymised representation it scores
on — so train and inference use identical features. Privacy holds: the merged graph carries only
hashes + buckets (no raw identity/amount ever leaves a bank).

Transductive node classification: fetch the merged graph from Neo4j, reconstruct the bucket
features, join labels via the shared salt (offline eval only), train on a stratified node mask, and
report recall@5%FPR + AUC on the held-out mask. Saves the checkpoint the graph engine loads.

Env: NEO4J_PASSWORD, ACN_SHARED_SALT. Usage:
    NEO4J_PASSWORD=... ACN_SHARED_SALT=... python scripts/train_gnn.py \\
        --splits-dir acn-data/data/splits/detect \\
        --out acn-data/models/gnn/graphsage_final.pt
"""

from __future__ import annotations

import argparse
import glob
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acn.gnn import metrics  # noqa: E402
from acn.graph import chain_features, db, score  # noqa: E402
from acn.pseudonymise import hashing  # noqa: E402


def _labels(splits_dir: str, salt: str) -> dict[str, int]:
    """hash -> 1 if the account touched any laundering transaction (offline label join)."""
    df = pd.concat(
        [pd.read_parquet(f) for f in glob.glob(f"{splits_dir}/INST_*.parquet")], ignore_index=True
    )
    lab: dict[str, int] = {}
    for r in df.itertuples(index=False):
        for inst, acct in ((r.src_institution, r.from_account), (r.dst_institution, r.to_account)):
            h = hashing.hash_account(salt, inst, str(acct))
            lab[h] = max(lab.get(h, 0), int(r.is_laundering))
    return lab


def main() -> int:
    import os

    import torch
    from sklearn.model_selection import train_test_split

    from acn.gnn.model import IN_DIM, GraphSAGE, normalise_features, weighted_bce

    ap = argparse.ArgumentParser(description="GraphSAGE training on the merged graph.")
    ap.add_argument("--splits-dir", default="acn-data/data/splits/detect")
    ap.add_argument("--out", default="acn-data/models/gnn/graphsage_final.pt")
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--lr", type=float, default=0.01)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--test-size", type=float, default=0.3)
    args = ap.parse_args()

    salt = os.environ.get("ACN_SHARED_SALT")
    if not salt:
        print("ERROR: ACN_SHARED_SALT not set.")
        return 1

    driver = db.connect()
    try:
        wide = (
            int(pd.Timestamp("2022-01-01").timestamp()),
            int(pd.Timestamp("2023-01-01").timestamp()),
        )
        graph = score.fetch_graph(driver, *wide)
        # ref_ts MUST match detection (the actual window end), not the wide fetch bound: age and
        # velocity features are relative to ref_ts, so a mismatch silently skews deployed scores.
        with driver.session() as sess:
            hi = sess.run("MATCH ()-[r:SENT]->() RETURN max(r.timestamp) AS hi").single()["hi"]
        ref_ts = int(hi) + 1
        nodes, feats, ei = score.reconstruct_features(graph, ref_ts=ref_ts)
        # Append the chain-aware block (Cypher path findings) → the model sees long-range structure.
        chain = chain_features.compute(driver, *wide)
        feats = chain_features.append(nodes, feats, chain)
        print(f"[gnn] chain features: {len(chain):,} accounts in a detected chain")
    finally:
        driver.close()
    lab = _labels(args.splits_dir, salt)
    y = np.array([lab.get(h, 0) for h in nodes])
    print(
        f"[gnn] merged graph: {len(nodes):,} nodes, {ei.shape[1]:,} edges, "
        f"{int(y.sum())} laundering ({y.mean():.3%})"
    )

    idx = np.arange(len(nodes))
    tr, te = train_test_split(idx, test_size=args.test_size, random_state=args.seed, stratify=y)

    torch.manual_seed(args.seed)
    x = torch.tensor(normalise_features(feats), dtype=torch.float)
    edge_index = torch.tensor(ei, dtype=torch.long)
    yt = torch.tensor(y, dtype=torch.float)
    trm = torch.zeros(len(nodes), dtype=torch.bool)
    trm[tr] = True

    net = GraphSAGE(in_dim=IN_DIM)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    t0 = time.perf_counter()
    for _ in range(args.epochs):
        net.train()
        opt.zero_grad()
        loss = weighted_bce(net(x, edge_index)[trm], yt[trm])
        loss.backward()
        opt.step()
    net.eval()
    with torch.no_grad():
        prob = torch.sigmoid(net(x, edge_index)).numpy()
    auc = metrics.auc_roc(y[te], prob[te])
    rec = metrics.recall_at_fpr(y[te], prob[te], fpr=0.05)
    print(
        f"[gnn] trained {args.epochs} epochs in {time.perf_counter() - t0:.0f}s | "
        f"held-out AUC {auc:.3f} | recall@5%FPR {rec:.3f}"
    )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    torch.save(net.state_dict(), args.out)
    print(f"[gnn] saved checkpoint → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
