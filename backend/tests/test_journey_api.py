from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from app.config import Settings
from app.journey.services import JourneyDeps, MockResponder
from app.main import create_app
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

JOURNEYS = "/api/v1/journeys"
IDEA = "민감한고객문의내용을 처리하는 멀티 에이전트 서비스"
SPEC = {
    "idea": IDEA,
    "team_size": 4,
    "duration_weeks": 8,
    "budget": "월 5만원",
    "expected_users": 20,
    "weekly_hours": 20,
    "data_traits": ["문서 검색"],
    "deployment_target": "small_group",
}


def make_client(deps=None):
    app = create_app(Settings(_env_file=None), checkpointer=InMemorySaver(), deps=deps)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client():
    with make_client() as client:
        yield client


def start(client, spec=SPEC):
    response = client.post(JOURNEYS, json=spec)
    assert response.status_code == 201
    return response.json()


def act(client, view, **action):
    return client.post(
        f"{JOURNEYS}/{view['journey_id']}/decisions",
        json={"revision": view["revision"], "action": action},
    )


def select(client, view, option_id):
    response = act(client, view, action="select", option_id=option_id)
    assert response.status_code == 200
    return response.json()


def error_code(response):
    return response.json()["error"]["code"]


def test_full_journey_through_the_api(client):
    view = start(client)
    seen = []
    while view["prompt"]:
        card = view["prompt"]["card"]
        seen.append(card["card_id"])
        view = select(client, view, card["recommendation"]["option_id"])

    assert len(seen) == 7
    assert view["status"] == "completed"
    assert {card["state"] for card in view["cards"]} == {"decided"}
    assert all(card["option_name"] for card in view["cards"])


def test_view_is_labelled_as_mock_and_lists_cards_in_order(client):
    view = start(client)

    assert "모델 미연결" in view["notice"]
    assert view["idea"] == IDEA
    assert [card["layer"] for card in view["cards"]] == [
        "agent",
        "model",
        "data",
        "backend",
        "devops",
        "mlops",
        "cloud",
    ]
    assert view["cards"][0]["state"] == "current"
    assert view["cards"][1]["state"] == "pending"


def test_get_returns_the_same_prompt_without_advancing(client):
    view = start(client)

    fetched = client.get(f"{JOURNEYS}/{view['journey_id']}").json()

    assert fetched == view


def test_journey_survives_a_new_service_with_the_same_checkpointer():
    saver = InMemorySaver()
    settings = Settings(_env_file=None)
    with TestClient(create_app(settings, checkpointer=saver)) as first:
        view = select(first, start(first), "question")
    with TestClient(create_app(settings, checkpointer=saver)) as second:
        resumed = second.get(f"{JOURNEYS}/{view['journey_id']}").json()

    assert resumed == view
    assert resumed["prompt"]["card"]["card_id"] == "model.provider"


# Clarify
def test_clarify_answers_including_skipping_all_of_them(client):
    view = start(client, {"idea": IDEA})
    assert view["prompt"]["type"] == "clarify"

    response = act(client, view, action="clarify", answers={"deployment_target": "local_demo"})
    view = response.json()
    assert view["prompt"]["round"] == 2

    view = act(client, view, action="clarify", answers={}).json()
    assert view["prompt"]["type"] == "decision"


# Duplicate and stale submissions
def test_double_submit_cannot_decide_the_next_card(client):
    view = start(client)
    assert select(client, view, "none")["prompt"]["card"]["card_id"] == "model.provider"

    repeated = act(client, view, action="select", option_id="none")

    assert repeated.status_code == 409
    assert error_code(repeated) == "stale_revision"
    current = client.get(f"{JOURNEYS}/{view['journey_id']}").json()
    assert current["cards"][1]["state"] == "current"


def test_concurrent_submits_apply_exactly_once(client):
    view = start(client)
    barrier = Barrier(2)

    def submit(_):
        barrier.wait()
        return act(client, view, action="select", option_id="none").status_code

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(submit, range(2)))

    assert codes == [200, 409]


# Wrong action for the step
def test_actions_must_match_the_current_prompt(client):
    clarifying = start(client, {"idea": IDEA})
    response = act(client, clarifying, action="select", option_id="none")
    assert (response.status_code, error_code(response)) == (409, "action_not_allowed")
    assert client.get(f"{JOURNEYS}/{clarifying['journey_id']}").json() == clarifying

    deciding = start(client)
    response = act(client, deciding, action="clarify", answers={})
    assert error_code(response) == "action_not_allowed"


def test_finished_journey_rejects_actions(client):
    view = start(client)
    while view["prompt"]:
        view = select(client, view, view["prompt"]["card"]["recommendation"]["option_id"])

    response = act(client, view, action="defer")

    assert (response.status_code, error_code(response)) == (409, "journey_finished")


# Gate-level rejection stays on the card with a message
def test_unknown_option_is_explained_on_the_same_card(client):
    view = start(client)

    next_view = select(client, view, "missing")

    assert next_view["prompt"]["card"]["card_id"] == "agent.hitl"
    assert next_view["prompt"]["error"]


