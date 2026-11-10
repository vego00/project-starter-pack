"""The workspace journey: moving between cards, reviewing later stages, the live graph, saving edits."""

import io
import zipfile
from uuid import UUID

import pytest
from app.config import Settings
from app.journey.constraints import displaced
from app.journey.design import DesignState, ServiceDesign
from app.journey.design_constraints import derive_design_constraints
from app.journey.design_edit import DesignEdit, apply_design_edit, keep_human_edits
from app.journey.state import JourneyState
from app.main import create_app
from app.registry.loader import load_registry
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

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


@pytest.fixture
def client():
    app = create_app(
        Settings(_env_file=None), checkpointer=InMemorySaver(), registry=load_registry()
    )
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def start(client):
    response = client.post(JOURNEYS, json=SPEC)
    assert response.status_code == 201
    return response.json()


def act(client, view, **action):
    return client.post(
        f"{JOURNEYS}/{view['journey_id']}/decisions",
        json={"revision": view["revision"], "action": action},
    )


def ok(client, view, **action):
    response = act(client, view, **action)
    assert response.status_code == 200, response.text
    return response.json()


def card_of(view):
    return view["prompt"]["card"]


def recommended(card):
    wanted = card["recommendation"]["option_id"]
    return wanted or next(o["option"]["id"] for o in card["options"] if not o["blocked_reason"])


def decide_all(client, view):
    while view["prompt"] and view["prompt"]["type"] == "decision":
        view = ok(client, view, action="select", option_id=recommended(card_of(view)))
    return view


def status(view, card_id):
    return next(card for card in view["cards"] if card["card_id"] == card_id)


def design_of(client, view):
    response = client.get(f"{JOURNEYS}/{view['journey_id']}/design")
    assert response.status_code == 200
    return response.json()


def edit_body(design, **changes):
    return {
        "design_revision": design["design_revision"],
        "nodes": design["nodes"],
        "workflow": design["workflow"],
        **changes,
    }


def save(client, view, body):
    return client.post(f"{JOURNEYS}/{view['journey_id']}/design", json=body)


def test_cards_carry_their_stage_and_are_asked_stage_first(client):
    view = start(client)

    assert status(view, "product.surface")["stage"] == 3
    assert status(view, "agent.topology")["stage"] == 4
    assert status(view, "cloud.target")["stage"] == 5
    assert status(view, "ops.tracing")["stage"] == 6
    assert card_of(view)["card_id"] == "product.surface"


def test_focus_moves_to_an_open_card_and_decides_it_out_of_order(client):
    view = start(client)

    view = ok(client, view, action="focus", card_id="ops.tracing")
    assert card_of(view)["card_id"] == "ops.tracing"

    view = ok(client, view, action="select", option_id="logs")
    assert status(view, "ops.tracing")["state"] == "decided"
    assert card_of(view)["card_id"] == "product.surface"


def test_focus_on_a_card_that_is_not_open_is_explained_on_the_same_card(client):
    view = start(client)
    first = card_of(view)["card_id"]
    view = ok(client, view, action="select", option_id=recommended(card_of(view)))

    view = ok(client, view, action="focus", card_id=first)

    assert view["prompt"]["error"]
    assert card_of(view)["card_id"] != first


def changed_early_stage(client):
    """A finished journey whose product surface then changed to another option."""
    view = decide_all(client, start(client))
    before = status(view, "product.surface")["option_name"]
    view = ok(client, view, action="reopen", card_id="product.surface")
    card = card_of(view)
    assert card["card_id"] == "product.surface"
    other = next(
        o["option"]["id"]
        for o in card["options"]
        if o["option"]["name"] != before and not o["blocked_reason"]
    )
    return decide_all(client, ok(client, view, action="select", option_id=other))


def test_changing_an_earlier_stage_flags_later_decisions(client):
    view = changed_early_stage(client)

    assert status(view, "agent.topology")["needs_review"] is True
    assert status(view, "product.surface")["needs_review"] is False


def test_choosing_the_same_option_again_flags_nothing(client):
    view = decide_all(client, start(client))
    view = ok(client, view, action="reopen", card_id="product.surface")
    view = ok(client, view, action="select", option_id=recommended(card_of(view)))
    view = decide_all(client, view)

    assert not any(card["needs_review"] for card in view["cards"])


