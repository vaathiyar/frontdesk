"""The voice stack — the only place a speech vendor is named.

Model and voice choices are code constants, not settings: they are wired to what the
rest of the pipeline expects, and a wrong value here is a broken call rather than a
tuning preference. Only the credentials come from the environment.

Imports are local to each builder so that importing this module — which the tests do
transitively — never drags in onnxruntime and the rest of the audio stack.
"""

from __future__ import annotations

from typing import Any

from receptionist.settings import settings

# Google Cloud Speech-to-Text.
STT_MODEL = "latest_long"
STT_LOCATION = "global"
STT_LANGUAGES = ["en-US"]

# Google Cloud Text-to-Speech. Chirp3-HD is set through `model_name`, not `model`.
TTS_MODEL = "chirp_3"
TTS_VOICE = "en-US-Chirp3-HD-Charon"


def build_stt() -> Any:
    from livekit.plugins import google

    return google.STT(
        model=STT_MODEL,
        languages=STT_LANGUAGES,
        location=STT_LOCATION,
        # Empty means fall back to Application Default Credentials.
        credentials_file=settings.google_credentials_file_path or None,
    )


def build_tts() -> Any:
    from livekit.plugins import google

    return google.TTS(
        voice_name=TTS_VOICE,
        model_name=TTS_MODEL,
        credentials_file=settings.google_credentials_file_path or None,
    )


def build_vad() -> Any:
    """Silero voice-activity detection. Weights ship inside the plugin wheel."""
    from livekit.plugins import silero

    return silero.VAD.load()
