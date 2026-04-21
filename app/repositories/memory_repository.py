from __future__ import annotations

from sqlmodel import Session, select

from app.domain.memory_candidate import MemoryCandidate
from app.domain.memory_entry import MemoryEntry
from app.repositories.models import MemoryCandidateRow, MemoryEntryRow


def _normalized_memory_key(text: str) -> str:
    """Stable comparison key for duplicate pending candidates (whitespace/case)."""
    return " ".join((text or "").lower().split())


class MemoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_candidate(self, *, chat_id: str, cand: MemoryCandidate) -> MemoryCandidateRow:
        row = MemoryCandidateRow(
            chat_id=chat_id,
            memory_type=cand.memory_type,
            target_layer=cand.target_layer,
            normalized_memory=cand.normalized_memory,
            source=cand.source,
            confidence=cand.confidence,
            status="candidate",
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def list_candidates(self, chat_id: str | None = None, status: str = "candidate") -> list[MemoryCandidateRow]:
        stmt = select(MemoryCandidateRow).where(MemoryCandidateRow.status == status)
        if chat_id is not None:
            stmt = stmt.where(MemoryCandidateRow.chat_id == chat_id)
        return list(self.session.exec(stmt.order_by(MemoryCandidateRow.created_at.asc())))

    def has_pending_equivalent_normalized_memory(
        self,
        *,
        chat_id: str,
        normalized_memory: str,
        memory_type: str | None = None,
        target_layer: str | None = None,
        source: str | None = None,
    ) -> bool:
        """
        True if a pending candidate with the same semantic identity already exists for this chat.

        The text alone is not enough, because the same phrase may be meaningful as a different memory
        type, layer, or source.
        """
        key = _normalized_memory_key(normalized_memory)
        for row in self.list_candidates(chat_id=chat_id):
            if _normalized_memory_key(row.normalized_memory) != key:
                continue
            if memory_type is not None and row.memory_type != memory_type:
                continue
            if target_layer is not None and row.target_layer != target_layer:
                continue
            if source is not None and row.source != source:
                continue
            return True
        return False

    def get_candidate(self, candidate_id: str) -> MemoryCandidateRow | None:
        return self.session.get(MemoryCandidateRow, candidate_id)

    def set_candidate_status(self, candidate_id: str, status: str) -> None:
        row = self.session.get(MemoryCandidateRow, candidate_id)
        if not row:
            return
        row.status = status
        self.session.add(row)
        self.session.commit()

    def add_memory_entry(self, *, user_id: str, entry: MemoryEntry) -> MemoryEntryRow:
        row = MemoryEntryRow(
            user_id=user_id,
            memory_type=entry.memory_type,
            target_layer=entry.target_layer,
            normalized_memory=entry.normalized_memory,
            source=entry.source,
            status=entry.status,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row
