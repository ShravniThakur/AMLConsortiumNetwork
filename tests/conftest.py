"""Shared pytest fixtures for ACN.

Two kinds of test live here: fast deterministic unit tests that run
everywhere (including CI), and service-dependent tests marked ``requires_services`` that
need the live Docker stack. The service fixtures below *skip* cleanly when a dependency is
unreachable — they never error the collector, so ``pytest`` is green on a machine with no
stack up.
"""

from __future__ import annotations

import os

import pytest

# The five fixed evaluation seeds.
EVAL_SEEDS = (42, 123, 456, 789, 1024)


@pytest.fixture(params=EVAL_SEEDS)
def seed(request: pytest.FixtureRequest) -> int:
    """Parametrised over the five fixed seeds — every reported metric is mean ± std."""
    return request.param


@pytest.fixture
def api_base_url() -> str:
    """Base URL of the FastAPI service for integration tests."""
    return os.environ.get("ACN_API_URL", "http://localhost:8000")


@pytest.fixture
def require_api(api_base_url: str):
    """Skip (not fail) if the FastAPI service is not reachable."""
    httpx = pytest.importorskip("httpx")
    try:
        httpx.get(f"{api_base_url}/health", timeout=2.0)
    except Exception:  # noqa: BLE001 — unreachable service => skip, not error
        pytest.skip("FastAPI /health not reachable — start the stack")
    return api_base_url
