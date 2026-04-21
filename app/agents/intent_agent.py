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
            "- optional list of pending memory candidates (ids + normalized_memory snippets)\n"
            "- optional normalized_request_json (for confirm/correction disambiguation)\n\n"
            "Decide intent.kind:\n"
            "- new_task: the user is asking a new question/task.\n"
            "- confirm: the user confirms the currently shown normalized request.\n"
            "- correction: the user wants to revise the currently shown normalized request.\n"
            "- start_chat: the user wants to start a chat (only if no chat exists / they explicitly request it).\n"
            "- close_chat: the user wants to close the chat (and trigger post-chat analysis).\n"
            "- memory_store: the user asks to store something as memory (produce memory_text payload).\n"
            "- memory_confirm: the user wants to confirm a specific memory candidate.\n"
            "- memory_reject: the user wants to reject a specific memory candidate.\n"
            "- help: the user asks how to use the system / what they can do.\n"
            "- other: none of the above.\n\n"
            "Rules:\n"
            "- Do NOT use keyword rules; use semantic judgment.\n"
            "- If the system is awaiting user feedback on a normalized request, and the user says 'yes/ok' in context, that's confirm.\n"
            "- If they propose changes ('no, change...', 'not that, do...'), that's correction.\n"
            "- If they ask a totally different thing while awaiting feedback, choose new_task.\n"
            "- If the user asks to remember/store a fact/preference/rule, choose memory_store and put the payload in memory_text.\n"
            "- If the user references a specific candidate id (e.g. 'confirm candidate <id>'), choose memory_confirm/memory_reject and set memory_candidate_id.\n"
            "- If there are pending_memory_candidates and the user says 'confirm it / save it / yes store that' and clearly refers to memory storage, choose memory_confirm.\n"
            "- For memory_confirm/memory_reject, set memory_candidate_id when you can identify it from context.\n"
            "- For correction, set correction_text to the raw_user_message (verbatim) unless it's empty.\n"
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
        if out.kind == "correction" and not (out.correction_text or "").strip():
            out = out.model_copy(update={"correction_text": raw_user_message})
        if out.kind == "memory_store" and not (out.memory_text or "").strip():
            out = out.model_copy(update={"memory_text": raw_user_message})
        return out

