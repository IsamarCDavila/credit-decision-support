from functools import lru_cache

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Identity(BaseModel):
    actor_id: str = Field(min_length=1)
    role: str = Field(pattern="^(analyst|reviewer|auditor|admin)$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CDS_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: SecretStr
    demo_identities: dict[str, Identity] = Field(default_factory=dict, repr=False)
    worker_lease_seconds: int = Field(default=30, ge=5, le=300)
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)

    @model_validator(mode="after")
    def validate_configuration(self) -> "Settings":
        if not self.database_url.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("PostgreSQL with psycopg is required")
        if any(len(token) < 24 for token in self.demo_identities):
            raise ValueError("Demo bearer tokens must contain at least 24 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
