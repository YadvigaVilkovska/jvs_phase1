from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel import select

from app.domain.execution_decision import ExecutionDecision
from app.domain.communication_rule import CommunicationRuleCandidate, CommunicationRuleState
from app.domain.chat_state import ChatState
from app.domain.memory_candidate import MemoryCandidate
from app.domain.normalized_user_request import NormalizedUserRequest
from app.repositories.communication_rule_repository import CommunicationRuleRepository
from app.repositories.models import (
    Chat,
    CommunicationRuleCandidateRow,
    CommunicationRuleEvidenceRow,
    CommunicationRuleStateRow,
    MemoryCandidateRow,
    MemoryEntryRow,
    NormalizedRequestRow,
)
from app.settings import settings
from app.services.communication_rule_service import CommunicationRuleService
from app.services.chat_orchestrator import CriticalTurnError
from app.services.memory_service import MemoryService
from app.services.chat_service import ChatService
from app.agents.normalization_agent import NormalizationAgent
from app.agents.execution_agent import ExecutionAgent
from app.agents.memory_agent import MemoryAgent
from app.services.execution_service import ExecutionService
from app.agents.communication_rule_agent import CommunicationRuleExtraction
from app.dev.stub_agents import (
    FakeExecutionAgent,
    FakeNeedsToolDecisionAgent,
    FakeNormalizationAgent,
    FakeIntentAgent,
    FakeSelfExecuteDecisionAgent,
)
from app.domain.turn_intent import TurnIntent


