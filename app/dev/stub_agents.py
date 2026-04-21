"""
Explicit in-process test doubles for normalization/execution agents.

Used by unit tests and by dev-only HTTP endpoints when JEEVES_DEV_STUB_AGENTS is enabled.
This is not production behavior; it avoids external API keys for local manual testing.
"""

from __future__ import annotations

from app.domain.execution_decision import ExecutionDecision
from app.domain.normalized_user_request import NormalizedUserRequest
from app.domain.turn_intent import TurnIntent


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


class FakeIntentAgent:
    """
    Test double for LLM intent routing.

    This is ONLY for unit tests and dev-only endpoints. Production routing must remain LLM-first.
    """

    async def classify(self, *, raw_user_message: str, context: dict) -> TurnIntent:
        text = (raw_user_message or "").strip().lower()
        awaiting_feedback = bool(context.get("awaiting_user_feedback"))
        has_norm = bool(context.get("has_normalized_request"))

        if text.startswith("запомни") or text.startswith("remember"):
            payload = raw_user_message.strip()
            for prefix in ("запомни", "remember"):
                if payload.lower().startswith(prefix):
                    payload = payload[len(prefix) :].strip(" :—-")
            return TurnIntent(kind="memory_store", memory_text=payload, confidence=0.9, reason="fake memory_store")

        if awaiting_feedback and has_norm:
            return TurnIntent(kind="other", confidence=0.5, reason="review must use explicit confirm/reject endpoints")

        return TurnIntent(kind="new_task", confidence=0.7, reason="fake new_task")


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
