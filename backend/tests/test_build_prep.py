"""Build preparation (ADR-026 ③): the stage after the design that asks what the bundle leaves."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.config import Settings
from app.journey.build_plan import plan_build
from app.journey.design import ServiceDesign
from app.journey.package import build_package
from app.journey.state import BuildAnswer, JourneyState
from app.main import create_app
from app.registry.loader import load_registry
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from tests.screen import prepared

REGISTRY = load_registry()
JOURNEYS = "/api/v1/journeys"
SPEC = {
    "idea": "제조 불량 원인을 찾아 주는 멀티 에이전트 서비스",
    "goal": "담당자가 근거와 함께 원인을 확인하는 상태",
    "team_size": 3,
    "duration_weeks": 4,
    "budget": "월 5만원",
    "expected_users": 5,
    "weekly_hours": 20,
    "data_traits": ["문서 검색"],
    "deployment_target": "local_demo",
    "has_gpu": False,
}
NOW = datetime(2026, 11, 27, tzinfo=UTC)
_spec = importlib.util.spec_from_file_location(
    "validator_fixture", Path(__file__).parent / "test_design_validator.py"
)
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


@pytest.fixture
def client():
    app = create_app(Settings(_env_file=None), checkpointer=InMemorySaver(), registry=REGISTRY)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def act(client, view, **action):
    response = client.post(
        f"{JOURNEYS}/{view['journey_id']}/decisions",
        json={"revision": view["revision"], "action": action},
    )
    return prepared(client, response, finish_build=False)


def ok(client, view, **action):
    response = act(client, view, **action)
    assert response.status_code == 200, response.text
    return response.json()


def to_build(client, view=None):
    """Takes every card's recommendation, asks for the design and stops at build preparation."""
    if view is None:
        view = prepared(client, client.post(JOURNEYS, json=SPEC), finish_build=False).json()
    while view["prompt"]["type"] != "build":
        prompt = view["prompt"]
        if prompt["type"] == "clarify":
            view = ok(client, view, action="clarify", answers={})
        elif prompt["type"] == "fork":
            view = ok(client, view, action="plan_deploy")
        else:
            view = ok(client, view, action="accept_recommendation")
    return view


def item(view, key):
    return next(i for i in view["build"]["items"] if i["id"] == key)


def state_of(client, view) -> JourneyState:
    return JourneyState.model_validate(client.app.state.journeys._read(view["journey_id"]).values)


# The stage in the journey


def test_the_design_leads_to_build_preparation_and_back_from_the_end(client):
    view = to_build(client)

    assert view["status"] == "completed" and view["design"] is not None
    assert view["build"]["remaining"] == len(view["build"]["items"]) > 0
    assert view["can_reopen"] is True

    done = ok(client, view, action="build_finish")
    assert done["prompt"] is None and done["build"]["remaining"] == view["build"]["remaining"]

    again = ok(client, done, action="build_prep")
    assert again["prompt"]["type"] == "build"


def test_build_actions_belong_to_build_preparation_only(client):
    view = to_build(client)
    done = ok(client, view, action="build_finish")

    assert act(client, done, action="build_accept_all").status_code == 409
    assert act(client, done, action="build_finish").status_code == 409
    assert (
        act(client, view := ok(client, done, action="build_prep"), action="build_prep").status_code
        == 409
    )
    assert view["prompt"]["type"] == "build"


# Answering


def test_one_item_by_recommendation_one_written_and_one_held(client):
    view = to_build(client)
    with_advice = [i for i in view["build"]["items"] if i["recommendation"]]
    first, second, third = with_advice[:3]

    view = ok(client, view, action="build_accept", key=first["id"])
    view = ok(client, view, action="build_answer", key=second["id"], value="직접 정한 답")
    view = ok(client, view, action="build_hold", key=third["id"])

    assert (item(view, first["id"])["status"], item(view, first["id"])["by"]) == (
        "answered",
        "recommended",
    )
    assert item(view, first["id"])["value"] == first["recommendation"]
    assert (item(view, second["id"])["value"], item(view, second["id"])["by"]) == (
        "직접 정한 답",
        "user",
    )
    assert item(view, third["id"])["status"] == "held"
    assert view["build"]["remaining"] == len(view["build"]["items"]) - 2


