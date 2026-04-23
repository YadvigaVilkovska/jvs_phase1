from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel import select

from app.api.ui_state import ChatUiMode, build_ui_state
from app.domain.chat_state import ChatState
from app.domain.execution_decision import ExecutionDecision
from app.domain.memory_candidate import MemoryCandidate
from app.domain.normalized_user_request import NormalizedUserRequest
from app.repositories.models import Chat, MemoryCandidateRow, MemoryEntryRow, NormalizedRequestRow
from app.settings import settings
from app.services.memory_service import MemoryService
from app.services.chat_service import ChatService
from app.agents.normalization_agent import NormalizationAgent
from app.agents.execution_agent import ExecutionAgent
from app.agents.memory_agent import MemoryAgent
from app.services.execution_service import ExecutionService
from app.dev.stub_agents import (
    FakeExecutionAgent,
    FakeNeedsToolDecisionAgent,
    FakeNormalizationAgent,
    FakeSelfExecuteDecisionAgent,
)


class FakeClarificationNormalizationAgent:
    async def normalize(self, *, raw_user_message: str, previous, revision: int) -> NormalizedUserRequest:
        return NormalizedUserRequest(
            normalized_user_request="need clarification before acting",
            continuity="new",
            needs_clarification=True,
            clarification_reason="Which project should I use",
            clarification_options=["Project A", "Project B"],
            ambiguity_handling="ask_user",
            revision=revision,
            semantic_utterance_interpretation="user refers to a project",
            dialog_attachment_interpretation="two candidate projects exist",
            understanding_clarification_kind="attachment_unclear",
        )

    async def apply_correction(self, *, correction_message: str, previous: NormalizedUserRequest) -> NormalizedUserRequest:
        return previous


@pytest.fixture()
def session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def disable_llm():
    # Tests should not depend on developer .env toggles.
    settings.openai_enabled = False
    settings.deepseek_enabled = False
    yield


@pytest.mark.asyncio
async def test_normalization_agent_pydanticai_test_model_normalize_and_correct():
    from pydantic_ai.models.test import TestModel

    model = TestModel(
        custom_output_args={
            "normalized_user_request": "write short client delay message",
            "continuity": "new",
            "needs_clarification": False,
            "clarification_reason": None,
            "clarification_options": [],
            "ambiguity_handling": "none",
            "revision": 1,
        }
    )
    agent = NormalizationAgent(model=model)
    out = await agent.normalize(raw_user_message="Напиши клиенту, что срок сдвигается.", previous=None, revision=1)
    assert isinstance(out, NormalizedUserRequest)
    assert out.revision == 1

    model2 = TestModel(
        custom_output_args={
            "normalized_user_request": "write short client message about two-day delay",
            "continuity": "correct_previous",
            "needs_clarification": False,
            "clarification_reason": None,
            "clarification_options": [],
            "ambiguity_handling": "none",
            "revision": 2,
        }
    )
    agent2 = NormalizationAgent(model=model2)
    corrected = await agent2.apply_correction(
        correction_message="Не просто delay, а на два дня.",
        previous=out,
    )
    assert isinstance(corrected, NormalizedUserRequest)
    assert corrected.revision == 2


@pytest.mark.asyncio
async def test_execution_agent_pydanticai_test_model_decide():
    from pydantic_ai.models.test import TestModel

    model = TestModel(
        custom_output_args={
            "can_execute_self": False,
            "needs_external_info": True,
            "needs_tool": False,
            "needs_delegate": False,
            "needs_decomposition": False,
            "needs_user_confirmation": True,
            "reason": "needs external information",
        }
    )
    agent = ExecutionAgent(model=model)
    decision = await agent.decide(
        request=NormalizedUserRequest(
            normalized_user_request="get today's weather in Berlin",
            continuity="new",
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            ambiguity_handling="none",
            revision=1,
        )
    )
    assert isinstance(decision, ExecutionDecision)
    assert decision.needs_external_info is True


