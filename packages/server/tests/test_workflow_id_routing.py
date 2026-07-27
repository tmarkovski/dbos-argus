"""Workflow ids are app-chosen and routinely contain slashes — DBOS itself
imposes no character restriction, and ids like `pr-review:owner/repo#20:v1`
are common. A client percent-encodes them, but the ASGI server decodes `%2F`
back to `/` before routing, so these routes must use `:path` params. When they
used segment params the request fell through to the SPA catch-all and returned
index.html with a 200, which the console then failed to parse as JSON.
"""

from __future__ import annotations

import pytest
from dbos_argus.db.rows import ResultRow
from dbos_argus.main import app
from fastapi.testclient import TestClient

# Slash (the route-breaking one), `#` and `:` — all legal in a DBOS id and all
# percent-encoded by the console's `encodeURIComponent`.
SLASHED_ID = "pr-review:bookmd/agentflow-test#20:v1"
ENCODED_ID = "pr-review%3Abookmd%2Fagentflow-test%2320%3Av1"


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Stub the three db reads so these tests assert routing and param
    decoding only — no schema or seed data needed."""
    captured: dict[str, object] = {}
    row = ResultRow(output=None, error='{"message": "boom"}', serialization="json")

    async def get_workflow_result(workflow_id: str) -> ResultRow:
        captured["workflow_id"] = workflow_id
        return row

    async def get_step_result(workflow_id: str, function_id: int) -> ResultRow:
        captured["workflow_id"] = workflow_id
        captured["function_id"] = function_id
        return row

    monkeypatch.setattr("dbos_argus.main.db.get_workflow_result", get_workflow_result)
    monkeypatch.setattr("dbos_argus.main.db.get_step_result", get_step_result)
    return captured


def test_workflow_result_accepts_encoded_slashes(seen: dict[str, object]) -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/workflows/{ENCODED_ID}/result")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert seen["workflow_id"] == SLASHED_ID
    assert response.json()["workflow_id"] == SLASHED_ID


def test_step_result_accepts_encoded_slashes(seen: dict[str, object]) -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/workflows/{ENCODED_ID}/steps/7/result")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert seen["workflow_id"] == SLASHED_ID
    assert seen["function_id"] == 7


def test_workflow_detail_accepts_encoded_slashes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    async def fetch(workflow_id: str) -> None:
        captured["workflow_id"] = workflow_id
        return None

    monkeypatch.setattr("dbos_argus.main.fetch_workflow_detail", fetch)

    with TestClient(app) as client:
        response = client.get(f"/api/workflows/{ENCODED_ID}")

    # A 404 (not the SPA's 200 + text/html) is the proof the route matched:
    # the handler ran and reported "not found" for the fully decoded id.
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert captured["workflow_id"] == SLASHED_ID
