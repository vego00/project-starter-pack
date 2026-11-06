from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.journey.composers.summary import compose_summary
from app.journey.constraints import Conflict, evaluate
from app.journey.state import Decision, Evidence, JourneyState, ProjectSpec
from app.registry.loader import Registry, load_registry

REGISTRY = Registry(card for card in load_registry().cards if card.card_id != "agent.topology")
IDEA = "강의 자료를 찾아 답하는 멀티 에이전트 서비스"
CHOICES = {
    "agent.hitl": "approval",
    "model.provider": "gemini",
    "data.primary_db": "postgres",
    "data.vector_store": "pgvector",
    "data.checkpointer": "postgres",
    "backend.execution": "queue",
    "devops.orchestration": "none",
    "mlops.model_serving": "external_api",
    "cloud.target": "local",
}


def decision(card_id, option_id, by="user", rationale=""):
    return Decision(
        card_id=card_id,
        card_version=1,
        option_id=option_id,
        by=by,
        rationale=rationale,
        at=datetime(2026, 11, 4, tzinfo=UTC),
    )


def make_state(spec=None, choices=None, **overrides):
    decisions = {k: decision(k, v) for k, v in (choices or CHOICES).items()}
    return JourneyState(
        journey_id=uuid4(),
        project_spec=ProjectSpec(**(spec or {"idea": IDEA})),
        decisions=decisions,
        **overrides,
    )


def compose(state=None, is_mock=True):
    return compose_summary(state or make_state(), REGISTRY, is_mock=is_mock)


def test_lists_every_decision_in_journey_order():
    document = compose()

    positions = [document.index(card.question) for card in REGISTRY.cards]
    assert positions == sorted(positions)
    assert "승인 후 실행 (직접 선택)" in document


def test_records_tradeoffs_and_rejected_options():
    document = compose()

    assert "**감수할 점:** 승인 대기와 거절 후 흐름까지 설계해야 합니다" in document
    assert "**고르지 않은 선택지:** 없음, 실행 중 질문" in document


def test_says_who_decided():
    state = make_state(
        choices={"agent.hitl": "none"},
        implied={"model.provider": decision("model.provider", "ollama", "implied", "규칙 설명")},
    )
    state.decisions["cloud.target"] = decision("cloud.target", "local", "recommended", "기본 이유")

    document = compose(state)

    assert "없음 (직접 선택)" in document
    assert "로컬만 (추천 수락)" in document
    assert "Ollama 로컬 (규칙으로 자동 확정)" in document
    assert "**이유:** 규칙 설명" in document


def test_mock_notice_appears_only_for_mock_runs():
    assert "모델 없이 카드 기본값" in compose(is_mock=True)
    assert "모델 없이 카드 기본값" not in compose(is_mock=False)


def test_does_not_claim_evidence_or_verification_it_lacks():
    document = compose()

    assert "강의 자료 근거는 아직 연결되어 있지 않습니다" in document
    assert "공식 문서로 다시 확인이 필요합니다" in document


def test_unanswered_signals_are_marked_unknown_not_guessed():
    document = compose()

    assert "- 팀 인원: 미확인" in document
    assert "답하지 않은 항목: 배포 목표" in document

    answered = compose(
        make_state(
            {
                "idea": IDEA,
                "team_size": 4,
                "deployment_target": "small_group",
                "data_traits": ["문서 검색", "개인정보"],
            }
        )
    )
    assert "- 팀 인원: 4" in answered
    assert "- 배포 목표: 소수 사용자" in answered
    assert "- 데이터 특징: 문서 검색, 개인정보" in answered


def test_linked_notes_appear_on_their_card_labelled_as_notes():
    item = Evidence(
        source_id="n",
        title="AX Work",
        kind="personal_note",
        location="Ch. 2",
        why="사람의 책임을 다룹니다.",
    )

    document = compose_summary(
        make_state(), REGISTRY, is_mock=True, evidence={"agent.hitl": [item], "cloud.target": []}
    )

    section = document.split("### 모델:")[0]
    assert "**참고 필기:** AX Work (Ch. 2). 사람의 책임을 다룹니다." in section
    assert "개인 필기이며 강의 원문이 아닙니다" in document
    assert "강의 자료 근거는 아직 연결되어 있지 않습니다" not in document


def test_gcb_opens_the_document_and_unknown_is_marked():
    spec = {"idea": IDEA, "goal": "목표 상태", "boundary": "외부 전송 금지"}

    document = compose(make_state(spec))

    project = document.split("## 결정")[0]
    assert "> 목표 상태" in project
    assert "> 외부 전송 금지" in project
    assert "**Context (필요한 상황)**\n\n> 미확인" in project


def test_gcb_text_cannot_add_document_structure():
    document = compose(make_state({"idea": IDEA, "goal": "목표\n## 가짜 제목"}))

    headings = [line for line in document.splitlines() if line.startswith("#")]
    assert not any("가짜" in line for line in headings)


def test_gpu_answer_is_stated_either_way():
    assert "- GPU 장비: 없음" in compose(make_state({"idea": IDEA, "has_gpu": False}))
    assert "- GPU 장비: 있음" in compose(make_state({"idea": IDEA, "has_gpu": True}))
    assert "- GPU 장비: 미확인" in compose()


def test_warnings_are_listed():
    warning = Conflict(rule_id="w", severity="warning", message="GPU를 확인하세요.", card_ids=[])

    assert "- GPU를 확인하세요." in compose(make_state(review_issues=[warning]))
    assert "규칙 검사에서 경고가 없습니다" in compose()


def test_components_come_from_chosen_options_only():
    document = compose()

    assert "`compose:worker`" in document and "`compose:redis`" in document
    assert "`compose:ollama`" not in document

    simple_choices = {
        **CHOICES,
        "backend.execution": "sync",
        "data.primary_db": "none",
        "data.vector_store": "none",
    }
    simple = compose(make_state(choices=simple_choices))
    assert "추가될 구성 요소" not in simple


@pytest.mark.parametrize("text", ["# 가짜 제목\n## 또 다른 제목", "첫 줄\n\n둘째 줄"])
def test_user_text_cannot_add_document_structure(text):
    document = compose(make_state({"idea": f"{IDEA}\n{text}"}))

    headings = [line for line in document.splitlines() if line.startswith("#")]
    assert not any("가짜" in line or "또 다른" in line for line in headings)
    assert "> # 가짜 제목" in document or "> 첫 줄" in document


def test_rationale_with_line_breaks_stays_on_its_line():
    state = make_state(choices={"agent.hitl": "none"})
    state.decisions["agent.hitl"] = decision("agent.hitl", "none", rationale="이유\n# 제목 주입")

    document = compose(state)

    assert "**이유:** 이유 # 제목 주입" in document
    assert "\n# 제목 주입" not in document


def test_same_input_gives_the_same_document():
    state = make_state()

    assert compose(state) == compose(state)


def test_shipped_choices_used_here_are_consistent():
    assert [c for c in evaluate(REGISTRY, CHOICES).conflicts if c.severity == "error"] == []