@pytest.mark.asyncio
async def test_memory_agent_pydanticai_test_model_post_chat_and_explicit():
    from pydantic_ai.models.test import TestModel

    post_chat_model = TestModel(
        custom_output_args=[
            {
                "memory_type": "preference",
                "target_layer": "core_profile",
                "normalized_memory": "user prefers short answers",
                "source": "post_chat_analysis",
                "confidence": 0.8,
                "requires_confirmation": True,
            }
        ]
    )
    explicit_model = TestModel(
        custom_output_args={
            "memory_type": "preference",
            "target_layer": "core_profile",
            "normalized_memory": "user prefers one concrete next step",
            "source": "user_requested",
            "confidence": 0.9,
            "requires_confirmation": True,
        }
    )
    agent = MemoryAgent(post_chat_model=post_chat_model, explicit_model=explicit_model)

    cands = await agent.post_chat_candidates(chat_transcript=["user: hello", "assistant: hi"])
    assert isinstance(cands, list)
    assert len(cands) == 1
    assert isinstance(cands[0], MemoryCandidate)
    assert cands[0].source == "post_chat_analysis"

    cand = await agent.explicit_memory_candidate(raw_user_message="I prefer short answers.")
    assert isinstance(cand, MemoryCandidate)
    assert cand.source == "user_requested"


@pytest.mark.asyncio
async def test_execution_decision_only_after_confirm(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")

    turn1 = await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")
    assert turn1.state.normalized_request is not None
    assert turn1.state.execution_decision is None

    turn2 = await svc.confirm(chat_id=state0.chat_id)
    assert turn2.state.execution_decision is not None


@pytest.mark.asyncio
async def test_self_executable_path_runs_execution_runner(session: Session):
    from pydantic_ai.models.test import TestModel

    runner_model = TestModel(custom_output_text="Here is the result.")
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeSelfExecuteDecisionAgent(),
        execution_service=ExecutionService(model=runner_model),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="do it")
    out = await svc.confirm(chat_id=state0.chat_id)
    assert out.state.execution_status == "completed"
    assert any("Here is the result." in m for m in out.state.assistant_messages)


@pytest.mark.asyncio
async def test_needs_tool_path_stays_blocked(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeNeedsToolDecisionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="needs tool")
    out = await svc.confirm(chat_id=state0.chat_id)
    assert out.state.execution_decision is not None
    assert out.state.execution_decision.needs_tool is True
    assert out.state.execution_status == "blocked"


