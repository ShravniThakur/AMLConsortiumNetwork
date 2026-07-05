"""Count commitments — detecting selective withholding.

Each institution publishes ``SHA256(institution_id + window_start + txn_count)`` per window.
If an institution later withholds transactions selectively, its published edge count won't
match the committed count, so withholding becomes **detectable** rather than silent. The
commitment proves *count*, not *content* (the residual limit is documented).
"""

from __future__ import annotations

import hashlib
import hmac


def commitment(institution_id: str, window_start: int, txn_count: int) -> str:
    """SHA-256 hex commitment to a window's transaction count."""
    msg = f"{institution_id}{window_start}{txn_count}".encode()
    return hashlib.sha256(msg).hexdigest()


def verify(institution_id: str, window_start: int, observed_count: int, committed: str) -> bool:
    """True iff the observed edge count reproduces the published commitment."""
    return hmac.compare_digest(commitment(institution_id, window_start, observed_count), committed)


def build_message(institution_id: str, window_start: int, txn_count: int) -> dict:
    """The ``count_commitments`` Kafka payload."""
    return {
        "institution_id": institution_id,
        "window_start": window_start,
        "commitment": commitment(institution_id, window_start, txn_count),
    }
