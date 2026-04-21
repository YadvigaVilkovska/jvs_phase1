from __future__ import annotations

from dataclasses import dataclass

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from app.agents.execution_agent import ExecutionAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.normalization_agent import NormalizationAgent
from app.domain.chat_state import ChatState
from app.domain.normalized_user_request import NormalizedUserRequest
from app.repositories.chat_repository import ChatRepository
from app.repositories.memory_repository import MemoryRepository
from app.services.communication_rule_service import CommunicationRuleService
from app.services.execution_service import ExecutionService


@dataclass(frozen=True)
class MainChatGraphDeps:
    chat_repo: ChatRepository
    normalization_agent: NormalizationAgent
    execution_agent: ExecutionAgent
    memory_agent: MemoryAgent | None = None
    communication_rule_service: CommunicationRuleService | None = None
    execution_service: ExecutionService | None = None


def _render_normalized(req: NormalizedUserRequest) -> str:
    parts = [
        "**Understanding (semantic)**",
        f"`{req.semantic_utterance_interpretation or '(not provided)'}`",
        "**Understanding (dialog attachment)**",
        f"`{req.dialog_attachment_interpretation or '(not provided)'}`",
        f"Understanding clarification kind: `{req.understanding_clarification_kind}`",
        "---",
        f"**Action line (normalized task):** `{req.normalized_user_request}`",
        f"Continuity: `{req.continuity}`",
    ]
    if req.needs_clarification:
        parts.append(f"Clarification needed: {req.clarification_reason or ''}".strip())
        if req.ambiguity_handling != "none":
            parts.append(f"Ambiguity handling: `{req.ambiguity_handling}`")
        if req.clarification_options:
            parts.append("Options: " + ", ".join(f"`{o}`" for o in req.clarification_options))
    else:
        parts.append("Clarification: not needed.")
    return "\n".join(parts)


