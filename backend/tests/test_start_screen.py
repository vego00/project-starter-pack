"""Start screen (ADR-023): chat fills what was said, picks and defaults fill the rest."""

import httpx
import pytest
from app.config import Settings
from app.journey.services import (
    GcbPick,
    GcbRecommendation,
    JourneyDeps,
    StartFailure,
    StartReply,
    describe_failure,
)
from app.journey.start import (
    NOTHING,
    StartChange,
    StartValue,
    answer_text,
    apply_start_changes,
    asked_field,
    fill_defaults,
    missing,
    to_spec,
)
from app.main import create_app
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

JOURNEYS = "/api/v1/journeys"
IDEA = "부트캠프 수강생 30명이 강의 자료에서 출처와 함께 답을 찾는 챗봇"
SAID = "우리 반 30명이 쓰고 문서에서 답을 찾아요. 수강생이 답을 찾는 상태면 돼요"


def change(field, value="", values=(), evidence=""):
    return StartChange(field=field, value=value, values=list(values), evidence=evidence)


def test_only_listed_choices_and_short_free_text_are_kept():
    fields, applied, rejected = apply_start_changes(
        {},
        [
            change("deployment_target", "small_group", evidence="우리 반"),
            change("has_gpu", "maybe", evidence="우리 반"),
            change("expected_users", "30명", evidence="30명"),
            change("data_traits", values=["문서 검색 필요"] * 2, evidence="문서에서 답을 찾아요"),
            change("data_traits_extra", "x", evidence="우리 반"),
            change("goal", "  수강생이   답을 찾는 상태 ", evidence="수강생이 답을 찾는 상태"),
        ],
        "said",
        message=SAID,
    )

    assert fields["deployment_target"].value == "small_group"
    assert fields["expected_users"].value == "30명"
    assert fields["data_traits"].value == ["문서 검색 필요"]
    assert fields["goal"].value == "수강생이 답을 찾는 상태"
    assert "has_gpu" not in fields
    assert applied == ["배포 범위", "사용자 수", "다루는 데이터", "목표"]
    assert len(rejected) == 2


def test_a_value_read_from_the_message_shows_its_words_and_unquoted_ones_are_dropped():
    fields, applied, rejected = apply_start_changes(
        {},
        [
            change("deployment_target", "small_group", evidence="  우리   반 "),
            change("context", "팀이 쓴다", evidence="팀원에게 공유"),
            change("boundary", "출처를 표시한다"),
        ],
        "said",
        message=SAID,
    )

    assert fields["deployment_target"].why == "‘우리 반’에서 읽었어요."
    assert applied == ["배포 범위"]
    assert rejected == [
        "상황: 문장에서 근거를 찾지 못해 채우지 않았어요.",
        "기준: 문장에서 근거를 찾지 못해 채우지 않았어요.",
    ]


def test_a_person_picking_a_value_needs_no_quote():
    fields, applied, _ = apply_start_changes({}, [change("has_gpu", "no")], "picked")

    assert fields["has_gpu"].why is None and applied == ["GPU 장비"]


def test_a_focused_field_is_the_only_one_that_moves():
    fields, applied, _ = apply_start_changes(
        {},
        [change("has_gpu", "yes", evidence="GPU는 있어요"), change("budget", "무료로만")],
        "said",
        focus="has_gpu",
        message="GPU는 있어요",
    )

    assert set(fields) == {"has_gpu"} and applied == ["GPU 장비"]


def test_defaults_fill_only_blank_signals_and_name_their_reason():
    said = {"has_gpu": StartValue(value="yes", source="said")}

    fields, labels = fill_defaults(said)

    assert fields["has_gpu"].value == "yes"
    assert fields["deployment_target"].value == "small_group"
    assert fields["deployment_target"].source == "default"
    assert fields["data_traits"].value == ["특별한 것 없음"]
    assert all(fields[name].why for name in fields if name != "has_gpu")
    assert "GPU 장비" not in labels
    assert missing(fields) == ["goal", "context", "boundary"]


def test_the_start_action_turns_picks_into_project_signals():
    fields, _ = fill_defaults(
        {
            "goal": StartValue(value="답을 찾는 상태", source="said"),
            "boundary": StartValue(value=NOTHING, source="recommended", why="x"),
            "team_size": StartValue(value="2", source="picked"),
        }
    )

    action = to_spec(fields)

    assert action["goal"] == "답을 찾는 상태" and action["boundary"] == ""
    assert action["answers"]["has_gpu"] is False
    assert action["answers"]["team_size"] == 2
    assert action["answers"]["expected_users"] == "10명 이하"
    assert action["answers"]["deployment_target"] == "small_group"


class ScriptedStart:
    def __init__(self, *replies, picks=None):
        self.replies = list(replies)
        self.picks = picks
        self.seen = []

    def write(self, current, chat, message, focus):
        self.seen.append((message, focus, len(chat)))
        return self.replies.pop(0)

    def recommend_gcb(self, current, chat, blank):
        return self.picks