class FakeCommunicationRuleAgent:
    async def extract(self, *, raw_user_message: str, context) -> CommunicationRuleExtraction:  # type: ignore[no-untyped-def]
        text = (raw_user_message or "").lower()
        if "короч" in text or "кратк" in text:
            return CommunicationRuleExtraction(
                propose_rule=True,
                rule_key="brevity",
                scope="current_chat",
                canonical_value={"value": "brief"},
                confidence=0.9,
                reason="fake brevity",
            )
        if "подробн" in text:
            return CommunicationRuleExtraction(
                propose_rule=True,
                rule_key="detail_level",
                scope="current_chat",
                canonical_value={"value": "high"},
                confidence=0.9,
                reason="fake detail_level",
            )
        return CommunicationRuleExtraction(propose_rule=False, confidence=0.6, reason="fake none")

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
async def test_communication_rule_service_lifecycle_and_applicable_rules(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    state1 = await svc.ingest_explicit_request(
        user_id="u1",
        chat_id="c1",
        raw_user_message="Отвечай короче, пожалуйста.",
    )
    assert isinstance(state1, CommunicationRuleState)
    assert state1.rule_key == "brevity"
    assert state1.score == pytest.approx(0.2)
    assert state1.status == "candidate"

    state2 = await svc.register_repeated_instruction(
        user_id="u1",
        chat_id="c1",
        raw_user_message="Отвечай короче.",
    )
    assert isinstance(state2, CommunicationRuleState)
    assert state2.score == pytest.approx(0.4)
    assert state2.status == "soft_active"

    state3 = svc.register_confirmation(user_id="u1", chat_id="c1", rule_key="brevity")
    assert isinstance(state3, CommunicationRuleState)
    assert state3.score == pytest.approx(0.75)
    assert state3.status == "active"
    context = svc.build_prompt_context(user_id="u1", chat_id="c1")
    assert "Отвечай кратко." in context

    state4 = svc.register_negative_feedback(user_id="u1", chat_id="c1", rule_key="brevity")
    assert isinstance(state4, CommunicationRuleState)
    assert state4.score == pytest.approx(0.45)
    assert state4.status == "soft_active"

    state5 = svc.register_revoke(user_id="u1", chat_id="c1", rule_key="brevity")
    assert isinstance(state5, CommunicationRuleState)
    assert state5.status == "revoked"
    assert state5.score == pytest.approx(0.0)

    applicable = svc.get_applicable_rules(user_id="u1", chat_id="c1")
    assert applicable["active_rules"] == []
    assert applicable["soft_rules"] == []


@pytest.mark.asyncio
async def test_initial_explicit_request_creates_candidate_not_soft_active(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    state = await svc.ingest_explicit_request(
        user_id="u1",
        chat_id="c1",
        raw_user_message="Отвечай короче.",
    )

    assert state is not None
    assert state.status == "candidate"
    assert svc.build_prompt_context(user_id="u1", chat_id="c1") == ""


@pytest.mark.asyncio
async def test_communication_rule_service_conflicting_current_chat_rule_overrides_global(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    await svc.ingest_explicit_request(user_id="u1", chat_id="c1", raw_user_message="Пиши кратко.")
    contradicted = await svc.ingest_explicit_request(user_id="u1", chat_id="c1", raw_user_message="Подробнее, пожалуйста.")
    await svc.register_repeated_instruction(user_id="u1", chat_id="c1", raw_user_message="Подробнее, пожалуйста.")

    assert isinstance(contradicted, CommunicationRuleState)
    brevity = repo.get_state("u1", "brevity", "current_chat", chat_id="c1")
    detail = repo.get_state("u1", "detail_level", "current_chat", chat_id="c1")
    assert brevity is not None
    assert detail is not None
    assert brevity.score == pytest.approx(0.2)
    assert detail.score == pytest.approx(0.4)
    context = svc.build_prompt_context(user_id="u1", chat_id="c1")
    assert "Дай подробные объяснения." in context
    assert "Отвечай кратко." not in context
    current_chat_brevity = repo.get_state("u1", "brevity", "current_chat", chat_id="c1")
    assert current_chat_brevity is not None
    assert current_chat_brevity.score == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_chat_first_communication_rule_lifecycle_through_ordinary_messages(session: Session):
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
        communication_rule_service=crs,
    )
    state0 = svc.start_chat(user_id="u1")

    await svc.post_user_message(chat_id=state0.chat_id, user_message="Отвечай короче.")
    await svc.confirm(chat_id=state0.chat_id)
    row1 = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row1 is not None
    assert row1.status == "candidate"
    assert row1.score == pytest.approx(0.2)

    await svc.post_user_message(chat_id=state0.chat_id, user_message="Пиши кратко.")
    await svc.confirm(chat_id=state0.chat_id)
    row2 = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row2 is not None
    assert row2.score >= 0.4

    await svc.confirm(chat_id=state0.chat_id)
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Подтверждаю правило")
    row3 = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row3 is not None
    assert row3.status == "active"
    assert row3.score >= 0.7

    await svc.confirm(chat_id=state0.chat_id)
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Да, так лучше")
    row4 = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row4 is not None
    row4_score = row4.score
    assert row4_score > 0.7

    await svc.confirm(chat_id=state0.chat_id)
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Без воды")
    row5 = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row5 is not None
    assert row5.status in {"candidate", "soft_active"}
    assert row5.score < row4_score

    await svc.confirm(chat_id=state0.chat_id)
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Нет, уже не надо")
    row6 = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row6 is not None
    assert row6.status == "revoked"
    assert row6.score == pytest.approx(0.0)
    assert "Отвечай кратко." not in crs.build_prompt_context(user_id="u1", chat_id=state0.chat_id)


@pytest.mark.asyncio
async def test_repeat_request_via_post_user_message_increases_score(session: Session):
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
        communication_rule_service=crs,
    )
    state0 = svc.start_chat(user_id="u1")

    await svc.post_user_message(chat_id=state0.chat_id, user_message="Отвечай короче.")
    await svc.confirm(chat_id=state0.chat_id)
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Пиши кратко.")

    row = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row is not None
    assert row.score >= 0.4
    assert row.status == "soft_active"


@pytest.mark.asyncio
async def test_chat_flow_repeat_updates_existing_communication_rule(session: Session):
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
        communication_rule_service=crs,
    )
    state0 = svc.start_chat(user_id="u1")

    await svc.post_user_message(chat_id=state0.chat_id, user_message="Отвечай короче.")
    await svc.confirm(chat_id=state0.chat_id)
    row1 = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row1 is not None
    row1_score = row1.score

    await svc.post_user_message(chat_id=state0.chat_id, user_message="Пиши кратко.")
    row2 = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row2 is not None
    assert row2.id == row1.id
    assert row2.score > row1_score


@pytest.mark.asyncio
async def test_chat_flow_confirm_updates_existing_communication_rule(session: Session):
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
        communication_rule_service=crs,
    )
    state0 = svc.start_chat(user_id="u1")

    await svc.post_user_message(chat_id=state0.chat_id, user_message="Отвечай короче.")
    await svc.confirm(chat_id=state0.chat_id)
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Пиши кратко.")
    await svc.confirm(chat_id=state0.chat_id)
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Да")

    row = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row is not None
    assert row.score >= 0.7
    assert row.status == "active"


@pytest.mark.asyncio
async def test_chat_flow_revoke_revokes_existing_communication_rule(session: Session):
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
        communication_rule_service=crs,
    )
    state0 = svc.start_chat(user_id="u1")

    await svc.post_user_message(chat_id=state0.chat_id, user_message="Отвечай короче.")
    await svc.confirm(chat_id=state0.chat_id)
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Пиши кратко.")
    await svc.confirm(chat_id=state0.chat_id)
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Да")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Не надо")

    row = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row is not None
    assert row.status == "revoked"
    assert row.score == pytest.approx(0.0)
    assert "Отвечай кратко." not in crs.build_prompt_context(user_id="u1", chat_id=state0.chat_id)


