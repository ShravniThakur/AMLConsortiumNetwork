"""Graph-engine tests.

Two tiers:

- **Pure** (always run): bucket midpoints, feature reconstruction, targeted routing + its
  broadcast guard, alert assembly + atomicity guards. No services needed.
- **Live Neo4j** (skipped if the DB is unreachable): each detection layer finds its planted
  pattern on a small fixture, ingest is idempotent, and the alert write is atomic (evidence +
  ``under_investigation`` together). Test nodes are namespaced with a per-run prefix and removed
  in teardown, so this never touches real graph data.
"""

from __future__ import annotations

import os
import uuid

import pytest

from acn.graph import alert, ingest, routing, score
from acn.graph.layers import (
    coordinated_new_accounts,
    flow_conservation,
    path_tracker,
    round_trip,
    sliding_window,
)
from acn.pseudonymise import buckets

BASE_TS = 1_726_000_000  # a fixed reference inside the detect window
DAY = 86400


# --------------------------------------------------------------------------- pure tests


def test_bucket_midpoints_monotonic_and_covered():
    mids = [buckets.bucket_midpoint(f"bucket_{i}") for i in range(1, buckets.N_BUCKETS + 1)]
    assert len(mids) == 10
    assert mids == sorted(mids)  # strictly increasing bands
    assert mids[0] < 1e4 < mids[-1]  # first below the ₹10K edge, last well above


def test_routing_targets_only_involved():
    candidate = {
        "pattern": "round_trip",
        "nodes": ["h1", "h2"],
        "institutions": ["INST_A", "INST_B"],
    }
    assert routing.route(candidate) == ["INST_A", "INST_B"]


def test_routing_rejects_broadcast():
    candidate = {"pattern": "x", "nodes": ["h1"], "institutions": ["INST_A"]}
    with pytest.raises(ValueError, match="uninvolved"):
        routing.assert_targeted(["INST_A", "INST_C"], candidate)


def test_routing_rejects_empty():
    with pytest.raises(ValueError, match="no involved institution"):
        routing.route({"pattern": "x", "nodes": ["h1"], "institutions": []})


def test_alert_build_is_pseudonymised_and_deterministic():
    candidate = {
        "pattern": "sliding_window",
        "nodes": ["hb", "ha"],
        "institutions": ["INST_A"],
        "score": 0.87,
    }
    a1 = alert.build_alert(candidate, window_start=BASE_TS, created_ts=BASE_TS + 10)
    a2 = alert.build_alert(candidate, window_start=BASE_TS, created_ts=BASE_TS + 99)
    assert a1["alert_id"] == a2["alert_id"]  # id independent of created_ts
    assert a1["evidence"] == ["ha", "hb"]  # sorted
    assert a1["recipients"] == ["INST_A"]
    # only pseudonymised fields — no raw id/amount anywhere
    assert set(a1) == {"alert_id", "pattern", "score", "recipients", "evidence", "created_ts"}


def test_alert_emit_guards_against_no_evidence():
    with pytest.raises(ValueError, match="no evidence"):
        alert.emit({"recipients": ["INST_A"], "evidence": []})


def test_feature_reconstruction_shape_and_flow():
    # a -> mid -> b : mid receives one bucket_5 and forwards one bucket_5 (flow-conserving)
    graph = {
        "nodes": ["a", "mid", "b"],
        "meta": {
            "a": {"institution_id": "INST_A", "first_seen_ts": BASE_TS - 10 * DAY},
            "mid": {"institution_id": "INST_B", "first_seen_ts": BASE_TS - 5 * DAY},
            "b": {"institution_id": None, "first_seen_ts": BASE_TS - 2 * DAY},
        },
        "edges": [
            ("a", "mid", "bucket_5", BASE_TS),
            ("mid", "b", "bucket_5", BASE_TS + 60),
        ],
    }
    nodes, feats, edge_index = score.reconstruct_features(graph, ref_ts=BASE_TS + DAY)
    assert feats.shape == (3, len(score._FEATURES) + buckets.N_BUCKETS)
    assert edge_index.shape == (2, 2)
    col = {n: i for i, n in enumerate(score._FEATURES)}
    mid = nodes.index("mid")
    assert feats[mid, col["txn_count"]] == 1  # one outgoing
    assert feats[mid, col["in_degree"]] == 1  # one incoming
    # in ≈ out (both bucket_5) → flow_ratio ≈ out/(in+1) ≈ 1
    assert 0.9 < feats[mid, col["flow_ratio"]] < 1.1


