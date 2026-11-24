from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_", env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore"
    )

    # Fail at startup for unsupported values instead of silently falling back to mock.
    provider: Literal["mock", "gemini", "exaone"] = "mock"
    decider: Literal["mock", "jev"] = "mock"
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    # Empty uses gemini_model. The design draft is the hardest call, so it can use another model.
    gemini_design_model: str | None = None
    exaone_api_key: SecretStr | None = None
    exaone_model: str | None = None  # Empty uses k-exaone_v2.5.
    jev_route: Literal["opencode", "vercel", "typesafe"] = "opencode"
    jev_model: str | None = None  # Empty uses the route's default model.
    ai_gateway_api_key: SecretStr | None = None
    opencode_api_key: SecretStr | None = None
    typesafe_api_key: SecretStr | None = None
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    database_url: SecretStr | None = None
    # Notes are private until sharing is permitted: "owner" is for the note owner's own instance.
    evidence_scope: Literal["none", "owner"] = "none"
    # ADR-018: the decider leaves out cards this project does not need. False asks every card.
    card_selection: bool = True
    # proxy: oauth2-proxy behind Nginx sends the signed-in email as X-User-Email; requests without
    # it get 401. local: every request is the same local user, for development and tests.
    auth: Literal["local", "proxy"] = "local"

    @field_validator(
        "gemini_api_key",
        "gemini_model",
        "gemini_design_model",
        "exaone_api_key",
        "exaone_model",
        "jev_model",
        "ai_gateway_api_key",
        "opencode_api_key",
        "typesafe_api_key",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # Compose passes unset variables as empty strings.
        return value or None

    @model_validator(mode="after")
    def _model_settings_are_complete(self):
        if self.provider == "gemini" and not (self.gemini_api_key and self.gemini_model):
            raise ValueError("provider=gemini needs APP_GEMINI_API_KEY and APP_GEMINI_MODEL")
        if self.provider == "exaone" and not self.exaone_api_key:
            raise ValueError("provider=exaone needs APP_EXAONE_API_KEY")
        if self.decider == "jev" and self.jev_route == "vercel" and not self.ai_gateway_api_key:
            raise ValueError("jev_route=vercel needs APP_AI_GATEWAY_API_KEY")
        if self.decider == "jev" and self.jev_route == "typesafe" and not self.typesafe_api_key:
            raise ValueError("jev_route=typesafe needs APP_TYPESAFE_API_KEY")
        return self
