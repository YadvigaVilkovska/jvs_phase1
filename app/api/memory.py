from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import db_session
from app.domain.memory_candidate import MemoryCandidate
from app.services.memory_service import MemoryService


router = APIRouter(prefix="/memory", tags=["memory"])


class StoreMemoryRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "chat_id": "paste-chat_id-from-start",
                    "candidate": {
                        "memory_type": "preference",
                        "target_layer": "long_term_memory",
                        "normalized_memory": "User prefers bullet lists under five items.",
                        "source": "user_requested",
                        "confidence": 0.85,
                        "requires_confirmation": True,
                    },
                }
            ]
        }
    )

    chat_id: str = Field(min_length=1, description="Chat this candidate belongs to.", examples=["550e8400-e29b-41d4-a716-446655440000"])
    candidate: MemoryCandidate = Field(
        description="Structured candidate (still requires `POST .../confirm` to become durable memory)."
    )


class StoreMemoryResponse(BaseModel):
    candidate_id: str
    status: str


@router.post("/store", response_model=StoreMemoryResponse)
def store_memory(req: StoreMemoryRequest, session: Session = Depends(db_session)):
    svc = MemoryService(session=session)
    row = svc.create_explicit_candidate(chat_id=req.chat_id, cand=req.candidate)
    return StoreMemoryResponse(candidate_id=row.id, status=row.status)


class MemoryCandidateResponse(BaseModel):
    id: str
    chat_id: str
    memory_type: str
    target_layer: str
    normalized_memory: str
    source: str
    confidence: float
    status: str


@router.get("/candidates", response_model=list[MemoryCandidateResponse])
def list_candidates(
    chat_id: str | None = Query(
        None,
        description="If set, only candidates for this chat; omit to list all.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
    session: Session = Depends(db_session),
):
    svc = MemoryService(session=session)
    rows = svc.list_candidates(chat_id=chat_id)
    return [
        MemoryCandidateResponse(
            id=r.id,
            chat_id=r.chat_id,
            memory_type=r.memory_type,
            target_layer=r.target_layer,
            normalized_memory=r.normalized_memory,
            source=r.source,
            confidence=r.confidence,
            status=r.status,
        )
        for r in rows
    ]


class ConfirmCandidateRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"user_id": "alice"}]})

    user_id: str = Field(
        min_length=1,
        description="Owner of the resulting memory entry (must match how you scope profile; same id as `POST /chat/start` user_id).",
        examples=["alice", "local-dev-user"],
    )


@router.post("/candidates/{candidate_id}/confirm")
def confirm_candidate(
    candidate_id: str,
    req: ConfirmCandidateRequest,
    session: Session = Depends(db_session),
):
    svc = MemoryService(session=session)
    try:
        entry = svc.confirm_candidate(candidate_id=candidate_id, user_id=req.user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"memory_entry_id": entry.id, "status": entry.status}


@router.post("/candidates/{candidate_id}/reject")
def reject_candidate(candidate_id: str, session: Session = Depends(db_session)):
    svc = MemoryService(session=session)
    try:
        svc.reject_candidate(candidate_id=candidate_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"candidate_id": candidate_id, "status": "rejected"}
