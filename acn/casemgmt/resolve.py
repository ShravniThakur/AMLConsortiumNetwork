"""Owner-side hash → account resolution.

A pseudonymised graph deliberately can't be reversed by anyone holding it — that is the whole
privacy property. But the **owning** institution knows its own customers and the shared salt, so
it (and only it) can map the hashes of *its own* accounts back to real account ids in order to
investigate and file a report. That inverse map is therefore **owner-only**: kept per-institution,
never centralised, and a bank can resolve only the accounts it owns.

We model each institution's private map as a namespaced Redis hash ``resolve:{institution}``
(``hash -> account_id``). On one machine this is a single Redis; conceptually each namespace lives
inside its owning bank. ``redis`` is imported lazily so the pure logic/tests need no server.
"""

from __future__ import annotations

from ..pseudonymise import hashing


def resolve_key(institution: str) -> str:
    return f"resolve:{institution}"


def write_resolution(r, institution: str, account_hash: str, account_id: str) -> None:
    """Record ``account_hash -> account_id`` in the owning institution's private map."""
    r.hset(resolve_key(institution), account_hash, account_id)


def resolve(r, institution: str, account_hash: str) -> str | None:
    """Return the real account id for a hash **owned by** ``institution``, or None.

    Looks only in that institution's namespace — a bank cannot resolve another bank's hashes.
    """
    return r.hget(resolve_key(institution), account_hash)


def build_from_partition(r, institution: str, partition, salt: str) -> int:
    """Populate ``institution``'s owner map from its own transaction rows; return entries written.

    Hashes every account the institution owns (senders it publishes + local receivers) the same
    ownership way the pseudonymiser does, and stores the inverse. Run per institution, on that
    institution's own data — the map never leaves it.
    """
    seen: dict[str, str] = {}
    for row in partition.itertuples(index=False):
        if getattr(row, "src_institution", None) == institution:
            acct = str(row.from_account)
            seen[hashing.hash_account(salt, institution, acct)] = acct
        if getattr(row, "dst_institution", None) == institution:
            acct = str(row.to_account)
            seen[hashing.hash_account(salt, institution, acct)] = acct
    if seen:
        r.hset(resolve_key(institution), mapping=seen)
    return len(seen)
