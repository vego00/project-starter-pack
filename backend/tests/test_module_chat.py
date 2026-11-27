"""Build-order conversation (ADR-022 phase 4): only what people say is stored, and validated."""

import pytest
from app.config import Settings
from app.journey.blueprint import EXAMPLES
from app.journey.modules import (
    ModuleChange,
    ModuleNote,
    apply_module_changes,
    build_module_plan,
)
from app.journey.services import JourneyDeps, ModuleReply
from app.main import create_app
from app.registry.loader import load_registry
from app.registry.modules import load_module_rules
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

REGISTRY = load_registry()
RULES = load_module_rules(REGISTRY)
TEAM = next(choices for example_id, _, _, choices in EXAMPLES if example_id == "team")
JOURNEYS = "/api/v1/journeys"
SPEC = {
    "idea": "강의 자료로 질문에 답하는 서비스",
    "goal": "수강생이 근거와 함께 답을 찾을 수 있는 상태",
    "team_size": 2,
    "duration_weeks": 6,
    "budget": "월 5만원",
    "expected_users": 30,
    "weekly_hours": 10,
    "data_traits": ["문서 검색"],
    "deployment_target": "small_group",
    "has_gpu": False,
}


def team_plan(notes=None):
    return build_module_plan(REGISTRY, RULES, TEAM, notes)


def apply(*changes, notes=None):
    return apply_module_changes(team_plan(notes), notes or {}, list(changes))


def test_a_goal_and_scope_are_stored_as_notes_and_shown_as_said():
    notes, applied, rejected = apply(
        ModuleChange(module="agent", field="goal", value="  강의 자료로  답한다 "),
        ModuleChange(module="agent", field="include", items=["근거 표시", "근거 표시", " "]),
        ModuleChange(module="agent", field="exclude", items=["음성 입력"]),
    )

    assert rejected == []
    assert applied == [
        "에이전트 흐름 · 목표",
        "에이전트 흐름 · 만들 것",
        "에이전트 흐름 · 안 만들 것",
    ]
    agent = next(m for m in team_plan(notes) if m.id == "agent")
    assert agent.goal.text == "강의 자료로 답한다" and agent.goal.source == "chat"
    assert [i.text for i in agent.include] == ["근거 표시"]
    assert [i.text for i in agent.exclude] == ["음성 입력"]
    # Rule parts are recomputed, never copied into the notes.
    assert set(ModuleNote.model_fields) == {"goal", "include", "exclude", "targets"}


def test_a_target_fills_only_an_open_criterion_and_must_be_measurable():
    notes, applied, rejected = apply(
        ModuleChange(module="agent", field="target", criterion="답변 응답 시간", value="5초 이내"),
    )
    agent = next(m for m in team_plan(notes) if m.id == "agent")
    timing = next(c for c in agent.criteria if c.text == "답변 응답 시간")
    assert (timing.target, timing.source, timing.needs_target) == ("5초 이내", "chat", True)

    _, applied, rejected = apply(
        ModuleChange(module="agent", field="target", criterion="답변 응답 시간", value="빠르게"),
        ModuleChange(module="agent", field="target", criterion="없는 기준", value="3초"),
        ModuleChange(module="nope", field="goal", value="목표"),
        ModuleChange(module="agent", field="goal", value=""),
    )
    assert applied == []
    assert len(rejected) == 4
    assert "정할 값으로 남겨 뒀어요" in rejected[0]


def test_too_many_scope_items_are_rejected_whole():
    _, applied, rejected = apply(
        ModuleChange(module="agent", field="include", items=[f"항목 {n}" for n in range(13)]),
    )
    assert applied == [] and rejected


class ScriptedWriter:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def write(self, plan, chat, message):
        self.seen.append((len(chat), message))
        return self.replies.pop(0)


def client_with(writer=None):
    deps = JourneyDeps(module_writer=writer)
    app = create_app(Settings(_env_file=None), checkpointer=InMemorySaver(), deps=deps)
    return TestClient(app, raise_server_exceptions=False)


