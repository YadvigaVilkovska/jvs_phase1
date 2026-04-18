from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class MemoryEntry(BaseModel):
    memory_type: Literal["fact", "preference", "rule"]
    target_layer: Literal["long_term_memory", "core_profile"]
    normalized_memory: str
    source: Literal["user_requested", "post_chat_analysis"]
    status: Literal["confirmed", "rejected", "archived"]

