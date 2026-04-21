from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.domain.execution_decision import ExecutionDecision
from app.domain.normalized_user_request import NormalizedUserRequest
from app.repositories.models import (
    Chat,
    ExecutionDecisionRow,
    Message,
    NormalizedRequestRow,
)


class ChatRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_chat(self, user_id: str) -> Chat:
        chat = Chat(user_id=user_id, status="open")
        self.session.add(chat)
        self.session.commit()
        self.session.refresh(chat)
        return chat

    def get_chat(self, chat_id: str) -> Chat | None:
        return self.session.get(Chat, chat_id)

    def close_chat(self, chat_id: str) -> None:
        chat = self.session.get(Chat, chat_id)
        if not chat:
            return
        chat.status = "closed"
        chat.closed_at = datetime.now(timezone.utc)
        self.session.add(chat)
        self.session.commit()

    def mark_post_chat_extraction_completed(self, chat_id: str) -> None:
        chat = self.session.get(Chat, chat_id)
        if not chat:
            return
        chat.post_chat_extraction_completed = True
        self.session.add(chat)
        self.session.commit()

    def set_chat_status(self, chat_id: str, status: str) -> None:
        chat = self.session.get(Chat, chat_id)
        if not chat:
            return
        chat.status = status
        self.session.add(chat)
        self.session.commit()

    def add_message(self, chat_id: str, actor: str, content: str) -> Message:
        msg = Message(chat_id=chat_id, actor=actor, content=content)
        self.session.add(msg)
        self.session.commit()
        self.session.refresh(msg)
        return msg

    def list_messages(self, chat_id: str) -> list[Message]:
        return list(
            self.session.exec(
                select(Message)
                .where(Message.chat_id == chat_id)
                .order_by(Message.created_at.asc())
            )
        )

    def get_latest_message(self, chat_id: str, *, actor: str | None = None) -> Message | None:
        stmt = select(Message).where(Message.chat_id == chat_id)
        if actor is not None:
            stmt = stmt.where(Message.actor == actor)
        rows = list(self.session.exec(stmt.order_by(Message.created_at.desc()).limit(1)))
        return rows[0] if rows else None

    def add_normalized_request(
        self,
        *,
        chat_id: str,
        message_id: str,
        req: NormalizedUserRequest,
    ) -> NormalizedRequestRow:
        row = NormalizedRequestRow(
            chat_id=chat_id,
            message_id=message_id,
            revision=req.revision,
            normalized_user_request=req.normalized_user_request,
            continuity=req.continuity,
            needs_clarification=req.needs_clarification,
            clarification_reason=req.clarification_reason,
            clarification_options_json=json.dumps(req.clarification_options, ensure_ascii=False),
            ambiguity_handling=req.ambiguity_handling,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def list_normalized_requests(self, chat_id: str) -> list[NormalizedRequestRow]:
        return list(
            self.session.exec(
                select(NormalizedRequestRow)
                .where(NormalizedRequestRow.chat_id == chat_id)
                .order_by(NormalizedRequestRow.revision.asc(), NormalizedRequestRow.created_at.asc())
            )
        )

    def get_latest_normalized_request(self, chat_id: str) -> NormalizedRequestRow | None:
        rows = list(
            self.session.exec(
                select(NormalizedRequestRow)
                .where(NormalizedRequestRow.chat_id == chat_id)
                .order_by(NormalizedRequestRow.revision.desc(), NormalizedRequestRow.created_at.desc())
                .limit(1)
            )
        )
        return rows[0] if rows else None

    def normalized_request_exists(self, *, chat_id: str, message_id: str, revision: int) -> bool:
        rows = list(
            self.session.exec(
                select(NormalizedRequestRow.id)
                .where(NormalizedRequestRow.chat_id == chat_id)
                .where(NormalizedRequestRow.message_id == message_id)
                .where(NormalizedRequestRow.revision == revision)
                .limit(1)
            )
        )
        return len(rows) > 0

    def add_execution_decision(
        self, *, chat_id: str, normalized_request_id: str, decision: ExecutionDecision
    ) -> ExecutionDecisionRow:
        row = ExecutionDecisionRow(
            chat_id=chat_id,
            normalized_request_id=normalized_request_id,
            can_execute_self=decision.can_execute_self,
            needs_external_info=decision.needs_external_info,
            needs_tool=decision.needs_tool,
            needs_delegate=decision.needs_delegate,
            needs_decomposition=decision.needs_decomposition,
            needs_user_confirmation=decision.needs_user_confirmation,
            reason=decision.reason,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row
