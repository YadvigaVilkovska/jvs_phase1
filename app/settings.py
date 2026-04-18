from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/jeeves.db"

    openai_enabled: bool = False
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_interpret_model: str = "gpt-4o-mini"
    openai_normalize_model: str = "gpt-4o-mini"

    deepseek_enabled: bool = False
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_response_model: str = "deepseek-chat"
    deepseek_normalize_model: str = "deepseek-chat"
    deepseek_execution_model: str = "deepseek-chat"
    deepseek_memory_model: str = "deepseek-chat"
    deepseek_runner_model: str = "deepseek-chat"

    response_fallback_model: str = "gpt-4o-mini"

    # Dev-only: use in-process stub agents for /dev/demo-flow and easier local manual testing without API keys.
    # Never enable in production.
    jeeves_dev_stub_agents: bool = False


settings = Settings()

