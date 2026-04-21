from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.llm.fallback import chain_normalization_openai_then_deepseek, run_agent_with_fallback


CommunicationRuleKey = Literal[
    "brevity",
    "detail_level",
    "emoji_usage",
    "formality",
    "answer_structure",
]


class CommunicationRuleExtraction(BaseModel):
    propose_rule: bool
    rule_key: CommunicationRuleKey | None = None
    scope: Literal["global", "current_chat"] = "current_chat"
    canonical_value: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


@dataclass(frozen=True)
class CommunicationRuleTurnContext:
    user_id: str
    chat_id: str


class CommunicationRuleAgent:
    """
    LLM-first extraction for probabilistic communication rules.

    Replaces deterministic phrase dictionaries. No keyword heuristics.
    """

    def __init__(self, *, model=None):
        self._model = model

    def _models(self):
        if self._model is not None:
            return [self._model]
        return chain_normalization_openai_then_deepseek()

    def _make_agent(self, model) -> Agent[None, CommunicationRuleExtraction]:
        system_prompt = (
            "You extract communication style rules from a single user message.\n"
            "Output a valid CommunicationRuleExtraction object.\n\n"
            "A rule is a durable preference about how Jeeves should communicate, e.g.:\n"
            "- be brief / more detailed\n"
            "- avoid emojis\n"
            "- be more formal\n"
            "- structure: conclusion first\n\n"
            "Rules:\n"
            "- Use semantic judgment; do NOT rely on keyword matching.\n"
            "- If the message is about the task content (not style), set propose_rule=false.\n"
            "- If propose_rule=true, set rule_key and canonical_value.\n"
            "- confidence is 0..1.\n"
        )
        return Agent(model, output_type=CommunicationRuleExtraction, system_prompt=system_prompt)

    async def extract(self, *, raw_user_message: str, context: CommunicationRuleTurnContext) -> CommunicationRuleExtraction:
        prompt = (
            "Extract a communication rule from the message if applicable.\n\n"
            f"raw_user_message: {raw_user_message}\n"
            f"context_json: {json.dumps({'user_id': context.user_id, 'chat_id': context.chat_id}, ensure_ascii=False)}\n"
        )
        return await run_agent_with_fallback(
            models=self._models(),
            build_agent=self._make_agent,
            prompt=prompt,
        )

