"""Case-management API tests (FastAPI TestClient with fake Neo4j/Redis dependencies).

No live services: the driver + redis dependencies are overridden with in-memory fakes, so these
exercise routing, the owner-only resolution wiring, the draft-STR attach, and error handling.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from services.api import cases  # noqa: E402
from services.api.main import app  # noqa: E402


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def single(self):
        return self._rows[0] if self._rows else None

    def data(self):
        return self._rows


class FakeSession:
    def __init__(self, responder):
        self._responder = responder

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **kw):
        return FakeResult(self._responder(query, kw))

    def execute_write(self, fn):
        return fn(self)  # fn calls tx.run(...).single(); we are the tx


class FakeDriver:
    def __init__(self, responder):
        self._responder = responder

    def session(self):
        return FakeSession(self._responder)

    def close(self):
        pass


class FakeRedis:
    def __init__(self, data=None):
        self.h = data or {}

    def hget(self, key, field):
        return self.h.get(key, {}).get(field)


CASE_ROW = {
    "pattern": "round_trip",
    "score": 0.9,
    "recipients": ["INST_A", "INST_B"],
    "created_ts": 1_726_000_000,
    "evidence_text": "funds returned via intermediaries",
    "timespan_days": 3,
    "accounts": [
        {"hash": "hA", "institution": "INST_A"},
        {"hash": "hB", "institution": "INST_B"},
    ],
    "edges": [{"source": "hA", "target": "hB"}],
}


def _responder(query, kw):
    if "WITH al, collect(DISTINCT n) AS nodes" in query:  # assemble_case
        return [CASE_ROW] if kw.get("alert_id") == "known" else []
    if "coalesce(al.case_status" in query:  # list_cases
        return [
            {
                "alert_id": "known",
                "pattern": "round_trip",
                "score": 0.9,
                "status": "open",
                "created_ts": 1,
                "institutions": ["INST_A"],
            }
        ]
    if "SET al.case_status" in query:  # record_decision
        return [{"alert_id": kw["alert_id"], "status": kw["status"]}]
    return []


@pytest.fixture
def client():
    driver = FakeDriver(_responder)
    redis = FakeRedis({"resolve:INST_A": {"hA": "real-A"}})
    app.dependency_overrides[cases.get_driver] = lambda: driver
    app.dependency_overrides[cases.get_redis] = lambda: redis
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_cases(client):
    r = client.get("/cases")
    assert r.status_code == 200
    assert r.json()["cases"][0]["alert_id"] == "known"


def test_get_case_pseudonymised_by_default(client):
    r = client.get("/cases/known")
    assert r.status_code == 200
    body = r.json()
    assert body["pattern"] == "round_trip"
    assert all(
        "account_id" not in a for a in body["accounts"]
    )  # no resolution without ?institution


def test_get_case_owner_resolution_and_draft(client):
    r = client.get("/cases/known", params={"institution": "INST_A", "draft": "true"})
    assert r.status_code == 200
    body = r.json()
    by_inst = {a["institution"]: a for a in body["accounts"]}
    assert by_inst["INST_A"]["account_id"] == "real-A"  # own account resolved
    assert "INST_B" not in by_inst  # other bank completely omitted for privacy
    assert body["draft_str"]["filed"] is False
    assert "real-A" in body["draft_str"]["narrative"]


def test_get_missing_case_404(client):
    assert client.get("/cases/nope").status_code == 404


def test_decision_valid_and_invalid(client):
    ok = client.post("/cases/known/decision", json={"decision": "file", "officer": "po1"})
    assert ok.status_code == 200 and ok.json()["status"] == "filed"
    bad = client.post("/cases/known/decision", json={"decision": "delete", "officer": "po1"})
    assert bad.status_code == 400
