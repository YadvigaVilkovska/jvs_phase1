from __future__ import annotations

import json
from dataclasses import dataclass

from sqlmodel import Session

from app.agents.execution_agent import ExecutionAgent
from app.agents.normalization_agent import NormalizationAgent
from app.domain.chat_state import ChatState
from app.domain.normalized_user_request import NormalizedUserRequest
from app.graph.graph_factory import GraphFactory
from app.repositories.chat_repository import ChatRepository
from app.services.execution_service import ExecutionService
from app.tasks.post_chat_analysis import run_post_chat_analysis


@dataclass(frozen=True)
class ChatTurnResult:
    state: ChatState


def _row_to_normalized_request(row) -> NormalizedUserRequest:
    """Rebuild NUR from persistence. Understanding-flow fields are not stored (see docs/UNDERSTANDING_FLOW.md)."""
    return NormalizedUserRequest(
        normalized_user_request=row.normalized_user_request,
        continuity=row.continuity,
        needs_clarification=row.needs_clarification,
        clarification_reason=row.clarification_reason,
        clarification_options=json.loads(row.clarification_options_json or "[]"),
        ambiguity_handling=row.ambiguity_handling,
        revision=row.revision,
    )


class ChatService:
    def __init__(
        self,
        *,
        session: Session,
        normalization_agent: NormalizationAgent | None = None,
        execution_agent: ExecutionAgent | None = None,
        execution_service: ExecutionService | None = None,
    ):
        self.session = session
        self.chat_repo = ChatRepository(session)
        self.normalization_agent = normalization_agent or NormalizationAgent()
        self.execution_agent = execution_agent or ExecutionAgent()
        self.graphs = GraphFactory(
            chat_repo=self.chat_repo,
            normalization_agent=self.normalization_agent,
            execution_agent=self.execution_agent,
            execution_service=execution_service,
        )

    def _load_state(self, chat_id: str) -> ChatState:
        chat = self.chat_repo.get_chat(chat_id)
        if not chat:
            raise ValueError("chat not found")

        latest = self.chat_repo.get_latest_normalized_request(chat_id)
        history_rows = self.chat_repo.list_normalized_requests(chat_id)
        history = [_row_to_normalized_request(r) for r in history_rows]
        normalized = _row_to_normalized_request(latest) if latest else None

        # Chat.status is used as the persisted orchestration status.
        awaiting_feedback = chat.status in ("awaiting_feedback", "awaiting_memory_review")
        awaiting_confirmation = chat.status == "awaiting_confirmation"

        return ChatState(
            chat_id=chat.id,
            user_id=chat.user_id,
            raw_user_message=None,
            normalized_request=normalized,
            normalized_request_history=history,
            awaiting_user_feedback=awaiting_feedback,
            awaiting_confirmation=awaiting_confirmation,
            execution_decision=None,
            execution_status="idle",
            assistant_messages=[],
            user_corrections=[],
            explicit_memory_command=False,
            memory_candidates=[],
            chat_closed=(chat.status == "closed"),
        )

    def start_chat(self, *, user_id: str) -> ChatState:
        chat = self.chat_repo.create_chat(user_id)
        return ChatState(chat_id=chat.id, user_id=user_id)

    async def post_user_message(self, *, chat_id: str, user_message: str) -> ChatTurnResult:
        state = self._load_state(chat_id)
        state.raw_user_message = user_message
        graph = self.graphs.main_chat_graph()
        out = await graph.ainvoke(state)
        return ChatTurnResult(state=ChatState.model_validate(out))

    async def post_correction(self, *, chat_id: str, correction_message: str) -> ChatTurnResult:
        state = self._load_state(chat_id)
        state.raw_user_message = correction_message
        state.awaiting_user_feedback = True
        graph = self.graphs.main_chat_graph()
        out = await graph.ainvoke(state)
        return ChatTurnResult(state=ChatState.model_validate(out))

    async def confirm(self, *, chat_id: str) -> ChatTurnResult:
        state = self._load_state(chat_id)
        state.awaiting_confirmation = True
        graph = self.graphs.main_chat_graph()
        out = await graph.ainvoke(state)
        return ChatTurnResult(state=ChatState.model_validate(out))

    async def close(self, *, chat_id: str) -> ChatTurnResult:
        """
        Close chat and trigger post-chat memory analysis (candidates only).

        This keeps strict separation: analysis creates candidates, confirmation happens via memory endpoints.

        Post-chat extraction runs until it completes successfully once (`chats.post_chat_extraction_completed`).
        Duplicate `/chat/close` calls do not create duplicate post-chat candidates. If extraction raises
        after the chat was already marked closed, a later close retries extraction (flag stays false).
        """
        chat = self.chat_repo.get_chat(chat_id)
        if not chat:
            raise ValueError("chat not found")
        if not chat.post_chat_extraction_completed:
            if chat.status != "closed":
                self.chat_repo.close_chat(chat_id)
            await run_post_chat_analysis(session=self.session, chat_id=chat_id)
            self.chat_repo.mark_post_chat_extraction_completed(chat_id)
        state = self._load_state(chat_id)
        state.chat_closed = True
        return ChatTurnResult(state=state)