def test_keeping_a_decision_clears_the_flag_without_redoing_the_design(client):
    view = changed_early_stage(client)
    generated_at = design_of(client, view)["provenance"]["generated_at"]

    view = ok(client, view, action="keep", card_id="agent.topology")

    assert status(view, "agent.topology")["needs_review"] is False
    assert design_of(client, view)["provenance"]["generated_at"] == generated_at


def test_keep_needs_a_flagged_card(client):
    view = decide_all(client, start(client))

    response = act(client, view, action="keep", card_id="agent.topology")

    assert response.status_code == 200
    assert not any(card["needs_review"] for card in response.json()["cards"])


def blanks(graph):
    return [node for node in graph["nodes"] if node["kind"] == "blank"]


def test_blueprint_starts_with_blanks_and_fills_as_cards_are_decided(client):
    view = start(client)
    assert any(node["card_id"] == "model.provider" for node in blanks(view["blueprint"]["system"]))
    assert view["blueprint"]["agent_is_draft"] is True

    view = decide_all(client, view)

    assert blanks(view["blueprint"]["system"]) == []
    assert blanks(view["blueprint"]["agent"]) == []
    assert view["blueprint"]["agent_is_draft"] is False


def test_blueprint_draws_the_chosen_option(client):
    view = start(client)
    view = ok(client, view, action="focus", card_id="ops.tracing")
    view = ok(client, view, action="select", option_id="langsmith")

    labels = [node["label"] for node in view["blueprint"]["system"]["nodes"]]
    assert "LangSmith 연결" in labels


def test_blueprint_edges_point_at_drawn_nodes(client):
    view = decide_all(client, start(client))
    for graph in (view["blueprint"]["agent"], view["blueprint"]["system"]):
        ids = {node["id"] for node in graph["nodes"]}
        assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])


def test_examples_are_complete_graphs(client):
    response = client.get("/api/v1/blueprint/examples")

    assert response.status_code == 200
    examples = response.json()
    assert len(examples) == 3
    for example in examples:
        assert blanks(example["blueprint"]["system"]) == []
        assert blanks(example["blueprint"]["agent"]) == []


def test_saving_an_edit_makes_a_new_revision_the_package_follows(client):
    view = decide_all(client, start(client))
    design = design_of(client, view)
    node = {**design["nodes"][0], "responsibility": "사람이 고친 책임 설명이에요"}

    response = save(client, view, edit_body(design, nodes=[node, *design["nodes"][1:]]))

    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["design_revision"] == design["design_revision"] + 1
    assert saved["change_requests"][-1]["to_revision"] == saved["design_revision"]
    assert design_of(client, view)["nodes"][0]["responsibility"] == node["responsibility"]

    archive = client.get(f"{JOURNEYS}/{view['journey_id']}/package.zip")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as package:
        text = package.read("starter-pack/docs/multi-agent-design.md").decode("utf-8")
    assert node["responsibility"] in text


def test_a_journey_can_still_change_a_decision_after_saving(client):
    view = decide_all(client, start(client))
    design = design_of(client, view)
    assert save(client, view, edit_body(design)).status_code == 200

    view = client.get(f"{JOURNEYS}/{view['journey_id']}").json()
    assert view["can_reopen"] is True
    view = ok(client, view, action="reopen", card_id="cloud.target")
    assert card_of(view)["card_id"] == "cloud.target"


def test_saving_keeps_fields_the_screen_does_not_send(client):
    view = decide_all(client, start(client))
    design = design_of(client, view)
    trimmed = [{k: v for k, v in node.items() if k != "eval_case_ids"} for node in design["nodes"]]

    saved = save(client, view, edit_body(design, nodes=trimmed)).json()

    assert [n["eval_case_ids"] for n in saved["nodes"]] == [
        n["eval_case_ids"] for n in design["nodes"]
    ]


def test_a_stale_edit_is_refused(client):
    view = decide_all(client, start(client))
    design = design_of(client, view)
    assert save(client, view, edit_body(design)).status_code == 200

    response = save(client, view, edit_body(design))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stale_design"


def test_an_edit_that_breaks_the_design_is_refused_with_the_reason(client):
    view = decide_all(client, start(client))
    design = design_of(client, view)
    workflow = {**design["workflow"], "entry": "no-such-node"}

    response = save(client, view, edit_body(design, workflow=workflow))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "design_has_errors"
    assert error["message"]
    assert design_of(client, view)["design_revision"] == design["design_revision"]


