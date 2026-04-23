from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from app.domain.chat_state import ChatState
from app.domain.normalized_user_request import NormalizedUserRequest


class ChatUiMode(str, Enum):
    """Authoritative UI mode for one chat turn."""

    CHAT = "chat"
    UNDERSTANDING_REVIEW = "understanding_review"
    CLARIFICATION = "clarification"


class ClarificationReason(str, Enum):
    """Stable explanation labels for why clarification mode is shown."""

    ASK_USER = "ask_user"


class UnderstandingUiBlock(BaseModel):
    """UI-facing understanding editor payload."""

    visible: bool = False
    text: str | None = None
    editable: bool = False
    submit_label: str | None = None


class ClarificationUiBlock(BaseModel):
    """UI-facing clarification prompt payload."""

    visible: bool = False
    question: str | None = None
    reason: ClarificationReason | None = None


class ChatUiState(BaseModel):
    """Authoritative UI contract for the current chat runtime state."""

    mode: ChatUiMode
    message_input_enabled: bool
    understanding: UnderstandingUiBlock
    clarification: ClarificationUiBlock


def build_ui_state(state: ChatState) -> ChatUiState:
    """Map internal runtime state to the single UI-facing contract."""

    normalized = state.normalized_request
    if _should_show_clarification(state, normalized):
        return ChatUiState(
            mode=ChatUiMode.CLARIFICATION,
            message_input_enabled=True,
            understanding=UnderstandingUiBlock(),
            clarification=ClarificationUiBlock(
                visible=True,
                question=_render_clarification_question(normalized),
                reason=ClarificationReason.ASK_USER,
            ),
        )

    if _should_show_understanding_review(state, normalized):
        return ChatUiState(
            mode=ChatUiMode.UNDERSTANDING_REVIEW,
            message_input_enabled=False,
            understanding=UnderstandingUiBlock(
                visible=True,
                text=normalized.normalized_user_request,
                editable=True,
                submit_label="OK",
            ),
            clarification=ClarificationUiBlock(),
        )

    return ChatUiState(
        mode=ChatUiMode.CHAT,
        message_input_enabled=True,
        understanding=UnderstandingUiBlock(),
        clarification=ClarificationUiBlock(),
    )


def require_ui_state(state: dict[str, object]) -> dict[str, object]:
    """Fail fast when the backend response does not carry the authoritative UI contract."""

    ui_state = state.get("ui_state")
    if not isinstance(ui_state, dict):
        raise ValueError("ui_state is required")
    return ui_state


def _should_show_clarification(
    state: ChatState,
    normalized: NormalizedUserRequest | None,
) -> bool:
    if normalized is None:
        return False
    if not normalized.needs_clarification:
        return False
    return state.awaiting_user_feedback or state.awaiting_confirmation


def _should_show_understanding_review(
    state: ChatState,
    normalized: NormalizedUserRequest | None,
) -> bool:
    if normalized is None:
        return False
    if normalized.needs_clarification:
        return False
    return state.awaiting_user_feedback or state.awaiting_confirmation


def _render_clarification_question(normalized: NormalizedUserRequest) -> str:
    """Render a real user-facing clarification question from the internal request."""

    reason = (normalized.clarification_reason or "I need a bit more detail to continue.").strip()
    if normalized.clarification_options:
        options = "; ".join(normalized.clarification_options)
        return (
            f"{reason} Please clarify by choosing one of these options or replying in your own words: "
            f"{options}."
        )
    if reason.endswith("?"):
        return reason
    return f"{reason} Please clarify."


__all__ = [
    "ChatUiMode",
    "ChatUiState",
    "ClarificationReason",
    "ClarificationUiBlock",
    "UnderstandingUiBlock",
    "build_ui_state",
    "require_ui_state",
]
