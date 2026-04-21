from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.repositories.models import CoreProfileEntryRow


class ProfileRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_entries(self, user_id: str, status: str = "confirmed") -> list[CoreProfileEntryRow]:
        return list(
            self.session.exec(
                select(CoreProfileEntryRow)
                .where(CoreProfileEntryRow.user_id == user_id)
                .where(CoreProfileEntryRow.status == status)
                .order_by(CoreProfileEntryRow.updated_at.desc())
            )
        )

    def upsert_entry(
        self,
        *,
        user_id: str,
        key: str,
        value: object,
        source: str,
        status: str = "confirmed",
    ) -> CoreProfileEntryRow:
        existing = list(
            self.session.exec(
                select(CoreProfileEntryRow)
                .where(CoreProfileEntryRow.user_id == user_id)
                .where(CoreProfileEntryRow.key == key)
                .where(CoreProfileEntryRow.status == status)
                .limit(1)
            )
        )
        if existing:
            row = existing[0]
            row.value_json = json.dumps(value, ensure_ascii=False)
            row.source = source
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = CoreProfileEntryRow(
                user_id=user_id,
                key=key,
                value_json=json.dumps(value, ensure_ascii=False),
                source=source,
                status=status,
            )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row
