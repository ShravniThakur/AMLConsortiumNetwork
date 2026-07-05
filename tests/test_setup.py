"""Setup smoke tests.

Deterministic tests here run everywhere and prove the scaffold is coherent: the package
imports, the health-aggregation logic behaves, and the Drive layout builder works. The
service-touching test is marked ``requires_services`` and skips when the stack is down —
so CI (no Kafka/Neo4j) stays green while a local run with the stack up actually exercises
``/health``.
"""

from __future__ import annotations

import importlib

import pytest

ACN_SUBPACKAGES = [
    "acn",
    "acn.data",
    "acn.gnn",
    "acn.pseudonymise",
    "acn.graph",
    "acn.explain",
    "acn.casemgmt",
]


@pytest.mark.parametrize("module", ACN_SUBPACKAGES)
def test_package_imports(module: str) -> None:
    """Every acn subpackage imports cleanly (the scaffold is wired up)."""
    assert importlib.import_module(module) is not None


def test_health_report_shape_when_deps_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no services reachable, gather_health reports every dep + flags degraded.

    This runs the real probes against unreachable hosts (fast, short timeouts) and asserts
    the *contract*: core deps down => degraded True, and the report carries all four keys.
    """
    # Point probes at a definitely-closed port so they fail fast and deterministically.
    monkeypatch.setenv("NEO4J_URI", "bolt://127.0.0.1:1")
    monkeypatch.setenv("NEO4J_PASSWORD", "x")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("KAFKA_BROKER", "127.0.0.1:1")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")

    from services.api import health

    report, degraded = health.gather_health()
    assert set(report) == {"neo4j", "redis", "kafka", "ollama"}
    assert degraded is True
    assert report["kafka"] == health.ERROR


@pytest.mark.requires_services
def test_health_endpoint_live(require_api: str) -> None:
    """When the stack is up, /health returns the documented shape (skips otherwise)."""
    import httpx

    resp = httpx.get(f"{require_api}/health", timeout=5.0)
    body = resp.json()
    assert body["status"] in {"ok", "degraded"}
    for dep in ("neo4j", "redis", "kafka", "ollama"):
        assert dep in body
