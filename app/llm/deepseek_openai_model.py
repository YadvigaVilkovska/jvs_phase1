"""OpenAI-compatible clients for pydantic-ai (OpenAIProvider + DeepSeek endpoint)."""

from __future__ import annotations

from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.settings import settings


def build_openai_provider_model(model_name: str) -> OpenAIModel:
    """OpenAI or OpenAI-compatible API using project OpenAI settings."""
    base = (settings.openai_base_url or "").strip() or None
    return OpenAIModel(
        model_name,
        provider=OpenAIProvider(
            api_key=settings.openai_api_key,
            base_url=base,
        ),
    )


def build_deepseek_openai_model(model_name: str) -> OpenAIModel:
    """DeepSeek via OpenAI-compatible client (settings.deepseek_*)."""
    return OpenAIModel(
        model_name,
        provider=OpenAIProvider(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        ),
    )
