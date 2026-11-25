"""Needs a real PostgreSQL: set TEST_DATABASE_URL. CI provides one, so these never skip there."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from app.journey.graph import build_graph, journey_config, journey_input
from app.journey.persistence import open_checkpointer
from app.journey.state import ProjectSpec
from app.registry.loader import load_registry
from psycopg_pool import PoolTimeout

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_DIR = Path(__file__).resolve().parents[1]
SPEC = {
    "idea": "강의 자료를 찾아 답하는 멀티 에이전트 서비스",
    "goal": "수강생이 근거와 함께 답을 찾을 수 있는 상태",
    "team_size": 4,
    "duration_weeks": 8,
    "budget": "월 5만원",
    "expected_users": 20,
    "weekly_hours": 20,
    "data_traits": ["문서 검색"],
    "deployment_target": "small_group",
    "has_gpu": False,
}

needs_postgres = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not set")


def step(journey_id, command, payload):
    """Each call is a new process: nothing but the database carries state between calls."""
    completed = subprocess.run(
        [
            sys.executable,
            str(BACKEND_DIR / "tests" / "journey_driver.py"),
            DATABASE_URL,
            str(journey_id),
            command,
            json.dumps(payload),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(BACKEND_DIR)},
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads(completed.stdout)


def select(option_id):
    return {"action": "select", "option_id": option_id}


@needs_postgres
def test_journey_continues_across_processes_until_completed():
    journey_id = uuid4()

    assert step(journey_id, "start", SPEC)["card_id"] == "product.surface"
    assert step(journey_id, "resume", select("web"))["card_id"] == "agent.topology"
    assert step(journey_id, "resume", select("pipeline"))["card_id"] == "agent.hitl"
    assert step(journey_id, "resume", select("question"))["card_id"] == "model.provider"

    # The fork after the agent design is answered in a new process too (ADR-024).
    assert step(journey_id, "resume", select("gemini"))["type"] == "fork"
    assert step(journey_id, "resume", {"action": "plan_deploy"})["card_id"] == "data.primary_db"
    walk = ("postgres", "pgvector", "postgres", "code", "sync", "none", "external_api")
    for option_id in walk:
        result = step(journey_id, "resume", select(option_id))
    assert result["card_id"] == "cloud.target"
    assert len(result["decisions"]) == 11

    assert step(journey_id, "resume", select("local"))["card_id"] == "ops.tracing"
    final = step(journey_id, "resume", select("none"))
    assert final["card_id"] is None
    assert final["status"] == "completed"
    assert len(final["decisions"]) == len(load_registry().cards)


@needs_postgres
def test_a_card_shown_in_one_process_is_prepared_in_another():
    journey_id = uuid4()
    shown = step(journey_id, "start", SPEC)
    assert (shown["card_id"], shown["preparing"]) == ("product.surface", True)

    prepared = step(journey_id, "resume", {"action": "prepare"})

    assert (prepared["card_id"], prepared["preparing"]) == ("product.surface", False)


@needs_postgres
def test_invalid_answer_after_restart_keeps_the_same_card():
    journey_id = uuid4()
    step(journey_id, "start", SPEC)

    result = step(journey_id, "resume", {})

    assert result["card_id"] == "product.surface"
    assert result["decisions"] == []


@needs_postgres
def test_journeys_are_isolated_and_setup_is_repeatable():
    registry = load_registry()
    first, second = uuid4(), uuid4()
    spec = ProjectSpec(**SPEC)

    with open_checkpointer(DATABASE_URL) as saver:
        graph = build_graph(registry, checkpointer=saver)
        graph.invoke(journey_input(first, spec), journey_config(first))
    with open_checkpointer(DATABASE_URL) as saver:  # setup() runs again on existing tables.
        graph = build_graph(registry, checkpointer=saver)
        graph.invoke(journey_input(second, spec), journey_config(second))
        missing = graph.get_state(journey_config(uuid4()))

    assert step(first, "resume", select("web"))["decisions"] == ["product.surface"]
    assert step(second, "resume", select("report"))["card_id"] == "agent.topology"
    assert missing.values == {}


def test_unreachable_database_fails_fast():
    with pytest.raises(PoolTimeout):
        with open_checkpointer("postgresql://nobody@127.0.0.1:1/none", timeout=0.5):
            pass
