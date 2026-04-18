from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.domain.execution_decision import ExecutionDecision
from app.domain.memory_candidate import MemoryCandidate
from app.domain.normalized_user_request import NormalizedUserRequest


class ChatState(BaseModel):
    """
    Orchestration snapshot for one graph step.

    Three-phase understanding (semantic → attachment → action) lives on
    `normalized_request` / history; see `docs/UNDERSTANDING_FLOW.md`.
    """

    chat_id: str
    user_id: str
    raw_user_message: str | None = None
    normalized_request: Optional[NormalizedUserRequest] = None
    normalized_request_history: List[NormalizedUserRequest] = Field(default_factory=list)
    awaiting_user_feedback: bool = False
    awaiting_confirmation: bool = False
    execution_decision: Optional[ExecutionDecision] = None
    execution_status: Literal["idle", "pending", "running", "completed", "blocked"] = "idle"
    assistant_messages: List[str] = Field(default_factory=list)
    user_corrections: List[str] = Field(default_factory=list)
    explicit_memory_command: bool = False
    memory_candidates: List[MemoryCandidate] = Field(default_factory=list)
    chat_closed: bool = False
