from __future__ import annotations

from typing import Iterable, List

from pydantic_ai import Agent

from app.domain.correction_memory import StandingPreferenceExtraction
from app.domain.memory_candidate import MemoryCandidate
from app.domain.normalized_user_request import NormalizedUserRequest
from app.llm.fallback import chain_deepseek_then_openai, run_agent_with_fallback
from app.settings import settings


class MemoryAgent:
    """
    Memory candidate generation. Primary: DeepSeek, fallback: OpenAI.
    """

    def __init__(self, *, post_chat_model=None, explicit_model=None):
        self._post_chat_model = post_chat_model
        self._explicit_model = explicit_model

    def _memory_models(self, injected):
        if injected is not None:
            return [injected]
        return chain_deepseek_then_openai(
            deepseek_model=settings.deepseek_memory_model or settings.deepseek_response_model,
        )

    def _make_post_chat_agent(self, model) -> Agent[None, list[MemoryCandidate]]:
        system_prompt = (
            "You are Jeeves' post-chat memory analysis layer.\n"
            "Input is a chat transcript (user/assistant messages).\n"
            "Output MUST be a JSON-serializable list of MemoryCandidate objects.\n\n"
            "Rules:\n"
            "- Produce candidates ONLY; do NOT write durable memory.\n"
            "- Each candidate MUST set memory_type (fact|preference|rule).\n"
            "- Each candidate MUST set target_layer (long_term_memory|core_profile).\n"
            "- normalized_memory must be short, explicit English.\n"
            "- source must be post_chat_analysis.\n"
            "- confidence is 0..1.\n"
            "- requires_confirmation must be true.\n"
            "- Return an empty list if nothing should be proposed.\n"
        )
        return Agent(model, output_type=list[MemoryCandidate], system_prompt=system_prompt)

    def _make_standing_preference_agent(self, model) -> Agent[None, StandingPreferenceExtraction]:
        system_prompt = (
            "You classify a user correction message during chat refinement (same revision turn as NormalizedUserRequest).\n"
            "Output StandingPreferenceExtraction.\n\n"
            "Set propose_memory=false and candidate=null when the message ONLY adjusts THIS deliverable "
            "(language, brevity, tone, formality, style of the current answer) without stating an ongoing rule — "
            "e.g. 'in Russian', 'shorter', 'without pathos', 'more formal for this text'.\n\n"
            "Set propose_memory=true only when the user expresses a DURABLE preference or rule for future "
            "conversations: e.g. 'always answer in Russian', 'never use emojis', 'address me with informal ты', "
            "'from now on keep answers brief'. Then fill candidate with memory_type preference or rule, "
            "appropriate target_layer (core_profile for address/identity defaults; long_term_memory otherwise), "
            "normalized_memory in short explicit English, source=user_requested, confidence 0..1, "
            "requires_confirmation=true.\n\n"
            "If one message mixes both (e.g. task-local language + 'always'), still set propose_memory=true with "
            "candidate capturing the standing preference; task-local parts are covered by normalization.\n"
            "If unsure whether it is standing vs one-shot, prefer propose_memory=false.\n"
        )
        return Agent(model, output_type=StandingPreferenceExtraction, system_prompt=system_prompt)

    def _make_explicit_agent(self, model) -> Agent[None, MemoryCandidate]:
        system_prompt = (
            "You are Jeeves' explicit memory command interpreter.\n"
            "Input is the user's explicit memory payload.\n"
            "Output MUST be a single MemoryCandidate object.\n\n"
            "Rules:\n"
            "- Create a candidate ONLY; do NOT write durable memory.\n"
            "- memory_type: fact|preference|rule.\n"
            "- target_layer: long_term_memory|core_profile.\n"
            "- normalized_memory must be short, explicit English.\n"
            "- source must be user_requested.\n"
            "- confidence is 0..1.\n"
            "- requires_confirmation must be true.\n"
        )
        return Agent(model, output_type=MemoryCandidate, system_prompt=system_prompt)

    async def post_chat_candidates(self, *, chat_transcript: Iterable[str]) -> List[MemoryCandidate]:
        models = self._memory_models(self._post_chat_model)
        if not models:
            return []

        transcript_text = "\n".join(chat_transcript)
        prompt = (
            "Extract memory candidates from this transcript.\n\n"
            f"transcript:\n{transcript_text}\n"
        )
        return await run_agent_with_fallback(
            models=models,
            build_agent=self._make_post_chat_agent,
            prompt=prompt,
        )

    async def explicit_memory_candidate(self, *, raw_user_message: str) -> MemoryCandidate:
        models = self._memory_models(self._explicit_model)
        if not models:
            payload = raw_user_message.strip()
            return MemoryCandidate(
                memory_type="fact",
                target_layer="long_term_memory",
                normalized_memory=payload,
                source="user_requested",
                confidence=0.2,
                requires_confirmation=True,
            )

        prompt = (
            "Convert this explicit memory payload into a MemoryCandidate.\n\n"
            f"payload: {raw_user_message}\n"
        )
        return await run_agent_with_fallback(
            models=models,
            build_agent=self._make_explicit_agent,
            prompt=prompt,
        )

    async def standing_preference_from_correction(
        self,
        *,
        correction_message: str,
        revised_normalized: NormalizedUserRequest,
    ) -> MemoryCandidate | None:
        """
        Optional MemoryCandidate for durable prefs expressed during a correction turn.
        Returns None if LLM disabled, or message is task-local only, or extraction declines.
        """
        models = self._memory_models(None)
        if not models:
            return None

        prompt = (
            "Classify this correction.\n\n"
            f"correction_message: {correction_message}\n\n"
            "Context — revised normalized task (for disambiguation only):\n"
            f"{revised_normalized.model_dump_json()}\n"
        )
        out = await run_agent_with_fallback(
            models=models,
            build_agent=self._make_standing_preference_agent,
            prompt=prompt,
        )
        if not out.propose_memory or out.candidate is None:
            return None
        cand = out.candidate
        if cand.source != "user_requested":
            cand = cand.model_copy(update={"source": "user_requested"})
        return cand