def test_a_rename_carries_the_references_the_screen_does_not_hold(client):
    view = decide_all(client, start(client))
    design = design_of(client, view)
    fields = design["state_fields"]
    old = next(
        (writer for field in fields for writer in field["writers"]), design["nodes"][0]["id"]
    )
    new = "renamed-node"
    swap = lambda value: new if value == old else value  # noqa: E731
    workflow = design["workflow"]
    body = edit_body(
        design,
        nodes=[{**node, "id": swap(node["id"])} for node in design["nodes"]],
        workflow={
            **workflow,
            "entry": swap(workflow["entry"]),
            "exits": [swap(item) for item in workflow["exits"]],
            "edges": [
                {**e, "source": swap(e["source"]), "target": swap(e["target"])}
                for e in workflow["edges"]
            ],
            "loop_limits": [
                {
                    **limit,
                    "node_ids": [swap(item) for item in limit["node_ids"]],
                    "on_exceeded": swap(limit["on_exceeded"]),
                }
                for limit in workflow["loop_limits"]
            ],
        },
        requirement_nodes={
            item["id"]: [swap(node_id) for node_id in item["node_ids"]]
            for item in design["requirements"]
        },
        renames={old: new},
    )

    response = save(client, view, body)

    assert response.status_code == 200, response.text
    assert old not in {w for f in response.json()["state_fields"] for w in f["writers"]}


