"""Neo4j connection helper for the graph engine.

One place to open a driver so every module (ingest, layers, ttl, score, alert) connects the
same way. ``neo4j`` is imported lazily so the pure detection-query builders and their tests
need no driver installed.

Host quirk (mirrors Kafka's advertised-listener fix): ``.env`` ships
``NEO4J_URI=bolt://neo4j:7687`` — the *docker-internal* hostname. Inside the compose network
(the FastAPI container) ``neo4j`` is the correct, reachable hostname; a process on the host Mac
cannot resolve it and must reach the mapped port on ``localhost``. ``connect()`` rewrites the
docker hostname to ``localhost`` **only when it isn't resolvable** (i.e. we're on the host), so
the same ``.env`` works both inside a container and from the host without breaking either.
"""

from __future__ import annotations

import os
import socket

_DOCKER_HOST = "neo4j"


def resolve_uri(uri: str | None = None) -> str:
    """Return a host-reachable Bolt URI.

    Rewrites the docker-internal ``neo4j`` hostname to ``localhost`` only if it does not resolve —
    which is true on the host Mac but false inside the compose network, where ``neo4j`` is correct.
    """
    uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    if f"//{_DOCKER_HOST}:" not in uri:
        return uri
    try:
        socket.gethostbyname(_DOCKER_HOST)
        return uri  # resolvable → we're inside the docker network; keep neo4j:7687
    except OSError:
        return uri.replace(f"//{_DOCKER_HOST}:", "//localhost:")  # host Mac → mapped port


def connect(uri: str | None = None, user: str | None = None, password: str | None = None):
    """Open a Neo4j driver from the environment (or explicit args). Caller closes it.

    Credentials come from ``NEO4J_USER`` / ``NEO4J_PASSWORD`` (never hard-coded, never logged).
    """
    from neo4j import GraphDatabase

    return GraphDatabase.driver(
        resolve_uri(uri),
        auth=(
            user or os.environ.get("NEO4J_USER", "neo4j"),
            password or os.environ["NEO4J_PASSWORD"],
        ),
    )