def test_score_plumbing_with_fresh_model():
    torch = pytest.importorskip("torch")
    pytest.importorskip("torch_geometric")
    from acn.gnn.model import GraphSAGE

    graph = {
        "nodes": ["a", "b", "c"],
        "meta": {h: {"institution_id": "INST_A", "first_seen_ts": BASE_TS - DAY} for h in "abc"},
        "edges": [("a", "b", "bucket_3", BASE_TS), ("b", "c", "bucket_3", BASE_TS + 60)],
    }
    nodes, feats, ei = score.reconstruct_features(graph, ref_ts=BASE_TS + DAY)
    # base reconstruct width (Cypher chain features are appended in the real pipeline, not here)
    model = GraphSAGE(in_dim=feats.shape[1])
    model.eval()
    with torch.no_grad():
        probs = score.score_graph(model, feats, ei)
    assert probs.shape == (3,)
    assert ((0.0 <= probs) & (probs <= 1.0)).all()
    cands = score.score_candidates([{"nodes": ["a", "b"]}], nodes, probs)
    assert 0.0 <= cands[0]["score"] <= 1.0


# --------------------------------------------------------------------- live Neo4j fixtures


@pytest.fixture(scope="module")
def driver():
    from acn.graph import db

    if "NEO4J_PASSWORD" not in os.environ:
        pytest.skip("NEO4J_PASSWORD not set")
    try:
        d = db.connect()
        d.verify_connectivity()
    except Exception as exc:  # noqa: BLE001 — any conn*ion* failure just skips live tests
        pytest.skip(f"Neo4j unavailable: {exc}")
    yield d
    d.close()


@pytest.fixture
def prefix(driver):
    """A unique hash prefix per test so fixtures never collide with real data; cleaned up after."""
    p = f"test_{uuid.uuid4().hex[:8]}_"
    yield p
    with driver.session() as s:
        # alert_id is a hash (not prefixed) — delete alerts via their evidence linkage first,
        # while the :EVIDENCE edges to the test accounts still exist, then the accounts.
        s.run(
            "MATCH (al:Alert)-[:EVIDENCE]->(n:Account) WHERE n.hash STARTS WITH $p "
            "DETACH DELETE al",
            p=p,
        )
        s.run("MATCH (a:Account) WHERE a.hash STARTS WITH $p DETACH DELETE a", p=p)


def _edge(prefix, src, dst, ts, inst, bucket="bucket_4"):
    """Craft a pseudonymised edge dict (ingest input) with namespaced hashes."""
    return {
        "event_id": f"{prefix}{src}->{dst}@{ts}",
        "event_type": "transfer",
        "src_hash": prefix + src,
        "dst_hash": prefix + dst,
        "amount_bucket": bucket,
        "threshold_proximity": "low",
        "timestamp": ts,
        "publishing_institution": inst,
    }


def _ingest(driver, edges):
    with ingest.Neo4jEdgeWriter(driver, batch_size=1000) as w:
        for e in edges:
            w.write(e)


# ------------------------------------------------------------------------ live layer tests


def test_ingest_idempotent(driver, prefix):
    edges = [_edge(prefix, "a", "b", BASE_TS, "INST_A")]
    _ingest(driver, edges)
    _ingest(driver, edges)  # replay
    with driver.session() as s:
        n = s.run(
            "MATCH (:Account {hash:$h})-[r:SENT]->() RETURN count(r) AS c", h=prefix + "a"
        ).single()["c"]
    assert n == 1  # MERGE on event_id — no duplicate under replay


