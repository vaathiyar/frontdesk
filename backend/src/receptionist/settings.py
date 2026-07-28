"""Runtime configuration — the one place that reads the environment.

App settings are prefixed RECEPTIONIST_; vendor credentials keep their conventional
names. Model and voice parameters are deliberately NOT here: they live as constants
next to the code that uses them (graph.py, voice/providers.py).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECEPTIONIST_", env_file=".env", extra="ignore")

    # Gemini authenticates with the API key. Cloud Speech-to-Text, Text-to-Speech and
    # Calendar authenticate with the service-account JSON at the second path.
    google_api_key: str = Field(default="", validation_alias="GOOGLE_API_KEY")
    google_credentials_file_path: str = Field(
        default="", validation_alias="GOOGLE_CREDENTIALS_FILE_PATH"
    )

    # Telnyx sends the confirmation text. Unset ⇒ the SMS is printed instead of sent,
    # so the REPL and tests never message a real phone.
    telnyx_api_key: str = Field(default="", validation_alias="TELNYX_API_KEY")
    telnyx_from_number: str = Field(default="", validation_alias="TELNYX_FROM_NUMBER")

    # profile_id -> Google Calendar ID. A profile listed here books against that real
    # calendar; anything omitted falls back to the in-memory fake, so local testing
    # needs zero calendar setup.
    calendar_ids: dict[str, str] = {}
    timezone: str = "America/Vancouver"

    # Which profile the local `agent.py console` answers as, absent SIP metadata.
    profile: str = "hvac"

    # Signed call-detail links, and where the SMS points.
    link_secret: str = "dev-insecure-secret-change-me"
    public_base_url: str = "http://localhost:8000"
    database_path: str = "calls.db"


settings = Settings()
