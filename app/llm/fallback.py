"""Single place: model chains + sequential Agent.run fallback on provider/runtime errors."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel

from app.llm.deepseek_openai_model import build_deepseek_openai_model, build_openai_provider_model
from app.settings import settings

OutputT = TypeVar("OutputT")


def chain_normalization_openai_then_deepseek() -> list[OpenAIModel]:
    """Primary OpenAI, fallback DeepSeek."""
    models: list[OpenAIModel] = []
    if settings.openai_enabled and (settings.openai_api_key or "").strip():
        models.append(
            build_openai_provider_model(
                settings.openai_normalize_model or settings.openai_interpret_model,
            )
        )
    if settings.deepseek_enabled and (settings.deepseek_api_key or "").strip():
        models.append(
            build_deepseek_openai_model(
                settings.deepseek_normalize_model or settings.deepseek_response_model,
            )
        )
    return models


def chain_deepseek_then_openai(*, deepseek_model: str, openai_fallback_model: str | None = None) -> list[OpenAIModel]:
    """Primary DeepSeek, fallback OpenAI."""
    om = (
        openai_fallback_model
        or settings.response_fallback_model
        or settings.openai_interpret_model
    )
    models: list[OpenAIModel] = []
    if settings.deepseek_enabled and (settings.deepseek_api_key or "").strip():
        models.append(build_deepseek_openai_model(deepseek_model))
    if settings.openai_enabled and (settings.openai_api_key or "").strip():
        models.append(build_openai_provider_model(om))
    return models


async def run_agent_with_fallback(
    *,
    models: list[OpenAIModel],
    build_agent: Callable[[OpenAIModel], Agent[None, OutputT]],
    prompt: str,
) -> OutputT:
    """
    Try each model in order; on any Exception from agent.run, try the next.
    Surfaces a single RuntimeError if every attempt fails.
    """
    if not models:
        raise RuntimeError(
            "No LLM providers available for this step. "
            "Enable and configure the required provider(s) and API keys in settings."
        )
    errors: list[str] = []
    last_exc: BaseException | None = None
    for m in models:
        try:
            agent = build_agent(m)
            result = await agent.run(prompt)
            return result.output
        except Exception as e:
            last_exc = e
            errors.append(f"{type(e).__name__}: {e}")
            continue
    msg = "All LLM providers failed: " + " | ".join(errors)
    if last_exc is not None:
        raise RuntimeError(msg) from last_exc
    raise RuntimeError(msg)
