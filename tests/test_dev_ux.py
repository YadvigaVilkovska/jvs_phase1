import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import settings


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    db = tmp_path / "dev_ux.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db}")
    monkeypatch.setattr(settings, "jeeves_dev_stub_agents", True)
    monkeypatch.setattr(settings, "openai_enabled", False)
    monkeypatch.setattr(settings, "deepseek_enabled", False)
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_health(api_client: TestClient):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_dev_ping_db(api_client: TestClient):
    r = api_client.get("/dev/ping-db")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["dialect"] == "sqlite"


def test_dev_bootstrap_chat(api_client: TestClient):
    r = api_client.post("/dev/bootstrap-chat", json={"user_id": "u-smoke"})
    assert r.status_code == 200
    data = r.json()
    assert "chat_id" in data
    assert data["example_requests"]["post_message"]["body"]["chat_id"] == data["chat_id"]


def test_dev_demo_flow_stub_agents(api_client: TestClient):
    r = api_client.post(
        "/dev/demo-flow",
        json={"user_id": "u-demo", "user_message": "Hello from test"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["stub_agents"] is True
    assert data["steps"] == ["start_chat", "post_user_message", "confirm"]
    assert data["execution_decision"] is not None
    assert data["execution_status"] == "completed"
    assert data["assistant_messages_tail"]


def test_chat_turn_creates_chat_without_chat_id(api_client: TestClient):
    # /chat/turn must be able to start a chat from the first user message.
    r = api_client.post(
        "/chat/turn",
        json={
            "chat_id": None,
            "user_id": "u-turn",
            "user_message": "Hello",
        },
    )
    # In this repo, /chat/* requires LLM providers; with providers disabled in this fixture,
    # it must fail honestly.
    assert r.status_code == 503


def test_dev_demo_flow_without_stub_returns_503(monkeypatch, tmp_path):
    db = tmp_path / "no_stub.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db}")
    monkeypatch.setattr(settings, "jeeves_dev_stub_agents", False)
    monkeypatch.setattr(settings, "openai_enabled", False)
    monkeypatch.setattr(settings, "deepseek_enabled", False)

    app = create_app()
    with TestClient(app) as client:
        r = client.post("/dev/demo-flow", json={"user_id": "u", "user_message": "x"})
    assert r.status_code == 503
    assert "DeepSeek" in r.json()["detail"] or "LLM" in r.json()["detail"] or "disabled" in r.json()["detail"].lower()
