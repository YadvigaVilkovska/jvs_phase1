from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import UniqueConstraint
from uuid import uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Chat(SQLModel, table=True):
    __tablename__ = "chats"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True)
    status: str = Field(default="open", index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    closed_at: Optional[datetime] = Field(default=None)
    # True after successful completion of run_post_chat_analysis for this chat (incl. zero candidates).
    post_chat_extraction_completed: bool = Field(default=False)


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    chat_id: str = Field(index=True)
    actor: str = Field(index=True)  # "user" | "assistant" | "system"
    content: str
    created_at: datetime = Field(default_factory=_utcnow)


class NormalizedRequestRow(SQLModel, table=True):
    __tablename__ = "normalized_requests"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    chat_id: str = Field(index=True)
    message_id: str = Field(index=True)
    revision: int = Field(index=True)

    normalized_user_request: str
    continuity: str
    needs_clarification: bool
    clarification_reason: Optional[str] = None
    clarification_options_json: str = Field(default="[]")
    ambiguity_handling: str

    created_at: datetime = Field(default_factory=_utcnow)

    @staticmethod
    def dumps_options(options: list[str]) -> str:
        return json.dumps(options, ensure_ascii=False)


class ExecutionDecisionRow(SQLModel, table=True):
    __tablename__ = "execution_decisions"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    chat_id: str = Field(index=True)
    normalized_request_id: str = Field(index=True)

    can_execute_self: bool
    needs_external_info: bool
    needs_tool: bool
    needs_delegate: bool
    needs_decomposition: bool
    needs_user_confirmation: bool
    reason: str

    created_at: datetime = Field(default_factory=_utcnow)


class MemoryCandidateRow(SQLModel, table=True):
    __tablename__ = "memory_candidates"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    chat_id: str = Field(index=True)

    memory_type: str
    target_layer: str
    normalized_memory: str
    source: str
    confidence: float
    status: str = Field(default="candidate", index=True)  # candidate|confirmed|rejected

    created_at: datetime = Field(default_factory=_utcnow)


class MemoryEntryRow(SQLModel, table=True):
    __tablename__ = "memory_entries"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True)

    memory_type: str
    target_layer: str
    normalized_memory: str
    source: str
    status: str = Field(index=True)

    created_at: datetime = Field(default_factory=_utcnow)


class CommunicationRuleCandidateRow(SQLModel, table=True):
    __tablename__ = "communication_rule_candidates"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True)
    chat_id: str = Field(index=True)
    rule_key: str = Field(index=True)
    rule_text: str
    scope: str = Field(index=True)
    extraction_confidence: float
    initial_score: float
    status: str = Field(default="candidate", index=True)
    rule_state_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class CommunicationRuleEvidenceRow(SQLModel, table=True):
    __tablename__ = "communication_rule_evidence"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    rule_state_id: str = Field(index=True)
    event_type: str = Field(index=True)
    delta: float
    message_id: str | None = Field(default=None, index=True)
    candidate_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class CommunicationRuleStateRow(SQLModel, table=True):
    __tablename__ = "communication_rule_state"
    __table_args__ = (
        UniqueConstraint("user_id", "rule_key", "scope", "chat_id", name="uq_communication_rule_state_identity"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True)
    chat_id: str | None = Field(default=None, index=True)
    rule_key: str = Field(index=True)
    scope: str = Field(index=True)
    canonical_value_json: str | None = None
    score: float
    status: str = Field(index=True)
    evidence_count: int = Field(default=0)
    last_confirmed_at: datetime | None = None
    last_applied_at: datetime | None = None
    updated_at: datetime = Field(default_factory=_utcnow, index=True)


class CoreProfileEntryRow(SQLModel, table=True):
    __tablename__ = "core_profile_entries"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True)
    key: str = Field(index=True)
    value_json: str
    source: str
    status: str = Field(default="confirmed", index=True)
    updated_at: datetime = Field(default_factory=_utcnow)

    @staticmethod
    def dumps_value(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)