@pytest.mark.asyncio
async def test_chat_flow_repeat_does_not_create_duplicate_rule_state(session: Session):
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
        communication_rule_service=crs,
    )
    state0 = svc.start_chat(user_id="u1")

    await svc.post_user_message(chat_id=state0.chat_id, user_message="Отвечай короче.")
    await svc.confirm(chat_id=state0.chat_id)
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Пиши кратко.")

    rows = list(
        session.exec(
            select(CommunicationRuleStateRow).where(CommunicationRuleStateRow.user_id == "u1")
        )
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_chat_flow_confirm_without_rule_state_does_nothing(session: Session):
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
        communication_rule_service=crs,
    )
    state0 = svc.start_chat(user_id="u1")

    out1 = await svc.post_user_message(chat_id=state0.chat_id, user_message="Да")
    row_after_confirm = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row_after_confirm is None

    with pytest.raises(ValueError, match="review_pending_use_confirm_or_reject"):
        await svc.post_user_message(chat_id=state0.chat_id, user_message="Не надо")
    row_after_revoke = crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id)
    assert row_after_revoke is None

    assert out1.state.chat_id == state0.chat_id
    assert crs.repository.get_state("u1", "brevity", "current_chat", chat_id=state0.chat_id) is None


def test_repeated_upsert_of_same_global_identity_does_not_create_second_row(session: Session):
    repo = CommunicationRuleRepository(session)
    first = repo.upsert_state(
        CommunicationRuleState(
            user_id="u1",
            chat_id=None,
            rule_key="brevity",
            scope="global",
            canonical_value_json='{"value": "brief"}',
            score=0.2,
            status="candidate",
            evidence_count=0,
        )
    )
    second = repo.upsert_state(
        CommunicationRuleState(
            user_id="u1",
            chat_id=None,
            rule_key="brevity",
            scope="global",
            canonical_value_json='{"value": "brief"}',
            score=0.4,
            status="soft_active",
            evidence_count=1,
        )
    )
    repo.commit()

    rows = list(session.exec(select(CommunicationRuleStateRow).where(CommunicationRuleStateRow.user_id == "u1")))
    assert len(rows) == 1
    assert first.id == second.id == rows[0].id


def test_candidate_rules_are_not_included_in_prompt_context(session: Session):
    repo = CommunicationRuleRepository(session)
    repo.add_candidate(
        CommunicationRuleCandidate(
            user_id="u1",
            chat_id="c1",
            rule_key="brevity",
            rule_text="Отвечай короче.",
            scope="current_chat",
            extraction_confidence=0.8,
            initial_score=0.2,
            status="candidate",
        )
    )
    svc = CommunicationRuleService(repository=repo)
    repo.commit()
    assert svc.build_prompt_context(user_id="u1", chat_id="c1") == ""


