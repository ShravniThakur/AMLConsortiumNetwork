"""Assemble an investigation case from an alert.

A *case* is what a compliance officer works from: the alert, its GNNExplainer evidence string, and
the accounts in the evidence subgraph — all **pseudonymised**. Resolution to real account ids is a
separate, per-institution step (``resolve_for``): each involved bank sees *its own* accounts
resolved and every other bank's account as a hash only. So the central case store never holds a raw
identity; the privacy boundary from detection carries straight through to case management.
"""

from __future__ import annotations

from . import resolve as resolve_mod

_CASE_QUERY = """
MATCH (al:Alert {alert_id: $alert_id})-[:EVIDENCE]->(n:Account)
RETURN al.pattern AS pattern, al.score AS score, al.recipients AS recipients,
       al.created_ts AS created_ts, al.evidence_text AS evidence_text,
       collect({hash: n.hash, institution: n.institution_id}) AS accounts
"""


def assemble_case(driver, alert_id: str) -> dict | None:
    """Build the pseudonymised case for ``alert_id`` from Neo4j, or None if it doesn't exist."""
    with driver.session() as session:
        rec = session.run(_CASE_QUERY, alert_id=alert_id).single()
    if rec is None or not rec["accounts"]:
        return None
    return {
        "alert_id": alert_id,
        "pattern": rec["pattern"],
        "score": rec["score"],
        "institutions": sorted(rec["recipients"] or []),
        "created_ts": rec["created_ts"],
        "evidence_text": rec["evidence_text"],
        "accounts": [{"hash": a["hash"], "institution": a["institution"]} for a in rec["accounts"]],
        "status": "open",
    }


def resolve_for(r, case: dict, institution: str) -> dict:
    """Return a copy of ``case`` with *only* ``institution``'s own accounts resolved to real ids.

    Accounts owned by other institutions keep hash-only — a bank is never shown another bank's
    real account. This is the per-institution view a filing officer at ``institution`` works from.
    """
    view = dict(case)
    accounts = []
    for a in case["accounts"]:
        entry = dict(a)
        if a["institution"] == institution:
            entry["account_id"] = resolve_mod.resolve(r, institution, a["hash"])
        accounts.append(entry)
    view["accounts"] = accounts
    view["viewing_institution"] = institution
    return view
