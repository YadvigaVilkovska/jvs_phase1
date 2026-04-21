from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent

from app.domain.execution_decision import ExecutionDecision
from app.domain.normalized_user_request import NormalizedUserRequest
from app.llm.fallback import chain_deepseek_then_openai, run_agent_with_fallback
from app.settings import settings


@dataclass(frozen=True)
class ExecutionRunResult:
    status: str  # completed|blocked
    message: str


class ExecutionService:
    """
    v1 execution runner.

    This runner does NOT decide *whether* to execute. It consumes an existing ExecutionDecision.
    Text-only self-execution. Primary: DeepSeek, fallback: OpenAI.
    """

    def __init__(self, *, model=None):
        self._model = model

    def _models(self):
        if self._model is not None:
            return [self._model]
        return chain_deepseek_then_openai(deepseek_model=settings.deepseek_runner_model)

    def _make_agent(self, model) -> Agent[None, str]:
        system_prompt = (
            "You are Jeeves' execution runner.\n"
            "You will receive a confirmed normalized request.\n"
            "You MUST produce a helpful final answer in plain text.\n\n"
            "Constraints:\n"
            "- Do not claim to have used tools, internet, or delegates.\n"
            "- If the request requires external info or tools, you should say you are blocked.\n"
            "- Keep it concise.\n"
        )
        return Agent(model, output_type=str, system_prompt=system_prompt)

    async def execute(
        self,
        *,
        decision: ExecutionDecision,
        request: NormalizedUserRequest,
        communication_rule_context: str = "",
    ) -> ExecutionRunResult:
        if not decision.can_execute_self:
            return ExecutionRunResult(status="blocked", message=decision.reason)

        if (
            decision.needs_external_info
            or decision.needs_tool
            or decision.needs_delegate
            or decision.needs_decomposition
            or decision.needs_user_confirmation
        ):
            return ExecutionRunResult(
                status="blocked",
                message=(
                    "Execution is blocked: requires external info/tool/delegate/decomposition/confirmation "
                    f"({decision.reason})"
                ),
            )

        prompt = (
            "Execute this request without external tools.\n"
            "Follow any language, length, tone, or format constraints stated in normalized_user_request exactly.\n\n"
            f"communication_rule_context:\n{communication_rule_context or '(none)'}\n\n"
            f"normalized_user_request: {request.normalized_user_request}\n"
        )
        text = await run_agent_with_fallback(
            models=self._models(),
            build_agent=self._make_agent,
            prompt=prompt,
        )
        return ExecutionRunResult(status="completed", message=text.strip())
