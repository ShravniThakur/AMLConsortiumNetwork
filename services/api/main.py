"""ACN service API.

Exposes ``GET /health`` (dependency-aggregating health check) and the ``/cases`` case-management
routes (list cases, view a case with owner-only resolution + draft STR, record officer decisions).
This module wires the app and structured JSON logging.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .cases import router as cases_router
from .health import gather_health

# One structured logger configured per service. A JSON
# formatter can be swapped in for production; the key rule is structured `extra`
# context and never a secret or raw data value in a log line.
logging.basicConfig(
    level=os.environ.get("ACN_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("acn.api")

# The git SHA is injected at build/deploy time; "unknown" locally is acceptable.
VERSION = os.environ.get("ACN_GIT_SHA", "unknown")

app = FastAPI(title="ACN Case Management API", version=VERSION)

# Allow the local compliance UI (dev server) to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ACN_CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(cases_router)


@app.get("/health")
def health() -> JSONResponse:
    """Aggregate the state of every dependency the API relies on.

    Returns 200 with ``status: ok`` when all core dependencies are reachable, or 503
    with ``status: degraded`` if Kafka, Neo4j, or Redis is down. ``ollama: unloaded`` is
    normal (the model loads on demand) and does not degrade the system.
    """
    report, core_down = gather_health()
    body = {
        "status": "degraded" if core_down else "ok",
        "version": VERSION,
        **report,
    }
    status_code = 503 if core_down else 200
    logger.info("health.checked", extra={"status": body["status"], **report})
    return JSONResponse(content=body, status_code=status_code)