def build_main_chat_graph(deps: MainChatGraphDeps):
    """
    Main Chat Graph (v1).

    This graph enforces the non-negotiable gate:
    - NEVER run ExecutionDecision before NormalizedUserRequest review/confirmation.
    """

    async def receive_user_message(state: ChatState) -> ChatState:
        if state.chat_closed:
            state.assistant_messages.append("Chat is closed.")
            return state

        explicit = state.explicit_normalized_review_action
        if explicit == "confirm":
            # Set only by POST /chat/confirm; never from free text / turn_intent.
            state.explicit_memory_command = False
            state.awaiting_confirmation = True
            state.awaiting_user_feedback = False
            if state.turn_intent is None:
                raise ValueError("turn_intent must be set by ChatOrchestrator (placeholder allowed)")
            return state

        if explicit == "correction":
            if not (state.raw_user_message or "").strip():
                return state
            deps.chat_repo.add_message(state.chat_id, "user", state.raw_user_message)
            if deps.communication_rule_service is not None:
                state.communication_rule_context = deps.communication_rule_service.build_prompt_context(
                    user_id=state.user_id,
                    chat_id=state.chat_id,
                )
                await deps.communication_rule_service.ingest_explicit_request(
                    user_id=state.user_id,
                    chat_id=state.chat_id,
                    raw_user_message=state.raw_user_message,
                )
                state.communication_rule_context = deps.communication_rule_service.build_prompt_context(
                    user_id=state.user_id,
                    chat_id=state.chat_id,
                )
            state.explicit_memory_command = False
            state.awaiting_confirmation = False
            if state.turn_intent is None:
                raise ValueError("turn_intent must be set by ChatOrchestrator (placeholder allowed)")
            return state

        if not state.raw_user_message:
            return state
        if state.turn_intent is None:
            raise ValueError("turn_intent must be precomputed by ChatOrchestrator")

        deps.chat_repo.add_message(state.chat_id, "user", state.raw_user_message)

        if deps.communication_rule_service is not None:
            # Build context for this turn + optionally ingest explicit communication preference requests.
            state.communication_rule_context = deps.communication_rule_service.build_prompt_context(
                user_id=state.user_id,
                chat_id=state.chat_id,
            )
            await deps.communication_rule_service.ingest_explicit_request(
                user_id=state.user_id,
                chat_id=state.chat_id,
                raw_user_message=state.raw_user_message,
            )
            state.communication_rule_context = deps.communication_rule_service.build_prompt_context(
                user_id=state.user_id,
                chat_id=state.chat_id,
            )

        state.explicit_memory_command = state.turn_intent.kind == "memory_store"
        if state.turn_intent.kind == "new_task":
            state.awaiting_confirmation = False
            state.awaiting_user_feedback = False
        return state

    async def handle_rule_feedback(state: ChatState) -> ChatState:
        if deps.communication_rule_service is None:
            return state

        kind = state.turn_intent.kind
        rule_key = state.turn_intent.communication_rule_key or "brevity"
        if kind == "rule_confirm":
            updated = deps.communication_rule_service.register_confirmation(
                user_id=state.user_id,
                chat_id=state.chat_id,
                rule_key=rule_key,
            )
        elif kind == "rule_positive_feedback":
            updated = deps.communication_rule_service.register_positive_feedback_after_apply(
                user_id=state.user_id,
                chat_id=state.chat_id,
                rule_key=rule_key,
            )
        elif kind == "rule_negative_correction":
            updated = deps.communication_rule_service.register_negative_correction(
                user_id=state.user_id,
                chat_id=state.chat_id,
                rule_key=rule_key,
            )
        elif kind == "rule_revoke":
            updated = deps.communication_rule_service.register_revoke(
                user_id=state.user_id,
                chat_id=state.chat_id,
                rule_key=rule_key,
            )
        else:
            return state

        state.communication_rule_context = deps.communication_rule_service.build_prompt_context(
            user_id=state.user_id,
            chat_id=state.chat_id,
        )
        if updated is not None:
            note = f"Communication rule updated: `{updated.rule_key}` -> `{updated.status}` (score={updated.score:.2f})."
            deps.chat_repo.add_message(state.chat_id, "assistant", note)
            state.assistant_messages.append(note)
        return state

    async def normalize_user_request(state: ChatState) -> ChatState:
        # Only normalize when we're not in confirmation step.
        if not state.raw_user_message:
            return state

        if state.awaiting_confirmation:
            # Confirmation endpoint should not trigger normalization.
            return state

        # If we're waiting for user feedback on an existing normalized request, we only normalize
        # when the intent is explicitly a new task (otherwise correction path handles it).
        if state.normalized_request is not None and state.awaiting_user_feedback:
            if state.turn_intent is None or state.turn_intent.kind != "new_task":
                return state

        revision = (state.normalized_request.revision + 1) if state.normalized_request is not None else 1
        req = await deps.normalization_agent.normalize(
            raw_user_message=state.raw_user_message,
            previous=state.normalized_request,
            revision=revision,
        )
        state.normalized_request = req
        state.normalized_request_history.append(req)
        state.awaiting_user_feedback = True
        state.awaiting_confirmation = False
        return state

    async def apply_user_correction(state: ChatState) -> ChatState:
        if not state.raw_user_message:
            return state
        if state.awaiting_confirmation:
            return state
        if state.normalized_request is None:
            return state
        state.explicit_normalized_review_action = None

        corr_text = (state.raw_user_message or "").strip()
        corrected = await deps.normalization_agent.apply_correction(
            correction_message=corr_text,
            previous=state.normalized_request,
        )
        state.user_corrections.append(corr_text)
        state.normalized_request = corrected
        state.normalized_request_history.append(corrected)

        mem_agent = deps.memory_agent or MemoryAgent()
        mem_repo = MemoryRepository(deps.chat_repo.session)  # type: ignore[attr-defined]
        try:
            pref = await mem_agent.standing_preference_from_correction(
                correction_message=corr_text,
                revised_normalized=corrected,
            )
        except RuntimeError:
            # e.g. all providers failed in run_agent_with_fallback; correction still applied.
            pref = None
        except ValidationError:
            # Malformed StandingPreferenceExtraction payload from the model.
            pref = None

        if pref is not None and mem_repo.has_pending_equivalent_candidate(chat_id=state.chat_id, cand=pref):
            pref = None

        if pref is not None:
            row = mem_repo.add_candidate(chat_id=state.chat_id, cand=pref)
            state.memory_candidates.append(pref)
            note = (
                "Optional standing preference (confirm via memory API before it is saved): "
                f"`{pref.normalized_memory}` (candidate id: `{row.id}`)."
            )
            deps.chat_repo.add_message(state.chat_id, "assistant", note)
            state.assistant_messages.append(note)

        state.awaiting_user_feedback = True
        state.awaiting_confirmation = False
        return state

    async def handle_memory_command(state: ChatState) -> ChatState:
        """
        Explicit memory command path:
        - create candidate only (no durable write)
        - show user what would be stored and target layer
        - require confirmation via memory candidate confirm endpoint
        """

        if not state.raw_user_message or not state.explicit_memory_command:
            return state

        mem_agent = deps.memory_agent or MemoryAgent()
        mem_repo = MemoryRepository(deps.chat_repo.session)  # type: ignore[attr-defined]

        payload = state.turn_intent.memory_text if state.turn_intent is not None else state.raw_user_message
        candidate = await mem_agent.explicit_memory_candidate(raw_user_message=payload)
        row = mem_repo.add_candidate(chat_id=state.chat_id, cand=candidate)

        state.memory_candidates.append(candidate)
        deps.chat_repo.set_chat_status(state.chat_id, "awaiting_memory_review")

        msg = (
            "I will store this as: "
            f"`{candidate.normalized_memory}`\n"
            f"Target layer: `{candidate.target_layer}`\n"
            f"Candidate id: `{row.id}`\n"
            "Confirm or reject using deterministic memory candidate actions (no free-text approvals)."
        )
        deps.chat_repo.add_message(state.chat_id, "assistant", msg)
        state.assistant_messages.append(msg)
        state.awaiting_user_feedback = True
        state.awaiting_confirmation = False
        return state

    async def show_normalized_request(state: ChatState) -> ChatState:
        # Do not re-show / re-persist during confirm runs (no user message).
        if not state.raw_user_message:
            return state
        if state.normalized_request is None:
            return state

        text = _render_normalized(state.normalized_request)
        deps.chat_repo.add_message(state.chat_id, "assistant", text)
        state.assistant_messages.append(text)

        # Persist normalized request row attached to latest USER message.
        latest_user_msg = deps.chat_repo.get_latest_message(state.chat_id, actor="user")
        if latest_user_msg is None:
            return state
        if deps.chat_repo.normalized_request_exists(
            chat_id=state.chat_id,
            message_id=latest_user_msg.id,
            revision=state.normalized_request.revision,
        ):
            return state
        deps.chat_repo.add_normalized_request(
            chat_id=state.chat_id,
            message_id=latest_user_msg.id,
            req=state.normalized_request,
        )
        return state

    async def wait_for_user_feedback(state: ChatState) -> ChatState:
        # Graph pauses here in product terms; API returns state and waits for /correction or /confirm.
        if state.explicit_memory_command:
            deps.chat_repo.set_chat_status(state.chat_id, "awaiting_memory_review")
        else:
            deps.chat_repo.set_chat_status(state.chat_id, "awaiting_feedback")
        return state

    async def confirm_normalized_request(state: ChatState) -> ChatState:
        if not state.awaiting_confirmation:
            return state
        state.explicit_normalized_review_action = None

        # Persist status and proceed to decision.
        deps.chat_repo.set_chat_status(state.chat_id, "awaiting_confirmation")
        return state

    async def decide_execution(state: ChatState) -> ChatState:
        if not state.awaiting_confirmation:
            return state
        if state.normalized_request is None:
            state.assistant_messages.append("Nothing to confirm yet.")
            return state

        # NON-NEGOTIABLE: decision only after confirmation.
        decision = await deps.execution_agent.decide(request=state.normalized_request)
        state.execution_decision = decision

        latest_req_row = deps.chat_repo.get_latest_normalized_request(state.chat_id)
        if latest_req_row is not None:
            deps.chat_repo.add_execution_decision(
                chat_id=state.chat_id,
                normalized_request_id=latest_req_row.id,
                decision=decision,
            )

        if not decision.can_execute_self:
            state.execution_status = "blocked"
        return state

    async def execute_task(state: ChatState) -> ChatState:
        if not state.execution_decision:
            return state
        if state.normalized_request is None:
            state.execution_status = "blocked"
            return state

        runner = deps.execution_service or ExecutionService()
        state.execution_status = "running"
        run = await runner.execute(
            decision=state.execution_decision,
            request=state.normalized_request,
            communication_rule_context=state.communication_rule_context,
        )

        if run.status == "completed":
            state.execution_status = "completed"
            deps.chat_repo.add_message(state.chat_id, "assistant", run.message)
            state.assistant_messages.append(run.message)
        else:
            state.execution_status = "blocked"
            msg = f"Execution blocked: {run.message}"
            deps.chat_repo.add_message(state.chat_id, "assistant", msg)
            state.assistant_messages.append(msg)
        return state

    builder = StateGraph(ChatState)
    builder.add_node("receive_user_message", receive_user_message)
    builder.add_node("handle_rule_feedback", handle_rule_feedback)
    builder.add_node("normalize_user_request", normalize_user_request)
    builder.add_node("apply_user_correction", apply_user_correction)
    builder.add_node("show_normalized_request", show_normalized_request)
    builder.add_node("handle_memory_command", handle_memory_command)
    builder.add_node("wait_for_user_feedback", wait_for_user_feedback)
    builder.add_node("confirm_normalized_request", confirm_normalized_request)
    builder.add_node("decide_execution", decide_execution)
    builder.add_node("execute_task", execute_task)
    builder.set_entry_point("receive_user_message")

    def _after_receive(state: ChatState) -> str:
        # confirm/correction of normalized requests use explicit_normalized_review_action from
        # POST /chat/confirm and POST /chat/correction, not turn_intent kinds.
        if state.explicit_normalized_review_action == "confirm":
            return "confirm_normalized_request"
        if state.explicit_normalized_review_action == "correction":
            return "apply_user_correction"
        if state.turn_intent is None:
            raise ValueError("turn_intent must be precomputed by ChatOrchestrator")
        intent_kind = state.turn_intent.kind
        if intent_kind in {"rule_confirm", "rule_positive_feedback", "rule_negative_correction", "rule_revoke"}:
            return "handle_rule_feedback"
        if intent_kind == "memory_store":
            return "handle_memory_command"
        return "normalize_user_request"

    builder.add_conditional_edges("receive_user_message", _after_receive)

    builder.add_edge("handle_rule_feedback", END)
    builder.add_edge("normalize_user_request", "show_normalized_request")
    builder.add_edge("apply_user_correction", "show_normalized_request")
    builder.add_edge("handle_memory_command", "wait_for_user_feedback")

    # After showing, we either wait for feedback (normal path) or, if confirm endpoint triggered,
    # proceed to decide_execution.
    def _after_show(state: ChatState) -> str:
        return "confirm_normalized_request" if state.awaiting_confirmation else "wait_for_user_feedback"

    builder.add_conditional_edges("show_normalized_request", _after_show)

    builder.add_edge("wait_for_user_feedback", END)
    builder.add_edge("confirm_normalized_request", "decide_execution")

    def _after_decide(state: ChatState) -> str:
        if state.execution_decision and state.execution_decision.can_execute_self:
            return "execute_task"
        return END

    builder.add_conditional_edges("decide_execution", _after_decide)
    builder.add_edge("execute_task", END)

    return builder.compile()
