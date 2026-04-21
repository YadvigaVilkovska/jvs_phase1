from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


TurnIntentKind = Literal[
    "new_task",
    "confirm",
    "correction",
    "rule_confirm",
    "rule_positive_feedback",
    "rule_negative_correction",
    "rule_revoke",
    "start_chat",
    "close_chat",
    "memory_store",
    "memory_confirm",
    "memory_reject",
    "help",
    "other",
]


class TurnIntent(BaseModel):
    """
    LLM-first intent classification for a single user turn.

    This is intentionally *not* a command parser. It is produced by an LLM as a structured output.
    """

    kind: TurnIntentKind

    # Optional payloads for non-message actions.
    memory_candidate_id: Optional[str] = None
    memory_text: Optional[str] = None
    correction_text: Optional[str] = None
    communication_rule_key: Optional[str] = None

    # Optional introspection (not necessarily shown to the user).
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
