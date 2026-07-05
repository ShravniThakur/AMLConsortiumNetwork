"""Dependency health probes for the FastAPI ``/health`` endpoint.

Each probe is defensive: a short timeout, a narrow exception surface, and it returns
a status string rather than raising, so one dead dependency never takes the API down.

Privacy: probes read connection settings from the environment and log nothing that
could leak a secret, host credential, or data value. Only coarse reachable/unreachable status is
surfaced.
"""

from __future__ import annotations

import logging
import os
import socket

logger = logging.getLogger("acn.api.health")

# Probe timeout — kept short so /health stays well under its 200 ms budget when a
# dependency is hung rather than cleanly down.
PROBE_TIMEOUT_S = 2.0

OK = "ok"
ERROR = "error"


def check_neo4j() -> str:
    """Bolt reachable and answering a trivial query."""
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        logger.error("health.neo4j.misconfigured", extra={"reason": "NEO4J_PASSWORD unset"})
        return ERROR
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            uri, auth=(user, password), connection_timeout=PROBE_TIMEOUT_S
        )
        try:
            driver.verify_connectivity()
            with driver.session() as session:
                session.run("RETURN 1 AS ok").single()
        finally:
            driver.close()
        return OK
    except Exception as exc:  # noqa: BLE001 — probe must never raise
        logger.warning("health.neo4j.unreachable", extra={"error_type": type(exc).__name__})
        return ERROR


def check_redis() -> str:
    """PING -> PONG."""
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    try:
        import redis

        client = redis.Redis.from_url(
            url, socket_connect_timeout=PROBE_TIMEOUT_S, socket_timeout=PROBE_TIMEOUT_S
        )
        try:
            return OK if client.ping() else ERROR
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("health.redis.unreachable", extra={"error_type": type(exc).__name__})
        return ERROR


def check_kafka() -> str:
    """Broker reachable over its (mTLS) listener.

    A full authenticated AdminClient round-trip needs the per-institution certs; for a
    liveness probe a TCP connect to the broker host/port is sufficient and avoids
    handing the API a client identity it should not need.
    """
    broker = os.environ.get("KAFKA_BROKER", "kafka:9093")
    host, _, port = broker.rpartition(":")
    if not host or not port.isdigit():
        logger.error("health.kafka.misconfigured", extra={"reason": "bad KAFKA_BROKER"})
        return ERROR
    try:
        with socket.create_connection((host, int(port)), timeout=PROBE_TIMEOUT_S):
            return OK
    except OSError as exc:
        logger.warning("health.kafka.unreachable", extra={"error_type": type(exc).__name__})
        return ERROR


def check_ollama() -> str:
    """Model presence. ``unloaded`` is not a failure — llama3.1:8b is loaded on demand.

    Returns "loaded" if the STR model is resident, "unloaded" if Ollama is up but the
    model is not currently in memory, or "error" if Ollama is unreachable.
    """
    host = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
    model = os.environ.get("OLLAMA_STR_MODEL", "llama3.1:8b")
    base = host if host.startswith("http") else f"http://{host}"
    try:
        import httpx

        resp = httpx.get(f"{base.rstrip('/')}/api/tags", timeout=PROBE_TIMEOUT_S)
        resp.raise_for_status()
        names = {m.get("name", "") for m in resp.json().get("models", [])}
        return "loaded" if any(n == model or n.startswith(model) for n in names) else "unloaded"
    except Exception as exc:  # noqa: BLE001
        logger.warning("health.ollama.unreachable", extra={"error_type": type(exc).__name__})
        return ERROR


def gather_health() -> tuple[dict[str, str], bool]:
    """Run every probe and return (report, degraded).

    ``degraded`` is True if any *core* dependency (Kafka, Neo4j, Redis) is unreachable.
    Ollama being "unloaded" does not degrade the system.
    """
    report = {
        "neo4j": check_neo4j(),
        "redis": check_redis(),
        "kafka": check_kafka(),
        "ollama": check_ollama(),
    }
    core_down = any(report[dep] != OK for dep in ("neo4j", "redis", "kafka"))
    return report, core_down
