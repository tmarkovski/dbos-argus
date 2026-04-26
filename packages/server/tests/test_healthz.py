from dbos_argus.main import app
from fastapi.testclient import TestClient


def test_healthz_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"ok", "degraded"}
        assert body["database"] in {"up", "down"}
