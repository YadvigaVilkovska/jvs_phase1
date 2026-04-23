import pytest
from fastapi.testclient import TestClient

from app.api.ui_state import ChatUiMode
from app.api.ui_state import require_ui_state
from app.domain.chat_state import ChatState
from app.domain.normalized_user_request import NormalizedUserRequest
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


def test_reject_review_returns_404_or_409_when_not_in_review(api_client: TestClient):
    r = api_client.post("/chat/reject_review", json={"chat_id": "missing-or-invalid"})
    assert r.status_code in (404, 409)


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


def test_chat_response_exposes_ui_state(monkeypatch, api_client: TestClient):
    req = NormalizedUserRequest(
        normalized_user_request="Draft a short reply",
        continuity="new",
        needs_clarification=False,
        clarification_reason=None,
        clarification_options=[],
        ambiguity_handling="none",
        revision=1,
    )

    class FakeResult:
        def __init__(self):
            self.state = ChatState(
                chat_id="chat-1",
                user_id="u1",
                normalized_request=req,
                awaiting_user_feedback=True,
            )

    class FakeChatService:
        def __init__(self, session):
            self.session = session

        async def post_user_message(self, *, chat_id: str, user_message: str):
            return FakeResult()

    monkeypatch.setattr("app.api.chat.ChatService", FakeChatService)

    r = api_client.post("/chat/message", json={"chat_id": "chat-1", "user_message": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["ui_state"]["mode"] == "understanding_review"
    assert body["ui_state"]["understanding"]["visible"] is True
    assert body["ui_state"]["understanding"]["text"] == "Draft a short reply"


def test_chat_reject_exposes_ui_state(monkeypatch, api_client: TestClient):
    class FakeResult:
        def __init__(self):
            self.state = ChatState(
                chat_id="chat-1",
                user_id="u1",
                normalized_request=None,
                awaiting_user_feedback=False,
                awaiting_confirmation=False,
            )

    class FakeChatService:
        def __init__(self, session):
            self.session = session

        async def reject(self, *, chat_id: str):
            return FakeResult()

    monkeypatch.setattr("app.api.chat.ChatService", FakeChatService)

    r = api_client.post("/chat/reject", json={"chat_id": "chat-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["ui_state"]["mode"] == ChatUiMode.CHAT
    assert body["ui_state"]["understanding"]["visible"] is False


def test_start_chat_exposes_ui_state(api_client: TestClient):
    r = api_client.post("/chat/start", json={"user_id": "u-start"})
    assert r.status_code == 200
    body = r.json()
    assert body["ui_state"]["mode"] == ChatUiMode.CHAT
    assert body["ui_state"]["understanding"]["visible"] is False


def test_root_html_mentions_ui_state_contract(api_client: TestClient):
    r = api_client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "ui_state" in body
    assert "understanding_review" in body
    assert "clarification" in body
    assert "/chat/reject" in body
    assert "defaultUiState" not in body
    assert "reviewBtn" not in body


def test_main_module_does_not_embed_chat_shell_contract():
    from app import main as main_module

    assert not hasattr(main_module, "CHAT_HTML")


def test_streamlit_requires_ui_state_contract():
    with pytest.raises(ValueError, match="ui_state is required"):
        require_ui_state({})