def test_issue_flow_through_the_api(client):
    view = start(client)
    for option_id in ("none", "gemini", "postgres", "sync", "none", "external_api"):
        view = select(client, view, option_id)
    view = act(client, view, action="reopen", card_id="model.provider").json()
    view = select(client, view, "ollama")
    view = select(client, view, "local")

    assert view["status"] == "needs_fix"
    assert view["prompt"]["type"] == "issues"
    assert error_code(act(client, view, action="defer")) == "action_not_allowed"

    view = act(client, view, action="reopen", card_id="mlops.model_serving").json()

    assert view["status"] == "completed"
    implied = next(c for c in view["cards"] if c["card_id"] == "mlops.model_serving")
    assert (implied["state"], implied["by"]) == ("implied", "implied")
    assert implied["rationale"]


def test_warnings_are_listed_on_the_finished_journey(client):
    view = start(client)
    for option_id in ("none", "gemini", "postgres", "sync", "none", "ollama", "gcp"):
        view = select(client, view, option_id)

    assert view["status"] == "completed"
    assert len(view["warnings"]) == 1


# Summary document
def finish(client, spec=SPEC):
    view = start(client, spec)
    if view["prompt"]["type"] == "clarify":
        view = act(client, view, action="clarify", answers={}).json()
        view = act(client, view, action="clarify", answers={}).json()
    while view["prompt"]:
        view = select(client, view, view["prompt"]["card"]["recommendation"]["option_id"])
    return view


def test_summary_downloads_as_markdown_once_finished(client):
    view = finish(client)

    response = client.get(f"{JOURNEYS}/{view['journey_id']}/summary.md")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.text.startswith("# 프로젝트 결정 요약")


def test_summary_is_unavailable_before_finishing(client):
    view = start(client)

    response = client.get(f"{JOURNEYS}/{view['journey_id']}/summary.md")

    assert (response.status_code, error_code(response)) == (409, "summary_unavailable")


def test_summary_of_unknown_journey_is_not_found(client):
    assert client.get(f"{JOURNEYS}/{uuid4()}/summary.md").status_code == 404


def test_summary_is_rewritten_after_an_issue_is_fixed(client):
    view = start(client)
    for option_id in ("none", "gemini", "postgres", "sync", "none", "external_api"):
        view = select(client, view, option_id)
    view = act(client, view, action="reopen", card_id="model.provider").json()
    view = select(client, select(client, view, "ollama"), "local")
    url = f"{JOURNEYS}/{view['journey_id']}/summary.md"
    assert client.get(url).status_code == 409

    act(client, view, action="reopen", card_id="mlops.model_serving")

    assert "Ollama 컨테이너 (규칙으로 자동 확정)" in client.get(url).text


# Errors
@pytest.mark.parametrize(
    "spec",
    [{"idea": "짧음"}, {"idea": f"{IDEA}{'가' * 3000}"}, {}, {**SPEC, "team_size": 0}],
)
def test_invalid_spec_is_rejected_without_echoing_input(client, spec):
    response = client.post(JOURNEYS, json=spec)

    assert (response.status_code, error_code(response)) == (422, "invalid_input")
    assert "민감한" not in response.text


def test_malformed_json_is_safe(client):
    response = client.post(
        JOURNEYS, content="{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "action",
    [{"action": "explode"}, {"action": "ask", "question": " "}, {"action": "select"}],
)
def test_malformed_action_is_rejected(client, action):
    view = start(client)

    response = client.post(
        f"{JOURNEYS}/{view['journey_id']}/decisions",
        json={"revision": view["revision"], "action": action},
    )

    assert response.status_code == 422


def test_unknown_and_malformed_ids(client):
    response = client.get(f"{JOURNEYS}/{uuid4()}")
    assert (response.status_code, error_code(response)) == (404, "journey_not_found")
    assert client.get(f"{JOURNEYS}/not-a-uuid").status_code == 422

    missing = client.post(
        f"{JOURNEYS}/{uuid4()}/decisions", json={"revision": 0, "action": {"action": "defer"}}
    )
    assert missing.status_code == 404


def test_without_a_database_journeys_report_unavailable():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.post(JOURNEYS, json=SPEC)

    assert (response.status_code, error_code(response)) == (503, "persistence_unavailable")


class FlakyResponder(MockResponder):
    def __init__(self):
        self.failures = 1

    def answer(self, state, card, question):
        if self.failures:
            self.failures -= 1
            raise RuntimeError(f"provider echoed {question}")
        return super().answer(state, card, question)


def test_failed_step_is_safe_then_recovers_on_next_read(caplog):
    with make_client(JourneyDeps(responder=FlakyResponder())) as client:
        view = start(client)

        failed = act(client, view, action="ask", question="민감한질문내용")
        assert (failed.status_code, error_code(failed)) == (503, "journey_failed")
        assert "민감한" not in failed.text
        assert "민감한" not in caplog.text

        recovered = client.get(f"{JOURNEYS}/{view['journey_id']}").json()

    assert recovered["prompt"]["card"]["card_id"] == "agent.hitl"
    assert recovered["prompt"]["qa"][0]["question"] == "민감한질문내용"
