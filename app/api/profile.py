from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import db_session
from app.services.profile_service import ProfileService


router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileResponse(BaseModel):
    user_id: str
    entries: dict
    confirmed_memories: list[str]


@router.get("", response_model=ProfileResponse)
def get_profile(user_id: str = Query(..., min_length=1), session: Session = Depends(db_session)):
    svc = ProfileService(session=session)
    profile = svc.get_profile(user_id=user_id)
    return ProfileResponse(
        user_id=profile.user_id,
        entries=profile.entries,
        confirmed_memories=profile.confirmed_memories,
    )

