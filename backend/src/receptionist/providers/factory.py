"""The one place that names a vendor.

`build_chat` is live (Gemini). `build_stt`/`build_tts` are the seams the voice
milestone fills in. Their model/voice params are code constants below — like the
chat params in agent/runner.py, deliberately not env-configurable; only the
credentials the providers authenticate with come from `Settings`.
"""

from __future__ import annotations

from receptionist.agent.runner import MessagesAPI
from receptionist.core.settings import Settings, settings
from receptionist.providers.gemini import GeminiMessages

# Voice params — fixed in code, not env-configurable (mirroring the chat params in
# agent/runner.py). Only the Google credentials these providers use come from Settings.
# --- Speech-to-text: Google Cloud Speech ---
STT_MODEL = "latest_long"
STT_LOCATION = "global"
# --- Text-to-speech: Google Cloud TTS ---
TTS_MODEL = "chirp_3"
TTS_VOICE = "en-US-Chirp3-HD-Charon"
# --- Voice activity detection ---
VAD = "silero"


def build_chat(config: Settings = settings) -> MessagesAPI:
    """The reasoning layer the ConversationRunner drives (Gemini today)."""
    return GeminiMessages.from_settings(config)


def build_stt() -> object:
    """Google Cloud Speech-to-Text (LiveKit plugin)."""
    from livekit.plugins import google

    # Confirmed vs livekit-plugins-google 1.6.7: STT kwargs are `model`, `languages`
    # (a list), `location`, and `credentials_file` (path to the service-account JSON). We
    # pass our GOOGLE_CREDENTIALS_FILE_PATH so no GOOGLE_APPLICATION_CREDENTIALS is needed;
    # empty ⇒ the plugin falls back to Application Default Credentials.
    return google.STT(
        model=STT_MODEL,
        languages=["en-US"],
        location=STT_LOCATION,
        credentials_file=settings.google_credentials_file_path or None,
    )


def build_tts() -> object:
    """Google Cloud Text-to-Speech (LiveKit plugin)."""
    from livekit.plugins import google

    # Confirmed vs livekit-plugins-google 1.6.7: `voice_name` (not `voice`), no `model`
    # kwarg (Chirp3-HD is `model_name="chirp_3"`), and `credentials_file` for the service
    # account — we pass our GOOGLE_CREDENTIALS_FILE_PATH (empty ⇒ Application Default Creds).
    return google.TTS(
        voice_name=TTS_VOICE,
        model_name=TTS_MODEL,
        credentials_file=settings.google_credentials_file_path or None,
    )


def build_vad() -> object:
    """Silero voice-activity detection (LiveKit plugin)."""
    from livekit.plugins import silero

    return silero.VAD.load()


def build_llm() -> object:
    """The reasoning LLM for the voice path — Gemini via LiveKit's Google plugin."""
    from livekit.plugins import google

    from receptionist.agent.runner import CHAT_MODEL

    # Confirmed vs livekit-plugins-google 1.6.7: the LLM kwarg is `model`.
    return google.LLM(model=CHAT_MODEL)


def build_calendar(profile_id: str, config: Settings = settings) -> object:
    """Calendar backend for a profile: the real Google Calendar when that profile has an id
    configured in `RECEPTIONIST_CALENDAR_IDS`, otherwise the in-memory fake.

    This keeps local `console` testing zero-setup — with no calendar ids configured every
    profile gets the fake. The GoogleCalendarService import (and, transitively, the vendor
    google-auth/googleapiclient deps) stays lazy so the fake/test path never loads it.
    """
    calendar_id = config.calendar_ids.get(profile_id)
    if calendar_id:
        from receptionist.services.google_calendar import GoogleCalendarService

        return GoogleCalendarService(calendar_id, config.timezone)

    from receptionist.services.calendar import FakeCalendarService

    return FakeCalendarService()
