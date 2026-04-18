from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import db_session
from app.domain.chat_state import ChatState
from app.services.chat_service import ChatService


router = APIRouter(prefix="/chat", tags=["chat"])


class StartChatRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"user_id": "alice"}]})

    user_id: str = Field(
        min_length=1,
        description="Opaque identifier for the human (scopes profile + memory). Reuse the same id across chats if you want continuity.",
        examples=["alice", "local-dev-user"],
    )


class StartChatResponse(BaseModel):
    chat_id: str


@router.post("/start", response_model=StartChatResponse)
def start_chat(req: StartChatRequest, session: Session = Depends(db_session)):
    svc = ChatService(session=session)
    state = svc.start_chat(user_id=req.user_id)
    return StartChatResponse(chat_id=state.chat_id)


class PostMessageRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "chat_id": "paste-chat_id-from-start",
                    "user_message": "Draft a short email telling the client we need two more days.",
                }
            ]
        }
    )

    chat_id: str = Field(
        min_length=1,
        description="The `chat_id` returned by `POST /chat/start`.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    user_message: str = Field(
        min_length=1,
        description="Raw user text for this turn. The graph will normalize it into a `NormalizedUserRequest` (requires DeepSeek unless using dev stub agents).",
        examples=["Summarize yesterday's meeting in three bullets."],
    )


class ChatStateResponse(BaseModel):
    state: ChatState


@router.post("/message", response_model=ChatStateResponse)
async def post_message(req: PostMessageRequest, session: Session = Depends(db_session)):
    svc = ChatService(session=session)
    try:
        result = await svc.post_user_message(chat_id=req.chat_id, user_message=req.user_message)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ChatStateResponse(state=result.state)


class PostCorrectionRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "chat_id": "paste-chat_id-from-start",
                    "correction_message": "Change tone to more formal and mention the new deadline explicitly.",
                }
            ]
        }
    )

    chat_id: str = Field(
        min_length=1,
        description="Same `chat_id` as other chat endpoints.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    correction_message: str = Field(
        min_length=1,
        description=(
            "How to revise the **same** NormalizedUserRequest (task-local constraints: language, length, tone for "
            "this deliverable). Durable preferences ('always…', 'never…') may also yield a separate MemoryCandidate "
            "for review — no automatic durable write."
        ),
        examples=["Use UK spelling and add a one-line subject suggestion."],
    )


@router.post("/correction", response_model=ChatStateResponse)
async def post_correction(req: PostCorrectionRequest, session: Session = Depends(db_session)):
    svc = ChatService(session=session)
    try:
        result = await svc.post_correction(chat_id=req.chat_id, correction_message=req.correction_message)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ChatStateResponse(state=result.state)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"chat_id": "paste-chat_id-from-start"}]})

    chat_id: str = Field(
        min_length=1,
        description="After you reviewed the normalized request in the chat state, call this to confirm and proceed to `ExecutionDecision` (nothing executes before this).",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )


@router.post("/confirm", response_model=ChatStateResponse)
async def confirm(req: ConfirmRequest, session: Session = Depends(db_session)):
    svc = ChatService(session=session)
    try:
        result = await svc.confirm(chat_id=req.chat_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ChatStateResponse(state=result.state)


class CloseChatRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"chat_id": "paste-chat_id-from-start"}]})

    chat_id: str = Field(
        min_length=1,
        description="Closes the chat and runs **post-chat memory candidate** extraction in-process (candidates only; confirm via `/memory/...`).",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )


@router.post("/close", response_model=ChatStateResponse)
async def close_chat(req: CloseChatRequest, session: Session = Depends(db_session)):
    svc = ChatService(session=session)
    try:
        result = await svc.close(chat_id=req.chat_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ChatStateResponse(state=result.state)
