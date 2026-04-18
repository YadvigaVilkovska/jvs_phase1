from __future__ import annotations

from app.agents.execution_agent import ExecutionAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.normalization_agent import NormalizationAgent
from app.graph.main_chat_graph import MainChatGraphDeps, build_main_chat_graph
from app.graph.memory_graph import MemoryGraphDeps, build_memory_graph
from app.repositories.chat_repository import ChatRepository
from app.repositories.memory_repository import MemoryRepository
from app.services.execution_service import ExecutionService


class GraphFactory:
    def __init__(
        self,
        *,
        chat_repo: ChatRepository,
        normalization_agent: NormalizationAgent,
        execution_agent: ExecutionAgent,
        memory_repo: MemoryRepository | None = None,
        memory_agent: MemoryAgent | None = None,
        execution_service: ExecutionService | None = None,
    ):
        self.chat_repo = chat_repo
        self.normalization_agent = normalization_agent
        self.execution_agent = execution_agent
        self.memory_repo = memory_repo
        self.memory_agent = memory_agent or MemoryAgent()
        self.execution_service = execution_service or ExecutionService()

    def main_chat_graph(self):
        return build_main_chat_graph(
            MainChatGraphDeps(
                chat_repo=self.chat_repo,
                normalization_agent=self.normalization_agent,
                execution_agent=self.execution_agent,
                memory_agent=self.memory_agent,
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

