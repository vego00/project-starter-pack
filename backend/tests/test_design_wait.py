"""The last answer comes back before the design; `design` makes it (작성자 결정 2026-11-25)."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import perf_counter, sleep

import app.journey.nodes as nodes
from tests.test_design_pipeline import IDEA, ScriptedDesigner, draft, make_client

JOURNEYS = "/api/v1/journeys"


class HeldDesigner(ScriptedDesigner):
    """Counts drafts; while `release` is clear, a draft waits inside the model."""

    def __init__(self, *outputs, delay=0.0):
        super().__init__(*outputs)
        self.calls = 0
        self.delay = delay
        self.entered = Event()
        self.release = Event()
        self.release.set()

    def draft(self, state, constraints, problems):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(10)
        sleep(self.delay)
        return super().draft(state, constraints, problems)


def post(client, view, **action):
    return client.post(
        f"{JOURNEYS}/{view['journey_id']}/decisions",
        json={"revision": view["revision"], "action": action},
    )


def to_designing(client):
    """Answers every card and returns the last answer's view and how long it took."""
    view = client.post(JOURNEYS, json={"idea": IDEA}).json()
    elapsed = 0.0
    for _ in range(60):
        prompt = view["prompt"]
        if prompt["type"] == "designing":
            return view, elapsed
        if prompt["type"] == "gcb":
            action = {
                "action": "gcb",
                "goal": "답을 찾을 수 있는 상태",
                "context": "",
                "boundary": "",
            }
        elif prompt["type"] == "clarify":
            action = {"action": "clarify", "answers": {}}
        elif prompt["type"] == "fork":
            action = {"action": "plan_deploy"}
        elif prompt["card"]["preparing"]:
            action = {"action": "prepare"}
        else:
            action = {"action": "accept_recommendation"}
        started = perf_counter()
        response = post(client, view, **action)
        elapsed = perf_counter() - started
        assert response.status_code == 200, response.text
        view = response.json()
    raise AssertionError("never reached the design")


def held_design(client, designer, view):
    designer.release.clear()
    pool = ThreadPoolExecutor(2)
    running = pool.submit(post, client, view, action="design")
    assert designer.entered.wait(10)
    return pool, running


def test_the_last_answer_comes_back_before_the_design():
    designer = HeldDesigner(draft(), delay=2.0)
    with make_client(designer) as client:
        view, elapsed = to_designing(client)
        summary = client.get(f"{JOURNEYS}/{view['journey_id']}/summary.md")
        assert (designer.calls, view["status"], view["design"]) == (0, "in_progress", None)

        started = perf_counter()
        done = post(client, view, action="design").json()
        designing = perf_counter() - started

    assert elapsed < 1.0
    assert summary.status_code == 200  # The decision summary needs no model.
    assert designing >= 2.0
    assert designer.calls == 1
    # The design leads to build preparation, which waits for the user like the end does.
    assert done["prompt"]["type"] == "build" and done["status"] == "completed"
    assert done["design"] is not None


def test_reading_during_the_design_shows_the_design_wait():
    designer = HeldDesigner(draft())
    with make_client(designer) as client:
        view, _ = to_designing(client)
        pool, running = held_design(client, designer, view)
        started = perf_counter()
        read = client.get(f"{JOURNEYS}/{view['journey_id']}")
        elapsed = perf_counter() - started
        designer.release.set()
        running.result()
        pool.shutdown()

    assert elapsed < 1.0
    # Not the last card again: the screen keeps waiting for the design.
    assert read.json()["prompt"]["type"] == "designing"
    assert read.json()["revision"] == view["revision"]


def test_a_second_design_and_a_change_are_refused_at_once():
    designer = HeldDesigner(draft())
    with make_client(designer) as client:
        view, _ = to_designing(client)
        pool, running = held_design(client, designer, view)
        started = perf_counter()
        again = post(client, view, action="design")
        change = post(client, view, action="revise", card_id="model.provider")
        elapsed = perf_counter() - started
        designer.release.set()
        first = running.result()
        pool.shutdown()

    assert elapsed < 1.0
    assert (again.status_code, again.json()["error"]["code"]) == (409, "designing")
    assert (change.status_code, change.json()["error"]["code"]) == (409, "designing")
    assert first.status_code == 200
    assert designer.calls == 1


def test_a_change_waiting_for_the_design_is_refused_with_the_reason():
    with make_client(HeldDesigner(draft())) as client:
        view, _ = to_designing(client)
        response = post(client, view, action="revise", card_id="model.provider")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "designing",
        "message": "설계를 만드는 중이에요. 설계가 끝나면 결정을 바꿀 수 있어요.",
    }


def test_a_design_stopped_midway_is_continued_by_design_not_by_a_read(monkeypatch):
    designer = HeldDesigner(draft())
    with make_client(designer) as client:
        view, _ = to_designing(client)
        working = nodes.generate_design

        def dies(*args, **kwargs):
            raise RuntimeError("process died")

        monkeypatch.setattr(nodes, "generate_design", dies)
        try:
            post(client, view, action="design")
        except RuntimeError:
            pass  # The test client re-raises what the server did not catch.
        monkeypatch.setattr(nodes, "generate_design", working)

        started = perf_counter()
        read = client.get(f"{JOURNEYS}/{view['journey_id']}").json()
        elapsed = perf_counter() - started
        calls_after_read = designer.calls
        done = post(client, read, action="design").json()

    assert elapsed < 1.0
    assert read["prompt"]["type"] == "designing"
    assert calls_after_read == 0
    assert done["prompt"]["type"] == "build" and done["design"] is not None
    assert designer.calls == 1


def test_a_failed_design_ends_with_the_reference_template():
    failures = [TimeoutError("model timed out")] * 4
    with make_client(HeldDesigner(*failures)) as client:
        view, _ = to_designing(client)
        done = post(client, view, action="design").json()
        values = client.app.state.journeys._read(view["journey_id"]).values

    # The design leads to build preparation, which waits for the user like the end does.
    assert done["prompt"]["type"] == "build" and done["status"] == "completed"
    assert values["design"]["status"] == "failed"


def test_no_bundle_is_built_while_the_design_is_made():
    designer = HeldDesigner(draft())
    with make_client(designer) as client:
        view, _ = to_designing(client)
        files = client.get(f"{JOURNEYS}/{view['journey_id']}/package")
        archive = client.get(f"{JOURNEYS}/{view['journey_id']}/package.zip")

    for response in (files, archive):
        assert (response.status_code, response.json()["error"]["code"]) == (409, "designing")
