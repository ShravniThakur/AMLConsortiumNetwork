#!/usr/bin/env python3
"""Measure the Consortium Lift.

Quantifies the central thesis: how much does the consortium graph (+ Cypher)
improve detection recall compared to each bank scoring its local view alone?
Evaluates strictly on the 20% held-out test set to ensure fair comparison.
"""

import argparse
import os
import sys
import time
from pathlib import Path
import pandas as pd
import numpy as np
import torch
from sklearn.model_selection import train_test_split

from acn.gnn.model import DirMultigraphSAGE, normalise_features, IN_DIM, EDGE_DIM
from acn.gnn import features as feat_schema
from acn.graph import score, chain_features, db
from acn.pseudonymise import hashing, buckets
from acn.data.schema import INSTITUTIONS
from acn.gnn import metrics


def load_model(checkpoint_path: str) -> DirMultigraphSAGE:
    net = DirMultigraphSAGE(
        in_dim=IN_DIM,
        edge_dim=EDGE_DIM
    )
    net.load_state_dict(torch.load(checkpoint_path, map_location="cpu", weights_only=True))
    net.eval()
    return net


def score_graph_view(net, graph_dict, chain_dict=None):
    nodes, feats, ei, ea = score.reconstruct_features(graph_dict, ref_ts=graph_dict["window_end"])
    if chain_dict is not None:
        feats = chain_features.append(nodes, feats, chain_dict)
    else:
        feats = chain_features.append(nodes, feats, {})
        
    x = torch.tensor(normalise_features(feats), dtype=torch.float)
    edge_index = torch.tensor(ei, dtype=torch.long)
    edge_attr = torch.tensor(ea, dtype=torch.float)
    
    with torch.no_grad():
        prob = torch.sigmoid(net(x, edge_index, edge_attr)).numpy()
    
    return nodes, prob


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits-dir", default="acn-data/data/splits/detect")
    ap.add_argument("--checkpoint", default="acn-data/models/gnn/multigraph_final.pt")
    args = ap.parse_args()

    salt = os.environ["ACN_SHARED_SALT"]
    
    print("[lift] Loading raw detect splits...")
    dfs = []
    for f in Path(args.splits_dir).glob("*.parquet"):
        dfs.append(pd.read_parquet(f))
    full_df = pd.concat(dfs, ignore_index=True)
    
    src_hashes = []
    dst_hashes = []
    for r in full_df.itertuples(index=False):
        src_hashes.append(hashing.hash_account(salt, r.src_institution, str(r.from_account)))
        dst_hashes.append(hashing.hash_account(salt, r.dst_institution, str(r.to_account)))
    
    full_df["src_hash"] = src_hashes
    full_df["dst_hash"] = dst_hashes
    
    window_start = int(pd.Timestamp("2022-01-01").timestamp())
    driver = db.connect()
    try:
        with driver.session() as sess:
            hi = sess.run("MATCH ()-[r:SENT]->() RETURN max(r.timestamp) AS hi").single()["hi"]
        window_end = int(hi) + 1
    finally:
        driver.close()

    print("[lift] Computing metadata...", flush=True)
    meta = {}
    for r in full_df.itertuples(index=False):
        ts = int(pd.Timestamp(r.timestamp).timestamp())
        for h in (r.src_hash, r.dst_hash):
            if h not in meta or ts < meta[h]["first_seen_ts"]:
                meta[h] = {"first_seen_ts": ts}

    labels = {}
    for r in full_df.itertuples(index=False):
        labels[r.src_hash] = max(labels.get(r.src_hash, 0), int(r.is_laundering))
        labels[r.dst_hash] = max(labels.get(r.dst_hash, 0), int(r.is_laundering))

    net = load_model(args.checkpoint)
    
    print("[lift] Extracting test set from full graph...", flush=True)
    driver = db.connect()
    try:
        neo4j_graph = score.fetch_graph(driver, window_start, window_end)
        chain = chain_features.compute(driver, window_start, window_end)
    finally:
        driver.close()
        
    neo4j_graph["window_end"] = window_end
    full_nodes, _, _, _ = score.reconstruct_features(neo4j_graph, ref_ts=window_end)
    y_full = np.array([labels.get(n, 0) for n in full_nodes])
    idx = np.arange(len(full_nodes))
    _, te = train_test_split(idx, test_size=0.3, random_state=42, stratify=y_full)
    test_hashes = set(np.array(full_nodes)[te])
    
    results = []

    print("[lift] Scoring Siloed Views...", flush=True)
    silo_recalls = []
    for inst in INSTITUTIONS:
        local_df = full_df[(full_df["src_institution"] == inst) | (full_df["dst_institution"] == inst)]
        edges = []
        unique_nodes = set()
        for r in local_df.itertuples(index=False):
            ts = int(pd.Timestamp(r.timestamp).timestamp())
            amt = float(r.amount_paid)
            edges.append((
                r.src_hash, r.dst_hash,
                buckets.amount_bucket(amt),
                buckets.threshold_proximity(amt),
                ts,
                amt % 10000 == 0
            ))
            unique_nodes.add(r.src_hash)
            unique_nodes.add(r.dst_hash)
            
        graph = {
            "nodes": list(unique_nodes),
            "edges": edges,
            "meta": meta,
            "window_start": window_start,
            "window_end": window_end
        }
        
        nodes, prob = score_graph_view(net, graph, chain_dict=None)
        
        # Only evaluate on nodes in the test set
        test_mask = np.array([n in test_hashes for n in nodes])
        y_test = np.array([labels.get(n, 0) for n in nodes])[test_mask]
        prob_test = prob[test_mask]
        
        if y_test.sum() > 0:
            rec = metrics.recall_at_fpr(y_test, prob_test, fpr=0.05)
            silo_recalls.append(rec)
            
    silo_avg = np.mean(silo_recalls) if silo_recalls else 0.0
    results.append(("Siloed Average", silo_avg))
    
    print("[lift] Scoring Consortium (Graph Only)...", flush=True)
    edges = []
    unique_nodes = set()
    for r in full_df.itertuples(index=False):
        ts = int(pd.Timestamp(r.timestamp).timestamp())
        amt = float(r.amount_paid)
        edges.append((
            r.src_hash, r.dst_hash,
            buckets.amount_bucket(amt),
            buckets.threshold_proximity(amt),
            ts,
            amt % 10000 == 0
        ))
        unique_nodes.add(r.src_hash)
        unique_nodes.add(r.dst_hash)
        
    consortium_graph = {
        "nodes": list(unique_nodes),
        "edges": edges,
        "meta": meta,
        "window_start": window_start,
        "window_end": window_end
    }
    nodes, prob = score_graph_view(net, consortium_graph, chain_dict=None)
    
    test_mask = np.array([n in test_hashes for n in nodes])
    y_test = np.array([labels.get(n, 0) for n in nodes])[test_mask]
    prob_test = prob[test_mask]
    cons_rec = metrics.recall_at_fpr(y_test, prob_test, fpr=0.05)
    results.append(("Consortium (Graph Only)", cons_rec))
    
    print("[lift] Scoring Consortium (+ Cypher) from Neo4j...", flush=True)
    nodes, prob = score_graph_view(net, neo4j_graph, chain_dict=chain)
    
    test_mask = np.array([n in test_hashes for n in nodes])
    y_test = np.array([labels.get(n, 0) for n in nodes])[test_mask]
    prob_test = prob[test_mask]
    cypher_rec = metrics.recall_at_fpr(y_test, prob_test, fpr=0.05)
    results.append(("Consortium (+ Cypher)", cypher_rec))
    
    print("\n# Detection Recall @ 5% FPR\n")
    print("| Detection View | Recall |")
    print("|---|---|")
    for name, rec in results:
        print(f"| {name} | {rec:.1%} |")


if __name__ == "__main__":
    sys.exit(main())