def client_with(writer=None):
    deps = JourneyDeps(start_writer=writer)
    app = create_app(Settings(_env_file=None), checkpointer=InMemorySaver(), deps=deps)
    return TestClient(app, raise_server_exceptions=False)


def post(client, view, path, **body):
    return client.post(
        f"{JOURNEYS}/{view['journey_id']}/start/{path}",
        json={"revision": view["start"]["revision"], **body},
    )


def value_of(view, name):
    return next(f for f in view["start"]["fields"] if f["name"] == name)


FIRST = StartReply(
    changes=[
        change("goal", "수강생이 출처와 함께 답을 찾는 상태", evidence="출처와 함께 답을 찾는"),
        change("deployment_target", "small_group", evidence="부트캠프 수강생"),
        change("expected_users", "30명", evidence="30명"),
    ],
    model_id="m",
)


def test_the_idea_fills_fields_and_the_chat_goes_on_until_the_journey_starts():
    writer = ScriptedStart(
        FIRST,
        StartReply(
            changes=[change("has_gpu", "no", evidence="GPU는 없어요"), change("budget", "무료로만")]
        ),
        picks=GcbRecommendation(
            picks=[GcbPick(field="boundary", value="답마다 출처를 표시한다", why="목표에서")]
        ),
    )
    with client_with(writer) as client:
        view = client.post(JOURNEYS, json={"idea": IDEA}).json()
        start = view["start"]
        assert start["mode"] == "model"
        assert [t["role"] for t in start["chat"]] == ["user", "assistant"]
        assert start["chat"][1]["changes"] == [
            "목표",
            "배포 범위",
            "사용자 수",
        ]
        assert value_of(view, "deployment_target")["display"] == "소수 사용자"
        assert value_of(view, "deployment_target")["source"] == "said"
        assert value_of(view, "has_gpu")["rule_read"] is True

        # In focus only GPU may change, though the model also sent a budget.
        view = post(client, view, "messages", text="GPU는 없어요", focus="has_gpu").json()
        assert writer.seen[-1] == ("GPU는 없어요", "has_gpu", 2)
        assert value_of(view, "has_gpu")["value"] == "no"
        assert value_of(view, "budget")["value"] is None
        assert view["start"]["chat"][-1]["text"].startswith("GPU 장비를 고쳤어요.")

        view = post(client, view, "edits", change={"field": "team_size", "value": "2~3명"}).json()
        assert value_of(view, "team_size")["source"] == "picked"

        view = post(client, view, "fill").json()
        assert value_of(view, "boundary")["source"] == "recommended"
        assert value_of(view, "boundary")["why"] == "목표에서"
        assert value_of(view, "context")["value"] == NOTHING
        assert value_of(view, "budget")["source"] == "default"
        assert view["start"]["missing"] == []

        submit = view["start"]["submit"]
        started = client.post(
            f"{JOURNEYS}/{view['journey_id']}/decisions",
            json={"revision": view["revision"], "action": submit},
        ).json()
        assert started["start"] is None
        assert started["prompt"]["type"] == "decision"
        assert post(client, view, "fill").json()["error"]["code"] == "start_closed"


def test_a_tapped_answer_stays_in_the_chat_and_the_next_question_offers_its_choices():
    # Only one scripted reply: a tapped answer must not call the model.
    with client_with(ScriptedStart(FIRST)) as client:
        view = client.post(JOURNEYS, json={"idea": IDEA}).json()
        # FIRST filled the goal and the deployment target, so the reply asks about the GPU.
        assert view["start"]["chat"][-1]["asks"] == "has_gpu"
        assert value_of(view, "has_gpu")["default"] == "no"
        assert value_of(view, "data_traits")["default"] == ["특별한 것 없음"]

        view = post(client, view, "answers", change={"field": "has_gpu", "value": "yes"}).json()
        said, reply = view["start"]["chat"][-2:]
        assert (said["role"], said["text"], said["picked"]) == ("user", "있어요", True)
        assert reply["text"].startswith("GPU 장비를 정했어요.")
        assert reply["changes"] == ["GPU 장비"]
        assert reply["asks"] == "data_traits"
        assert value_of(view, "has_gpu")["source"] == "picked"

        values = ["문서 검색 필요", "개인정보 포함"]
        view = post(client, view, "answers", change={"field": "data_traits", "values": values})
        assert view.json()["start"]["chat"][-2]["text"] == "문서 검색 필요, 개인정보 포함"

        bad = post(client, view.json(), "answers", change={"field": "has_gpu", "value": "maybe"})
        assert bad.status_code == 422


def test_a_failed_reply_changes_nothing_and_says_why():
    timeout = StartFailure(
        reason="모델이 제한 시간 안에 답하지 않았어요. 잠시 후 다시 보내 주세요."
    )
    with client_with(ScriptedStart(FIRST, timeout)) as client:
        view = client.post(JOURNEYS, json={"idea": IDEA}).json()
        response = post(client, view, "messages", text="GPU는 없어요")

        assert response.status_code == 503
        assert response.json()["error"]["message"] == timeout.reason
        again = client.get(f"{JOURNEYS}/{view['journey_id']}").json()
        assert again["start"]["revision"] == view["start"]["revision"]
        assert len(again["start"]["chat"]) == 2


