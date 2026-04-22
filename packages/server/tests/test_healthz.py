from dbos_argus.main import app
from fastapi.testclient import TestClient


def test_healthz_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"ok", "degraded"}
        assert body["database"] in {"up", "down"}


def test_ws_apps_sends_hello() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/apps?api_key=test-key") as ws:
            greeting = ws.receive_json()
            assert greeting["type"] == "hello"
            assert "connection_id" in greeting
            assert "server_version" in greeting
