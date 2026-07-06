"""Graph-engine runner (Units 05–06) — runs on the local Mac against Kafka/Neo4j/Redis.

Phases (``--phase``):

  ingest  Consume the pseudonymised ``edges_INST_*`` topics (server principal, group
          ``acn-graph-engine``) and MERGE them into Neo4j until the stream goes idle.
  detect  Run the six Cypher detection layers over the detect window, score candidates with the
          GraphSAGE checkpoint (if given), and raise **targeted** alerts (atomic evidence write +
          emit to ``alerts``).
  explain run GNNExplainer on the top-``--max-explain`` alerts and attach a plain-language
          evidence string (which hops + features drove the score) to each Alert; write a report.
  ttl     Prune edges/orphans past the 90-day TTL (respects ``under_investigation``).
  all     ingest → detect (no ttl/explain; prune is scheduled, explain is on-alert).

Env: NEO4J_* (creds), REDIS_URL, KAFKA_BROKER + KAFKA_SSL_* (server cert for the ``alerts``
producer and the edge consumer). Records node/edge counts, per-layer hits, and latency to stdout
for the execution log. No raw id/amount/salt is ever printed.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acn.data.schema import DETECT_END, DETECT_START  # noqa: E402
from acn.graph import alert, chain_features, db, ingest, score, ttl  # noqa: E402
from acn.pseudonymise import producer as kafka_producer  # noqa: E402

GROUP_ID = "acn-graph-engine"  # the consumer group the server principal is ACL'd for
IDLE_POLLS = 20  # consecutive empty polls that mean "stream drained"


def _window(driver=None) -> tuple[int, int]:
    """Detection window. Derived from the actual edge timestamps in Neo4j when a driver is given
    (whole laundering chains span a wide, sample-dependent range — a hardcoded window would miss
    them); falls back to the schema DETECT_START/END constants otherwise.
    """
    if driver is not None:
        with driver.session() as s:
            rec = s.run(
                "MATCH ()-[r:SENT]->() RETURN min(r.timestamp) AS lo, max(r.timestamp) AS hi"
            ).single()
        if rec and rec["lo"] is not None:
            return int(rec["lo"]), int(rec["hi"]) + 1
    start = int(pd.Timestamp(DETECT_START).timestamp())
    end = int(pd.Timestamp(DETECT_END).timestamp()) + 86400
    return start, end


def phase_ingest(driver) -> None:
    from acn.pseudonymise.consumer import IdempotentConsumer

    config = kafka_producer.ssl_config_from_env()
    config |= {"group.id": GROUP_ID, "auto.offset.reset": "earliest", "enable.auto.commit": True}
    writer = ingest.Neo4jEdgeWriter(driver, batch_size=1000)
    consumer = IdempotentConsumer(config, sink=writer.write)
    processed = idle = 0
    try:
        while idle < IDLE_POLLS:
            outcome = consumer.poll_once(timeout=1.0)
            if outcome is None:
                idle += 1
                continue
            idle = 0
            if outcome == "processed":
                processed += 1
    finally:
        writer.flush()
        consumer.close()
    print(f"[ingest] processed={processed} dead_letters={len(consumer.deduper.dead_letters)}")
    print(f"[ingest] graph now: {ingest.counts(driver)}")


def phase_detect(driver, checkpoint: str | None) -> None:
    from acn.graph.layers import ALL_LAYERS

    start, end = _window(driver)
    # Run + time each layer individually so a slow/variable-length layer is visible immediately
    # (path_tracker / round_trip expand paths and are the ones to watch on the full graph).
    candidates: list[dict] = []
    for layer in ALL_LAYERS:
        t0 = time.perf_counter()
        hits = layer.detect(driver, start, end)
        dt = (time.perf_counter() - t0) * 1000
        flag = "  <-- over 100ms budget" if dt > 100 else ""
        print(f"[detect] {layer.PATTERN}: {len(hits)} candidates in {dt:.0f} ms{flag}")
        candidates.extend(hits)
    print(f"[detect] {len(candidates)} candidates total")

    graph = score.fetch_graph(driver, start, end)
    if checkpoint and os.path.exists(checkpoint):
        model = score.load_model(checkpoint)
        nodes, feats, ei, ea = score.reconstruct_features(graph, ref_ts=end)
        # Same chain-aware block the model was trained with (Cypher path findings).
        feats = chain_features.append(nodes, feats, chain_features.compute(driver, start, end))
        probs = score.score_graph(model, feats, ei, ea)
        score.score_candidates(candidates, nodes, probs)
        print(f"[detect] scored {len(candidates)} candidates with DirMultigraphSAGE")
    else:
        print(f"[detect] no checkpoint at {checkpoint!r}; skipping model scoring")

    prod = None
    if os.environ.get("KAFKA_SSL_CERTFILE"):
        from confluent_kafka import Producer

        prod = Producer(kafka_producer.ssl_config_from_env())
    raised = 0
    for c in candidates:
        if not c.get("institutions"):
            continue  # no owned account in evidence → nothing to route (correct)
        alert.raise_alert(driver, c, window_start=start, created_ts=int(time.time()), producer=prod)
        raised += 1
    print(f"[detect] raised {raised} targeted alerts")


def phase_ttl(driver) -> None:
    result = ttl.prune(driver, now_ts=int(time.time()))
    print(f"[ttl] {result}")


def phase_explain(driver, checkpoint: str, max_explain: int, report: str) -> None:
    """Explain the top-scoring alerts: GNNExplainer → evidence attached to each Alert."""
    from collections import Counter

    from acn.explain import evidence as ev
    from acn.explain import gnn_explainer as gx

    start, end = _window(driver)
    graph = score.fetch_graph(driver, start, end)
    nodes, feats, ei, ea = score.reconstruct_features(graph, ref_ts=end)
    # Append the same chain-aware feature block the model was trained + detected with, or the
    # feature width won't match the checkpoint's input dim and the forward pass fails.
    feats = chain_features.append(nodes, feats, chain_features.compute(driver, start, end))
    idx = {h: i for i, h in enumerate(nodes)}
    model = score.load_model(checkpoint)
    probs = score.score_graph(model, feats, ei, ea)
    edge_attrs = {(e[0], e[1]): (e[2], e[3]) for e in graph["edges"]}
    in_deg = Counter(e[1] for e in graph["edges"])  # per-hash inflow count

    with driver.session() as s:
        alerts = s.run(
            "MATCH (al:Alert)-[:EVIDENCE]->(n:Account) "
            "RETURN al.alert_id AS id, al.pattern AS pattern, al.score AS score, "
            "collect(n.hash) AS nodes, "
            "collect(DISTINCT n.institution_id) AS insts "
            "ORDER BY al.score DESC LIMIT $lim",
            lim=max_explain,
        ).data()

    explainer = gx.build_explainer(model)
    edge_counts, attached, sample_text = [], 0, ""
    for a in alerts:
        ev_nodes = [h for h in a["nodes"] if h in idx]
        if not ev_nodes:
            continue
        # Explain the highest-scoring node that actually has inflow (where the model has edges to
        # attribute); fall back to plain max-prob (→ honestly flagged feature-only evidence).
        with_inflow = [h for h in ev_nodes if in_deg.get(h, 0) > 0]
        target = max(with_inflow or ev_nodes, key=lambda h: probs[idx[h]])
        res = gx.explain_node(explainer, feats, ei, idx[target], edge_attr=ea)
        insts = sorted(i for i in a["insts"] if i)
        candidate = {
            "pattern": a["pattern"],
            "nodes": a["nodes"],
            "institutions": insts,
            "score": a["score"],
        }
        evidence = ev.build_evidence(candidate, res, nodes, edge_attrs)
        alert.attach_evidence(driver, a["id"], evidence)
        edge_counts.append(res["n_edges"])
        attached += 1
        if not sample_text and evidence["has_evidence"]:
            sample_text = evidence["text"]

    mean_edges = sum(edge_counts) / len(edge_counts) if edge_counts else 0
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(
        f"# GNNExplainer report\n\n"
        f"- Checkpoint: `{checkpoint}`\n"
        f"- Alerts explained: {attached} (top-{max_explain} by score)\n"
        f"- Mean edges per explanation: {mean_edges:.2f}\n\n"
        f"## Sample evidence\n\n> {sample_text or '(none had incoming-edge evidence)'}\n"
    )
    print(f"[explain] attached evidence to {attached} alerts; mean edges/expl {mean_edges:.2f}")
    print(f"[explain] report → {report}")


def main() -> int:
    ap = argparse.ArgumentParser(description="ACN graph engine (Units 05–06).")
    ap.add_argument("--phase", choices=["ingest", "detect", "ttl", "explain", "all"], default="all")
    ap.add_argument("--checkpoint", default="acn-data/models/gnn/multigraph_final.pt")
    ap.add_argument("--max-explain", type=int, default=50, help="How many top alerts to explain")
    ap.add_argument("--report", default="acn-data/logs/explain_report.md")
    args = ap.parse_args()

    driver = db.connect()
    try:
        if args.phase in ("ingest", "all"):
            phase_ingest(driver)
        if args.phase in ("detect", "all"):
            phase_detect(driver, args.checkpoint)
        if args.phase == "ttl":
            phase_ttl(driver)
        if args.phase == "explain":
            phase_explain(driver, args.checkpoint, args.max_explain, args.report)
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
