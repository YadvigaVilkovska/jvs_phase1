from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class CoreProfile(BaseModel):
    """
    Deepest memory layer (operational profile).

    This is intentionally minimal in v1: it stores confirmed entries as structured data
    and keeps a change history at the persistence layer.
    """

    user_id: str
    entries: Dict[str, Any] = Field(default_factory=dict)
    confirmed_memories: List[str] = Field(default_factory=list)

