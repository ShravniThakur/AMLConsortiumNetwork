"""Idempotent edge consumer.

The graph engine (server principal) consumes all five ``edges_INST_*`` topics. It must be
safe to re-run: on replay or restart it must not process the same edge twice. Dedupe is on
``event_id`` (the deterministic per-transaction id). ``EdgeDeduper`` holds the pure
parse+dedupe logic (testable without a broker); ``IdempotentConsumer`` wraps it with the
mTLS ``confluent-kafka`` client. The durable idempotency is Neo4j ``MERGE`` on ``event_id``
 — the sink is a callback so the graph engine plugs in the real Neo4j writer. Malformed
messages go to a dead-letter list, never crashing the consumer.
"""

from __future__ import annotations

import json
from collections.abc import Callable

EDGE_TOPICS = [f"edges_INST_{x}" for x in "ABCDE"]


class EdgeDeduper:
    """Parse + dedupe pseudonymised-edge messages; hand each *new* edge to ``sink``."""

    def __init__(self, sink: Callable[[dict], None]):
        self._sink = sink
        self._seen: set[str] = set()
        self.dead_letters: list[bytes] = []

    def handle(self, raw_value: bytes) -> str:
        """Process one raw message value → 'processed' | 'duplicate' | 'invalid'."""
        try:
            parsed = json.loads(raw_value)
            event_id = parsed["event_id"]
        except (ValueError, KeyError, TypeError):
            self.dead_letters.append(raw_value)
            return "invalid"
        if event_id in self._seen:
            return "duplicate"  # replay / restart — do not double-process
        self._seen.add(event_id)
        self._sink(parsed)
        return "processed"


class IdempotentConsumer:
    """mTLS Kafka consumer over the edge topics, deduping via ``EdgeDeduper``."""

    def __init__(self, config: dict, sink: Callable[[dict], None], topics=None):
        from confluent_kafka import Consumer

        self._consumer = Consumer(config)
        self._consumer.subscribe(topics or EDGE_TOPICS)
        self.deduper = EdgeDeduper(sink)

    def poll_once(self, timeout: float = 1.0) -> str | None:
        """Poll one message and handle it. Returns the outcome, or None if nothing/error."""
        msg = self._consumer.poll(timeout)
        if msg is None or msg.error():
            return None
        return self.deduper.handle(msg.value())

    def close(self) -> None:
        self._consumer.close()
