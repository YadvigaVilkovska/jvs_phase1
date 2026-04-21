from __future__ import annotations

from app.agents.intent_agent import IntentAgent
from app.agents.execution_agent import ExecutionAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.normalization_agent import NormalizationAgent
from app.graph.main_chat_graph import MainChatGraphDeps, build_main_chat_graph
from app.graph.memory_graph import MemoryGraphDeps, build_memory_graph
from app.repositories.communication_rule_repository import CommunicationRuleRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.memory_repository import MemoryRepository
from app.services.communication_rule_service import CommunicationRuleService
from app.services.execution_service import ExecutionService


class GraphFactory:
    def __init__(
        self,
        *,
        chat_repo: ChatRepository,
        normalization_agent: NormalizationAgent,
        execution_agent: ExecutionAgent,
        intent_agent: IntentAgent,
        memory_repo: MemoryRepository | None = None,
        communication_rule_repo: CommunicationRuleRepository | None = None,
        memory_agent: MemoryAgent | None = None,
        communication_rule_service: CommunicationRuleService | None = None,
        execution_service: ExecutionService | None = None,
    ):
        self.chat_repo = chat_repo
        self.normalization_agent = normalization_agent
        self.execution_agent = execution_agent
        self.intent_agent = intent_agent
        self.memory_repo = memory_repo
        self.communication_rule_repo = communication_rule_repo
        self.memory_agent = memory_agent or MemoryAgent()
        self.communication_rule_service = communication_rule_service or (
            CommunicationRuleService(repository=communication_rule_repo)
            if communication_rule_repo is not None
            else None
        )
        self.execution_service = execution_service or ExecutionService()

    def main_chat_graph(self):
        return build_main_chat_graph(
            MainChatGraphDeps(
                chat_repo=self.chat_repo,
                normalization_agent=self.normalization_agent,
                execution_agent=self.execution_agent,
                intent_agent=self.intent_agent,
                memory_agent=self.memory_agent,
                communication_rule_service=self.communication_rule_service,
                execution_service=self.execution_service,
            )
        )

    def memory_graph(self):
        if self.memory_repo is None:
            self.memory_repo = MemoryRepository(self.chat_repo.session)  # type: ignore[attr-defined]
        return build_memory_graph(
            MemoryGraphDeps(
                chat_repo=self.chat_repo,
                memory_repo=self.memory_repo,
                memory_agent=self.memory_agent,
            )
        )
