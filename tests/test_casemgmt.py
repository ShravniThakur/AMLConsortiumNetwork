"""Case-management tests: owner-side resolution, per-institution case views, draft STR.

Pure tests use a dict-backed fake Redis; the live case-assembly test hits Neo4j and skips when the
DB is unreachable.
"""

from __future__ import annotations

import os
import uuid

import pandas as pd
import pytest

from acn.casemgmt import case as case_mod
from acn.casemgmt import resolve as resolve_mod
from acn.casemgmt import str_draft
from acn.pseudonymise import hashing


class FakeRedis:
    """Minimal Redis hash store for the pure resolution tests."""

    def __init__(self):
        self.h: dict[str, dict[str, str]] = {}

    def hset(self, key, field=None, value=None, mapping=None):
        d = self.h.setdefault(key, {})
        if mapping:
            d.update({str(k): str(v) for k, v in mapping.items()})
        if field is not None:
            d[str(field)] = str(value)

    def hget(self, key, field):
        return self.h.get(key, {}).get(str(field))


SALT = "test-salt"


# ------------------------------------------------------------------- owner-side resolution


def test_resolution_is_owner_only():
    r = FakeRedis()
    h_a = hashing.hash_account(SALT, "INST_A", "acct-1")
    resolve_mod.write_resolution(r, "INST_A", h_a, "acct-1")
    # the owner resolves its own account
    assert resolve_mod.resolve(r, "INST_A", h_a) == "acct-1"
    # a different institution cannot resolve it (separate namespace)
    assert resolve_mod.resolve(r, "INST_B", h_a) is None


def test_build_from_partition_hashes_owned_accounts():
    r = FakeRedis()
    part = pd.DataFrame(
        {
            "from_account": ["a1", "a2"],
            "to_account": ["b1", "a1"],
            "src_institution": ["INST_A", "INST_A"],
            "dst_institution": ["INST_B", "INST_A"],
        }
    )
    n = resolve_mod.build_from_partition(r, "INST_A", part, SALT)
    # INST_A owns a1, a2 (senders) and a1 (its own receiver) -> {a1, a2}
    assert n == 2
    assert resolve_mod.resolve(r, "INST_A", hashing.hash_account(SALT, "INST_A", "a1")) == "a1"
    # b1 is owned by INST_B, so INST_A's map must not contain it
    assert resolve_mod.resolve(r, "INST_A", hashing.hash_account(SALT, "INST_B", "b1")) is None


# --------------------------------------------------------------------- per-institution view


def _case():
    return {
        "alert_id": "abc123",
        "pattern": "round_trip",
        "score": 0.91,
        "institutions": ["INST_A", "INST_B"],
        "created_ts": 1_726_000_000,
        "evidence_text": "Account x returned funds via y and z.",
        "accounts": [
            {"hash": "hA", "institution": "INST_A"},
            {"hash": "hB", "institution": "INST_B"},
        ],
        "status": "open",
    }


def test_resolve_for_only_resolves_own_accounts():
    r = FakeRedis()
    resolve_mod.write_resolution(r, "INST_A", "hA", "real-A")
    resolve_mod.write_resolution(r, "INST_B", "hB", "real-B")

    view = case_mod.resolve_for(r, _case(), "INST_A")
    by_inst = {a["institution"]: a for a in view["accounts"]}
    assert view["viewing_institution"] == "INST_A"
    assert by_inst["INST_A"]["account_id"] == "real-A"  # own account resolved
    assert "account_id" not in by_inst["INST_B"]  # other bank stays hash-only


# ------------------------------------------------------------------------------- draft STR


def test_template_draft_is_pseudonymised_for_other_banks_and_never_files():
    r = FakeRedis()
    resolve_mod.write_resolution(r, "INST_A", "hA", "real-A")
    view = case_mod.resolve_for(r, _case(), "INST_A")

    d = str_draft.draft(view, use_llm=False)
    assert d["requires_human_review"] is True
    assert d["filed"] is False
    assert d["source"] == "template"
    text = d["narrative"]
    assert "DRAFT SUSPICIOUS TRANSACTION REPORT" in text
    assert "real-A" in text  # the reporting bank's own account appears resolved
    assert "real-B" not in text  # the other bank's account never resolved
    assert "hB"[:12] not in text or "pseudonymised" in text  # other bank stays pseudonymised


def test_template_mentions_pattern_and_officer_gate():
    r = FakeRedis()
    view = case_mod.resolve_for(r, _case(), "INST_A")
    text = str_draft.render_template(view)
    assert "cycle layering" in text  # round_trip phrasing
    assert "must verify" in text and "No report is submitted automatically" in text


# ------------------------------------------------------------------------ live Neo4j assembly


def test_assemble_case_from_alert():
    from acn.graph import alert, db, ingest

    if "NEO4J_PASSWORD" not in os.environ:
        pytest.skip("NEO4J_PASSWORD not set")
    try:
        driver = db.connect()
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Neo4j unavailable: {exc}")

    p = f"case_{uuid.uuid4().hex[:8]}_"
    try:
        edges = [
            {
                "event_id": f"{p}a-mid",
                "event_type": "transfer",
                "src_hash": p + "a",
                "dst_hash": p + "mid",
                "amount_bucket": "bucket_4",
                "threshold_proximity": "low",
                "timestamp": 1_726_000_000,
                "publishing_institution": "INST_A",
            },
            {
                "event_id": f"{p}mid-b",
                "event_type": "transfer",
                "src_hash": p + "mid",
                "dst_hash": p + "b",
                "amount_bucket": "bucket_4",
                "threshold_proximity": "low",
                "timestamp": 1_726_000_600,
                "publishing_institution": "INST_B",
            },
        ]
        with ingest.Neo4jEdgeWriter(driver) as w:
            for e in edges:
                w.write(e)
        candidate = {
            "pattern": "sliding_window",
            "nodes": [p + "a", p + "mid", p + "b"],
            "institutions": ["INST_A", "INST_B"],
            "score": 0.88,
        }
        raised = alert.raise_alert(driver, candidate, window_start=1_726_000_000, created_ts=1)
        c = case_mod.assemble_case(driver, raised["alert_id"])
        assert c is not None
        assert c["pattern"] == "sliding_window"
        assert len(c["accounts"]) == 3
        assert set(c["institutions"]) == {"INST_A", "INST_B"}
    finally:
        with driver.session() as s:
            s.run(
                "MATCH (al:Alert)-[:EVIDENCE]->(n:Account) WHERE n.hash STARTS WITH $p "
                "DETACH DELETE al",
                p=p,
            )
            s.run("MATCH (a:Account) WHERE a.hash STARTS WITH $p DETACH DELETE a", p=p)
        driver.close()
