from __future__ import annotations

import app as app_module
from fastapi.testclient import TestClient


def test_root_and_meta():
    with TestClient(app_module.app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert root.json()["service"] == "Voice AI Property Assistant"

        meta = client.get("/meta")
        assert meta.status_code == 200
        body = meta.json()
        assert body["model"] == "qwen/qwen3.8-27b"
        assert "tts" in body and "avatar" in body


def test_inventory_endpoint(db_required):
    with TestClient(app_module.app) as client:
        response = client.get("/rooms")
        assert response.status_code == 200
        assert response.json()["count"] == 12


def test_health_endpoint(db_required):
    with TestClient(app_module.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["database"]["ok"] is True


def test_portrait_endpoint():
    with TestClient(app_module.app) as client:
        response = client.get("/avatar/portrait")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")


def test_chat_uses_pipeline(monkeypatch):
    class FakePipeline:
        def process_text(self, text, session_id=None, *, speak=True, with_avatar=True):
            return {
                "session_id": session_id or "generated",
                "reply": f"echo: {text}",
                "rooms": [],
                "audio": None,
                "avatar": None,
            }

    monkeypatch.setattr(app_module, "get_pipeline", lambda: FakePipeline())
    with TestClient(app_module.app) as client:
        response = client.post("/chat", json={"message": "hello", "speak": False,
                                             "avatar": False})
        assert response.status_code == 200
        assert response.json()["reply"] == "echo: hello"


def test_session_reset():
    with TestClient(app_module.app) as client:
        response = client.delete("/sessions/abc")
        assert response.status_code == 200
        assert response.json()["status"] == "reset"
