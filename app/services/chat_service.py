from __future__ import annotations

from sqlmodel import Session

from app.agents.execution_agent import ExecutionAgent
from app.agents.intent_agent import IntentAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.normalization_agent import NormalizationAgent
from app.domain.chat_state import ChatState
from app.graph.graph_factory import GraphFactory
from app.services.chat_orchestrator import ChatOrchestrator, ChatTurnResult
from app.services.communication_rule_service import CommunicationRuleService
from app.services.execution_service import ExecutionService
from app.tasks.post_chat_analysis import run_post_chat_analysis


def _run_post_chat_analysis(*, session: Session, chat_id: str):
    return run_post_chat_analysis(session=session, chat_id=chat_id)


class ChatService:
    """
    Thin facade over the application orchestration layer.

    Keeping this class small preserves the public API while making the workflow easier to test.
    """

    def __init__(
        self,
        *,
        session: Session,
        normalization_agent: NormalizationAgent | None = None,
        execution_agent: ExecutionAgent | None = None,
        intent_agent: IntentAgent | None = None,
        communication_rule_service: CommunicationRuleService | None = None,
        execution_service: ExecutionService | None = None,
        graph_factory: GraphFactory | None = None,
    ):
        self.orchestrator = ChatOrchestrator(
            session=session,
            normalization_agent=normalization_agent,
            execution_agent=execution_agent,
            intent_agent=intent_agent,
            communication_rule_service=communication_rule_service,
            execution_service=execution_service,
            graph_factory=graph_factory,
            post_chat_analysis_runner=_run_post_chat_analysis,
        )
        self.chat_repo = self.orchestrator.chat_repo
        self.graphs = self.orchestrator.graphs
        self.communication_rule_service = self.orchestrator.communication_rule_service

    def start_chat(self, *, user_id: str) -> ChatState:
        return self.orchestrator.start_chat(user_id=user_id)

    async def post_turn(self, *, user_id: str, chat_id: str | None, user_message: str) -> tuple[str, ChatTurnResult]:
        return await self.orchestrator.post_turn(user_id=user_id, chat_id=chat_id, user_message=user_message)

    async def post_user_message(self, *, chat_id: str, user_message: str) -> ChatTurnResult:
        return await self.orchestrator.post_user_message(chat_id=chat_id, user_message=user_message)

    async def post_correction(self, *, chat_id: str, correction_message: str) -> ChatTurnResult:
        return await self.orchestrator.post_correction(chat_id=chat_id, correction_message=correction_message)

    async def confirm(self, *, chat_id: str) -> ChatTurnResult:
        return await self.orchestrator.confirm(chat_id=chat_id)

    async def reject_review(self, *, chat_id: str) -> ChatTurnResult:
        return await self.orchestrator.reject_review(chat_id=chat_id)

    async def close(self, *, chat_id: str) -> ChatTurnResult:
        return await self.orchestrator.close(chat_id=chat_id)
