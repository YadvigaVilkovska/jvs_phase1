from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic_ai.models.test import TestModel
from sqlalchemy import text
from sqlmodel import Session

from app.api.deps import db_session
from app.dev.stub_agents import FakeIntentAgent, FakeNormalizationAgent, FakeSelfExecuteDecisionAgent
from app.services.chat_service import ChatService
from app.services.execution_service import ExecutionService
from app.settings import settings


router = APIRouter(prefix="/dev", tags=["dev"])


class BootstrapChatRequest(BaseModel):
    user_id: str = Field(
        default="local-dev-user",
        min_length=1,
        description="User id used for chat + profile/memory scoping (same as /chat/start).",
        examples=["local-dev-user"],
    )


class BootstrapChatResponse(BaseModel):
    chat_id: str
    example_requests: dict[str, Any]


@router.post("/bootstrap-chat", response_model=BootstrapChatResponse)
def bootstrap_chat(req: BootstrapChatRequest, session: Session = Depends(db_session)):
    svc = ChatService(session=session)
    state = svc.start_chat(user_id=req.user_id)
    cid = state.chat_id
    return BootstrapChatResponse(
        chat_id=cid,
        example_requests={
            "post_message": {
                "method": "POST",
                "path": "/chat/message",
                "body": {"chat_id": cid, "user_message": "Describe what you want done in plain language."},
            },
            "post_correction": {
                "method": "POST",
                "path": "/chat/correction",
                "body": {"chat_id": cid, "correction_message": "Adjust the normalized request like this: ..."},
            },
            "post_confirm": {
                "method": "POST",
                "path": "/chat/confirm",
                "body": {"chat_id": cid},
            },
            "post_close": {
                "method": "POST",
                "path": "/chat/close",
                "body": {"chat_id": cid},
            },
        },
    )


class DemoFlowRequest(BaseModel):
    user_id: str = Field(default="local-dev-user", min_length=1, examples=["local-dev-user"])
    user_message: str = Field(
        default="Hello — please normalize this request.",
        min_length=1,
        description="First user turn after start; triggers normalization (requires LLM unless stub mode).",
    )


class DemoFlowResponse(BaseModel):
    chat_id: str
    stub_agents: bool
    steps: list[str]
    normalized_revision: int | None
    execution_decision: dict | None
    execution_status: str | None
    assistant_messages_tail: list[str]


def _chat_service_for_demo(session: Session) -> ChatService:
    if settings.jeeves_dev_stub_agents:
        runner = TestModel(custom_output_text="Demo: stub runner output (no external tools).")
        return ChatService(
            session=session,
            intent_agent=FakeIntentAgent(),
            normalization_agent=FakeNormalizationAgent(),
            execution_agent=FakeSelfExecuteDecisionAgent(),
            execution_service=ExecutionService(model=runner),
        )
    return ChatService(session=session)


@router.post("/demo-flow", response_model=DemoFlowResponse)
async def demo_flow(req: DemoFlowRequest, session: Session = Depends(db_session)):
    """
    Runs: start chat → one user message → confirm (same flow as manual /chat calls).

    Without `JEEVES_DEV_STUB_AGENTS=true`, a real DeepSeek-backed normalization agent is required.
    """
    steps: list[str] = []
    svc = _chat_service_for_demo(session)
    stub = settings.jeeves_dev_stub_agents

    st0 = svc.start_chat(user_id=req.user_id)
    chat_id = st0.chat_id
    steps.append("start_chat")

    try:
        t1 = await svc.post_user_message(chat_id=chat_id, user_message=req.user_message)
    except RuntimeError as e:
        msg = str(e)
        if "LLM" in msg or "DeepSeek" in msg or "disabled" in msg.lower():
            raise HTTPException(
                status_code=503,
                detail=(
                    f"{msg} "
                    "For a keyless local demo, set JEEVES_DEV_STUB_AGENTS=true "
                    "(see README) or configure DeepSeek in .env."
                ),
            ) from e
        raise

    steps.append("post_user_message")
    if t1.state.normalized_request is None:
        raise HTTPException(
            status_code=500,
            detail="Expected a normalized request after the first message; check chat/graph state.",
        )

    t2 = await svc.confirm(chat_id=chat_id)
    steps.append("confirm")

    rev = t2.state.normalized_request.revision if t2.state.normalized_request else None
    dec = t2.state.execution_decision.model_dump() if t2.state.execution_decision else None
    tail = t2.state.assistant_messages[-8:] if t2.state.assistant_messages else []

    return DemoFlowResponse(
        chat_id=chat_id,
        stub_agents=stub,
        steps=steps,
        normalized_revision=rev,
        execution_decision=dec,
        execution_status=t2.state.execution_status,
        assistant_messages_tail=tail,
    )


def _db_dialect_label() -> str:
    p = urlparse(settings.database_url)
    s = (p.scheme or "").lower()
    if s.startswith("postgres"):
        return "postgresql"
    return s or "unknown"


@router.get("/ping-db")
def ping_db(session: Session = Depends(db_session)):
    session.execute(text("SELECT 1"))
    return {"ok": True, "dialect": _db_dialect_label()}
