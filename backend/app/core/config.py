"""Application settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # The repo-root .env serves both Docker Compose and local development; a backend/.env
    # (if present) takes precedence. Real environment variables override both.
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = (
        "postgresql+psycopg://meddefender:meddefender-local-dev@127.0.0.1:55432/meddefender"
    )

    # Root secret from which per-device HMAC keys are derived (KMS stand-in). Required.
    device_key_master_secret: SecretStr = Field(min_length=32)

    # Browser security
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ]
    )
    cookie_secure: bool = False
    session_ttl_minutes: int = 480
    session_idle_minutes: int = 60
    login_max_failures: int = 5
    login_lockout_minutes: int = 5

    # Device message pipeline
    freshness_window_seconds: int = 30
    future_skew_seconds: int = 5
    max_sequence_gap: int = 1000
    max_message_bytes: int = 16_384
    auth_failure_threshold: int = 3
    auth_failure_window_seconds: int = 60
    rate_limit_messages: int = 30
    rate_limit_window_seconds: int = 10
    nonce_retention_hours: int = 24

    # Simulation
    generator_enabled: bool = True
    generator_interval_seconds: float = 5.0
    telemetry_retention_hours: int = 6
    event_backlog_limit: int = 500

    # Demo accounts created by the seed command (local demo only)
    demo_password_viewer: SecretStr | None = None
    demo_password_operator: SecretStr | None = None
    demo_password_admin: SecretStr | None = None

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("device_key_master_secret")
    @classmethod
    def _reject_placeholder(cls, value: SecretStr) -> SecretStr:
        if "change-me" in value.get_secret_value():
            raise ValueError("DEVICE_KEY_MASTER_SECRET still contains the placeholder text")
        return value

    def assert_production_safe(self) -> None:
        """Refuse obviously unsafe settings outside development and test."""
        if self.environment != "production":
            return
        problems = []
        if "dev-only" in self.device_key_master_secret.get_secret_value():
            problems.append("DEVICE_KEY_MASTER_SECRET is a development default")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))

    @property
    def master_secret_bytes(self) -> bytes:
        return self.device_key_master_secret.get_secret_value().encode("utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
