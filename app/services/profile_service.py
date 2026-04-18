from __future__ import annotations

import json

from sqlmodel import Session

from app.domain.core_profile import CoreProfile
from app.repositories.profile_repository import ProfileRepository


class ProfileService:
    def __init__(self, *, session: Session):
        self.session = session
        self.repo = ProfileRepository(session)

    def get_profile(self, *, user_id: str) -> CoreProfile:
        rows = self.repo.list_entries(user_id=user_id, status="confirmed")
        entries = {r.key: json.loads(r.value_json) for r in rows}
        confirmed = [r.key for r in rows]
        return CoreProfile(user_id=user_id, entries=entries, confirmed_memories=confirmed)

