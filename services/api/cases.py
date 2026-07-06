"""Case-management API routes.

Exposes the investigation workflow over the alerts the graph engine produced:

- ``GET  /cases``                    — list cases (alerts) by lifecycle status, worst score first
- ``GET  /cases/{alert_id}``         — the pseudonymised case; pass ``?institution=`` to resolve
                                       that bank's own accounts (owner-only) and ``?draft=true`` to
                                       attach a draft STR
- ``POST /cases/{alert_id}/decision``— record an officer decision (file / dismiss / escalate)

The Neo4j driver / Redis client are injected via dependencies so tests can override them. No route
resolves another institution's account, and no route files anything — that is the officer's call.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from acn import redis_client as redis_store
from acn.casemgmt import case as case_mod
from acn.casemgmt import store, str_draft
from acn.graph import db as graph_db

logger = logging.getLogger("acn.api.cases")

router = APIRouter(prefix="/cases", tags=["cases"])


def get_driver() -> Iterator:
    driver = graph_db.connect()
    try:
        yield driver
    finally:
        driver.close()


def get_redis():
    return redis_store.connect()


class Decision(BaseModel):
    decision: str  # file | dismiss | escalate
    officer: str


@router.get("")
def list_cases(
    status: str | None = None,
    institution: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    driver=Depends(get_driver),
) -> dict:
    return {"cases": store.list_cases(driver, status=status, institution=institution, limit=limit)}


@router.get("/{alert_id}")
def get_case(
    alert_id: str,
    institution: str | None = None,
    draft: bool = False,
    use_llm: bool = False,
    driver=Depends(get_driver),
    r=Depends(get_redis),
) -> dict:
    case = case_mod.assemble_case(driver, alert_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"no case for alert {alert_id}")
    if institution:
        case = case_mod.resolve_for(r, case, institution)
        if draft:
            case["draft_str"] = str_draft.draft(case, use_llm=use_llm)
    return case


@router.post("/{alert_id}/decision")
def decide(
    alert_id: str,
    body: Decision,
    driver=Depends(get_driver),
) -> dict:
    try:
        return store.record_decision(driver, alert_id, body.decision, body.officer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
