from __future__ import annotations

from dataclasses import dataclass

from langgraph.graph import END, StateGraph

from app.agents.memory_agent import MemoryAgent
from app.domain.chat_state import ChatState
from app.repositories.chat_repository import ChatRepository
from app.repositories.memory_repository import MemoryRepository


@dataclass(frozen=True)
class MemoryGraphDeps:
    chat_repo: ChatRepository
    memory_repo: MemoryRepository
    memory_agent: MemoryAgent


def build_memory_graph(deps: MemoryGraphDeps):
    async def post_chat_memory_analysis(state: ChatState) -> ChatState:
        # Runs only after chat is closed in product terms.
        return state

    async def create_memory_candidates(state: ChatState) -> ChatState:
        # Candidate extraction uses the memory agent.
        # This MUST NOT write confirmed memory automatically.
        messages = deps.chat_repo.list_messages(state.chat_id)
        transcript = [f"{m.actor}: {m.content}" for m in messages if m.actor in ("user", "assistant")]
        state.memory_candidates = await deps.memory_agent.post_chat_candidates(chat_transcript=transcript)
        return state

    async def store_memory_candidates(state: ChatState) -> ChatState:
        # Persist candidates (status=candidate) for later user review.
        for cand in state.memory_candidates:
            deps.memory_repo.add_candidate(chat_id=state.chat_id, cand=cand)
        return state

    async def review_memory_candidates(state: ChatState) -> ChatState:
        """
        Bridge node.

        Real user review happens via API:
        - GET /memory/candidates
        - POST /memory/candidates/{id}/confirm
        - POST /memory/candidates/{id}/reject
        """

        return state

    async def confirm_memory_candidate(state: ChatState) -> ChatState:
        # Bridge stub: confirmation is handled by API + MemoryService.
        return state

    async def reject_memory_candidate(state: ChatState) -> ChatState:
        # Bridge stub: rejection is handled by API + MemoryService.
        return state

    async def write_memory_entry(state: ChatState) -> ChatState:
        # Bridge stub: durable write is handled by API + MemoryService after user confirmation.
        return state

    builder = StateGraph(ChatState)
    builder.add_node("post_chat_memory_analysis", post_chat_memory_analysis)
    builder.add_node("create_memory_candidates", create_memory_candidates)
    builder.add_node("store_memory_candidates", store_memory_candidates)
    builder.add_node("review_memory_candidates", review_memory_candidates)
    builder.add_node("confirm_memory_candidate", confirm_memory_candidate)
    builder.add_node("reject_memory_candidate", reject_memory_candidate)
    builder.add_node("write_memory_entry", write_memory_entry)

    builder.set_entry_point("post_chat_memory_analysis")
    builder.add_edge("post_chat_memory_analysis", "create_memory_candidates")
    builder.add_edge("create_memory_candidates", "store_memory_candidates")
    builder.add_edge("store_memory_candidates", "review_memory_candidates")
    builder.add_edge("review_memory_candidates", END)
    return builder.compile()

