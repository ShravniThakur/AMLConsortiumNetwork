"""Ingest pseudonymised edges into Neo4j.

Consumes the ``edges_INST_*`` topics (via the idempotent consumer) and MERGEs
each edge into the cross-institution graph. The UNIQUE constraint on ``Account.hash`` is what
collapses the *same* ownership-hashed account — published by any institution — onto **one**
node, which is what makes cross-institution layering visible. ``MERGE`` on
``event_id`` makes the write idempotent under replay/restart, matching the consumer's dedupe.

Writes are **batched** (UNWIND) because the detect window is ~150k edges; a per-edge round
trip would dominate ingest time. ``Neo4jEdgeWriter.write`` is drop-in as the consumer sink.

Security: only pseudonymised fields ever reach Neo4j (hashes, bucket, proximity flag,
timestamp, institution) — re-verified here against the pseudonymised-edge schema before any write.
"""

from __future__ import annotations

from ..pseudonymise.edge import EDGE_KEYS

# The account_id / amount are never present; these are the only keys we persist.
_ALLOWED = EDGE_KEYS

# One MERGE per edge, run over a batch via UNWIND. Ownership hashing means the publisher only
# knows its own (src) institution, so dst.institution_id is left for dst's owner to set when it
# publishes that account as a sender — never guessed here.
_MERGE = """
UNWIND $rows AS row
MERGE (s:Account {hash: row.src_hash})
  ON CREATE SET s.institution_id = row.publishing_institution, s.first_seen_ts = row.timestamp
  ON MATCH  SET s.first_seen_ts = CASE
      WHEN s.first_seen_ts IS NULL OR row.timestamp < s.first_seen_ts
      THEN row.timestamp ELSE s.first_seen_ts END
MERGE (d:Account {hash: row.dst_hash})
  ON CREATE SET d.first_seen_ts = row.timestamp
  ON MATCH  SET d.first_seen_ts = CASE
      WHEN d.first_seen_ts IS NULL OR row.timestamp < d.first_seen_ts
      THEN row.timestamp ELSE d.first_seen_ts END
FOREACH (_ IN CASE WHEN row.event_type = 'transfer' THEN [1] ELSE [] END |
  MERGE (s)-[e:SENT {event_id: row.event_id}]->(d)
    ON CREATE SET e.amount_bucket = row.amount_bucket,
                  e.threshold_proximity = row.threshold_proximity,
                  e.timestamp = row.timestamp)
"""


def _clean(edge: dict) -> dict:
    """Keep only the locked pseudonymised keys — a defensive guard against a raw-field leak."""
    extra = set(edge) - _ALLOWED
    if extra:
        raise ValueError(f"edge has non-pseudonymised keys, refusing to ingest: {extra}")
    return edge


class Neo4jEdgeWriter:
    """Buffer edges and MERGE them into Neo4j in batches. Usable as the consumer sink."""

    def __init__(self, driver, batch_size: int = 1000):
        self._driver = driver
        self._batch_size = batch_size
        self._buffer: list[dict] = []
        self.total_written = 0

    def write(self, edge: dict) -> None:
        """Sink entry point: validate + buffer one edge, flushing when the batch fills."""
        self._buffer.append(_clean(edge))
        if len(self._buffer) >= self._batch_size:
            self.flush()

    def flush(self) -> int:
        """MERGE the buffered edges in one transaction; return how many were written."""
        if not self._buffer:
            return 0
        rows, self._buffer = self._buffer, []
        with self._driver.session() as session:
            session.execute_write(lambda tx: tx.run(_MERGE, rows=rows).consume())
        self.total_written += len(rows)
        return len(rows)

    def __enter__(self) -> Neo4jEdgeWriter:
        return self

    def __exit__(self, *exc) -> None:
        self.flush()


def counts(driver) -> dict[str, int]:
    """Return node/edge counts — recorded in the execution log after a replay."""
    with driver.session() as session:
        nodes = session.run("MATCH (n:Account) RETURN count(n) AS c").single()["c"]
        edges = session.run("MATCH ()-[r:SENT]->() RETURN count(r) AS c").single()["c"]
    return {"accounts": nodes, "sent_edges": edges}
