from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_", env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore"
    )

    # Fail at startup for unsupported providers instead of silently falling back to mock.
    provider: Literal["mock"] = "mock"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    database_url: SecretStr | None = None
