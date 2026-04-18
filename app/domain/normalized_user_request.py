from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


UnderstandingClarificationKind = Literal[
    "none",
    "phrase_unclear",
    "attachment_unclear",
    "execution_data_missing",
]


class NormalizedUserRequest(BaseModel):
    """
    Chat-first contract: one object per revision.

    Encodes the understanding flow (see docs/UNDERSTANDING_FLOW.md):
    - semantic_utterance_interpretation (phase 1)
    - dialog_attachment_interpretation (phase 2)
    - normalized_user_request (phase 3 — action line)
    """

    normalized_user_request: str
    continuity: Literal["new", "continue", "correct_previous", "unclear"]
    needs_clarification: bool
    clarification_reason: str | None = None
    clarification_options: List[str] = Field(default_factory=list)
    ambiguity_handling: Literal["none", "ask_user", "answer_with_options"]
    revision: int = 1

    semantic_utterance_interpretation: str = Field(
        default="",
        description="Phase 1: what the user's words mean in isolation (short plain English).",
    )
    dialog_attachment_interpretation: str = Field(
        default="",
        description="Phase 2: what in the dialog/history this refers to, or what referential link is unresolved.",
    )
    understanding_clarification_kind: UnderstandingClarificationKind = Field(
        default="none",
        description="Which understanding gate failed, if any (LLM-assigned; not keyword-derived).",
    )

    @field_validator("clarification_reason", mode="before")
    @classmethod
    def _coerce_sentinel_strings_to_none(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, str) and v.strip().lower() in ("", "null", "none"):
            return None
        return v

    @model_validator(mode="after")
    def _enforce_understanding_clarification_gates(self):
        kind = self.understanding_clarification_kind
        if kind == "none" or self.needs_clarification:
            return self

        defaults = {
            "phrase_unclear": "The user's utterance could not be interpreted reliably enough to attach or act.",
            "attachment_unclear": "The utterance is understood in isolation, but what it refers to in the conversation is unclear.",
            "execution_data_missing": "Utterance and referent are clear enough, but factual parameters are missing before execution.",
        }
        return self.model_copy(
            update={
                "needs_clarification": True,
                "clarification_reason": self.clarification_reason or defaults[kind],
                "ambiguity_handling": "ask_user"
                if self.ambiguity_handling == "none"
                else self.ambiguity_handling,
            }
        )


__all__ = ["NormalizedUserRequest", "UnderstandingClarificationKind"]
