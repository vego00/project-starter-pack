"""Each journey belongs to the email that started it (oauth2-proxy sends it as X-User-Email)."""

import os
from uuid import uuid4

import pytest
from app.config import Settings
from app.main import create_app
from app.owners import PostgresOwners
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from tests.test_journey_api import JOURNEYS, REGISTRY, SPEC, act

ALICE = {"X-User-Email": "alice@example.com"}
BOB = {"X-User-Email": "bob@example.com"}
DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def client():
    settings = Settings(_env_file=None, auth="proxy")
    app = create_app(settings, checkpointer=InMemorySaver(), registry=REGISTRY)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def start_as(client, headers):
    response = client.post(JOURNEYS, json=SPEC, headers=headers)
    assert response.status_code == 201
    return response.json()


def test_requests_without_a_signed_in_email_are_refused(client):
    assert client.post(JOURNEYS, json=SPEC).status_code == 401
    view = start_as(client, ALICE)
    response = client.get(f"{JOURNEYS}/{view['journey_id']}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "login_required"


def test_another_user_cannot_read_change_or_download_a_journey(client):
    view = start_as(client, ALICE)
    path = f"{JOURNEYS}/{view['journey_id']}"

    for response in (
        client.get(path, headers=BOB),
        client.get(f"{path}/design", headers=BOB),
        client.get(f"{path}/package.zip", headers=BOB),
        client.post(
            f"{path}/decisions",
            json={"revision": view["revision"], "action": {"action": "select", "option_id": "x"}},
            headers=BOB,
        ),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "journey_not_found"

    assert client.get(path, headers=ALICE).json() == view


def test_the_owner_email_ignores_case_and_spaces(client):
    view = start_as(client, {"X-User-Email": " Alice@Example.com "})
    assert client.get(f"{JOURNEYS}/{view['journey_id']}", headers=ALICE).status_code == 200


def test_an_unknown_journey_looks_the_same_as_someone_elses(client):
    response = client.get(f"{JOURNEYS}/{uuid4()}", headers=ALICE)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "journey_not_found"


def test_health_needs_no_sign_in(client):
    assert client.get("/health").status_code == 200


def test_local_mode_needs_no_header():
    app = create_app(Settings(_env_file=None), checkpointer=InMemorySaver(), registry=REGISTRY)
    with TestClient(app) as client:
        view = client.post(JOURNEYS, json=SPEC).json()
        assert act(client, view, action="select", option_id="nope").status_code != 404


@pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not set")
def test_postgres_owners_are_saved_and_setup_can_run_again():
    with ConnectionPool(DATABASE_URL, kwargs={"row_factory": dict_row}) as pool:
        owners = PostgresOwners(pool)
        owners.setup()
        owners.setup()
        journey_id = uuid4()
        owners.add(journey_id, "alice@example.com")
        assert owners.owner(journey_id) == "alice@example.com"
        assert owners.owner(uuid4()) is None
