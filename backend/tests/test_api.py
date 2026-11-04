import pytest
from app.config import Settings
from app.main import create_app, get_provider
from app.schemas import GenerateResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture
def app():
    return create_app(Settings(_env_file=None))


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def test_health_does_not_claim_model_connection(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "mock", "model_connected": False}


@pytest.mark.parametrize(
    "problem",
    [
        "회의록에서 담당자별 할 일을 정리하고 싶어요.",
        "강의 노트에서 프로젝트 관련 내용을 찾기 어려워요.",
        "반복해서 작성하는 주간 보고서를 줄이고 싶어요.",
    ],
)
def test_generate_contract_and_explicit_mock(client, problem):
    response = client.post(
        "/api/v1/starter-packs/generate",
        json={
            "pain_point": f"  {problem}  ",
            "context": "  부트캠프 팀 프로젝트  ",
        },
    )
    assert response.status_code == 200
    output = GenerateResponse.model_validate(response.json())
    assert output.is_mock is True
    assert output.provider == "mock"
    assert output.starter_pack.pain_point == problem
    assert output.starter_pack.agent_recommended is None
    assert output.starter_pack.agent_blueprint.tools == []
    assert "실제 분석 결과가 아닙니다" in output.notice
    assert any("부트캠프 팀 프로젝트" in item for item in output.starter_pack.assumptions)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"pain_point": ""},
        {"pain_point": " " * 20},
        {"pain_point": "짧은 입력"},
        {"pain_point": "a" * 3001},
        {"pain_point": 42},
        {"pain_point": "a" * 10, "context": "b" * 2001},
        {"pain_point": "a" * 10, "unknown": True},
    ],
)
def test_rejects_invalid_input_without_echoing_it(client, payload):
    response = client.post("/api/v1/starter-packs/generate", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
    assert "input" not in response.json()


def test_accepts_length_boundaries_and_unicode(client):
    for problem in ["가" * 10, "😀" * 10, "가" * 3000]:
        assert (
            client.post(
                "/api/v1/starter-packs/generate",
                json={
                    "pain_point": problem,
                    "context": "맥" * 2000,
                },
            ).status_code
            == 200
        )


def test_invalid_json_is_safe(client):
    response = client.post(
        "/api/v1/starter-packs/generate",
        content="{secret",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "failure, status, code",
    [
        (TimeoutError("private input"), 504, "generation_timeout"),
        (RuntimeError("secret-key"), 503, "generation_failed"),
        (None, 502, "invalid_output"),
    ],
)
def test_provider_failure_is_safe_and_retryable(app, client, failure, status, code):
    class BrokenProvider:
        async def generate_structured(self, task_input):
            if failure:
                raise failure
            return {"unexpected": "private data"}

    app.dependency_overrides[get_provider] = BrokenProvider
    response = client.post(
        "/api/v1/starter-packs/generate", json={"pain_point": "충분한 길이의 문제 입력입니다."}
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private" not in response.text and "secret" not in response.text
    app.dependency_overrides.clear()
    assert (
        client.post(
            "/api/v1/starter-packs/generate",
            json={
                "pain_point": "충분한 길이의 문제 입력입니다.",
            },
        ).status_code
        == 200
    )


def test_cors_allows_only_configured_origins(client):
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    assert (
        client.options("/api/v1/starter-packs/generate", headers=headers).headers[
            "access-control-allow-origin"
        ]
        == headers["Origin"]
    )
    headers["Origin"] = "https://untrusted.example"
    assert (
        "access-control-allow-origin"
        not in client.options("/api/v1/starter-packs/generate", headers=headers).headers
    )


def test_unsupported_provider_does_not_silently_use_mock():
    with pytest.raises(ValidationError):
        Settings(provider="gemini", _env_file=None)
