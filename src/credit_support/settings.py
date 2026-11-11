import os
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Identity(BaseModel):
    actor_id: str = Field(min_length=1)
    role: str = Field(pattern="^(analyst|reviewer|auditor|admin)$")
    demo_session_id: UUID | None = None
    demo_expires_at: datetime | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CDS_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: SecretStr
    demo_identities: dict[str, Identity] = Field(default_factory=dict, repr=False)
    worker_lease_seconds: int = Field(default=30, ge=5, le=300)
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    llm_live_enabled: bool = False
    llm_model: Literal["gpt-5.6-terra"] = "gpt-5.6-terra"
    llm_budget_usd: Decimal = Field(default=Decimal("2.00"), gt=0, le=2)
    llm_max_calls: int = Field(default=64, ge=1, le=100)
    llm_timeout_seconds: float = Field(default=60, ge=1, le=120)
    guided_demo_enabled: bool = False
    demo_session_ttl_seconds: int = Field(default=1800, ge=60, le=7200)
    demo_max_active_sessions: int = Field(default=20, ge=1, le=100)
    demo_max_sessions: int = Field(default=200, ge=1, le=1000)
    demo_requests_per_minute: int = Field(default=8, ge=1, le=60)
    db_statement_timeout_ms: int = Field(default=15000, ge=100, le=120000)
    db_lock_timeout_ms: int = Field(default=5000, ge=100, le=30000)
    public_demo: bool = False
    public_origin: str | None = None

    @model_validator(mode="after")
    def validate_configuration(self) -> "Settings":
        if self.public_demo:
            origin = urlsplit(self.public_origin or "")
            if (
                origin.scheme != "https"
                or not origin.hostname
                or origin.username
                or origin.password
                or origin.path not in ("", "/")
                or origin.query
                or origin.fragment
            ):
                raise ValueError("Public demo requires an explicit HTTPS origin")
            if (
                self.llm_live_enabled
                or (self.openai_api_key and self.openai_api_key.get_secret_value())
                or self.demo_identities
            ):
                raise ValueError(
                    "Public demo forbids provider keys, live models, and static identities"
                )
            self.public_origin = (self.public_origin or "").rstrip("/")
        if not self.database_url.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("PostgreSQL with psycopg is required")
        if any(len(token) < 24 for token in self.demo_identities):
            raise ValueError("Demo bearer tokens must contain at least 24 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    public = os.environ.get("CDS_PUBLIC_DEMO", "").lower() in {"true", "1", "yes", "on"}
    return Settings(_env_file=None if public else ".env")  # type: ignore[call-arg]