def finish(client):
    view = client.post(JOURNEYS, json=SPEC).json()
    while view["prompt"]:
        prompt = view["prompt"]
        if prompt["type"] == "clarify":
            action = {"action": "clarify", "answers": {}}
        elif prompt["type"] == "fork":
            action = {"action": "plan_deploy"}
        elif prompt["type"] == "designing":
            action = {"action": "design"}
        elif prompt["type"] == "build":
            action = {"action": "build_finish"}
        elif prompt["card"]["preparing"]:
            action = {"action": "prepare"}
        else:
            action = {"action": "accept_recommendation"}
        response = client.post(
            f"{JOURNEYS}/{view['journey_id']}/decisions",
            json={"revision": view["revision"], "action": action},
        )
        assert response.status_code == 200, response.json()
        view = response.json()
    return view


def post(client, view, path, **body):
    return client.post(
        f"{JOURNEYS}/{view['journey_id']}/modules/{path}",
        json={"revision": view["module_revision"], **body},
    )


def agent_of(view):
    return next(m for m in view["modules"] if m["id"] == "agent")


GOAL = {"module": "agent", "field": "goal", "value": "강의 자료로 답한다"}


def test_the_conversation_fills_the_plan_and_undo_goes_back_step_by_step():
    writer = ScriptedWriter(
        ModuleReply(reply="목표를 채웠어요.", changes=[ModuleChange(**GOAL)], model_id="m"),
        ModuleReply(
            reply="빼는 것도 적었어요. 시작 조건은 뺄 수 없어요.",
            changes=[ModuleChange(module="agent", field="exclude", items=["음성 입력"])],
        ),
    )
    with client_with(writer) as client:
        view = finish(client)
        assert view["module_mode"] == "model"
        revision = view["revision"]

        view = post(client, view, "messages", text="에이전트는 강의 자료로 답해요").json()
        view = post(client, view, "messages", text="음성은 빼고 시작 조건도 빼 줘").json()

        assert [t["role"] for t in view["module_chat"]] == ["user", "assistant"] * 2
        assert view["module_chat"][1]["changes"] == ["에이전트 흐름 · 목표"]
        assert agent_of(view)["goal"]["text"] == "강의 자료로 답한다"
        assert [i["text"] for i in agent_of(view)["exclude"]] == ["음성 입력"]
        assert agent_of(view)["gates"]
        assert view["module_undo_count"] == 2
        # Model calls are recorded as metadata, without the text.
        assert view["revision"] == revision + 2
        assert writer.seen == [
            (0, "에이전트는 강의 자료로 답해요"),
            (2, "음성은 빼고 시작 조건도 빼 줘"),
        ]

        view = post(client, view, "undo").json()
        assert agent_of(view)["exclude"] == [] and agent_of(view)["goal"]
        view = post(client, view, "undo").json()
        assert agent_of(view)["goal"] is None
        assert view["module_undo_count"] == 0
        assert post(client, view, "undo").json()["error"]["code"] == "module_undo_empty"


def test_a_failed_reply_changes_nothing():
    with client_with(ScriptedWriter(None)) as client:
        view = finish(client)
        response = post(client, view, "messages", text="목표는 이거예요")

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "module_reply_failed"
        again = client.get(f"{JOURNEYS}/{view['journey_id']}").json()
        assert again["module_chat"] == [] and again["module_revision"] == view["module_revision"]


def test_without_a_model_the_plan_is_edited_with_forms():
    with client_with() as client:
        view = finish(client)
        assert view["module_mode"] == "form"
        assert post(client, view, "messages", text="안녕").status_code == 409

        view = post(client, view, "edits", change=GOAL).json()
        assert agent_of(view)["goal"]["text"] == "강의 자료로 답한다"

        bad = {"module": "agent", "field": "target", "criterion": "답변 응답 시간", "value": "빨리"}
        response = post(client, view, "edits", change=bad)
        assert response.status_code == 422
        assert "정할 값으로 남겨 뒀어요" in response.json()["error"]["message"]

        stale = client.post(
            f"{JOURNEYS}/{view['journey_id']}/modules/edits",
            json={"revision": view["module_revision"] - 1, "change": GOAL},
        )
        assert stale.json()["error"]["code"] == "stale_revision"


def test_the_plan_cannot_be_filled_before_every_decision_is_made():
    with client_with() as client:
        view = client.post(JOURNEYS, json=SPEC).json()
        assert view["module_mode"] == "closed"
        response = post(client, view, "edits", change=GOAL)
        assert response.json()["error"]["code"] == "modules_closed"


@pytest.mark.parametrize("text", ["", "가" * 2001])
def test_a_message_must_have_text_within_the_limit(text):
    with client_with(ScriptedWriter()) as client:
        view = finish(client)
        assert post(client, view, "messages", text=text).status_code == 422
