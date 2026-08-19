"""Application settings. Everything secret comes from the environment."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "staging", "prod"]

# Fixed development-only values. They are rejected outside dev/test so a
# misconfigured deployment fails loudly instead of running on a known key.
DEV_SECRET_KEY = "dev-only-insecure-secret-key-change-me"
DEV_PII_KEY = "ZGV2LW9ubHktaW5zZWN1cmUtcGlpLWtleS0zMmJ5dGU="  # 32 bytes, base64


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- app -------------------------------------------------------------
    environment: Environment = "dev"
    app_name: str = "SihhatAI"
    build_sha: str = Field(default_factory=lambda: os.getenv("BUILD_SHA", "unknown"))
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # --- storage ---------------------------------------------------------
    database_url: str = "postgresql+psycopg://sihhat:sihhat@localhost:5432/sihhat"
    redis_url: str = "redis://localhost:6379/0"

    # --- security --------------------------------------------------------
    secret_key: str = DEV_SECRET_KEY
    pii_encryption_key: str = DEV_PII_KEY  # base64-encoded 32 bytes (AES-256-GCM)
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    jwt_algorithm: str = "HS256"

    # --- i18n ------------------------------------------------------------
    default_language: str = "uz"
    supported_languages: tuple[str, ...] = ("uz", "ru", "en")

    # --- AI --------------------------------------------------------------
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    local_llm_base_url: str | None = None  # e.g. http://edge:11434 (Ollama)
    openai_model: str = "gpt-4o"
    anthropic_model: str = "claude-sonnet-4-5"
    local_model: str = "llama3:8b"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    #: Hard ceiling in USD for a single consultation's model spend.
    cost_ceiling_per_consultation_usd: float = 0.05
    #: Wall-clock budget for the online path before we degrade to local.
    latency_budget_ms: int = 6000
    #: Below this confidence we refuse to rank and ask follow-up questions instead.
    min_confidence_to_rank: float = 0.4
    #: Cosine similarity required for a semantic cache hit.
    semantic_cache_threshold: float = 0.97
    semantic_cache_ttl_seconds: int = 60 * 60 * 24 * 7

    # --- observability ---------------------------------------------------
    sentry_dsn: str | None = None
    metrics_enabled: bool = True

    @field_validator("secret_key")
    @classmethod
    def _reject_dev_secret(cls, v: str, info) -> str:
        env = (info.data or {}).get("environment", "dev")
        if env in ("staging", "prod") and v == DEV_SECRET_KEY:
            raise ValueError("SECRET_KEY must be set outside dev/test")
        return v

    @field_validator("pii_encryption_key")
    @classmethod
    def _reject_dev_pii_key(cls, v: str, info) -> str:
        env = (info.data or {}).get("environment", "dev")
        if env in ("staging", "prod") and v == DEV_PII_KEY:
            raise ValueError("PII_ENCRYPTION_KEY must be set outside dev/test")
        return v

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def testing(self) -> bool:
        return self.environment == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
