"""
Explicit in-process test doubles for normalization/execution agents.

Used by unit tests and by dev-only HTTP endpoints when JEEVES_DEV_STUB_AGENTS is enabled.
This is not production behavior; it avoids external API keys for local manual testing.
"""

from __future__ import annotations

from app.domain.execution_decision import ExecutionDecision
from app.domain.normalized_user_request import NormalizedUserRequest


class FakeNormalizationAgent:
    async def normalize(self, *, raw_user_message: str, previous, revision: int) -> NormalizedUserRequest:
        return NormalizedUserRequest(
            normalized_user_request=f"normalize: {raw_user_message}",
            continuity="new",
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            ambiguity_handling="none",
            revision=revision,
        )

    async def apply_correction(self, *, correction_message: str, previous: NormalizedUserRequest) -> NormalizedUserRequest:
        return previous.model_copy(
            update={
                "normalized_user_request": f"corrected: {correction_message}",
                "continuity": "correct_previous",
                "revision": previous.revision + 1,
            }
        )


class FakeExecutionAgent:
    async def decide(self, *, request: NormalizedUserRequest) -> ExecutionDecision:
        return ExecutionDecision(
            can_execute_self=False,
            needs_external_info=False,
            needs_tool=False,
            needs_delegate=False,
            needs_decomposition=False,
            needs_user_confirmation=False,
            reason="fake",
        )


class FakeSelfExecuteDecisionAgent:
    async def decide(self, *, request: NormalizedUserRequest) -> ExecutionDecision:
        return ExecutionDecision(
            can_execute_self=True,
            needs_external_info=False,
            needs_tool=False,
            needs_delegate=False,
            needs_decomposition=False,
            needs_user_confirmation=False,
            reason="safe to execute",
        )


class FakeNeedsToolDecisionAgent:
    async def decide(self, *, request: NormalizedUserRequest) -> ExecutionDecision:
        return ExecutionDecision(
            can_execute_self=False,
            needs_external_info=False,
            needs_tool=True,
            needs_delegate=False,
            needs_decomposition=False,
            needs_user_confirmation=False,
            reason="needs a tool",
        )
