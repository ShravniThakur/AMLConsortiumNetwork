"""Ownership-based HMAC-SHA256 account hashing — the linchpin.

Every account is hashed with **its owning institution's id** (for the destination, derived
from the To-Bank column → ``dst_institution``), keyed by the shared salt — never with the
*publishing* institution's id. So when bank X sends to an account at bank Y, both X (as
observer) and Y (as owner) produce the **same** hash for that account, keeping the
cross-institution graph connected without revealing identity.

HMAC-SHA256, not plain SHA-256, to close length-extension attacks. The salt is the most
sensitive secret in the system — it is passed in from the environment and **never logged**.
"""

from __future__ import annotations

import hashlib
import hmac


def _salt_bytes(salt: str | bytes) -> bytes:
    return salt if isinstance(salt, bytes) else salt.encode("utf-8")


def hash_account(salt: str | bytes, owning_institution: str, account_id: str) -> str:
    """HMAC-SHA256(key=salt, msg=owning_institution + account_id) as hex.

    Keyed on the **owning** institution, so the same real account always yields the same
    hash regardless of who publishes the edge (the connectivity guarantee).
    """
    msg = f"{owning_institution}{account_id}".encode()
    return hmac.new(_salt_bytes(salt), msg, hashlib.sha256).hexdigest()


def make_event_id(
    salt: str | bytes,
    publishing_institution: str,
    from_account: str,
    to_account: str,
    amount: float,
    timestamp: int,
) -> str:
    """Deterministic, globally-unique event id (HMAC of the transaction's identity).

    Deterministic per transaction, so replaying the same transaction yields the same id and
    Neo4j ``MERGE`` on it is idempotent. The raw fields are only *hashed* in,
    never exposed.
    """
    msg = f"{publishing_institution}|{from_account}|{to_account}|{amount}|{timestamp}".encode()
    return hmac.new(_salt_bytes(salt), msg, hashlib.sha256).hexdigest()
