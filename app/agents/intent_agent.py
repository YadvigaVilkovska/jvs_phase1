from __future__ import annotations

import json

from pydantic_ai import Agent

from app.domain.turn_intent import TurnIntent
from app.llm.fallback import chain_normalization_openai_then_deepseek, run_agent_with_fallback


class IntentAgent:
    """
    LLM-first routing for a user turn.

    This replaces keyword heuristics ("yes"/"confirm"/"исправь") with structured intent classification.
    Primary: OpenAI (cheap, fast), fallback: DeepSeek (same chain as normalization).
    """

    def __init__(self, *, model=None):
        self._model = model

    def _models(self):
        if self._model is not None:
            return [self._model]
        return chain_normalization_openai_then_deepseek()

    def _make_agent(self, model) -> Agent[None, TurnIntent]:
        system_prompt = (
            "You are Jeeves' turn-intent router.\n"
            "Your ONLY job is to output a valid TurnIntent object.\n\n"
            "You will receive:\n"
            "- raw_user_message\n"
            "- minimal chat state context (awaiting flags, chat_closed)\n"
            "- optional list of pending memory candidates (ids + normalized_memory snippets)\n\n"
            "Decide intent.kind:\n"
            "- new_task: the user is asking a new question/task.\n"
            "- rule_confirm: the user confirms a communication style rule that was just applied.\n"
            "- rule_positive_feedback: the user says the communication style works better.\n"
            "- rule_negative_correction: the user wants the assistant to stop or change the applied style.\n"
            "- rule_revoke: the user explicitly cancels a communication style rule.\n"
            "- start_chat: the user wants to start a chat (only if no chat exists / they explicitly request it).\n"
            "- memory_store: the user asks to store something as memory (produce memory_text payload).\n"
            "- rule_confirm: the user confirms a communication style rule and set communication_rule_key.\n"
            "- rule_positive_feedback: the user gives positive feedback about an applied communication style and set communication_rule_key.\n"
            "- rule_negative_correction: the user asks to weaken or change an applied communication style and set communication_rule_key.\n"
            "- rule_revoke: the user explicitly cancels a communication style rule and set communication_rule_key.\n"
            "- help: the user asks how to use the system / what they can do.\n"
            "- other: none of the above.\n\n"
            "Rules:\n"
            "- Do NOT use keyword rules; use semantic judgment.\n"
            "- Do NOT output confirm/correction for normalized request review; those are deterministic UI actions.\n"
            "- Do NOT output memory_confirm/memory_reject; memory candidate decisions are deterministic UI actions.\n"
            "- Do NOT output close_chat; closing is a deterministic UI action.\n"
            "- If a communication style rule is already active and the user confirms it worked, choose rule_confirm or rule_positive_feedback.\n"
            "- If the user says to stop using a style rule or to switch it, choose rule_negative_correction or rule_revoke.\n"
            "- For rule_* intents, set communication_rule_key to the most relevant rule_key.\n"
            "- If the message explicitly confirms a style rule (e.g. 'keep it short', 'yes, keep this style'), choose rule_confirm.\n"
            "- If the user asks to remember/store a fact/preference/rule, choose memory_store and put the payload in memory_text.\n"
            "- Set confidence 0..1 and a short reason.\n"
        )
        return Agent(model, output_type=TurnIntent, system_prompt=system_prompt)

    async def classify(
        self,
        *,
        raw_user_message: str,
        context: dict,
    ) -> TurnIntent:
        prompt = (
            "Classify this user message.\n\n"
            f"raw_user_message: {raw_user_message}\n\n"
            f"context_json: {json.dumps(context, ensure_ascii=False)}\n"
        )
        out = await run_agent_with_fallback(
            models=self._models(),
            build_agent=self._make_agent,
            prompt=prompt,
        )
        if out.kind in {"confirm", "correction", "memory_confirm", "memory_reject", "close_chat"}:
            return TurnIntent(
                kind="other",
                confidence=0.0,
                reason=f"blocked intent kind for deterministic action: {out.kind}",
            )
        if out.kind == "memory_store" and not (out.memory_text or "").strip():
            out = out.model_copy(update={"memory_text": raw_user_message})
        if out.kind.startswith("rule_") and not (out.communication_rule_key or "").strip():
            out = out.model_copy(update={"communication_rule_key": "brevity"})
        return out