@pytest.mark.asyncio
async def test_confirmation_does_not_create_candidate_row(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    await svc.ingest_explicit_request(user_id="u1", chat_id="c1", raw_user_message="Отвечай короче.")
    await svc.register_repeated_instruction(user_id="u1", chat_id="c1", raw_user_message="Пиши кратко.")

    before = len(list(session.exec(select(CommunicationRuleStateRow).where(CommunicationRuleStateRow.user_id == "u1"))))
    candidate_before = len(
        list(
            session.exec(select(CommunicationRuleCandidateRow).where(CommunicationRuleCandidateRow.user_id == "u1"))
        )
    )

    svc.register_confirmation(user_id="u1", chat_id="c1", rule_key="brevity")

    candidate_after = len(
        list(
            session.exec(select(CommunicationRuleCandidateRow).where(CommunicationRuleCandidateRow.user_id == "u1"))
        )
    )
    after = len(list(session.exec(select(CommunicationRuleStateRow).where(CommunicationRuleStateRow.user_id == "u1"))))

    assert before == after
    assert candidate_before == candidate_after == 1


@pytest.mark.asyncio
async def test_repeated_instruction_does_not_create_extra_candidate_row(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    await svc.ingest_explicit_request(user_id="u1", chat_id="c1", raw_user_message="Отвечай короче.")
    candidate_before = len(
        list(
            session.exec(select(CommunicationRuleCandidateRow).where(CommunicationRuleCandidateRow.user_id == "u1"))
        )
    )
    await svc.register_repeated_instruction(user_id="u1", chat_id="c1", raw_user_message="Пиши кратко.")
    candidate_after = len(
        list(
            session.exec(select(CommunicationRuleCandidateRow).where(CommunicationRuleCandidateRow.user_id == "u1"))
        )
    )
    assert candidate_before == candidate_after == 1


@pytest.mark.asyncio
async def test_one_event_persists_state_and_evidence_atomically(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    state = await svc.ingest_explicit_request(user_id="u1", chat_id="c1", raw_user_message="Отвечай короче.")
    assert state is not None

    states = list(session.exec(select(CommunicationRuleStateRow).where(CommunicationRuleStateRow.user_id == "u1")))
    evidence = list(session.exec(select(CommunicationRuleEvidenceRow).where(CommunicationRuleEvidenceRow.rule_state_id == states[0].id)))
    candidates = list(session.exec(select(CommunicationRuleCandidateRow).where(CommunicationRuleCandidateRow.user_id == "u1")))
    assert len(states) == 1
    assert len(evidence) == 1
    assert len(candidates) == 1


@pytest.mark.asyncio
async def test_atomic_rollback_cleans_partial_writes(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    original_add_candidate = repo.add_candidate

    def fail_add_candidate(*args, **kwargs):
        raise RuntimeError("boom")

    repo.add_candidate = fail_add_candidate  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="boom"):
            await svc.ingest_explicit_request(user_id="u1", chat_id="c1", raw_user_message="Отвечай короче.")
    finally:
        repo.add_candidate = original_add_candidate  # type: ignore[method-assign]

    states = list(session.exec(select(CommunicationRuleStateRow).where(CommunicationRuleStateRow.user_id == "u1")))
    evidence = list(session.exec(select(CommunicationRuleEvidenceRow)))
    candidates = list(session.exec(select(CommunicationRuleCandidateRow).where(CommunicationRuleCandidateRow.user_id == "u1")))
    assert states == []
    assert evidence == []
    assert candidates == []


@pytest.mark.asyncio
async def test_chat_turn_populates_rule_context_without_rendering_it_in_assistant_text(session: Session):
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
            intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
        communication_rule_service=crs,
    )
    state0 = svc.start_chat(user_id="u1")

    turn1 = await svc.post_user_message(chat_id=state0.chat_id, user_message="Отвечай короче.")
    assert turn1.state.communication_rule_context == ""
    assert all("Communication rules context" not in message for message in turn1.state.assistant_messages)
    rows = list(session.exec(select(CommunicationRuleStateRow).where(CommunicationRuleStateRow.user_id == "u1")))
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_next_turn_reuses_active_communication_rules(session: Session):
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
            intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
        communication_rule_service=crs,
    )
    state0 = svc.start_chat(user_id="u1")

    turn1 = await svc.post_user_message(chat_id=state0.chat_id, user_message="Отвечай короче.")
    assert turn1.state.communication_rule_context == ""
    await svc.confirm(chat_id=state0.chat_id)

    await svc.communication_rule_service.register_repeated_instruction(
        user_id="u1",
        chat_id=state0.chat_id,
        raw_user_message="Пиши кратко.",
    )
    svc.communication_rule_service.register_confirmation(
        user_id="u1",
        chat_id=state0.chat_id,
        rule_key="brevity",
    )

    turn2 = await svc.post_user_message(chat_id=state0.chat_id, user_message="Сделай текст лучше.")
    assert turn2.state.communication_rule_context
    assert "Отвечай кратко." in turn2.state.communication_rule_context
    applicable = svc.communication_rule_service.get_applicable_rules(user_id="u1", chat_id=state0.chat_id)
    assert len(applicable["active_rules"]) == 1


@pytest.mark.asyncio
async def test_current_chat_rule_from_chat_a_is_not_applied_in_chat_b(session: Session):
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
            intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
        communication_rule_service=crs,
    )
    chat_a = svc.start_chat(user_id="u1")
    chat_b = svc.start_chat(user_id="u1")

    await svc.communication_rule_service.ingest_explicit_request(
        user_id="u1",
        chat_id=chat_a.chat_id,
        raw_user_message="Отвечай короче.",
    )
    await svc.communication_rule_service.register_repeated_instruction(
        user_id="u1",
        chat_id=chat_a.chat_id,
        raw_user_message="Пиши кратко.",
    )

    context_a = svc.communication_rule_service.build_prompt_context(user_id="u1", chat_id=chat_a.chat_id)
    context_b = svc.communication_rule_service.build_prompt_context(user_id="u1", chat_id=chat_b.chat_id)

    assert context_a
    assert "Отвечай кратко." in context_a
    assert context_b == ""


