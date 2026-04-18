from __future__ import annotations

"""
Post-chat memory candidate analysis.

v1 behavior (honest):
- The analysis logic runs in-process when `run_post_chat_analysis` is called (e.g. from `POST /chat/close`).
- There is no production-grade queue/worker (Redis/Celery/RQ) wired yet; that remains out of scope for v1.
- This module is the single entry point a future worker would call unchanged.
"""

from sqlmodel import Session

from app.agents.memory_agent import MemoryAgent
from app.repositories.chat_repository import ChatRepository
from app.repositories.memory_repository import MemoryRepository


async def run_post_chat_analysis(*, session: Session, chat_id: str) -> int:
    chat_repo = ChatRepository(session)
    mem_repo = MemoryRepository(session)

    # Load transcript (messages) — for v1 we only use assistant/user content ordering.
    messages = chat_repo.list_messages(chat_id)
    transcript = [f"{m.actor}: {m.content}" for m in messages if m.actor in ("user", "assistant")]
    agent = MemoryAgent()
    candidates = await agent.post_chat_candidates(chat_transcript=transcript)
    for cand in candidates:
        mem_repo.add_candidate(chat_id=chat_id, cand=cand)
    return len(candidates)

