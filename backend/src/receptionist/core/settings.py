"""Runtime configuration — the single source of truth for env-sourced settings.

Every module reads config from the `settings` singleton below; nothing else in the
backend touches the environment directly. App settings are prefixed RECEPTIONIST_;
Google credentials keep their conventional, unprefixed names.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECEPTIONIST_", env_file=".env", extra="ignore")

    # --- Google credentials (unprefixed, conventional names) ---
    # Gemini authenticates with the API key. Cloud Speech-to-Text, Text-to-Speech, and
    # Calendar use the service-account JSON at GOOGLE_CREDENTIALS_FILE_PATH; the app passes
    # that path to the Google clients explicitly (STT/TTS via `credentials_file`, Calendar
    # via `from_service_account_file`), so no GOOGLE_APPLICATION_CREDENTIALS var is needed.
    google_api_key: str = Field(default="", validation_alias="GOOGLE_API_KEY")
    google_credentials_file_path: str = Field(
        default="", validation_alias="GOOGLE_CREDENTIALS_FILE_PATH"
    )

    # Chat model params (model, effort, max tokens) live in agent/runner.py, and
    # voice params (STT/TTS models & voice, VAD) in providers/factory.py — both as
    # code constants, deliberately not env-configurable.

    # --- Google Calendar (real booking backend; optional) ---
    # Map of profile_id -> Google Calendar ID (RECEPTIONIST_CALENDAR_IDS as a JSON object,
    # which pydantic-settings parses into this dict). A profile listed here books against
    # that calendar via GoogleCalendarService; any profile unset/omitted falls back to the
    # in-memory fake — so local `console` testing needs zero calendar setup.
    calendar_ids: dict[str, str] = {}
    # IANA timezone all calendar reasoning and booking happen in (RECEPTIONIST_TIMEZONE).
    timezone: str = "America/Vancouver"

    # --- Links / web ---
    # HMAC key for signing shareable call-detail links.
    link_secret: str = "dev-insecure-secret-change-me"
    # Base URL the hardlinks in notifications are built against.
    public_base_url: str = "http://localhost:8000"


settings = Settings()
