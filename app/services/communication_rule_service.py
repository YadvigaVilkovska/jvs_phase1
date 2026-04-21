from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.agents.communication_rule_agent import CommunicationRuleAgent, CommunicationRuleTurnContext
from app.domain.communication_rule import (
    CommunicationRuleCandidate,
    CommunicationRuleEvidence,
    CommunicationRuleEvidenceType,
    CommunicationRuleState,
)
from app.repositories.communication_rule_repository import CommunicationRuleRepository
from app.repositories.models import CommunicationRuleCandidateRow, CommunicationRuleStateRow

INITIAL_REQUEST_DELTA = 0.20
REPEAT_REQUEST_DELTA = 0.20
EXPLICIT_CONFIRMATION_DELTA = 0.35
POSITIVE_FEEDBACK_DELTA = 0.15
NEGATIVE_FEEDBACK_DELTA = -0.30
EXPLICIT_REVOKE_DELTA = -1.0
SOFT_ACTIVE_THRESHOLD = 0.35
ACTIVE_THRESHOLD = 0.70
MIN_SCORE = 0.0
MAX_SCORE = 1.0

_OPPOSITE_RULE_KEY = {
    "brevity": "detail_level",
    "detail_level": "brevity",
}


@dataclass(frozen=True)
class RuleExtraction:
    """LLM-first extraction result for chat-driven rule learning."""

    rule_key: str
    rule_text: str
    scope: str
    extraction_confidence: float
    canonical_value: dict[str, str]