def test_accept_all_records_each_item_with_the_recommendation_it_took(client):
    view = to_build(client)
    held = next(i for i in view["build"]["items"] if i["recommendation"])
    view = ok(client, view, action="build_hold", key=held["id"])
    before = {i["id"]: i for i in view["build"]["items"]}

    view = ok(client, view, action="build_accept_all")

    answers = state_of(client, view).build_answers
    for key, shown in before.items():
        if key == held["id"]:
            assert answers[key].by == "held" and item(view, key)["status"] == "held"
        elif shown["recommendation"]:
            assert (answers[key].by, answers[key].value) == ("recommended", shown["recommendation"])
        else:
            assert key not in answers and item(view, key)["status"] == "open"


def test_an_unknown_item_or_one_without_advice_is_refused_and_nothing_is_kept(client):
    view = to_build(client)

    refused = ok(client, view, action="build_accept", key="no-such-item")

    assert refused["prompt"]["error"] and state_of(client, refused).build_answers == {}


def test_the_same_revision_cannot_answer_twice(client):
    view = to_build(client)
    key = next(i["id"] for i in view["build"]["items"] if i["recommendation"])

    ok(client, view, action="build_accept", key=key)
    second = act(client, view, action="build_hold", key=key)

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "stale_revision"


# Answers outlive a new design


def test_changing_the_provider_asks_again_only_what_reads_it(client):
    view = ok(client, to_build(client), action="build_accept_all")
    assert item(view, "model_ids")["status"] == "answered"
    assert item(view, "data_scope")["status"] == "answered"
    provider = next(c for c in view["cards"] if c["card_id"] == "model.provider")["option_id"]
    other = next(o for o in ("openai", "gemini") if o != provider)

    view = ok(client, view, action="reopen", card_id="model.provider")
    view = ok(client, view, action="select", option_id=other)
    view = to_build(client, view)

    assert item(view, "model_ids")["status"] == "recheck"
    assert item(view, "model_ids")["previous"]
    assert item(view, "data_scope")["status"] == "answered"
    kept = ok(client, view, action="build_keep", key="model_ids")
    assert item(kept, "model_ids")["status"] == "answered"


# The plan behind the screen


def design(unknowns=(), **choices):
    fields = _fixture.valid_design()
    decisions = {d["card_id"]: d for d in fields["provenance"]["decisions"]}
    for card_id, option_id in choices.items():
        decisions[card_id] = {"card_id": card_id, "card_version": REGISTRY.card(card_id).version,
                              "option_id": option_id, "by": "user"}  # fmt: skip
    fields["provenance"]["decisions"] = list(decisions.values())
    fields["unknowns"] = list(unknowns)
    return ServiceDesign(**fields)


def plan(the_design, answers=None):
    return plan_build(the_design, REGISTRY, "아이디어", answers=answers)


def answer(spec_item, value="답", by="user"):
    return BuildAnswer(value=value, by=by, at=NOW, design_revision=1, inputs=spec_item.inputs)


def test_a_question_keeps_its_answer_in_a_new_design_while_its_words_stay():
    form = {"text": "기획서 양식은 무엇인가요?", "blocks_confirmation": False,
            "recommendation": "문제, 해결, 기대 효과", "options": ["세 섹션", "한 장 요약"]}  # fmt: skip
    first = plan(design([form]))
    question = next(i for i in first.open if i.question == form["text"])
    assert question.options == ("세 섹션", "한 장 요약") and question.recommendation
    answers = {question.id: answer(question)}

    same = plan(design([form], **{"agent.hitl": "question"}), answers)
    advice_changed = plan(design([{**form, "recommendation": "한 장으로"}]), answers)
    reworded = plan(design([{**form, "text": "기획서 섹션은 무엇인가요?"}]), answers)

    assert [a.id for a in same.answered] == [question.id]
    assert next(i for i in advice_changed.open if i.id == question.id).status == "recheck"
    assert question.id not in {i.id for i in (*reworded.open, *reworded.answered)}
    assert any(i.question.startswith("기획서 섹션") for i in reworded.open)