def test_design_cannot_be_saved_before_it_exists(client):
    view = start(client)

    response = client.post(
        f"{JOURNEYS}/{view['journey_id']}/design",
        json={
            "design_revision": 1,
            "nodes": [{"id": "a"}],
            "workflow": {"entry": "a", "exits": ["a"], "edges": []},
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "design_unavailable"


def test_only_a_chosen_service_gets_its_mark_and_every_node_has_a_box(client):
    view = start(client)
    system = view["blueprint"]["system"]
    assert all(node["group"] for node in system["nodes"])
    assert not any(node["icon"] == "googlegemini" for node in system["nodes"])

    view = ok(client, view, action="focus", card_id="model.provider")
    view = ok(client, view, action="select", option_id="gemini")

    marks = {node["id"]: node["icon"] for node in view["blueprint"]["system"]["nodes"]}
    assert marks["model"] == "googlegemini"


def reopen_with_another_option(client, view, card_id):
    view = ok(client, view, action="reopen", card_id=card_id)
    other = next(
        o["option"]["id"]
        for o in card_of(view)["options"]
        if o["option"]["id"] != recommended(card_of(view)) and not o["blocked_reason"]
    )
    return decide_all(client, ok(client, view, action="select", option_id=other))


def test_edits_survive_a_changed_decision(client):
    view = decide_all(client, start(client))
    design = design_of(client, view)
    node = {**design["nodes"][0], "responsibility": "다시 만들어도 남아야 하는 설명"}
    assert (
        save(client, view, edit_body(design, nodes=[node, *design["nodes"][1:]])).status_code == 200
    )

    view = client.get(f"{JOURNEYS}/{view['journey_id']}").json()
    view = reopen_with_another_option(client, view, "product.surface")

    assert design_of(client, view)["nodes"][0]["responsibility"] == node["responsibility"]


def carry_setup(client):
    view = decide_all(client, start(client))
    service = client.app.state.journeys
    state = JourneyState.model_validate(service._snapshot(UUID(view["journey_id"])).values)
    base = state.design.current
    return base, derive_design_constraints(state, load_registry())


def edit_of(base, **changes):
    data = base.model_dump(mode="json")
    return DesignEdit(
        design_revision=base.design_revision,
        nodes=changes.get("nodes", data["nodes"]),
        workflow=changes.get("workflow", data["workflow"]),
        renames=changes.get("renames", {}),
    )


def regenerated(base):
    return DesignState(
        status="review_required",
        current=base.model_copy(update={"design_revision": base.design_revision + 2}),
    )


def edited_state(base, edited):
    return DesignState(status="review_required", current=edited, generated=base)


def test_a_field_edit_is_put_on_the_new_design(client):
    base, constraints = carry_setup(client)
    data = base.model_dump(mode="json")
    nodes = [{**data["nodes"][0], "done_when": "사람이 정한 완료 기준"}, *data["nodes"][1:]]
    edited = apply_design_edit(base, edit_of(base, nodes=nodes), constraints)

    kept = keep_human_edits(edited_state(base, edited), regenerated(base), constraints)

    assert kept.current.nodes[0].done_when == "사람이 정한 완료 기준"
    assert kept.current.design_revision == base.design_revision + 2
    assert kept.generated.nodes[0].done_when == base.nodes[0].done_when


def test_an_added_node_comes_back_with_its_connections(client):
    base, constraints = carry_setup(client)
    data = base.model_dump(mode="json")
    first = data["workflow"]["edges"][0]
    extra = {
        "id": "human-added",
        "kind": "code",
        "responsibility": "사람이 넣은 노드",
        "inputs": [],
        "outputs": [],
        "tools": [],
        "done_when": "끝",
        "on_failure": "멈춤",
    }
    workflow = {
        **data["workflow"],
        "edges": [
            {**first, "target": "human-added"},
            {"source": "human-added", "target": first["target"], "condition": None},
            *data["workflow"]["edges"][1:],
        ],
    }
    edited = apply_design_edit(
        base, edit_of(base, nodes=[*data["nodes"], extra], workflow=workflow), constraints
    )

    kept = keep_human_edits(edited_state(base, edited), regenerated(base), constraints)

    assert "human-added" in {node.id for node in kept.current.nodes}
    targets = {(edge.source, edge.target) for edge in kept.current.workflow.edges}
    assert (first["source"], "human-added") in targets
    assert not [i for i in kept.current.validation if i.severity == "error"]


def test_an_edit_that_no_longer_fits_is_reported_not_silently_dropped(client):
    base, constraints = carry_setup(client)
    edited = base.model_copy(
        update={
            "nodes": [
                base.nodes[0].model_copy(update={"done_when": "새 설계에서 사라질 노드의 기준"}),
                *base.nodes[1:],
            ]
        }
    )
    without_first = base.nodes[0].id
    fresh = regenerated(base)
    renamed = fresh.current.model_dump(mode="json")
    swap = lambda v: "brand-new" if v == without_first else v  # noqa: E731
    renamed["nodes"][0]["id"] = "brand-new"
    renamed["workflow"]["entry"] = swap(renamed["workflow"]["entry"])
    renamed["workflow"]["exits"] = [swap(v) for v in renamed["workflow"]["exits"]]
    for e in renamed["workflow"]["edges"]:
        e["source"], e["target"] = swap(e["source"]), swap(e["target"])
    for limit in renamed["workflow"]["loop_limits"]:
        limit["node_ids"] = [swap(v) for v in limit["node_ids"]]
        limit["on_exceeded"] = swap(limit["on_exceeded"])
    for item in renamed["requirements"]:
        item["node_ids"] = [swap(v) for v in item["node_ids"]]
    for field in renamed["state_fields"]:
        field["writers"] = [swap(v) for v in field["writers"]]
        field["readers"] = [swap(v) for v in field["readers"]]
    fresh = DesignState(status="review_required", current=ServiceDesign.model_validate(renamed))

    kept = keep_human_edits(edited_state(base, edited), fresh, constraints)

    assert any(without_first in warning for warning in kept.current.warnings)


def test_a_failed_regeneration_keeps_the_edited_design(client):
    base, constraints = carry_setup(client)
    edited = base.model_copy(update={"design_revision": base.design_revision + 1})
    failed = DesignState(status="failed", current=base, error="템플릿")

    kept = keep_human_edits(edited_state(base, edited), failed, constraints)

    assert kept.status == "failed"
    assert kept.current == edited
    assert "이전 설계" in kept.error


def test_a_design_nobody_edited_is_left_alone(client):
    base, constraints = carry_setup(client)
    fresh = regenerated(base)

    previous = DesignState(status="review_required", current=base)
    assert keep_human_edits(previous, fresh, constraints) is fresh


def revise(client, view, card_id):
    return ok(client, view, action="revise", card_id=card_id)


def another_option(card, held):
    return next(
        o["option"]["id"]
        for o in card["options"]
        if o["option"]["id"] != held and not o["blocked_reason"]
    )


def test_revising_keeps_the_decision_until_another_option_is_chosen(client):
    view = ok(client, start(client), action="select", option_id="web")

    view = revise(client, view, "product.surface")

    assert card_of(view)["card_id"] == "product.surface"
    assert view["prompt"]["current_option_id"] == "web"
    surface = status(view, "product.surface")
    assert (surface["state"], surface["option_id"], surface["editing"]) == ("decided", "web", True)
    assert any(node["id"] == "surface" for node in view["blueprint"]["system"]["nodes"])

    view = ok(client, view, action="select", option_id="report")

    surface = status(view, "product.surface")
    assert (surface["option_id"], surface["editing"]) == ("report", False)


def test_cancelling_a_revision_changes_nothing(client):
    view = ok(client, start(client), action="select", option_id="web")
    following = card_of(view)["card_id"]
    decided_at = status(view, "product.surface")

    view = revise(client, view, "product.surface")
    view = ok(client, view, action="defer")

    assert card_of(view)["card_id"] == following
    assert status(view, "product.surface") == decided_at
    assert status(view, "product.surface")["state"] != "deferred"


def test_choosing_the_same_option_does_not_ask_to_review_later_ones(client):
    view = ok(client, start(client), action="select", option_id="web")
    view = ok(client, view, action="select", option_id=recommended(card_of(view)))

    view = revise(client, view, "product.surface")
    view = ok(client, view, action="select", option_id="web")

    assert not status(view, "agent.topology")["needs_review"]


def test_changing_a_revised_decision_asks_to_review_later_ones(client):
    view = ok(client, start(client), action="select", option_id="web")
    view = ok(client, view, action="select", option_id=recommended(card_of(view)))

    view = revise(client, view, "product.surface")
    view = ok(client, view, action="select", option_id="report")

    assert status(view, "agent.topology")["needs_review"]


def test_cancelling_after_the_end_returns_without_a_new_design(client):
    view = decide_all(client, start(client))
    revision = design_of(client, view)["design_revision"]

    view = revise(client, view, "product.surface")
    assert view["prompt"]["type"] == "decision"
    view = ok(client, view, action="defer")

    assert view["prompt"] is None and view["can_reopen"]
    assert view["status"] == "completed"
    assert design_of(client, view)["design_revision"] == revision


def test_the_same_option_after_the_end_keeps_the_design(client):
    view = decide_all(client, start(client))
    revision = design_of(client, view)["design_revision"]
    held = status(view, "product.surface")["option_id"]

    view = revise(client, view, "product.surface")
    view = ok(client, view, action="select", option_id=held)

    assert view["prompt"] is None and view["can_reopen"]
    assert design_of(client, view)["design_revision"] == revision


def test_another_option_after_the_end_makes_a_new_design(client):
    view = decide_all(client, start(client))
    revision = design_of(client, view)["design_revision"]
    held = status(view, "product.surface")["option_id"]

    view = revise(client, view, "product.surface")
    view = ok(client, view, action="select", option_id=another_option(card_of(view), held))
    view = decide_all(client, view)

    assert view["prompt"] is None and view["can_reopen"]
    assert design_of(client, view)["design_revision"] > revision


def test_a_card_that_was_not_decided_cannot_be_revised(client):
    view = start(client)

    view = revise(client, view, "ops.tracing")

    assert view["prompt"]["error"]
    assert card_of(view)["card_id"] == "product.surface"


def gcb_view(client):
    response = client.post(
        JOURNEYS, json={"idea": "강의 자료를 찾아 답하는 서비스를 만들고 싶어요"}
    )
    assert response.status_code == 201
    view = response.json()
    assert view["prompt"]["type"] == "gcb"
    return view


def test_the_first_screen_asks_everything_at_once(client):
    view = gcb_view(client)
    assert [q["field"] for q in view["prompt"]["questions"]]

    view = ok(
        client,
        view,
        action="gcb",
        goal="찾을 수 있는 상태",
        answers={"team_size": 3, "expected_users": "숫자가 아님"},
    )

    assert view["prompt"]["type"] == "decision"


def test_the_gcb_step_alone_still_leads_to_clarifying(client):
    view = ok(client, gcb_view(client), action="gcb", goal="찾을 수 있는 상태")

    assert view["prompt"]["type"] in ("clarify", "decision")


def test_options_carry_their_icons_before_being_chosen(client):
    view = ok(client, start(client), action="select", option_id="web")
    view = ok(client, view, action="focus", card_id="data.primary_db")

    icons = {o["option"]["id"]: o["icon"] for o in card_of(view)["options"]}

    assert icons["postgres"] == "postgresql"
    assert icons["none"] == "none"


def model_steps(client, view):
    service = client.app.state.journeys
    state = JourneyState.model_validate(service._snapshot(UUID(view["journey_id"])).values)
    return [event.node for event in state.trace if event.node in ("advisor", "recommender")]


def test_opening_a_decided_card_calls_no_model(client):
    view = ok(client, start(client), action="select", option_id="web")
    calls = model_steps(client, view)

    view = revise(client, view, "product.surface")

    assert model_steps(client, view) == calls
    assert card_of(view)["recommendation"]["option_id"] == "web"


def test_a_card_an_earlier_change_affected_is_advised_again(client):
    view = ok(client, start(client), action="select", option_id="web")
    view = ok(client, view, action="select", option_id=recommended(card_of(view)))
    view = revise(client, view, "product.surface")
    view = ok(client, view, action="select", option_id="report")
    assert status(view, "agent.topology")["needs_review"]
    calls = len(model_steps(client, view))

    view = revise(client, view, "agent.topology")

    assert len(model_steps(client, view)) == calls + 2


def test_opening_a_decided_card_after_the_end_calls_no_model(client):
    view = decide_all(client, start(client))
    calls = model_steps(client, view)

    view = revise(client, view, "product.surface")

    assert view["prompt"]["type"] == "decision"
    assert model_steps(client, view) == calls


def test_changing_an_answer_names_a_later_answer_it_contradicts():
    chosen = {"mlops.model_serving": "external_api"}

    assert displaced(load_registry(), chosen, "model.provider", "gemini", "ollama") == chosen


def test_changing_an_answer_names_an_automatic_choice_it_releases():
    assert displaced(load_registry(), {}, "model.provider", "ollama", "gemini") == {
        "mlops.model_serving": "ollama"
    }


def test_a_card_being_changed_lists_the_later_decisions_to_look_at_again(client):
    view = ok(client, start(client), action="select", option_id="web")
    assert card_of(view)["to_review"] == []
    view = ok(client, view, action="select", option_id=recommended(card_of(view)))

    view = revise(client, view, "product.surface")

    held = status(view, "agent.topology")["option_name"]
    assert card_of(view)["to_review"] == [f"Agent 구조: {held}"]


def example_blueprint(client, example_id):
    examples = client.get("/api/v1/blueprint/examples").json()
    return next(item for item in examples if item["id"] == example_id)["blueprint"]


def test_decisions_on_one_postgres_share_a_service_with_a_line_each(client):
    system = example_blueprint(client, "team")["system"]

    database = next(node for node in system["nodes"] if node["id"] == "database")

    assert [row["card_id"] for row in database["rows"]] == [
        "data.primary_db",
        "data.checkpointer",
        "data.vector_store",
    ]
    assert not {"checkpoint", "search"} & {node["id"] for node in system["nodes"]}
    assert [edge for edge in system["edges"] if edge["target"] == "database"] == [
        {"source": "runner", "target": "database", "label": None, "dashed": False}
    ]


def test_a_service_answering_one_decision_stays_a_plain_node(client):
    system = example_blueprint(client, "private")["system"]

    assert not any(node["rows"] for node in system["nodes"])
    assert {"database", "search"} <= {node["id"] for node in system["nodes"]}


@pytest.mark.parametrize(
    ("example_id", "expected"),
    [
        ("basic", {"mlops.model_serving", "data.vector_store", "backend.execution"}),
        ("private", {"data.checkpointer"}),
        ("team", {"mlops.model_serving"}),
    ],
)
def test_an_answer_that_draws_no_service_stays_reachable(client, example_id, expected):
    notes = example_blueprint(client, example_id)["notes"]

    assert {note["card_id"] for note in notes} == expected


def test_every_decision_on_the_system_graph_has_somewhere_to_press(client):
    view = decide_all(client, start(client))
    blueprint = view["blueprint"]

    reachable = {note["card_id"] for note in blueprint["notes"]}
    for node in blueprint["system"]["nodes"]:
        reachable |= {row["card_id"] for row in node["rows"]} | {node["card_id"]}

    decided = {
        card["card_id"]
        for card in view["cards"]
        if card["state"] in ("decided", "implied") and card["layer"] != "agent"
    }
    assert decided <= reachable
