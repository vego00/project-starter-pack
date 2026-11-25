"""A card shows its options before the models answer; `prepare` asks them (작성자 결정 2026-11-25)."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import perf_counter, sleep

from app.journey.deciders.mock import MockDecider
from app.journey.services import JourneyDeps, LLMAdvisor, MockAdvisor
from app.journey.state import JourneyState
from tests.test_journey_api import JOURNEYS, REGISTRY, SPEC, make_client


class HeldAdvisor(MockAdvisor):
    """Counts calls; while `release` is clear, a call waits inside the model."""

    def __init__(self, delay=0.0):
        self.calls = 0
        self.delay = delay
        self.entered = Event()
        self.release = Event()
        self.release.set()

    def advise(self, state, card):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(10)
        sleep(self.delay)
        return super().advise(state, card)


class CountingDecider(MockDecider):
    def __init__(self, fail=False):
        super().__init__()
        self.calls = 0
        self.fail = fail

    def decide(self, state, question):
        if question.id.startswith("recommend."):
            self.calls += 1
            if self.fail:
                raise RuntimeError("decider down")
        return super().decide(state, question)


class FailingLLM:
    def generate(self, *, system, user, schema):
        raise TimeoutError("model timed out")


def post(client, view, **action):
    return client.post(
        f"{JOURNEYS}/{view['journey_id']}/decisions",
        json={"revision": view["revision"], "action": action},
    )


def first_card(client):
    response = client.post(JOURNEYS, json=SPEC)
    assert response.status_code == 201
    return response.json()


def card(view):
    return view["prompt"]["card"]


def journey_state(client, view):
    service = client.app.state.journeys
    return JourneyState.model_validate(service._read(view["journey_id"]).values)


def test_a_card_comes_with_its_options_and_no_model_call():
    advisor, decider = HeldAdvisor(), CountingDecider()
    with make_client(JourneyDeps(advisor=advisor, decider=decider)) as client:
        view = first_card(client)
        shown = card(view)
        assert shown["preparing"] is True
        assert shown["recommendation"] is None
        assert shown["options"] and all(o["note"] == "" for o in shown["options"])
        assert (advisor.calls, decider.calls) == (0, 0)

        view = post(client, view, action="prepare").json()
        assert card(view)["preparing"] is False
        assert card(view)["recommendation"]["option_id"]
        assert (advisor.calls, decider.calls) == (1, 1)

        option = card(view)["recommendation"]["option_id"]
        view = post(client, view, action="select", option_id=option).json()

    # Choosing shows the next card at once; its models wait for its own `prepare`.
    assert card(view)["preparing"] is True
    assert (advisor.calls, decider.calls) == (1, 1)


def test_the_next_card_does_not_wait_for_a_slow_model():
    advisor = HeldAdvisor(delay=2.0)
    with make_client(JourneyDeps(advisor=advisor)) as client:
        view = post(client, first_card(client), action="prepare").json()
        option = card(view)["recommendation"]["option_id"]

        started = perf_counter()
        view = post(client, view, action="select", option_id=option).json()
        shown = perf_counter() - started
        started = perf_counter()
        view = post(client, view, action="prepare").json()
        prepared = perf_counter() - started

    assert card(view)["preparing"] is False
    assert shown < 1.0
    assert prepared >= 2.0


def held_prepare(client, advisor, view):
    """Starts `prepare` in the background and returns once it is inside the model."""
    advisor.release.clear()
    pool = ThreadPoolExecutor(2)
    running = pool.submit(post, client, view, action="prepare")
    assert advisor.entered.wait(10)
    return pool, running


def test_a_choice_made_while_preparing_is_kept():
    advisor = HeldAdvisor()
    with make_client(JourneyDeps(advisor=advisor)) as client:
        view = first_card(client)
        card_id = card(view)["card_id"]
        option = next(o["option"]["id"] for o in card(view)["options"] if not o["blocked_reason"])
        pool, running = held_prepare(client, advisor, view)
        chosen = pool.submit(post, client, view, action="select", option_id=option)
        sleep(0.2)  # The choice now waits behind the preparation.
        advisor.release.set()
        codes = (running.result().status_code, chosen.result().status_code)
        pool.shutdown()
        decision = journey_state(client, view).decisions[card_id]
        after = chosen.result().json()

    assert codes == (200, 200)
    assert (decision.option_id, decision.by) == (option, "user")
    assert card(after)["card_id"] != card_id


def test_two_prepares_run_the_models_once():
    advisor = HeldAdvisor()
    with make_client(JourneyDeps(advisor=advisor)) as client:
        view = first_card(client)
        pool, running = held_prepare(client, advisor, view)
        again = pool.submit(post, client, view, action="prepare")
        sleep(0.2)
        advisor.release.set()
        codes = sorted([running.result().status_code, again.result().status_code])
        pool.shutdown()

    assert codes == [200, 409]
    assert advisor.calls == 1


def test_a_recommendation_the_user_never_saw_is_not_accepted():
    advisor = HeldAdvisor()
    with make_client(JourneyDeps(advisor=advisor)) as client:
        view = first_card(client)
        pool, running = held_prepare(client, advisor, view)
        accepted = pool.submit(post, client, view, action="accept_recommendation")
        sleep(0.2)
        advisor.release.set()
        running.result()
        response = accepted.result()
        pool.shutdown()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stale_revision"


def test_reading_a_journey_does_not_wait_for_a_preparation():
    advisor = HeldAdvisor()
    with make_client(JourneyDeps(advisor=advisor)) as client:
        view = first_card(client)
        pool, running = held_prepare(client, advisor, view)
        started = perf_counter()
        read = client.get(f"{JOURNEYS}/{view['journey_id']}")
        elapsed = perf_counter() - started
        advisor.release.set()
        running.result()
        pool.shutdown()

    assert read.status_code == 200
    assert elapsed < 1.0
    # The last stop before the run in progress: the card with its options only.
    assert read.json()["revision"] == view["revision"]
    assert card(read.json())["preparing"] is True


def test_preparing_a_prepared_card_again_calls_nothing():
    advisor = HeldAdvisor()
    with make_client(JourneyDeps(advisor=advisor)) as client:
        view = post(client, first_card(client), action="prepare").json()
        again = post(client, view, action="prepare").json()

    assert again["prompt"]["error"] == "이미 추천까지 준비된 카드예요."
    assert advisor.calls == 1


def test_failed_models_still_finish_the_preparation():
    deps = JourneyDeps(
        advisor=LLMAdvisor(FailingLLM(), REGISTRY), decider=CountingDecider(fail=True)
    )
    with make_client(deps) as client:
        view = post(client, first_card(client), action="prepare").json()

    # ADR-016: the card's own text, and "비교 필요" instead of another model.
    shown = card(view)
    assert shown["preparing"] is False
    assert shown["advice_source"] == "card_text"
    assert shown["recommendation"]["status"] == "needs_comparison"
    assert shown["recommendation"]["option_id"] is None
