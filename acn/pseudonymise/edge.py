"""Assemble the pseudonymised-edge message.

Turns one raw transaction into the pseudonymised edge published to Kafka:
hashed src/dst (ownership-based), a fixed amount bucket, a
threshold-proximity flag, the timestamp, and the publishing institution — **never** a raw
account id or the exact amount. ``build_edge`` is the single choke point where a raw
transaction becomes safe to transport; ``assert_no_raw_leak`` is its guard.
"""

from __future__ import annotations

import pandas as pd

from . import buckets, hashing

# The complete set of keys a pseudonymised edge may contain (schema lock).
EDGE_KEYS = frozenset(
    {
        "event_id",
        "event_type",
        "src_hash",
        "dst_hash",
        "amount_bucket",
        "threshold_proximity",
        "timestamp",
        "publishing_institution",
    }
)


def build_edge(
    row, salt: str | bytes, publishing_institution: str, event_type: str = "transfer"
) -> dict:
    """Build the pseudonymised edge for one transaction row.

    ``row`` needs ``from_account``, ``to_account``, ``src_institution`` (owner of the source =
    the publisher), ``dst_institution`` (owner of the destination, from To-Bank), ``amount_paid``
    and ``timestamp``. The source is hashed with the **publisher's** institution (it owns the
    sending account); the destination with ``dst_institution`` — the ownership rule.
    """
    from_account = str(row["from_account"])
    to_account = str(row["to_account"])
    amount = float(row["amount_paid"])
    ts = int(pd.Timestamp(row["timestamp"]).timestamp())
    src_owner = str(row["src_institution"])
    dst_owner = str(row["dst_institution"])

    return {
        "event_id": hashing.make_event_id(
            salt, publishing_institution, from_account, to_account, amount, ts
        ),
        "event_type": event_type,
        "src_hash": hashing.hash_account(salt, src_owner, from_account),
        "dst_hash": hashing.hash_account(salt, dst_owner, to_account),
        "amount_bucket": buckets.amount_bucket(amount),
        "threshold_proximity": buckets.threshold_proximity(amount),
        "timestamp": ts,
        "publishing_institution": publishing_institution,
    }


def assert_no_raw_leak(edge: dict, from_account: str, to_account: str, amount: float) -> None:
    """Fail loudly if a raw account id or the exact amount appears in the edge (a leak).

        A defensive guard for the producer — a pseudonymisation leak is a stop-the-line bug
    , so we check rather than trust.
    """
    if set(edge) - EDGE_KEYS:
        raise ValueError(f"edge has unexpected keys: {set(edge) - EDGE_KEYS}")
    raw = {str(from_account), str(to_account), str(amount), str(float(amount))}
    for value in edge.values():
        if str(value) in raw:
            raise ValueError("raw account id / amount leaked into a pseudonymised edge")
