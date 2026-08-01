"""Runtime configuration — the one place that reads the environment.

App settings are prefixed RECEPTIONIST_; vendor credentials keep their conventional
names. Model and voice parameters are deliberately NOT here: they live as constants
next to the code that uses them (worker/agent/graph.py, worker/voice/speech.py).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECEPTIONIST_", env_file=".env", extra="ignore")

    # Gemini authenticates with the API key. Cloud Speech-to-Text, Text-to-Speech and
    # Calendar authenticate with a service account, given either inline as JSON or as a
    # path to the key file — inline wins, and worker/lib/google_auth.py explains why.
    #
    # The inline one stays a plain `str`, deliberately: as a dict field pydantic-settings
    # would parse it while building this singleton, so one mangled paste would turn
    # `import receptionist.settings` into a ValidationError and take down serve.py, which
    # never touches Google at all. worker/lib/google_auth.py parses it lazily instead.
    google_api_key: str = Field(default="", validation_alias="GOOGLE_API_KEY")
    google_credentials_json: str = Field(default="", validation_alias="GOOGLE_CREDENTIALS_JSON")
    google_credentials_file_path: str = Field(
        default="", validation_alias="GOOGLE_CREDENTIALS_FILE_PATH"
    )

    # Telnyx sends the confirmation text. Unset ⇒ the SMS is composed and recorded on the
    # call as skipped rather than sent, so the tests never message a real phone.
    telnyx_api_key: str = Field(default="", validation_alias="TELNYX_API_KEY")
    telnyx_from_number: str = Field(default="", validation_alias="TELNYX_FROM_NUMBER")

    # profile_id -> Google Calendar ID. Every registered profile needs one: the worker
    # checks this at startup (`require_calendar_ids`) and refuses to run otherwise, rather
    # than discovering a missing calendar with a caller on the line.
    calendar_ids: dict[str, str] = {}
    timezone: str = "America/Vancouver"

    # Signed call-detail links, and where the SMS points.
    link_secret: str = "dev-insecure-secret-change-me"
    public_base_url: str = "http://localhost:8000"
    database_path: str = "calls.db"


settings = Settings()