def test_sliding_window_detects_hop(driver, prefix):
    _ingest(
        driver,
        [
            _edge(prefix, "a", "mid", BASE_TS, "INST_A"),
            _edge(prefix, "mid", "b", BASE_TS + 600, "INST_B"),
        ],
    )
    hits = sliding_window.detect(driver, BASE_TS - DAY, BASE_TS + DAY)
    focuses = {h["meta"]["focus"] for h in hits}
    assert prefix + "mid" in focuses


def test_path_tracker_detects_cross_institution_chain(driver, prefix):
    _ingest(
        driver,
        [
            _edge(prefix, "a", "b", BASE_TS, "INST_A"),
            _edge(prefix, "b", "c", BASE_TS + DAY, "INST_B"),
            _edge(prefix, "c", "d", BASE_TS + 2 * DAY, "INST_A"),
        ],
    )
    hits = path_tracker.detect(driver, BASE_TS - DAY, BASE_TS + DAY, min_hops=3, max_hops=6)
    chain = {prefix + x for x in "abcd"}
    assert any(chain.issubset(set(h["nodes"])) for h in hits)


def test_round_trip_detects_cycle(driver, prefix):
    _ingest(
        driver,
        [
            _edge(prefix, "a", "b", BASE_TS, "INST_A"),
            _edge(prefix, "b", "c", BASE_TS + DAY, "INST_B"),
            _edge(prefix, "c", "a", BASE_TS + 2 * DAY, "INST_C"),
        ],
    )
    hits = round_trip.detect(driver, BASE_TS - DAY, BASE_TS + DAY)
    assert any(h["meta"]["focus"] == prefix + "a" for h in hits)


def test_flow_conservation_detects_passthrough(driver, prefix):
    # mid receives 2x bucket_6 and forwards 2x bucket_6 → in ≈ out
    _ingest(
        driver,
        [
            _edge(prefix, "s1", "mid", BASE_TS, "INST_A", bucket="bucket_6"),
            _edge(prefix, "s2", "mid", BASE_TS + 60, "INST_A", bucket="bucket_6"),
            _edge(prefix, "mid", "d1", BASE_TS + 120, "INST_B", bucket="bucket_6"),
            _edge(prefix, "mid", "d2", BASE_TS + 180, "INST_B", bucket="bucket_6"),
        ],
    )
    hits = flow_conservation.detect(driver, BASE_TS - DAY, BASE_TS + DAY)
    assert any(h["meta"]["focus"] == prefix + "mid" for h in hits)


def test_coordinated_new_accounts_detects_cluster(driver, prefix):
    # three accounts, all first-seen in a burst, funnel into one target
    _ingest(
        driver,
        [
            _edge(prefix, "n1", "target", BASE_TS, "INST_A"),
            _edge(prefix, "n2", "target", BASE_TS + 3600, "INST_B"),
            _edge(prefix, "n3", "target", BASE_TS + 7200, "INST_C"),
        ],
    )
    hits = coordinated_new_accounts.detect(
        driver, BASE_TS - DAY, BASE_TS + DAY, min_cluster=3, burst_seconds=DAY
    )
    assert any(h["meta"]["focus"] == prefix + "target" for h in hits)


def test_alert_persist_is_atomic(driver, prefix):
    _ingest(
        driver,
        [
            _edge(prefix, "a", "mid", BASE_TS, "INST_A"),
            _edge(prefix, "mid", "b", BASE_TS + 600, "INST_B"),
        ],
    )
    candidate = {
        "pattern": "sliding_window",
        "nodes": [prefix + "a", prefix + "mid", prefix + "b"],
        "institutions": ["INST_A", "INST_B"],
        "score": 0.9,
    }
    a = alert.raise_alert(driver, candidate, window_start=BASE_TS, created_ts=BASE_TS + 1)
    assert a["n_evidence"] == 3
    with driver.session() as s:
        # evidence linked AND accounts flagged, in the same write
        ev = s.run(
            "MATCH (al:Alert {alert_id:$id})-[:EVIDENCE]->(n:Account) "
            "RETURN count(n) AS c, "
            "sum(CASE WHEN n.under_investigation THEN 1 ELSE 0 END) AS flagged",
            id=a["alert_id"],
        ).single()
    assert ev["c"] == 3
    assert ev["flagged"] == 3