def test_a_failed_first_reading_says_why_in_the_chat():
    failure = StartFailure(reason="모델 호출 한도에 걸렸어요(HTTP 429). 잠시 후 다시 보내 주세요.")
    with client_with(ScriptedStart(failure)) as client:
        view = client.post(JOURNEYS, json={"idea": IDEA}).json()

        answer = view["start"]["chat"][1]["text"]
        assert answer.startswith(failure.reason) and "직접 채워도" in answer


def json_error():
    try:
        StartReply.model_validate_json("not json")
    except Exception as exc:  # noqa: BLE001 - only the exception object is needed
        return exc


def _status_error(status):
    request = httpx.Request("POST", "https://model.example/v1")
    return httpx.HTTPStatusError("x", request=request, response=httpx.Response(status))


@pytest.mark.parametrize(
    ("exc", "says"),
    [
        (httpx.ReadTimeout("x"), "제한 시간"),
        (json_error(), "형식(JSON)"),
        (_status_error(429), "HTTP 429"),
        (_status_error(401), "키가 거부"),
        (_status_error(503), "서버에 오류"),
        (_status_error(400), "HTTP 400"),
        (httpx.ConnectError("x"), "연결하지 못했어요"),
        (RuntimeError("x"), "RuntimeError"),
    ],
)
def test_each_failure_is_named(exc, says):
    assert says in describe_failure(exc)


def test_without_a_model_the_fields_are_picked_and_blanks_become_defaults():
    with client_with() as client:
        view = client.post(JOURNEYS, json={"idea": IDEA}).json()
        assert view["start"]["mode"] == "form"
        assert [t["role"] for t in view["start"]["chat"]] == ["user"]
        assert post(client, view, "messages", text="안녕").status_code == 409

        bad = post(client, view, "edits", change={"field": "has_gpu", "value": "maybe"})
        assert bad.status_code == 422

        view = post(client, view, "fill").json()
        assert value_of(view, "goal")["value"] == NOTHING
        assert view["start"]["missing"] == []
        stale = client.post(
            f"{JOURNEYS}/{view['journey_id']}/start/fill",
            json={"revision": view["start"]["revision"] - 1},
        )
        assert stale.json()["error"]["code"] == "stale_revision"


@pytest.mark.parametrize("focus", ["nope", "x" * 41])
def test_focus_must_name_a_field(focus):
    with client_with(ScriptedStart(FIRST)) as client:
        view = client.post(JOURNEYS, json={"idea": IDEA}).json()
        assert post(client, view, "messages", text="안녕", focus=focus).status_code == 422


def said(value):
    return StartValue(value=value, source="said")


def test_the_bot_asks_the_rule_fields_first_without_offering_to_fill():
    current = {"goal": said("답을 찾는 상태"), "deployment_target": said("public_service")}

    assert asked_field(current) == "has_gpu"
    assert answer_text("deployment_target", current) == (
        "배포 범위를 정했어요. 모델을 직접 실행할 GPU 장비가 있나요?"
    )


def test_once_rules_are_set_it_offers_to_fill_and_keeps_asking_the_rest():
    current = {
        "goal": said("답을 찾는 상태"),
        "deployment_target": said("public_service"),
        "has_gpu": said("yes"),
        "data_traits": said(["특별한 것 없음"]),
    }

    assert asked_field(current) == "context"
    assert answer_text("data_traits", current) == (
        "다루는 데이터를 정했어요. 남은 7칸은 '빈칸은 알아서 채워 주세요'로 한 번에 "
        "채울 수도 있어요. 누가 어떤 상황에서 쓰는 서비스인가요?"
    )

    for name in ("context", "boundary", "expected_users", "team_size", "duration_weeks"):
        current[name] = said("값")
    assert asked_field(current) == "weekly_hours"
    current["weekly_hours"] = said("값")
    assert asked_field(current) == "budget"
    current["budget"] = said("값")
    assert asked_field(current) is None
    assert answer_text("budget", current).endswith("모두 채웠어요. 결정을 시작할 수 있어요.")


def test_asking_in_words_fills_the_blanks_like_the_button():
    writer = ScriptedStart(
        FIRST,
        StartReply(action="fill"),
        picks=GcbRecommendation(
            picks=[GcbPick(field="boundary", value="답마다 출처를 표시한다", why="목표에서")]
        ),
    )
    with client_with(writer) as client:
        view = client.post(JOURNEYS, json={"idea": IDEA}).json()
        view = post(client, view, "messages", text="알아서 채워봐").json()

        answer = view["start"]["chat"][-1]
        assert answer["text"].startswith("빈칸 ")
        assert "기준" in answer["changes"] and "GPU 장비" in answer["changes"]
        assert value_of(view, "boundary")["source"] == "recommended"
        assert value_of(view, "has_gpu")["source"] == "default"
        assert view["start"]["missing"] == []
