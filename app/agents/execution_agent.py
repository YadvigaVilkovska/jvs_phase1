from __future__ import annotations

from pydantic_ai import Agent

from app.domain.execution_decision import ExecutionDecision
from app.domain.normalized_user_request import NormalizedUserRequest
from app.llm.fallback import chain_deepseek_then_openai, run_agent_with_fallback
from app.settings import settings


class ExecutionAgent:
    """
    ExecutionDecision layer. Primary: DeepSeek, fallback: OpenAI.
    """

    def __init__(self, *, model=None):
        self._model = model

    def _models(self):
        if self._model is not None:
            return [self._model]
        return chain_deepseek_then_openai(
            deepseek_model=settings.deepseek_execution_model or settings.deepseek_response_model,
        )

    def _make_agent(self, model) -> Agent[None, ExecutionDecision]:
        system_prompt = (
            "You are Jeeves' ExecutionDecision layer.\n"
            "Input is a confirmed NormalizedUserRequest.\n"
            "Output MUST be a valid ExecutionDecision object.\n\n"
            "Rules:\n"
            "- First decide can_execute_self.\n"
            "- If cannot execute, set the appropriate needs_* flags.\n"
            "- Do not override the user's intent; do not re-normalize.\n"
            "- reason must be a short, explicit explanation.\n"
        )
        return Agent(model, output_type=ExecutionDecision, system_prompt=system_prompt)

    async def decide(self, *, request: NormalizedUserRequest) -> ExecutionDecision:
        prompt = (
            "Given the confirmed normalized request below, decide whether Jeeves can execute.\n\n"
            f"normalized_request_json: {request.model_dump_json()}\n"
        )
        return await run_agent_with_fallback(
            models=self._models(),
            build_agent=self._make_agent,
            prompt=prompt,
        )