@pytest.mark.asyncio
async def test_correction_creates_new_revision_same_object_contract(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")

    turn1 = await svc.post_user_message(chat_id=state0.chat_id, user_message="initial")
    assert turn1.state.normalized_request is not None
    assert turn1.state.normalized_request.revision == 1

    turn2 = await svc.post_correction(chat_id=state0.chat_id, correction_message="change it")
    assert turn2.state.normalized_request is not None
    assert turn2.state.normalized_request.revision == 2
    assert len(turn2.state.normalized_request_history) >= 2


@pytest.mark.parametrize(
    "user_message",
    [
        "запомни что я люблю короткие ответы",
        "remember that I prefer short answers",
    ],
)
@pytest.mark.asyncio
async def test_explicit_memory_prefix_creates_candidate_not_durable_entry(session: Session, user_message: str):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")

    turn1 = await svc.post_user_message(chat_id=state0.chat_id, user_message=user_message)
    assert turn1.state.execution_decision is None

    candidates = list(session.exec(select(MemoryCandidateRow).where(MemoryCandidateRow.chat_id == state0.chat_id)))
    assert len(candidates) == 1

    entries = list(session.exec(select(MemoryEntryRow).where(MemoryEntryRow.user_id == "u1")))
    assert len(entries) == 0


def test_memory_candidate_confirm_creates_entry_only_after_confirmation(session: Session):
    mem = MemoryService(session=session)
    chat = Chat(user_id="u1")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    row = mem.create_explicit_candidate(
        chat_id=chat.id,
        cand=MemoryCandidate(
            memory_type="fact",
            target_layer="long_term_memory",
            normalized_memory="user prefers one next step",
            source="user_requested",
            confidence=0.9,
            requires_confirmation=True,
        ),
    )
    assert row.status == "candidate"
    assert len(list(session.exec(select(MemoryEntryRow)))) == 0

    entry = mem.confirm_candidate(candidate_id=row.id, user_id="u1")
    assert entry.status == "confirmed"
    assert len(list(session.exec(select(MemoryEntryRow)))) == 1


def test_memory_candidate_confirm_rejects_wrong_user(session: Session):
    mem = MemoryService(session=session)
    chat = Chat(user_id="u1")
    session.add(chat)
    session.commit()
    session.refresh(chat)

    row = mem.create_explicit_candidate(
        chat_id=chat.id,
        cand=MemoryCandidate(
            memory_type="preference",
            target_layer="core_profile",
            normalized_memory="user prefers short answers",
            source="user_requested",
            confidence=0.8,
            requires_confirmation=True,
        ),
    )

    with pytest.raises(ValueError, match="does not belong to this user"):
        mem.confirm_candidate(candidate_id=row.id, user_id="u2")


def test_memory_candidate_confirm_fails_when_candidate_chat_missing(session: Session):
    mem = MemoryService(session=session)

    row = mem.create_explicit_candidate(
        chat_id="missing-chat-id",
        cand=MemoryCandidate(
            memory_type="preference",
            target_layer="core_profile",
            normalized_memory="user prefers short answers",
            source="user_requested",
            confidence=0.8,
            requires_confirmation=True,
        ),
    )

    with pytest.raises(ValueError, match="candidate chat not found"):
        mem.confirm_candidate(candidate_id=row.id, user_id="u1")


def test_pending_memory_dedup_respects_semantic_identity(session: Session):
    mem = MemoryService(session=session)
    chat = Chat(user_id="u1")
    session.add(chat)
    session.commit()
    session.refresh(chat)

    mem.create_explicit_candidate(
        chat_id=chat.id,
        cand=MemoryCandidate(
            memory_type="preference",
            target_layer="core_profile",
            normalized_memory="user prefers short answers",
            source="user_requested",
            confidence=0.9,
            requires_confirmation=True,
        ),
    )

    repo = mem.repo
    assert repo.has_pending_equivalent_normalized_memory(
        chat_id=chat.id,
        normalized_memory="user prefers short answers",
        memory_type="preference",
        target_layer="core_profile",
        source="user_requested",
    )
    assert not repo.has_pending_equivalent_normalized_memory(
        chat_id=chat.id,
        normalized_memory="user prefers short answers",
        memory_type="rule",
        target_layer="core_profile",
        source="user_requested",
    )


@pytest.mark.asyncio
async def test_close_chat_triggers_post_chat_analysis_safely(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")
    closed = await svc.close(chat_id=state0.chat_id)
    assert closed.state.chat_closed is True


@pytest.mark.asyncio
async def test_second_close_does_not_rerun_post_chat_analysis(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")

    calls: list[str] = []

    async def track_post_chat(*, session, chat_id: str) -> int:
        calls.append(chat_id)
        return 0

    with patch("app.services.chat_service.run_post_chat_analysis", side_effect=track_post_chat):
        await svc.close(chat_id=state0.chat_id)
        await svc.close(chat_id=state0.chat_id)

    assert calls == [state0.chat_id]


@pytest.mark.asyncio
async def test_close_retries_post_chat_after_failed_extraction(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")

    attempts = 0

    async def flaky_post_chat(*, session, chat_id: str) -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient extraction failure")
        return 0

    with patch("app.services.chat_service.run_post_chat_analysis", side_effect=flaky_post_chat):
        with pytest.raises(RuntimeError):
            await svc.close(chat_id=state0.chat_id)
        row = session.get(Chat, state0.chat_id)
        assert row is not None
        assert row.status == "closed"
        assert row.post_chat_extraction_completed is False

        await svc.close(chat_id=state0.chat_id)

    row2 = session.get(Chat, state0.chat_id)
    assert row2 is not None
    assert row2.post_chat_extraction_completed is True
    assert attempts == 2


def test_graph_contains_required_node_names(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    main = svc.graphs.main_chat_graph()
    main_nodes = set(main.get_graph().nodes.keys())
    assert "apply_user_correction" in main_nodes
    assert "handle_memory_command" in main_nodes

    mem = svc.graphs.memory_graph()
    mem_nodes = set(mem.get_graph().nodes.keys())
    assert "review_memory_candidates" in mem_nodes
    assert "confirm_memory_candidate" in mem_nodes
    assert "reject_memory_candidate" in mem_nodes
    assert "write_memory_entry" in mem_nodes


@pytest.mark.asyncio
async def test_confirm_does_not_duplicate_normalized_requests(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")

    await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")
    before = list(
        session.exec(select(NormalizedRequestRow).where(NormalizedRequestRow.chat_id == state0.chat_id))
    )
    assert len(before) == 1

    await svc.confirm(chat_id=state0.chat_id)
    after1 = list(
        session.exec(select(NormalizedRequestRow).where(NormalizedRequestRow.chat_id == state0.chat_id))
    )
    assert len(after1) == 1

    await svc.confirm(chat_id=state0.chat_id)
    after2 = list(
        session.exec(select(NormalizedRequestRow).where(NormalizedRequestRow.chat_id == state0.chat_id))
    )
    assert len(after2) == 1


@pytest.mark.asyncio
async def test_reject_clears_understanding_and_allows_new_task(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")

    turn1 = await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")
    assert turn1.state.normalized_request is not None

    rejected = await svc.reject(chat_id=state0.chat_id)
    assert rejected.state.normalized_request is None
    assert rejected.state.awaiting_user_feedback is False
    assert rejected.state.awaiting_confirmation is False

    turn2 = await svc.post_user_message(chat_id=state0.chat_id, user_message="new task")
    assert turn2.state.normalized_request is not None
    assert turn2.state.normalized_request.normalized_user_request == "normalize: new task"
    assert turn2.state.normalized_request.revision == 1


def test_chat_response_includes_ui_state():
    state = ChatState(chat_id="c1", user_id="u1")

    ui_state = build_ui_state(state)

    assert ui_state.mode == ChatUiMode.CHAT
    assert ui_state.message_input_enabled is True
    assert ui_state.understanding.visible is False
    assert ui_state.clarification.visible is False


def test_understanding_review_maps_to_ui_state():
    req = NormalizedUserRequest(
        normalized_user_request="Draft a short reply",
        continuity="new",
        needs_clarification=False,
        clarification_reason=None,
        clarification_options=[],
        ambiguity_handling="none",
        revision=1,
        semantic_utterance_interpretation="user wants a reply",
        dialog_attachment_interpretation="new task",
        understanding_clarification_kind="none",
    )
    state = ChatState(
        chat_id="c1",
        user_id="u1",
        normalized_request=req,
        awaiting_user_feedback=True,
    )

    ui_state = build_ui_state(state)

    assert ui_state.mode == ChatUiMode.UNDERSTANDING_REVIEW
    assert ui_state.message_input_enabled is False
    assert ui_state.understanding.visible is True
    assert ui_state.understanding.editable is True
    assert ui_state.understanding.text == "Draft a short reply"
    assert ui_state.understanding.submit_label == "OK"
    assert ui_state.clarification.visible is False


def test_ask_user_maps_to_clarification_ui_state():
    req = NormalizedUserRequest(
        normalized_user_request="need clarification before acting",
        continuity="new",
        needs_clarification=True,
        clarification_reason="Which project should I use",
        clarification_options=["Project A", "Project B"],
        ambiguity_handling="ask_user",
        revision=1,
        semantic_utterance_interpretation="user refers to a project",
        dialog_attachment_interpretation="two candidate projects exist",
        understanding_clarification_kind="attachment_unclear",
    )
    state = ChatState(
        chat_id="c1",
        user_id="u1",
        normalized_request=req,
        awaiting_user_feedback=True,
    )

    ui_state = build_ui_state(state)

    assert ui_state.mode == ChatUiMode.CLARIFICATION
    assert ui_state.message_input_enabled is True
    assert ui_state.clarification.visible is True
    assert ui_state.clarification.question is not None
    assert "Which project should I use" in ui_state.clarification.question
    assert "Project A" in ui_state.clarification.question
    assert ui_state.understanding.visible is False


def test_ui_state_is_authoritative_for_ui_rendering():
    req1 = NormalizedUserRequest(
        normalized_user_request="Summarize the meeting",
        continuity="new",
        needs_clarification=False,
        clarification_reason=None,
        clarification_options=[],
        ambiguity_handling="none",
        revision=1,
        semantic_utterance_interpretation="user requests summary",
        dialog_attachment_interpretation="new task",
        understanding_clarification_kind="none",
    )
    req2 = req1.model_copy(
        update={
            "semantic_utterance_interpretation": "different debug wording",
            "dialog_attachment_interpretation": "different attachment wording",
        }
    )

    state1 = ChatState(chat_id="c1", user_id="u1", normalized_request=req1, awaiting_user_feedback=True)
    state2 = ChatState(chat_id="c1", user_id="u1", normalized_request=req2, awaiting_user_feedback=True)

    ui_state1 = build_ui_state(state1)
    ui_state2 = build_ui_state(state2)

    assert ui_state1 == ui_state2


@pytest.mark.asyncio
async def test_clarification_turn_service_state_maps_to_real_question(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeClarificationNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")

    turn = await svc.post_user_message(chat_id=state0.chat_id, user_message="Do it for the project")
    ui_state = build_ui_state(turn.state)

    assert ui_state.mode == ChatUiMode.CLARIFICATION
    assert ui_state.clarification.visible is True
    assert ui_state.clarification.question is not None
    assert "Please clarify" in ui_state.clarification.question
