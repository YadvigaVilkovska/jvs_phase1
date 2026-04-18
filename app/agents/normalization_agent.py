from __future__ import annotations

import json
from typing import Optional

from pydantic_ai import Agent

from app.domain.normalized_user_request import NormalizedUserRequest
from app.llm.fallback import chain_normalization_openai_then_deepseek, run_agent_with_fallback
from app.settings import settings


class NormalizationAgent:
    """
    LLM-first normalization. Primary: OpenAI, fallback: DeepSeek.
    Tests inject `TestModel` via `model=` (single provider, no fallback).
    """

    def __init__(self, *, model=None):
        self._model = model

    def _normalization_models(self):
        if self._model is not None:
            return [self._model]
        return chain_normalization_openai_then_deepseek()

    def _make_agent(self, model) -> Agent[None, NormalizedUserRequest]:
        system_prompt = (
            "You are Jeeves' Normalization layer.\n"
            "Your ONLY job is to produce a valid NormalizedUserRequest object.\n"
            "Do NOT decide tools, execution plans, delegation, or memory writes.\n\n"
            "Understanding flow (populate all three; order is conceptual, single output object):\n"
            "1) semantic_utterance_interpretation — what the user's words mean in isolation.\n"
            "2) dialog_attachment_interpretation — what prior message/topic they attach to, or say if referent is unknown.\n"
            "3) normalized_user_request — the action line: what to do once (1)-(2) are clear enough; short machine English.\n\n"
            "understanding_clarification_kind (choose exactly one; LLM judgment, not keywords):\n"
            "- none — no understanding-level block.\n"
            "- phrase_unclear — you cannot interpret the utterance itself.\n"
            "- attachment_unclear — utterance is understood but what it refers to in the thread is not.\n"
            "- execution_data_missing — referent/meaning clear but factual parameters for execution are missing.\n"
            "If phrase_unclear or attachment_unclear, you MUST set needs_clarification=true and explain in clarification_reason.\n\n"
            "Rules:\n"
            "- continuity: new|continue|correct_previous|unclear.\n"
            "- needs_clarification: true if ambiguity prevents next step.\n"
            "- If needs_clarification=true, set clarification_reason and provide clarification_options.\n"
            "- ambiguity_handling must be ask_user or answer_with_options when ambiguous, else none.\n"
            "- revision is an integer version counter.\n"
        )
        return Agent(model, output_type=NormalizedUserRequest, system_prompt=system_prompt)

    def _make_correction_agent(self, model) -> Agent[None, NormalizedUserRequest]:
        """Stronger contract for revision turns: user comment must semantically reshape the task line."""
        system_prompt = (
            "You are Jeeves' Normalization layer in CORRECTION mode.\n"
            "The user is revising an already drafted NormalizedUserRequest. Their latest message is the authority "
            "on what the task must become.\n\n"
            "Critical rules:\n"
            "- Output ONE new NormalizedUserRequest (same schema). Set continuity to `correct_previous` unless the "
            "task truly changed scope (then choose appropriately).\n"
            "- Field `normalized_user_request` must be rewritten as the FULL, STANDALONE specification of the task "
            "AFTER applying the user's correction — not a small edit to the old wording, not a summary that silently "
            "keeps old constraints. A reader who only sees `normalized_user_request` must infer the complete current "
            "intent including language, tone, length, format, audience, and any new constraints the user demanded.\n"
            "- The previous JSON in the user message is CONTEXT ONLY. Do not preserve outdated or contradicted "
            "requirements from it if the user's correction overrides them.\n"
            "- If the user says something essential is missing, wrong, or loses meaning without more context, set "
            "needs_clarification=true with clarification_reason and options (or use ambiguity_handling as required "
            "by the contract). Do not pretend the task is executable with the old spec.\n"
            "- If the correction only constrains how to deliver an already-understood task (e.g. output language, "
            "tone, register, length, format) and does not say essential facts are missing or the answer would be "
            "meaningless, keep needs_clarification=false unless a separate factual gap still blocks execution.\n"
            "- Durable 'always/never' prefs for all future chats belong in memory elsewhere; keep this line about "
            "the current deliverable unless the user only states standing prefs (then clarify or encode only what "
            "belongs in this task).\n"
            "- normalized_user_request remains short machine-friendly English.\n"
            "- Refresh semantic_utterance_interpretation and dialog_attachment_interpretation so they reflect the "
            "correction; do not leave stale phase-1/2 text from the previous JSON unless it still holds.\n"
            "- Set understanding_clarification_kind consistently with how you filled needs_clarification.\n"
        )
        return Agent(model, output_type=NormalizedUserRequest, system_prompt=system_prompt)

    async def normalize(
        self,
        *,
        raw_user_message: str,
        previous: Optional[NormalizedUserRequest],
        revision: int,
    ) -> NormalizedUserRequest:
        models = self._normalization_models()
        prev_json = previous.model_dump() if previous is not None else None
        prompt = (
            "Convert the user's raw chat message into NormalizedUserRequest.\n\n"
            f"raw_user_message: {raw_user_message}\n"
            f"previous_normalized_request_json: {json.dumps(prev_json, ensure_ascii=False) if prev_json else 'null'}\n\n"
            f"Set revision={revision}.\n"
        )
        data = await run_agent_with_fallback(
            models=models,
            build_agent=self._make_agent,
            prompt=prompt,
        )
        if data.revision != revision:
            data = data.model_copy(update={"revision": revision})
        return data

    async def apply_correction(
        self,
        *,
        correction_message: str,
        previous: NormalizedUserRequest,
    ) -> NormalizedUserRequest:
        models = self._normalization_models()
        expected_revision = previous.revision + 1
        prompt = (
            "Rebuild the NormalizedUserRequest so the user's correction is fully merged into the task.\n\n"
            "The correction_message is an instruction to change what we should do or how the output must read — "
            "treat it as mandatory semantic input, not a hint.\n"
            "- Rewrite normalized_user_request from scratch if needed so it reflects the combined intent "
            "(do not lightly rephrase the previous line while ignoring the comment).\n"
            "- If the user indicates missing context, wrong framing, or that the answer would be meaningless "
            "without more detail, switch to needs_clarification or adjust ambiguity fields per contract.\n\n"
            f"previous_normalized_request_json (context; superseded where the correction conflicts):\n"
            f"{json.dumps(previous.model_dump(), ensure_ascii=False)}\n\n"
            f"user_correction_message (authoritative for what must change):\n{correction_message}\n\n"
            f"Set revision={expected_revision}.\n"
        )
        data = await run_agent_with_fallback(
            models=models,
            build_agent=self._make_correction_agent,
            prompt=prompt,
        )
        if data.revision != expected_revision:
            data = data.model_copy(update={"revision": expected_revision})
        return data
