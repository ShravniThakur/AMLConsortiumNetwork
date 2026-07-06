"""Assemble + emit a targeted alert with its evidence subgraph, atomically.

Two hard requirements from the spec:

- **Atomic alert + evidence.** An alert without its preserved evidence subgraph is useless for
  a downstream review, so the ``:Alert`` node, its ``:EVIDENCE`` links, and the
  ``under_investigation`` flags on the evidence accounts are written in **one** Neo4j
  transaction — all or nothing. ``under_investigation`` may only go ``false → true`` inside this
  transaction; it also shields those nodes from TTL pruning.
- **Targeted routing.** The alert carries only its involved institutions as
  ``recipients`` (computed by ``routing``); the Kafka emit is guarded so a broadcast can't slip
  through. Institutions don't read ``alerts`` directly — the server publishes it and FastAPI
  the alert consumer enforces per-institution visibility.

The payload is pseudonymised-only (hashes, pattern, score, recipients) — re-checked before emit.
No raw id/amount/salt ever appears in an alert.
"""

from __future__ import annotations

import hashlib
import json

from . import routing

ALERTS_TOPIC = "alerts"

# Cap the evidence-subgraph width carried by an alert. A hub (fan-out source, pass-through mid,
# fan-in target) can touch thousands of distinct counterparties in a window; carrying all of them
# would (a) blow past Kafka's ~1MB message limit on emit, and (b) flag thousands of leaf accounts
# `under_investigation` for one alert — unactionable to review and needlessly shielded from TTL.
# We keep the focal account plus a bounded, deterministic sample; the true width is recorded on the
# payload (`n_evidence_total`) so nothing is silently lost.
MAX_EVIDENCE_NODES = 500

# One transaction: create/merge the alert, link evidence, flag accounts under investigation.
_WRITE_ALERT = """
MATCH (a:Account) WHERE a.hash IN $nodes
WITH collect(a) AS ev
WHERE size(ev) > 0
MERGE (al:Alert {alert_id: $alert_id})
  ON CREATE SET al.pattern = $pattern, al.score = $score,
                al.created_ts = $created_ts, al.recipients = $recipients,
                al.timespan_days = $timespan_days
FOREACH (n IN ev |
  MERGE (al)-[:EVIDENCE]->(n)
  SET n.under_investigation = true)
RETURN al.alert_id AS alert_id, size(ev) AS n_evidence
"""


def alert_id(candidate: dict, window_start: int) -> str:
    """Deterministic id from pattern + sorted evidence nodes + window → idempotent re-runs.

    Uses the *full* node set (pre-cap), so the id is stable regardless of the evidence sample.
    """
    key = candidate["pattern"] + "|" + ",".join(sorted(candidate["nodes"])) + f"|{window_start}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _cap_evidence(candidate: dict) -> tuple[list[str], int]:
    """Return a sorted, width-capped evidence node list plus the true (pre-cap) node count.

    Deterministic (sorted then truncated) and focus-preserving: if the candidate names a focal
    account (``meta.focus`` — the hub/mid/target every layer records) it is always kept in the
    sample even when it sorts past the cap, so the account the alert is *about* is never dropped.
    """
    nodes = sorted(set(candidate["nodes"]))
    n_total = len(nodes)
    if n_total <= MAX_EVIDENCE_NODES:
        return nodes, n_total
    sample = nodes[:MAX_EVIDENCE_NODES]
    focus = candidate.get("meta", {}).get("focus")
    if focus and focus not in sample:
        sample[-1] = focus  # guarantee the focal account survives the cut
    return sorted(sample), n_total


def build_alert(
    candidate: dict, window_start: int, created_ts: int, explanation: dict | None = None
) -> dict:
    """Assemble the pseudonymised alert payload with its targeted recipient list.

    ``explanation`` is optional and additive: when given, its plain-language ``text``
    and structured evidence ride along in the payload so a downstream reviewer can
    show *why* the alert fired. It is pseudonymised-only, same as the rest of the payload.
    """
    recipients = routing.route(candidate)  # raises on broadcast / empty (guard)
    evidence, n_total = _cap_evidence(candidate)
    alert = {
        "alert_id": alert_id(candidate, window_start),
        "pattern": candidate["pattern"],
        "score": round(float(candidate.get("score", 0.0)), 6),
        "timespan_days": candidate.get("timespan_days", 0),
        "recipients": recipients,
        "evidence": evidence,
        "created_ts": created_ts,
    }
    if n_total > len(evidence):
        # Evidence was capped; record the real width so downstream isn't misled by the sample.
        alert["n_evidence_total"] = n_total
    if explanation is not None:
        alert["evidence_text"] = explanation.get("text", "")
        alert["explanation"] = explanation
    return alert


def _assert_safe(alert: dict) -> None:
    """Guard: an alert must have evidence and non-broadcast recipients before it leaves."""
    if not alert.get("evidence"):
        raise ValueError("refusing to emit an alert with no evidence subgraph")
    if not alert.get("recipients"):
        raise ValueError("refusing to emit an alert with no recipients (unactionable)")


def persist(driver, alert: dict) -> int:
    """Write the alert + evidence + under_investigation flags in one atomic transaction.

    Returns the evidence-node count. Raises if no evidence node matched (the alert is not written
    at all — never a partial state).
    """
    _assert_safe(alert)
    with driver.session() as session:
        rec = session.execute_write(
            lambda tx: tx.run(
                _WRITE_ALERT,
                nodes=alert["evidence"],
                alert_id=alert["alert_id"],
                pattern=alert["pattern"],
                score=alert["score"],
                timespan_days=alert.get("timespan_days", 0),
                recipients=alert["recipients"],
                created_ts=alert["created_ts"],
            ).single()
        )
    if rec is None:
        raise ValueError(f"alert {alert['alert_id']} matched no evidence node — not persisted")
    return rec["n_evidence"]


def attach_evidence(driver, the_alert_id: str, evidence: dict) -> bool:
    """Store an explanation on an existing Alert node (additive; pseudonymised-only).

    ``evidence.text`` goes on ``al.evidence_text`` and the structured object as ``al.evidence_json``
    so the STR/UI can render it. Returns True if the alert existed and was updated.
    """
    payload = json.dumps({k: v for k, v in evidence.items() if k != "text"})
    with driver.session() as session:
        rec = session.execute_write(
            lambda tx: tx.run(
                "MATCH (al:Alert {alert_id: $id}) "
                "SET al.evidence_text = $text, al.evidence_json = $json "
                "RETURN al.alert_id AS id",
                id=the_alert_id,
                text=evidence.get("text", ""),
                json=payload,
            ).single()
        )
    return rec is not None


def emit(alert: dict, producer=None, topic: str = ALERTS_TOPIC) -> None:
    """Publish the alert to the ``alerts`` topic (server principal). Targeted, never broadcast.

    ``producer`` is injectable so tests need no broker. The evidence is already persisted in
    Neo4j before this call, so a failed emit loses no evidence — it can be retried.
    """
    _assert_safe(alert)
    if producer is None:
        return
    producer.produce(topic, value=json.dumps(alert).encode())
    producer.flush()


def raise_alert(driver, candidate: dict, window_start: int, created_ts: int, producer=None) -> dict:
    """End to end: build → persist atomically → emit. Returns the alert payload."""
    alert = build_alert(candidate, window_start, created_ts)
    alert["n_evidence"] = persist(driver, alert)
    emit(alert, producer=producer)
    return alert
