"""mTLS Kafka producer — replays detect-window transactions as pseudonymised edges.

Each institution's producer pseudonymises **in-process** and publishes only pseudonymised edges to
its **own** ``edges_INST_X`` topic over the mTLS listener. ACLs ensure it can write only its own
topic.
It also publishes a per-window ``count_commitments`` message so selective withholding is
detectable. ``confluent-kafka`` is imported lazily so the pure code stays import-safe.
"""

from __future__ import annotations

import json
import os
import time

from . import commitments, edge


def ssl_config(broker: str, cafile: str, certfile: str, keyfile: str) -> dict:
    """confluent-kafka SSL/mTLS client config (hostname check off for local dev certs)."""
    return {
        "bootstrap.servers": broker,
        "security.protocol": "SSL",
        "ssl.ca.location": cafile,
        "ssl.certificate.location": certfile,
        "ssl.key.location": keyfile,
        "ssl.endpoint.identification.algorithm": "none",
    }


def ssl_config_from_env() -> dict:
    """Build the client config from the KAFKA_* env vars."""
    return ssl_config(
        os.environ.get("KAFKA_BROKER", "localhost:9093"),
        os.environ["KAFKA_SSL_CAFILE"],
        os.environ["KAFKA_SSL_CERTFILE"],
        os.environ["KAFKA_SSL_KEYFILE"],
    )


class EdgeProducer:
    """Publishes pseudonymised edges to the institution's own topic + count commitments."""

    def __init__(self, institution: str, config: dict):
        from confluent_kafka import Producer

        self.institution = institution
        self.topic = f"edges_{institution}"
        self._producer = Producer(config)

    def publish_edge(self, edge_dict: dict) -> None:
        """Send one pseudonymised edge, keyed by event_id (idempotency).

        ``poll(0)`` serves delivery callbacks so the internal queue drains as messages are
        acked; on a full queue (large replays exceed the default 100k buffer) we poll to make
        room and retry rather than dropping the edge.
        """
        payload = json.dumps(edge_dict).encode()
        while True:
            try:
                self._producer.produce(self.topic, key=edge_dict["event_id"], value=payload)
                break
            except BufferError:
                self._producer.poll(0.5)  # let deliveries complete, then retry
        self._producer.poll(0)

    def publish_commitment(self, window_start: int, txn_count: int) -> None:
        msg = commitments.build_message(self.institution, window_start, txn_count)
        self._producer.produce("count_commitments", value=json.dumps(msg).encode())

    def flush(self, timeout: float = 10.0) -> None:
        self._producer.flush(timeout)


def replay_partition(
    institution: str,
    partition,
    salt: str | bytes,
    config: dict,
    rate: float | None = None,
) -> int:
    """Replay one institution's detect-window partition as pseudonymised edges.

    Runs pseudonymisation per row (with a no-leak guard), publishes to the own topic, then a
    count commitment for the window. ``rate`` (edges/sec) throttles for a live demo; ``None``
    is as-fast-as-possible. Returns the number of edges published.
    """
    producer = EdgeProducer(institution, config)
    count = 0
    window_start: int | None = None
    for row in partition.to_dict("records"):
        pseudonymised = edge.build_edge(row, salt, institution)
        edge.assert_no_raw_leak(
            pseudonymised, row["from_account"], row["to_account"], row["amount_paid"]
        )
        producer.publish_edge(pseudonymised)
        window_start = pseudonymised["timestamp"] if window_start is None else window_start
        count += 1
        if rate:
            time.sleep(1.0 / rate)
    producer.publish_commitment(window_start or 0, count)
    producer.flush()
    return count