@pytest.mark.asyncio
async def test_revoked_rules_are_not_returned_as_applicable(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    await svc.ingest_explicit_request(user_id="u1", chat_id="c1", raw_user_message="Отвечай короче.")
    svc.register_revoke(user_id="u1", chat_id="c1", rule_key="brevity")

    applicable = svc.get_applicable_rules(user_id="u1", chat_id="c1")
    assert applicable["active_rules"] == []
    assert applicable["soft_rules"] == []
    assert svc.build_prompt_context(user_id="u1", chat_id="c1") == ""


@pytest.mark.asyncio
async def test_conflicting_global_and_current_chat_rules_resolve_in_favor_of_current_chat(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    repo.upsert_state(
        CommunicationRuleState(
            user_id="u1",
            chat_id=None,
            rule_key="brevity",
            scope="global",
            canonical_value_json='{"value": "brief"}',
            score=0.8,
            status="active",
            evidence_count=1,
        )
    )
    await svc.ingest_explicit_request(user_id="u1", chat_id="chat-a", raw_user_message="Подробнее, пожалуйста.")
    await svc.register_repeated_instruction(user_id="u1", chat_id="chat-a", raw_user_message="Подробнее, пожалуйста.")
    context = svc.build_prompt_context(user_id="u1", chat_id="chat-a")
    assert "Дай подробные объяснения." in context
    assert "Отвечай кратко." not in context


@pytest.mark.asyncio
async def test_current_chat_conflicting_rule_does_not_modify_opposite_rule_score_automatically(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    repo.upsert_state(
        CommunicationRuleState(
            user_id="u1",
            chat_id=None,
            rule_key="brevity",
            scope="global",
            canonical_value_json='{"value": "brief"}',
            score=0.8,
            status="active",
            evidence_count=1,
        )
    )
    await svc.ingest_explicit_request(user_id="u1", chat_id="chat-a", raw_user_message="Подробнее, пожалуйста.")
    await svc.register_repeated_instruction(user_id="u1", chat_id="chat-a", raw_user_message="Подробнее, пожалуйста.")

    global_rule = repo.get_state("u1", "brevity", "global", chat_id=None)
    current_rule = repo.get_state("u1", "detail_level", "current_chat", chat_id="chat-a")

    assert global_rule is not None
    assert global_rule.score == pytest.approx(0.8)
    assert current_rule is not None
    assert "Дай подробные объяснения." in svc.build_prompt_context(user_id="u1", chat_id="chat-a")
    assert "Отвечай кратко." not in svc.build_prompt_context(user_id="u1", chat_id="chat-a")


@pytest.mark.asyncio
async def test_global_fallback_feedback_updates_matching_global_rule_only_when_no_current_chat_rule_exists(session: Session):
    repo = CommunicationRuleRepository(session)
    svc = CommunicationRuleService(repository=repo, agent=FakeCommunicationRuleAgent())

    repo.upsert_state(
        CommunicationRuleState(
            user_id="u1",
            chat_id=None,
            rule_key="brevity",
            scope="global",
            canonical_value_json='{"value": "brief"}',
            score=0.8,
            status="active",
            evidence_count=1,
        )
    )

    updated_global = svc.register_negative_feedback(user_id="u1", chat_id="chat-a", rule_key="brevity")
    assert updated_global is not None
    assert updated_global.scope == "global"
    assert updated_global.score == pytest.approx(0.5)

    await svc.ingest_explicit_request(user_id="u1", chat_id="chat-a", raw_user_message="Подробнее, пожалуйста.")
    await svc.register_repeated_instruction(user_id="u1", chat_id="chat-a", raw_user_message="Подробнее, пожалуйста.")

    current_rule = svc.register_negative_feedback(user_id="u1", chat_id="chat-a", rule_key="detail_level")
    assert current_rule is not None
    assert current_rule.scope == "current_chat"
    assert current_rule.score == pytest.approx(0.1)

    global_after = repo.get_state("u1", "brevity", "global", chat_id=None)
    assert global_after is not None
    assert global_after.score == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_execution_decision_only_after_confirm(session: Session):
    svc = ChatService(
        session=session,
            intent_agent=FakeIntentAgent(),
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
    crs = CommunicationRuleService(
        repository=CommunicationRuleRepository(session),
        agent=FakeCommunicationRuleAgent(),
    )
    svc = ChatService(
        session=session,
            intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeSelfExecuteDecisionAgent(),
        execution_service=ExecutionService(model=object()),
        communication_rule_service=crs,
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="Отвечай короче.")
    await svc.communication_rule_service.register_repeated_instruction(
        user_id="u1",
        chat_id=state0.chat_id,
        raw_user_message="Пиши кратко.",
    )
    svc.communication_rule_service.register_confirmation(
        user_id="u1",
        chat_id=state0.chat_id,
        rule_key="brevity",
    )

    with patch("app.services.execution_service.run_agent_with_fallback") as mocked_runner:
        mocked_runner.return_value = "Here is the result."
        out = await svc.confirm(chat_id=state0.chat_id)

    assert out.state.execution_status == "completed"
    assert any("Here is the result." in m for m in out.state.assistant_messages)
    assert mocked_runner.call_count == 1
    assert "communication_rule_context:" in mocked_runner.call_args.kwargs["prompt"]
    assert "Отвечай кратко." in mocked_runner.call_args.kwargs["prompt"]


@pytest.mark.asyncio
async def test_needs_tool_path_stays_blocked(session: Session):
    svc = ChatService(
        session=session,
            intent_agent=FakeIntentAgent(),
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
            intent_agent=FakeIntentAgent(),
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
            intent_agent=FakeIntentAgent(),
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


class _FixedIntentAgent:
    def __init__(self, intent: TurnIntent):
        self._intent = intent

    async def classify(self, *, raw_user_message: str, context: dict) -> TurnIntent:
        return self._intent


class _RecordingIntentAgent:
    def __init__(self, intent: TurnIntent):
        self._intent = intent
        self.calls: list[tuple[str, dict]] = []

    async def classify(self, *, raw_user_message: str, context: dict) -> TurnIntent:
        self.calls.append((raw_user_message, context))
        return self._intent


class _FailingIntentAgent:
    async def classify(self, *, raw_user_message: str, context: dict) -> TurnIntent:
        raise AssertionError("graph must not re-classify intent")


class _RecordingMemoryAgent:
    def __init__(self):
        self.seen_correction_message = None

    async def standing_preference_from_correction(self, *, correction_message: str, revised_normalized):
        self.seen_correction_message = correction_message
        return None


@pytest.mark.asyncio
async def test_chat_message_close_is_not_text_routed(session: Session, monkeypatch):
    svc = ChatService(
        session=session,
        intent_agent=_FixedIntentAgent(TurnIntent(kind="new_task", confidence=1.0, reason="test")),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")

    async def _noop_post_chat(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.chat_service.run_post_chat_analysis", _noop_post_chat)
    out = await svc.post_user_message(chat_id=state0.chat_id, user_message="close the chat please")
    assert out.state.chat_closed is False
    closed = await svc.close(chat_id=state0.chat_id)
    assert closed.state.chat_closed is True


@pytest.mark.asyncio
async def test_one_turn_classifies_intent_exactly_once_for_new_chat(session: Session):
    intent_agent = _RecordingIntentAgent(TurnIntent(kind="new_task", confidence=1.0, reason="test"))
    svc = ChatService(
        session=session,
        intent_agent=intent_agent,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )

    await svc.post_turn(user_id="u1", chat_id=None, user_message="hello")

    assert len(intent_agent.calls) == 1


@pytest.mark.asyncio
async def test_review_confirm_uses_explicit_action(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")

    confirmed = await svc.confirm(chat_id=state0.chat_id)
    assert confirmed.state.awaiting_confirmation is True
    assert confirmed.state.execution_decision is not None or confirmed.state.execution_status in {"blocked", "idle"}


@pytest.mark.asyncio
async def test_review_text_through_turn_is_rejected(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")

    with pytest.raises(ValueError, match="review_pending_use_confirm_or_reject"):
        await svc.post_user_message(chat_id=state0.chat_id, user_message="да")


@pytest.mark.asyncio
async def test_post_user_message_is_blocked_while_review_pending(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    turn1 = await svc.post_user_message(chat_id=state0.chat_id, user_message="do it")
    assert turn1.state.awaiting_user_feedback is True
    with pytest.raises(ValueError, match="review_pending_use_confirm_or_reject"):
        await svc.post_user_message(chat_id=state0.chat_id, user_message="some free text")


@pytest.mark.asyncio
async def test_reject_review_exits_review_mode_without_execution(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    turn1 = await svc.post_user_message(chat_id=state0.chat_id, user_message="do it")
    assert turn1.state.awaiting_user_feedback is True
    out = await svc.reject_review(chat_id=state0.chat_id)
    assert out.state.awaiting_user_feedback is False
    assert out.state.awaiting_confirmation is False
    assert out.state.execution_status == "idle"
    assert any("не подтверждён" in m.lower() for m in out.state.assistant_messages)


@pytest.mark.asyncio
async def test_after_reject_review_user_can_send_new_message_again(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    turn1 = await svc.post_user_message(chat_id=state0.chat_id, user_message="first task")
    assert turn1.state.awaiting_user_feedback is True
    await svc.reject_review(chat_id=state0.chat_id)
    turn2 = await svc.post_user_message(chat_id=state0.chat_id, user_message="second task")
    assert turn2.state.normalized_request is not None


@pytest.mark.asyncio
async def test_confirm_flow_uses_endpoint_not_text_intent(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=_FixedIntentAgent(TurnIntent(kind="other", confidence=1.0, reason="ignored")),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeSelfExecuteDecisionAgent(),
        execution_service=ExecutionService(model=object()),
    )
    state0 = svc.start_chat(user_id="u1")
    turn1 = await svc.post_user_message(chat_id=state0.chat_id, user_message="do it")
    assert turn1.state.awaiting_user_feedback is True
    with patch("app.services.execution_service.run_agent_with_fallback") as mocked_runner:
        mocked_runner.return_value = "Here is the result."
        out = await svc.confirm(chat_id=state0.chat_id)
    assert out.state.execution_status == "completed"
    assert mocked_runner.call_count == 1


@pytest.mark.asyncio
async def test_free_text_cannot_apply_correction_during_review(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")
    row1 = svc.chat_repo.get_latest_normalized_request(state0.chat_id)
    assert row1 is not None
    with pytest.raises(ValueError, match="review_pending_use_confirm_or_reject"):
        await svc.post_user_message(chat_id=state0.chat_id, user_message="исправь или не так")
    row2 = svc.chat_repo.get_latest_normalized_request(state0.chat_id)
    assert row2.revision == row1.revision


@pytest.mark.asyncio
async def test_explicit_correction_does_not_use_intent_agent(session: Session):
    intent_agent = _RecordingIntentAgent(TurnIntent(kind="new_task", confidence=1.0, reason="test"))
    svc = ChatService(
        session=session,
        intent_agent=intent_agent,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")
    n_calls = len(intent_agent.calls)
    out = await svc.post_correction(chat_id=state0.chat_id, correction_message="change it")
    assert out.state.normalized_request is not None
    assert out.state.normalized_request.revision == 2
    assert len(intent_agent.calls) == n_calls


@pytest.mark.asyncio
async def test_explicit_confirm_does_not_use_intent_agent(session: Session):
    intent_agent = _RecordingIntentAgent(TurnIntent(kind="new_task", confidence=1.0, reason="test"))
    svc = ChatService(
        session=session,
        intent_agent=intent_agent,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")
    n_calls = len(intent_agent.calls)
    out = await svc.confirm(chat_id=state0.chat_id)
    assert out.state.execution_decision is not None or out.state.execution_status in {"blocked", "idle"}
    assert len(intent_agent.calls) == n_calls


def test_bundled_html_disables_composer_during_review():
    from app.main import CHAT_HTML

    assert "reviewActions" in CHAT_HTML
    assert "syncUiFromState" in CHAT_HTML
    assert "/chat/reject_review" in CHAT_HTML
    assert "lastState?.awaiting_user_feedback" in CHAT_HTML


@pytest.mark.asyncio
async def test_single_memory_candidate_confirm_uses_explicit_action(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )

    state0 = svc.start_chat(user_id="u1")
    mem = MemoryService(session=session)
    candidate = mem.create_explicit_candidate(
        chat_id=state0.chat_id,
        cand=MemoryCandidate(
            memory_type="preference",
            target_layer="core_profile",
            normalized_memory="user prefers short answers",
            source="user_requested",
            confidence=0.9,
            requires_confirmation=True,
        ),
    )

    entry = mem.confirm_candidate(candidate_id=candidate.id, user_id="u1")
    assert entry.status == "confirmed"
    assert mem.repo.get_candidate(candidate.id).status == "confirmed"


@pytest.mark.asyncio
async def test_single_memory_candidate_reject_uses_explicit_action(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )

    state0 = svc.start_chat(user_id="u1")
    mem = MemoryService(session=session)
    candidate = mem.create_explicit_candidate(
        chat_id=state0.chat_id,
        cand=MemoryCandidate(
            memory_type="preference",
            target_layer="core_profile",
            normalized_memory="user prefers short answers",
            source="user_requested",
            confidence=0.9,
            requires_confirmation=True,
        ),
    )

    mem.reject_candidate(candidate_id=candidate.id)
    assert mem.repo.get_candidate(candidate.id).status == "rejected"


@pytest.mark.asyncio
async def test_close_chat_uses_explicit_action(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="hello")
    closed = await svc.close(chat_id=state0.chat_id)
    assert closed.state.chat_closed is True


@pytest.mark.asyncio
async def test_non_fallback_case_still_uses_intent_agent(session: Session):
    intent_agent = _RecordingIntentAgent(TurnIntent(kind="new_task", confidence=1.0, reason="test"))
    svc = ChatService(
        session=session,
        intent_agent=intent_agent,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )

    state0 = svc.start_chat(user_id="u1")
    out = await svc.post_user_message(chat_id=state0.chat_id, user_message="hello world")
    assert len(intent_agent.calls) == 1
    assert out.state.turn_intent is not None
    assert out.state.turn_intent.kind == "new_task"


@pytest.mark.asyncio
async def test_multiple_memory_candidates_do_not_use_turn_text_for_approval(session: Session):
    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )

    state0 = svc.start_chat(user_id="u1")
    mem = MemoryService(session=session)
    mem.create_explicit_candidate(
        chat_id=state0.chat_id,
        cand=MemoryCandidate(
            memory_type="preference",
            target_layer="core_profile",
            normalized_memory="user prefers short answers",
            source="user_requested",
            confidence=0.9,
            requires_confirmation=True,
        ),
    )
    mem.create_explicit_candidate(
        chat_id=state0.chat_id,
        cand=MemoryCandidate(
            memory_type="preference",
            target_layer="core_profile",
            normalized_memory="user prefers direct answers",
            source="user_requested",
            confidence=0.9,
            requires_confirmation=True,
        ),
    )

    with pytest.raises(CriticalTurnError):
        await svc.post_user_message(chat_id=state0.chat_id, user_message="confirm")


@pytest.mark.asyncio
async def test_graph_applies_explicit_correction_path_without_reclassifying(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=_FailingIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    state0.raw_user_message = "make it shorter"
    state0.explicit_normalized_review_action = "correction"
    state0.turn_intent = TurnIntent(kind="other", confidence=1.0, reason="orchestrator placeholder")
    state0.normalized_request = NormalizedUserRequest(
        normalized_user_request="normalize: hello",
        continuity="new",
        needs_clarification=False,
        clarification_reason=None,
        clarification_options=[],
        ambiguity_handling="none",
        revision=1,
    )

    out = await svc.graphs.main_chat_graph().ainvoke(state0)
    result = ChatState.model_validate(out)

    assert result.explicit_normalized_review_action is None
    assert result.normalized_request is not None


@pytest.mark.asyncio
async def test_graph_confirm_path_uses_explicit_action_not_turn_intent(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=_FailingIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    state0.raw_user_message = None
    state0.explicit_normalized_review_action = "confirm"
    state0.turn_intent = TurnIntent(kind="other", confidence=1.0, reason="orchestrator placeholder")
    state0.normalized_request = NormalizedUserRequest(
        normalized_user_request="normalize: hello",
        continuity="new",
        needs_clarification=False,
        clarification_reason=None,
        clarification_options=[],
        ambiguity_handling="none",
        revision=1,
    )

    out = await svc.graphs.main_chat_graph().ainvoke(state0)
    result = ChatState.model_validate(out)

    assert result.awaiting_confirmation is True
    assert result.explicit_normalized_review_action is None


@pytest.mark.asyncio
async def test_turn_intent_routes_new_task_without_reclassification(session: Session):
    svc = ChatService(
        session=session,
        intent_agent=_FailingIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    state0 = svc.start_chat(user_id="u1")
    state0.raw_user_message = "new task"
    state0.turn_intent = TurnIntent(kind="new_task", confidence=1.0, reason="precomputed")

    out = await svc.graphs.main_chat_graph().ainvoke(state0)
    result = ChatState.model_validate(out)

    assert result.normalized_request is not None


@pytest.mark.asyncio
async def test_correction_passes_normalized_correction_text_into_memory_analysis(session: Session):
    memory_agent = _RecordingMemoryAgent()
    svc = ChatService(
        session=session,
        intent_agent=FakeIntentAgent(),
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    svc.graphs.memory_agent = memory_agent
    state0 = svc.start_chat(user_id="u1")
    await svc.post_user_message(chat_id=state0.chat_id, user_message="make it shorter")

    await svc.post_correction(chat_id=state0.chat_id, correction_message="shorter, but keep the subject line")

    assert memory_agent.seen_correction_message == "shorter, but keep the subject line"


def test_pending_memory_dedup_uses_full_candidate_identity(session: Session):
    mem = MemoryService(session=session)
    chat = Chat(user_id="u1")
    session.add(chat)
    session.commit()
    session.refresh(chat)

    base = MemoryCandidate(
        memory_type="preference",
        target_layer="core_profile",
        normalized_memory="user prefers short answers",
        source="user_requested",
        confidence=0.9,
        requires_confirmation=True,
    )
    mem.create_explicit_candidate(chat_id=chat.id, cand=base)

    different_layer = base.model_copy(update={"target_layer": "long_term_memory"})
    repo = mem.repo
    assert not repo.has_pending_equivalent_candidate(chat_id=chat.id, cand=different_layer)
    assert repo.has_pending_equivalent_candidate(chat_id=chat.id, cand=base)


@pytest.mark.asyncio
async def test_memory_candidate_confirm_uses_explicit_action_endpoint(session: Session):
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

    svc = ChatService(
        session=session,
        normalization_agent=FakeNormalizationAgent(),
        execution_agent=FakeExecutionAgent(),
    )
    assert len(list(session.exec(select(MemoryEntryRow).where(MemoryEntryRow.user_id == "u1")))) == 0
    confirmed = MemoryService(session=session).confirm_candidate(candidate_id=row.id, user_id="u1")
    assert confirmed.status == "confirmed"


@pytest.mark.asyncio
async def test_close_chat_triggers_post_chat_analysis_safely(session: Session):
    svc = ChatService(
        session=session,
            intent_agent=FakeIntentAgent(),
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
            intent_agent=FakeIntentAgent(),
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
            intent_agent=FakeIntentAgent(),
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
    assert "close_chat" not in main_nodes

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
            intent_agent=FakeIntentAgent(),
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