class CommunicationRuleService:
    """Lifecycle service for probabilistic communication preferences."""

    def __init__(self, *, repository: CommunicationRuleRepository, agent: CommunicationRuleAgent | None = None):
        self.repository = repository
        self.agent = agent or CommunicationRuleAgent()

    async def extract_rule(
        self,
        *,
        raw_user_message: str,
        user_id: str,
        chat_id: str,
    ) -> RuleExtraction | None:
        try:
            out = await self.agent.extract(
                raw_user_message=raw_user_message,
                context=CommunicationRuleTurnContext(user_id=user_id, chat_id=chat_id),
            )
        except RuntimeError:
            # Honest no-provider failure: this layer is optional; do not block core chat.
            return None
        if not out.propose_rule or out.rule_key is None:
            return None
        return RuleExtraction(
            rule_key=out.rule_key,
            rule_text=raw_user_message.strip(),
            scope=out.scope,
            extraction_confidence=out.confidence,
            canonical_value=out.canonical_value or {"value": out.rule_key},
        )

    async def ingest_explicit_request(self, *, user_id: str, chat_id: str, raw_user_message: str) -> CommunicationRuleState | None:
        extraction = await self.extract_rule(raw_user_message=raw_user_message, user_id=user_id, chat_id=chat_id)
        if extraction is None:
            return None
        return self._apply_evidence(
            user_id=user_id,
            chat_id=chat_id,
            rule_key=extraction.rule_key,
            rule_text=extraction.rule_text,
            scope=extraction.scope,
            event_type="explicit_request",
            delta=INITIAL_REQUEST_DELTA,
            extraction_confidence=extraction.extraction_confidence,
            canonical_value=extraction.canonical_value,
            create_candidate=True,
        )

    async def register_repeated_instruction(self, *, user_id: str, chat_id: str, raw_user_message: str) -> CommunicationRuleState | None:
        extraction = await self.extract_rule(raw_user_message=raw_user_message, user_id=user_id, chat_id=chat_id)
        if extraction is None:
            return None
        return self._apply_evidence(
            user_id=user_id,
            chat_id=chat_id,
            rule_key=extraction.rule_key,
            rule_text=extraction.rule_text,
            scope=extraction.scope,
            event_type="repeat_request",
            delta=REPEAT_REQUEST_DELTA,
            extraction_confidence=extraction.extraction_confidence,
            canonical_value=extraction.canonical_value,
            create_candidate=False,
        )

    def apply_feedback(
        self,
        *,
        user_id: str,
        chat_id: str,
        rule_key: str,
        event_type: CommunicationRuleEvidenceType,
    ) -> CommunicationRuleState | None:
        delta_by_event = {
            "explicit_confirmation": EXPLICIT_CONFIRMATION_DELTA,
            "positive_feedback": POSITIVE_FEEDBACK_DELTA,
            "negative_feedback": NEGATIVE_FEEDBACK_DELTA,
            "explicit_revoke": EXPLICIT_REVOKE_DELTA,
        }
        if event_type not in delta_by_event:
            raise ValueError(f"Unsupported feedback event: {event_type}")

        state_row = self._resolve_state_for_feedback(user_id=user_id, chat_id=chat_id, rule_key=rule_key)
        if state_row is None:
            return None

        if event_type == "explicit_revoke":
            return self._apply_state_event(
                state_row=state_row,
                event_type=event_type,
                delta=MIN_SCORE - state_row.score,
                score=MIN_SCORE,
                status="revoked",
            )

        new_score = _clamp(state_row.score + delta_by_event[event_type])
        status = _status_for_score(new_score)

        return self._apply_state_event(
            state_row=state_row,
            event_type=event_type,
            delta=new_score - state_row.score,
            score=new_score,
            status=status,
        )

    def register_positive_feedback(self, *, user_id: str, chat_id: str, rule_key: str) -> CommunicationRuleState | None:
        return self.apply_feedback(user_id=user_id, chat_id=chat_id, rule_key=rule_key, event_type="positive_feedback")

    def register_negative_feedback(self, *, user_id: str, chat_id: str, rule_key: str) -> CommunicationRuleState | None:
        return self.apply_feedback(user_id=user_id, chat_id=chat_id, rule_key=rule_key, event_type="negative_feedback")

    def register_confirmation(self, *, user_id: str, chat_id: str, rule_key: str) -> CommunicationRuleState | None:
        return self.apply_feedback(user_id=user_id, chat_id=chat_id, rule_key=rule_key, event_type="explicit_confirmation")

    def register_revoke(self, *, user_id: str, chat_id: str, rule_key: str) -> CommunicationRuleState | None:
        return self.apply_feedback(user_id=user_id, chat_id=chat_id, rule_key=rule_key, event_type="explicit_revoke")

    def get_applicable_rules(self, *, user_id: str, chat_id: str | None = None) -> dict[str, list[CommunicationRuleState]]:
        rows = self.repository.list_applicable_states(user_id=user_id, chat_id=chat_id)
        soft_rules: list[CommunicationRuleState] = []
        active_rules: list[CommunicationRuleState] = []
        for row in rows:
            state = _row_to_state(row)
            if state.status == "active":
                active_rules.append(state)
            elif state.status == "soft_active":
                soft_rules.append(state)
        return {"soft_rules": soft_rules, "active_rules": active_rules}

    def build_prompt_context(self, *, user_id: str, chat_id: str | None = None) -> str:
        applicable = self.get_applicable_rules(user_id=user_id, chat_id=chat_id)
        rendered = self._resolve_precedence(applicable["active_rules"], applicable["soft_rules"])
        parts = []
        if rendered["active"]:
            parts.append("Активные правила общения:")
            parts.extend(f"- {self._render_rule_instruction(rule)}" for rule in rendered["active"])
        if rendered["soft"]:
            parts.append("Мягкие правила общения:")
            parts.extend(f"- {self._render_rule_instruction(rule)}" for rule in rendered["soft"])
        return "\n".join(parts)

    def _apply_evidence(
        self,
        *,
        user_id: str,
        chat_id: str,
        rule_key: str,
        rule_text: str,
        scope: str,
        event_type: CommunicationRuleEvidenceType,
        delta: float,
        extraction_confidence: float,
        canonical_value: dict[str, str],
        create_candidate: bool,
    ) -> CommunicationRuleState:
        now = datetime.now(timezone.utc)
        try:
            existing_state = self.repository.get_state(user_id, rule_key, scope, chat_id=chat_id if scope == "current_chat" else None)
            is_new_state = existing_state is None

            if is_new_state:
                state_row = self.repository.upsert_state(
                    CommunicationRuleState(
                        user_id=user_id,
                        chat_id=chat_id if scope == "current_chat" else None,
                        rule_key=rule_key,
                        scope=scope,
                        canonical_value_json=json.dumps(canonical_value, ensure_ascii=False),
                        score=_clamp(delta),
                        status=_status_for_score(delta),
                        evidence_count=0,
                        updated_at=now,
                    )
                )
            else:
                updated_score = _clamp(existing_state.score + delta)
                state_row = self.repository.upsert_state(
                    CommunicationRuleState(
                        user_id=user_id,
                        chat_id=existing_state.chat_id,
                        rule_key=rule_key,
                        scope=scope,
                        canonical_value_json=existing_state.canonical_value_json,
                        score=updated_score,
                        status=_status_for_score(updated_score),
                        evidence_count=existing_state.evidence_count,
                        last_confirmed_at=existing_state.last_confirmed_at,
                        last_applied_at=existing_state.last_applied_at,
                        updated_at=now,
                    )
                )

            candidate_row = self._maybe_create_candidate(
                create_candidate=create_candidate,
                is_new_state=is_new_state,
                user_id=user_id,
                chat_id=chat_id,
                rule_key=rule_key,
                rule_text=rule_text,
                scope=scope,
                extraction_confidence=extraction_confidence,
                state_row=state_row,
                now=now,
            )

            self.repository.add_evidence(
                CommunicationRuleEvidence(
                    rule_state_id=state_row.id,
                    event_type=event_type,
                    delta=delta,
                    created_at=now,
                    candidate_id=candidate_row.id if candidate_row is not None else None,
                )
            )

            final_state = self.repository.upsert_state(
                CommunicationRuleState(
                    user_id=state_row.user_id,
                    chat_id=state_row.chat_id,
                    rule_key=state_row.rule_key,
                    scope=state_row.scope,
                    canonical_value_json=state_row.canonical_value_json,
                    score=state_row.score,
                    status=state_row.status,
                    evidence_count=state_row.evidence_count + 1,
                    last_confirmed_at=now if event_type == "explicit_confirmation" else state_row.last_confirmed_at,
                    last_applied_at=state_row.last_applied_at,
                    updated_at=now,
                )
            )
            self.repository.commit()
            return _row_to_state(final_state)
        except Exception:
            self.repository.rollback()
            raise

    def _resolve_state_for_feedback(self, *, user_id: str, chat_id: str, rule_key: str) -> CommunicationRuleStateRow | None:
        current_chat_state = self.repository.get_state(user_id, rule_key, "current_chat", chat_id=chat_id)
        if current_chat_state is not None:
            return current_chat_state
        return self.repository.get_state(user_id, rule_key, "global", chat_id=None)

    def _resolve_precedence(
        self,
        active_rules: list[CommunicationRuleState],
        soft_rules: list[CommunicationRuleState],
    ) -> dict[str, list[CommunicationRuleState]]:
        all_rules = active_rules + soft_rules
        current_chat_rules = [rule for rule in all_rules if rule.scope == "current_chat"]
        current_rule_keys = {rule.rule_key for rule in current_chat_rules}
        current_opposites = {
            opposite
            for opposite in (_OPPOSITE_RULE_KEY.get(rule.rule_key) for rule in current_chat_rules)
            if opposite is not None
        }
        return {
            "active": self._prefer_current_chat_over_global(active_rules, current_rule_keys, current_opposites),
            "soft": self._prefer_current_chat_over_global(soft_rules, current_rule_keys, current_opposites),
        }

    def _prefer_current_chat_over_global(
        self,
        rules: list[CommunicationRuleState],
        current_rule_keys: set[str],
        current_opposites: set[str],
    ) -> list[CommunicationRuleState]:
        current_chat_rules = [rule for rule in rules if rule.scope == "current_chat"]
        global_rules = [rule for rule in rules if rule.scope == "global"]
        filtered_global_rules = [
            rule
            for rule in global_rules
            if rule.rule_key not in current_rule_keys and rule.rule_key not in current_opposites
        ]
        ordered: list[CommunicationRuleState] = []
        seen_keys: set[str] = set()
        for rule in current_chat_rules + filtered_global_rules:
            if rule.rule_key in seen_keys:
                continue
            ordered.append(rule)
            seen_keys.add(rule.rule_key)
        return ordered

    def _render_rule_instruction(self, rule: CommunicationRuleState) -> str:
        payload = self._parse_canonical_value(rule.canonical_value_json)
        if rule.rule_key == "brevity":
            return "Отвечай кратко."
        if rule.rule_key == "emoji_usage":
            value = self._scalar_value(payload)
            if value == "avoid":
                return "Не используй эмодзи."
            return "Можно использовать эмодзи, но редко."
        if rule.rule_key == "detail_level":
            value = self._scalar_value(payload)
            if value == "high":
                return "Дай подробные объяснения."
            return "Держи объяснения краткими, но достаточными."
        if rule.rule_key == "formality":
            return "Используй более формальный тон."
        if rule.rule_key == "answer_structure":
            return "Сначала дай вывод, затем детали."
        return "Следуй предпочтениям пользователя по стилю общения."

    @staticmethod
    def _parse_canonical_value(raw: str | None):
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    @staticmethod
    def _scalar_value(value) -> str | None:
        if isinstance(value, dict):
            scalar = value.get("value")
            return str(scalar).lower() if scalar is not None else None
        if value is None:
            return None
        return str(value).lower()

    def _maybe_create_candidate(
        self,
        *,
        create_candidate: bool,
        is_new_state: bool,
        user_id: str,
        chat_id: str,
        rule_key: str,
        rule_text: str,
        scope: str,
        extraction_confidence: float,
        state_row: CommunicationRuleStateRow,
        now: datetime,
    ) -> CommunicationRuleCandidateRow | None:
        if not create_candidate or not is_new_state:
            return None
        return self.repository.add_candidate(
            CommunicationRuleCandidate(
                user_id=user_id,
                chat_id=chat_id,
                rule_key=rule_key,
                rule_text=rule_text,
                scope=scope,
                extraction_confidence=extraction_confidence,
                initial_score=state_row.score,
                status=state_row.status,
                created_at=now,
                rule_state_id=state_row.id,
            )
        )

    def _apply_state_event(
        self,
        *,
        state_row: CommunicationRuleStateRow,
        event_type: CommunicationRuleEvidenceType,
        delta: float,
        score: float,
        status: str,
    ) -> CommunicationRuleState:
        try:
            now = datetime.now(timezone.utc)
            updated = self.repository.upsert_state(
                CommunicationRuleState(
                    user_id=state_row.user_id,
                    chat_id=state_row.chat_id,
                    rule_key=state_row.rule_key,
                    scope=state_row.scope,
                    canonical_value_json=state_row.canonical_value_json,
                    score=score,
                    status=status,
                    evidence_count=state_row.evidence_count + 1,
                    last_confirmed_at=now if event_type == "explicit_confirmation" else state_row.last_confirmed_at,
                    last_applied_at=state_row.last_applied_at,
                    updated_at=now,
                )
            )
            self.repository.add_evidence(
                CommunicationRuleEvidence(
                    rule_state_id=updated.id,
                    event_type=event_type,
                    delta=delta,
                    created_at=now,
                )
            )
            self.repository.commit()
            return _row_to_state(updated)
        except Exception:
            self.repository.rollback()
            raise


def _clamp(score: float) -> float:
    return max(MIN_SCORE, min(MAX_SCORE, score))


def _status_for_score(score: float) -> str:
    if score < SOFT_ACTIVE_THRESHOLD:
        return "candidate"
    if score < ACTIVE_THRESHOLD:
        return "soft_active"
    return "active"


def _row_to_state(row) -> CommunicationRuleState:
    return CommunicationRuleState(
        user_id=row.user_id,
        chat_id=row.chat_id,
        rule_key=row.rule_key,
        scope=row.scope,
        canonical_value_json=row.canonical_value_json,
        score=row.score,
        status=row.status,
        evidence_count=row.evidence_count,
        last_confirmed_at=row.last_confirmed_at,
        last_applied_at=row.last_applied_at,
        updated_at=row.updated_at,
    )
