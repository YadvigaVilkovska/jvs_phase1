from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.domain.communication_rule import (
    CommunicationRuleCandidate,
    CommunicationRuleEvidence,
    CommunicationRuleState,
)
from app.repositories.models import (
    CommunicationRuleCandidateRow,
    CommunicationRuleEvidenceRow,
    CommunicationRuleStateRow,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommunicationRuleRepository:
    """Persistence adapter for probabilistic communication rules."""

    def __init__(self, session: Session):
        self.session = session

    def add_candidate(self, candidate: CommunicationRuleCandidate) -> CommunicationRuleCandidateRow:
        row = CommunicationRuleCandidateRow(
            user_id=candidate.user_id,
            chat_id=candidate.chat_id,
            rule_key=candidate.rule_key,
            rule_text=candidate.rule_text,
            scope=candidate.scope,
            extraction_confidence=candidate.extraction_confidence,
            initial_score=candidate.initial_score,
            status=candidate.status,
            rule_state_id=candidate.rule_state_id,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def upsert_state(self, state: CommunicationRuleState) -> CommunicationRuleStateRow:
        row = self.get_state(state.user_id, state.rule_key, state.scope, chat_id=state.chat_id)
        if row is None:
            row = CommunicationRuleStateRow(
                user_id=state.user_id,
                chat_id=state.chat_id if state.scope == "current_chat" else None,
                rule_key=state.rule_key,
                scope=state.scope,
                canonical_value_json=state.canonical_value_json or "null",
                score=state.score,
                status=state.status,
                evidence_count=state.evidence_count,
                last_confirmed_at=state.last_confirmed_at,
                last_applied_at=state.last_applied_at,
                updated_at=state.updated_at or _utcnow(),
            )
            self.session.add(row)
        else:
            row.canonical_value_json = state.canonical_value_json or "null"
            row.score = state.score
            row.status = state.status
            row.evidence_count = state.evidence_count
            row.last_confirmed_at = state.last_confirmed_at
            row.last_applied_at = state.last_applied_at
            row.updated_at = state.updated_at or _utcnow()
            row.chat_id = state.chat_id if state.scope == "current_chat" else None
            self.session.add(row)
        self.session.flush()
        return row

    def get_state(
        self,
        user_id: str,
        rule_key: str,
        scope: str,
        chat_id: str | None = None,
    ) -> CommunicationRuleStateRow | None:
        rows = list(
            self.session.exec(
                select(CommunicationRuleStateRow)
                .where(CommunicationRuleStateRow.user_id == user_id)
                .where(CommunicationRuleStateRow.rule_key == rule_key)
                .where(CommunicationRuleStateRow.scope == scope)
                .where(CommunicationRuleStateRow.chat_id == chat_id if scope == "current_chat" else CommunicationRuleStateRow.chat_id.is_(None))
                .limit(1)
            )
        )
        return rows[0] if rows else None

    def list_states(self, user_id: str) -> list[CommunicationRuleStateRow]:
        return list(
            self.session.exec(
                select(CommunicationRuleStateRow)
                .where(CommunicationRuleStateRow.user_id == user_id)
                .order_by(CommunicationRuleStateRow.updated_at.desc())
            )
        )

    def list_applicable_states(self, user_id: str, chat_id: str | None = None) -> list[CommunicationRuleStateRow]:
        stmt = (
            select(CommunicationRuleStateRow)
            .where(CommunicationRuleStateRow.user_id == user_id)
            .where(CommunicationRuleStateRow.status.in_(("soft_active", "active")))
        )
        if chat_id is None:
            stmt = stmt.where(CommunicationRuleStateRow.scope == "global")
        else:
            stmt = stmt.where(
                (CommunicationRuleStateRow.scope == "global")
                | (
                    (CommunicationRuleStateRow.scope == "current_chat")
                    & (CommunicationRuleStateRow.chat_id == chat_id)
                )
            )
        return list(self.session.exec(stmt.order_by(CommunicationRuleStateRow.updated_at.desc())))

    def add_evidence(self, evidence: CommunicationRuleEvidence) -> CommunicationRuleEvidenceRow:
        row = CommunicationRuleEvidenceRow(
            rule_state_id=evidence.rule_state_id,
            event_type=evidence.event_type,
            delta=evidence.delta,
            message_id=evidence.message_id,
            candidate_id=evidence.candidate_id,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