def test_an_item_that_stops_applying_is_hidden_and_its_answer_returns_with_it():
    code = plan(design(**{"backend.implementation": "code"}))
    model_ids = next(i for i in code.open if i.id == "model_ids")
    answers = {"model_ids": answer(model_ids)}

    n8n = plan(design(**{"backend.implementation": "n8n"}), answers)
    back = plan(design(**{"backend.implementation": "code"}), answers)

    assert "model_ids" not in {i.id for i in (*n8n.open, *n8n.answered)}
    assert "model_ids" in {i.id for i in back.answered}


def test_the_bundle_lists_what_was_set_and_leaves_only_hands_on_work_open():
    the_design = design(**{"model.provider": "gemini", "product.surface": "web",
                           "data.primary_db": "postgres"})  # fmt: skip
    first = plan(the_design)
    answers = {i.id: answer(i, i.recommendation or "직접", "recommended" if i.recommendation
                            else "user") for i in first.open}  # fmt: skip

    files = build_package(plan(the_design, answers))
    build, gates = files["BUILD.md"], files["docs/gates.md"]

    assert "## 정한 것 (빌드 준비)" in build
    assert build.split("## 남은 결정", 1)[1].split("##", 1)[0].strip() == "- 없음"
    opened = [line for line in gates.splitlines() if line.startswith("- [ ]")]
    assert opened and all(("API 키" in line or "모델 파일" in line) for line in opened)
    assert "- [x] 다루는 데이터를 써도 되는 범위" in gates and "받음: 2026-11-27" in gates
    assert "- 지킬 것: 구현 전에 테이블과 색인 구조를 docs/data-model.md에 먼저 쓴다" in gates
    assert files == build_package(plan(the_design, answers))


def test_a_journey_saved_before_build_preparation_reads_with_no_answers():
    old = json.loads((Path(__file__).parent / "fixtures" / "journey_state_before_design.json")
                     .read_text("utf-8"))["completed"]  # fmt: skip

    assert JourneyState.model_validate(old).build_answers == {}


def test_every_asked_start_condition_names_a_build_item():
    from app.registry.build_decisions import default_build_decisions
    from app.registry.modules import default_module_rules

    items = {item.id for item in default_build_decisions().items}
    asked = [g for m in default_module_rules().modules for g in m.gates if g.kind == "asked"]

    assert asked and all(gate.asks in items for gate in asked)


def test_an_edit_after_the_end_keeps_the_journey_at_the_end(client):
    done = ok(client, to_build(client), action="build_finish")
    module = done["modules"][0]["id"]

    edited = client.post(
        f"{JOURNEYS}/{done['journey_id']}/modules/edits",
        json={"revision": done["module_revision"],
              "change": {"module": module, "field": "goal", "value": "근거를 함께 보인다"}},
    )  # fmt: skip

    assert edited.status_code == 200, edited.text
    assert edited.json()["prompt"] is None
    in_build = ok(client, edited.json(), action="build_prep")
    edited = client.post(
        f"{JOURNEYS}/{in_build['journey_id']}/modules/edits",
        json={"revision": in_build["module_revision"],
              "change": {"module": module, "field": "goal", "value": "근거를 보인다"}},
    )  # fmt: skip
    assert edited.json()["prompt"]["type"] == "build"


def test_build_actions_wait_while_a_design_is_made(client):
    view = prepared(client, client.post(JOURNEYS, json=SPEC), finish_build=False).json()
    while view["prompt"]["type"] != "designing":
        prompt = view["prompt"]
        if prompt["type"] == "fork":
            view = act(client, view, action="plan_deploy").json()
        elif prompt["type"] == "clarify":
            view = act(client, view, action="clarify", answers={}).json()
        else:
            response = client.post(
                f"{JOURNEYS}/{view['journey_id']}/decisions",
                json={"revision": view["revision"], "action": {"action": "accept_recommendation"}},
            )
            view = response.json()
            if view["prompt"]["type"] == "decision" and view["prompt"]["card"]["preparing"]:
                view = act(client, view, action="prepare").json()

    refused = client.post(
        f"{JOURNEYS}/{view['journey_id']}/decisions",
        json={"revision": view["revision"], "action": {"action": "build_accept_all"}},
    )

    assert refused.status_code == 409 and refused.json()["error"]["code"] == "designing"
