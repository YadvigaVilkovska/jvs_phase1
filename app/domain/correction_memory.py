"""Structured LLM output for optional standing preference during correction turns."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.memory_candidate import MemoryCandidate


class StandingPreferenceExtraction(BaseModel):
    """If the user's correction encodes a durable preference/rule, propose a candidate (review required)."""

    propose_memory: bool = Field(
        description="True only if the message states an ongoing preference for future chats, not just this deliverable."
    )
    candidate: MemoryCandidate | None = None
