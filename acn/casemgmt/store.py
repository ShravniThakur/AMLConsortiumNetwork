"""Case list + officer decisions, persisted on the Alert node in Neo4j.

A case is an alert plus its lifecycle. The officer's decision is the only thing that moves a case
out of ``open`` — the system never files or closes on its own. ``under_investigation`` on the
evidence accounts transitions ``true -> false`` only here, by an explicit decision (matching the
detection-side rule that it may only go ``false -> true`` inside alert creation).
"""

from __future__ import annotations

import time

# What an officer may decide. "file" preserves the case (a filed STR is archived, never pruned);
# "dismiss" clears the investigation hold; "escalate" keeps it open for a senior reviewer.
VALID_DECISIONS = {"file", "dismiss", "escalate"}

_LIST = """
MATCH (al:Alert)-[:EVIDENCE]->(n:Account)
WITH al, collect(DISTINCT n.institution_id) AS insts
WHERE $status IS NULL OR coalesce(al.case_status, 'open') = $status
RETURN al.alert_id AS alert_id, al.pattern AS pattern, al.score AS score,
       coalesce(al.case_status, 'open') AS status, al.created_ts AS created_ts,
       [i IN insts WHERE i IS NOT NULL] AS institutions
ORDER BY al.score DESC
LIMIT $limit
"""

# One transaction: record the decision on the alert, and (for a terminal decision) release the
# investigation hold on the evidence accounts unless the case was filed (filed => archived).
_DECIDE = """
MATCH (al:Alert {alert_id: $alert_id})
SET al.case_status = $status, al.decided_by = $officer, al.decided_ts = $ts
WITH al
OPTIONAL MATCH (al)-[:EVIDENCE]->(n:Account)
FOREACH (_ IN CASE WHEN $release THEN [1] ELSE [] END |
  SET n.under_investigation = false)
RETURN al.alert_id AS alert_id, al.case_status AS status
"""

_STATUS_FOR = {"file": "filed", "dismiss": "dismissed", "escalate": "escalated"}


def list_cases(driver, status: str | None = None, limit: int = 50) -> list[dict]:
    """List cases (alerts) as summaries, optionally filtered by lifecycle status."""
    with driver.session() as s:
        return s.run(_LIST, status=status, limit=limit).data()


def record_decision(driver, alert_id: str, decision: str, officer: str) -> dict:
    """Apply an officer's decision to a case. Raises ValueError on an unknown decision."""
    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"invalid decision {decision!r}; expected one of {sorted(VALID_DECISIONS)}"
        )
    status = _STATUS_FOR[decision]
    release = decision == "dismiss"  # only a dismissal releases the hold; a filed case stays held
    with driver.session() as s:
        rec = s.execute_write(
            lambda tx: tx.run(
                _DECIDE,
                alert_id=alert_id,
                status=status,
                officer=officer,
                ts=int(time.time()),
                release=release,
            ).single()
        )
    if rec is None:
        raise KeyError(f"no case for alert {alert_id}")
    return {"alert_id": rec["alert_id"], "status": rec["status"], "decided_by": officer}
