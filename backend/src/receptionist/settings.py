"""Runtime configuration — the one place that reads the environment.

App settings are prefixed RECEPTIONIST_; vendor credentials keep their conventional
names. Model and voice parameters are deliberately NOT here: they live as constants
next to the code that uses them (worker/agent/graph.py, worker/voice/speech.py).
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# CockroachDB hands you a `postgresql://` string, and SQLAlchemy needs the `cockroachdb`
# prefix to load the right dialect — `postgresql://` reaches the database but leaves
# Alembic introspecting it as plain Postgres, which fails in ways that don't say so. So
# the scheme is rewritten here and everything after it is passed through untouched, which
# is what lets the connection string be pasted in exactly as CockroachDB gives it.
_CRDB_SCHEMES = ("postgresql://", "postgres://")
_CRDB_DRIVER = "cockroachdb+psycopg://"


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

    # Where the SMS points: the SPA's origin, since it is the SPA that serves /c/{id}.
    public_base_url: str = "http://localhost:8000"

    # CockroachDB. Paste the connection string as-is, password and all — the validator
    # below fixes the scheme. No default: an empty value raises DatabaseNotConfigured at
    # startup (core/db/engine.py) rather than silently writing calls nowhere.
    database_url: str = ""

    # Which origins the SPA may call the API from. Unused locally, where Vite proxies
    # /api and the browser sees one origin; it is the deployed SPA's host that needs it.
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("database_url")
    @classmethod
    def _use_the_cockroach_dialect(cls, url: str) -> str:
        for scheme in _CRDB_SCHEMES:
            if url.startswith(scheme):
                return _CRDB_DRIVER + url.removeprefix(scheme)
        return url


settings = Settings()
