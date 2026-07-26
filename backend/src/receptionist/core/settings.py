"""Runtime configuration, sourced from the environment (see .env.example)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECEPTIONIST_", env_file=".env", extra="ignore")

    # HMAC key for signing shareable call-detail links.
    link_secret: str = "dev-insecure-secret-change-me"

    # Reasoning layer — decoupled from the (later) STT/TTS choice, so it swaps freely.
    llm_model: str = "claude-opus-5"
    llm_effort: str = "medium"
    llm_max_tokens: int = 4096

    # Base URL the hardlinks in notifications are built against.
    public_base_url: str = "http://localhost:8000"


settings = Settings()
