"""Shared Redis client.

A single decode-responses Redis connection from ``REDIS_URL``. Used by the case-management
owner-side resolution map (``resolve:{institution}`` hashes) and the ``/health`` probe. ``redis`` is
imported lazily so the pure logic and its tests need no server.
"""

from __future__ import annotations

import os


def connect(url: str | None = None):
    """Return a decode-responses Redis client from ``REDIS_URL`` (or the given url)."""
    import redis

    return redis.Redis.from_url(
        url or os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
