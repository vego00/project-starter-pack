import pytest
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture
def client():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        yield client


def test_health_does_not_claim_model_connection(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "provider": "mock",
        "model_connected": False,
        "journeys_available": False,
    }


def test_cors_allows_only_configured_origins(client):
    def preflight(origin):
        return client.options(
            "/api/v1/journeys",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        ).headers.get("access-control-allow-origin")

    assert preflight("http://localhost:5173") == "http://localhost:5173"
    assert preflight("https://evil.example") is None


def test_unsupported_provider_does_not_silently_use_mock():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, provider="gemini")


def test_database_url_is_hidden_from_repr():
    settings = Settings(_env_file=None, database_url="postgresql://u:secret-value@h/d")

    assert "secret-value" not in repr(settings)
