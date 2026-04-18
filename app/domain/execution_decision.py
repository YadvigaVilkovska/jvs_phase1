from __future__ import annotations

from pydantic import BaseModel


class ExecutionDecision(BaseModel):
    can_execute_self: bool
    needs_external_info: bool
    needs_tool: bool
    needs_delegate: bool
    needs_decomposition: bool
    needs_user_confirmation: bool
    reason: str

