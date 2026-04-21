from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CommunicationRuleScope = Literal["global", "current_chat", "topic"]
CommunicationRuleStatus = Literal["candidate", "soft_active", "active", "rejected", "revoked"]
CommunicationRuleEvidenceType = Literal[
    "initial_explicit_request",
    "repeat_request",
    "explicit_confirmation",
    "positive_feedback_after_apply",
    "negative_correction",
    "explicit_revoke",
    "stability_bonus",
    # Backward-compatible aliases used by older tests/flows.
    "positive_feedback",
    "negative_feedback",
    "explicit_request",
]


class CommunicationRuleCandidate(BaseModel):
    """Candidate extracted from chat before it is promoted into rule state."""

    user_id: str
    chat_id: str
    rule_key: str
    rule_text: str
    scope: CommunicationRuleScope
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    initial_score: float = Field(ge=0.0, le=1.0)
    status: CommunicationRuleStatus
    created_at: datetime | None = None
    rule_state_id: str | None = None


class CommunicationRuleEvidence(BaseModel):
    """Single evidence event used to update rule score over time."""

    rule_state_id: str
    event_type: CommunicationRuleEvidenceType
    delta: float
    message_id: str | None = None
    created_at: datetime | None = None
    candidate_id: str | None = None


class CommunicationRuleState(BaseModel):
    """Durable probabilistic policy state for a communication preference."""

    user_id: str
    chat_id: str | None = None
    rule_key: str
    scope: CommunicationRuleScope
    canonical_value_json: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    status: CommunicationRuleStatus
    evidence_count: int = 0
    last_confirmed_at: datetime | None = None
    last_applied_at: datetime | None = None
    updated_at: datetime | None = None
    canonical_value_format: str = "json"


__all__ = [
    "CommunicationRuleCandidate",
    "CommunicationRuleEvidence",
    "CommunicationRuleScope",
    "CommunicationRuleState",
    "CommunicationRuleStatus",
    "CommunicationRuleEvidenceType",
]
