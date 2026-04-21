from __future__ import annotations

from sqlmodel import Session

from app.agents.memory_agent import MemoryAgent
from app.domain.memory_candidate import MemoryCandidate
from app.domain.memory_entry import MemoryEntry
from app.repositories.models import Chat
from app.repositories.memory_repository import MemoryRepository


class MemoryService:
    def __init__(self, *, session: Session, memory_agent: MemoryAgent | None = None):
        self.session = session
        self.repo = MemoryRepository(session)
        self.memory_agent = memory_agent or MemoryAgent()

    def create_explicit_candidate(self, *, chat_id: str, cand: MemoryCandidate):
        # MUST remain candidate until user confirms.
        return self.repo.add_candidate(chat_id=chat_id, cand=cand)

    def list_candidates(self, *, chat_id: str | None = None):
        return self.repo.list_candidates(chat_id=chat_id, status="candidate")

    def confirm_candidate(self, *, candidate_id: str, user_id: str):
        row = self.repo.get_candidate(candidate_id)
        if not row or row.status != "candidate":
            raise ValueError("candidate not found or not pending")

        chat = self.session.get(Chat, row.chat_id)
        if not chat:
            raise ValueError("candidate chat not found")
        if chat.user_id != user_id:
            raise ValueError("candidate does not belong to this user")

        self.repo.set_candidate_status(candidate_id, "confirmed")
        entry = MemoryEntry(
            memory_type=row.memory_type,  # type: ignore[arg-type]
            target_layer=row.target_layer,  # type: ignore[arg-type]
            normalized_memory=row.normalized_memory,
            source=row.source,  # type: ignore[arg-type]
            status="confirmed",
        )
        return self.repo.add_memory_entry(user_id=user_id, entry=entry)

    def reject_candidate(self, *, candidate_id: str):
        row = self.repo.get_candidate(candidate_id)
        if not row or row.status != "candidate":
            raise ValueError("candidate not found or not pending")
        self.repo.set_candidate_status(candidate_id, "rejected")
