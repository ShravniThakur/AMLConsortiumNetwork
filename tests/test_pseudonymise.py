"""Pseudonymisation property tests — the privacy boundary in code.

Highest-value tests in the project: hash determinism + ownership, the no-raw-data-leak
property, fixed bucket boundaries, and count-commitment correctness. All pure stdlib
(hmac/hashlib), so they run everywhere.
"""

from __future__ import annotations

import json

import pytest

from acn.pseudonymise import buckets, commitments, consumer, edge, hashing

SALT = "unit-04-test-salt"


def _row(from_account, to_account, src_inst, dst_inst, amount=5000.0, ts="2022-09-11 10:00:00"):
    return {
        "from_account": from_account,
        "to_account": to_account,
        "src_institution": src_inst,
        "dst_institution": dst_inst,
        "amount_paid": amount,
        "timestamp": ts,
    }


# ----------------------------------------------------------- hash ownership rule
def test_same_account_hashes_identically_regardless_of_publisher():
    # Account "ACC" is owned by INST_B. Whether INST_A sends TO it or INST_B sends FROM it,
    # both edges must carry the SAME hash for that account (ownership-based hashing).
    e_to = edge.build_edge(_row("S1", "ACC", "INST_A", "INST_B"), SALT, "INST_A")
    e_from = edge.build_edge(_row("ACC", "T1", "INST_B", "INST_C"), SALT, "INST_B")
    assert e_to["dst_hash"] == e_from["src_hash"]

    # A third publisher (INST_D) sending to the same owned account → same hash again.
    e_other = edge.build_edge(_row("S9", "ACC", "INST_D", "INST_B"), SALT, "INST_D")
    assert e_other["dst_hash"] == e_to["dst_hash"]


def test_different_owner_gives_different_hash():
    a = hashing.hash_account(SALT, "INST_B", "ACC")
    b = hashing.hash_account(SALT, "INST_C", "ACC")  # same account string, different owner
    assert a != b


def test_hash_is_hmac_not_plain_sha256():
    # HMAC depends on the salt (key); plain SHA-256 would not change with the salt.
    assert hashing.hash_account("salt-1", "INST_B", "ACC") != hashing.hash_account(
        "salt-2", "INST_B", "ACC"
    )


# ----------------------------------------------------------------- no-leak property
def test_no_raw_account_or_amount_in_published_edge():
    e = edge.build_edge(
        _row("SRC-ACCOUNT-123", "DST-ACCOUNT-456", "INST_A", "INST_B", amount=987654.0),
        SALT,
        "INST_A",
    )
    # exact key set, and none of the raw values appear anywhere in the message
    assert set(e) == set(edge.EDGE_KEYS)
    edge.assert_no_raw_leak(e, "SRC-ACCOUNT-123", "DST-ACCOUNT-456", 987654.0)  # must not raise
    values = " ".join(str(v) for v in e.values())
    assert "SRC-ACCOUNT-123" not in values and "DST-ACCOUNT-456" not in values
    assert "987654" not in values
    assert e["amount_bucket"].startswith("bucket_")


def test_assert_no_raw_leak_catches_a_leak():
    leaky = {"src_hash": "ACC", "event_type": "transfer"}  # raw account leaked as a value
    with pytest.raises(ValueError, match="leaked"):
        edge.assert_no_raw_leak(leaky, "ACC", "T1", 100.0)


# --------------------------------------------------------------------- buckets
def test_bucket_boundaries():
    assert buckets.amount_bucket(9_000) == "bucket_1"  # ≤ ₹10K
    assert buckets.amount_bucket(10_000) == "bucket_1"  # boundary lands in lower bucket
    assert buckets.amount_bucket(10_001) == "bucket_2"
    assert buckets.amount_bucket(5_000_000) == "bucket_9"  # ₹50L boundary
    assert buckets.amount_bucket(9_000_000) == "bucket_10"  # > ₹50L


def test_threshold_proximity_band():
    assert buckets.threshold_proximity(950_000) == "high"  # within 10% of ₹10L
    assert buckets.threshold_proximity(1_050_000) == "high"
    assert buckets.threshold_proximity(500_000) == "low"
    assert buckets.threshold_proximity(2_000_000) == "low"


# ---------------------------------------------------------------- commitments
def test_commitment_verifies_and_detects_tampering():
    c = commitments.commitment("INST_A", 1_662_000_000, txn_count=1234)
    assert commitments.verify("INST_A", 1_662_000_000, 1234, c) is True
    assert commitments.verify("INST_A", 1_662_000_000, 1233, c) is False  # withheld one txn
    msg = commitments.build_message("INST_A", 1_662_000_000, 1234)
    assert msg["commitment"] == c and msg["institution_id"] == "INST_A"


# ---------------------------------------------------------------- idempotency key
def test_event_id_is_deterministic_and_unique():
    r = _row("A", "B", "INST_A", "INST_B")
    e1 = edge.build_edge(r, SALT, "INST_A")
    e2 = edge.build_edge(r, SALT, "INST_A")
    assert e1["event_id"] == e2["event_id"]  # replay → same id → MERGE idempotent
    e_diff = edge.build_edge(_row("A", "C", "INST_A", "INST_B"), SALT, "INST_A")
    assert e_diff["event_id"] != e1["event_id"]


# ---------------------------------------------------------------- consumer idempotency
def test_consumer_dedupes_on_replay():
    sunk = []
    dedupe = consumer.EdgeDeduper(sink=sunk.append)
    e = edge.build_edge(_row("A", "B", "INST_A", "INST_B"), SALT, "INST_A")
    raw = json.dumps(e).encode()

    assert dedupe.handle(raw) == "processed"
    assert dedupe.handle(raw) == "duplicate"  # replay of the same edge → skipped
    assert len(sunk) == 1  # the sink saw it exactly once

    assert dedupe.handle(b"not json") == "invalid"
    assert dedupe.handle(json.dumps({"no": "event_id"}).encode()) == "invalid"
    assert len(dedupe.dead_letters) == 2  # malformed → dead-letter, consumer survives
