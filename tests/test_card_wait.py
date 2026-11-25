import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "benchmarks" / "card_wait.py"
spec = importlib.util.spec_from_file_location("card_wait", TOOL)
card_wait = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card_wait)


def events(*pairs):
    return [{"node": node, "latency_ms": ms} for node, ms in pairs]


ANSWER = (("decision_gate", 1), ("constraint_engine", 1), ("controller", 1))


def test_an_answer_that_ran_the_models_shows_nothing_until_they_finish():
    trace = events(
        *ANSWER, ("advisor", 900), ("recommender", 300), ("retriever", 2), ("present", 1)
    )

    (wait,) = card_wait.card_waits(trace)

    # The three preparers run together, so the longest one counts.
    assert wait["options_ms"] == wait["recommendation_ms"] == 904


def test_a_prepared_card_shows_its_options_before_its_recommendation():
    trace = events(
        *ANSWER,
        ("present", 1),
        ("decision_gate", 1),
        ("advisor", 900),
        ("recommender", 300),
        ("retriever", 2),
        ("present", 1),
    )

    (wait,) = card_wait.card_waits(trace)

    assert (wait["options_ms"], wait["recommendation_ms"]) == (4, 906)


def test_runs_that_show_no_card_are_left_out():
    trace = events(("decision_gate", 1), ("qa", 50), ("fork_gate", 1), ("constraint_engine", 1))

    assert card_wait.card_waits(trace) == []
