from __future__ import annotations

import json
from dataclasses import dataclass

from sqlmodel import Session

from app.agents.execution_agent import ExecutionAgent
from app.agents.intent_agent import IntentAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.normalization_agent import NormalizationAgent
from app.domain.chat_state import ChatState
from app.domain.normalized_user_request import NormalizedUserRequest
from app.graph.graph_factory import GraphFactory
from app.repositories.chat_repository import ChatRepository
from app.repositories.communication_rule_repository import CommunicationRuleRepository
from app.services.communication_rule_service import CommunicationRuleService
from app.services.execution_service import ExecutionService
from app.services.memory_service import MemoryService


@dataclass(frozen=True)
class ChatTurnResult:
    """Use-case result for one chat turn."""

    state: ChatState


def _row_to_normalized_request(row) -> NormalizedUserRequest:
    """Rebuild a normalized request from persistence."""
    return NormalizedUserRequest(
        normalized_user_request=row.normalized_user_request,
        continuity=row.continuity,
        needs_clarification=row.needs_clarification,
        clarification_reason=row.clarification_reason,
        clarification_options=json.loads(row.clarification_options_json or "[]"),
        ambiguity_handling=row.ambiguity_handling,
        revision=row.revision,
    )


class ChatOrchestrator:
    """
    Application use-case orchestration for chat flow.

    This class owns the high-level chat workflow and keeps repositories, graph execution,
    and post-chat analysis in one place. It is intentionally separate from the HTTP layer.
    """

    def __init__(
        self,
        *,
        session: Session,
        normalization_agent: NormalizationAgent | None = None,
        execution_agent: ExecutionAgent | None = None,
        intent_agent: IntentAgent | None = None,
        memory_agent: MemoryAgent | None = None,
        communication_rule_service: CommunicationRuleService | None = None,
        execution_service: ExecutionService | None = None,
        graph_factory: GraphFactory | None = None,
        post_chat_analysis_runner=None,
    ):
        self.session = session
        self.chat_repo = ChatRepository(session)
        self.normalization_agent = normalization_agent or NormalizationAgent()
        self.execution_agent = execution_agent or ExecutionAgent()
        self.intent_agent = intent_agent or IntentAgent()
        self.memory_agent = memory_agent or MemoryAgent()
        self.communication_rule_service = communication_rule_service or CommunicationRuleService(
            repository=CommunicationRuleRepository(session)
        )
        self.execution_service = execution_service or ExecutionService()
        self.post_chat_analysis_runner = post_chat_analysis_runner
        self.graphs = graph_factory or GraphFactory(
            chat_repo=self.chat_repo,
            normalization_agent=self.normalization_agent,
            execution_agent=self.execution_agent,
            intent_agent=self.intent_agent,
            memory_agent=self.memory_agent,
            communication_rule_service=self.communication_rule_service,
            execution_service=self.execution_service,
        )

    def _load_state(self, chat_id: str) -> ChatState:
        chat = self.chat_repo.get_chat(chat_id)
        if not chat:
            raise ValueError("chat not found")

        latest = self.chat_repo.get_latest_normalized_request(chat_id)
        history_rows = self.chat_repo.list_normalized_requests(chat_id)
        history = [_row_to_normalized_request(r) for r in history_rows]
        normalized = _row_to_normalized_request(latest) if latest else None

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
            communication_rule_context=self.communication_rule_service.build_prompt_context(
                user_id=chat.user_id,
                chat_id=chat.id,
            ),
            chat_closed=(chat.status == "closed"),
        )

    def start_chat(self, *, user_id: str) -> ChatState:
        chat = self.chat_repo.create_chat(user_id)
        return ChatState(chat_id=chat.id, user_id=user_id)

    async def post_turn(
        self,
        *,
        user_id: str,
        chat_id: str | None,
        user_message: str,
    ) -> tuple[str, ChatTurnResult]:
        if chat_id:
            return chat_id, await self.post_user_message(chat_id=chat_id, user_message=user_message)

        await self.intent_agent.classify(
            raw_user_message=user_message,
            context={
                "chat_exists": False,
                "chat_closed": False,
                "awaiting_user_feedback": False,
                "awaiting_confirmation": False,
                "pending_memory_candidates": [],
                "latest_normalized_request_summary": None,
            },
        )
        created = self.start_chat(user_id=user_id)
        return created.chat_id, await self.post_user_message(chat_id=created.chat_id, user_message=user_message)

    async def post_user_message(self, *, chat_id: str, user_message: str) -> ChatTurnResult:
        state = self._load_state(chat_id)
        state.raw_user_message = user_message

        mem_svc = MemoryService(session=self.session)
        pending = mem_svc.list_candidates(chat_id=chat_id)
        state.turn_intent = await self.intent_agent.classify(
            raw_user_message=user_message,
            context={
                "chat_id": state.chat_id,
                "user_id": state.user_id,
                "chat_closed": state.chat_closed,
                "awaiting_user_feedback": state.awaiting_user_feedback,
                "awaiting_confirmation": state.awaiting_confirmation,
                "has_normalized_request": state.normalized_request is not None,
                "normalized_request_json": state.normalized_request.model_dump() if state.normalized_request else None,
                "communication_rule_context": state.communication_rule_context,
                "pending_memory_candidates": [
                    {
                        "id": r.id,
                        "normalized_memory": r.normalized_memory,
                        "memory_type": r.memory_type,
                        "target_layer": r.target_layer,
                        "status": r.status,
                    }
                    for r in pending
                ],
            },
        )

        if state.turn_intent.kind == "close_chat":
            return await self.close(chat_id=chat_id)
        if state.turn_intent.kind in {"memory_confirm", "memory_reject"}:
            cid = (state.turn_intent.memory_candidate_id or "").strip()
            if not cid:
                state.assistant_messages.append("Please specify the memory candidate id to confirm/reject.")
                return ChatTurnResult(state=state)
            try:
                if state.turn_intent.kind == "memory_confirm":
                    mem_svc.confirm_candidate(candidate_id=cid, user_id=state.user_id)
                    state.assistant_messages.append(f"Memory candidate confirmed: `{cid}`")
                else:
                    mem_svc.reject_candidate(candidate_id=cid)
                    state.assistant_messages.append(f"Memory candidate rejected: `{cid}`")
            except ValueError as e:
                state.assistant_messages.append(str(e))
            return ChatTurnResult(state=state)

        out = await self.graphs.main_chat_graph().ainvoke(state)
        return ChatTurnResult(state=ChatState.model_validate(out))

    async def post_correction(self, *, chat_id: str, correction_message: str) -> ChatTurnResult:
        return await self.post_user_message(chat_id=chat_id, user_message=correction_message)

    async def confirm(self, *, chat_id: str) -> ChatTurnResult:
        state = self._load_state(chat_id)
        state.awaiting_confirmation = True
        out = await self.graphs.main_chat_graph().ainvoke(state)
        return ChatTurnResult(state=ChatState.model_validate(out))

    async def close(self, *, chat_id: str) -> ChatTurnResult:
        chat = self.chat_repo.get_chat(chat_id)
        if not chat:
            raise ValueError("chat not found")
        if not chat.post_chat_extraction_completed:
            if chat.status != "closed":
                self.chat_repo.close_chat(chat_id)
            runner = self.post_chat_analysis_runner
            if runner is None:
                from app.tasks.post_chat_analysis import run_post_chat_analysis as runner

            await runner(session=self.session, chat_id=chat_id)
            self.chat_repo.mark_post_chat_extraction_completed(chat_id)
        state = self._load_state(chat_id)
        state.chat_closed = True
        return ChatTurnResult(state=state)
