"""The voice stack — the only place a speech vendor is named.

Model and voice choices are code constants, not settings: they are wired to what the
rest of the pipeline expects, and a wrong value here is a broken call rather than a
tuning preference. Only the credentials come from the environment.

The plugin imports are at module scope on purpose. LiveKit plugins register themselves
when imported, and registration has to happen on the main thread — deferring these into
the builders looks tidier but crashes every call with "Plugins must be registered on the
main thread", because the job entrypoint does not run there.
"""

from __future__ import annotations

from typing import Any

from livekit.plugins import google, silero

from receptionist.google_auth import credential_kwargs

# Google Cloud Speech-to-Text.
STT_MODEL = "latest_long"
STT_LOCATION = "global"
STT_LANGUAGES = ["en-US"]

# Google Cloud Text-to-Speech. Chirp3-HD is set through `model_name`, not `model`.
TTS_MODEL = "chirp_3"
TTS_VOICE = "en-US-Chirp3-HD-Zephyr"


def build_stt() -> Any:
    # `credential_kwargs()` returns {} when nothing is configured, and the empty splat is
    # what reaches Application Default Credentials. Passing `credentials_file=None`
    # explicitly does not: livekit counts None as a supplied value.
    return google.STT(
        model=STT_MODEL,
        languages=STT_LANGUAGES,
        location=STT_LOCATION,
        **credential_kwargs(),
    )


def build_tts() -> Any:
    return google.TTS(
        voice_name=TTS_VOICE,
        model_name=TTS_MODEL,
        **credential_kwargs(),
    )


def load_vad() -> Any:
    """Silero voice-activity detection. Weights ship inside the plugin wheel.

    Loaded once per worker process by the prewarm hook, not per call: reading the model
    in while a caller waits would put a pause on the front of every conversation.
    """
    return silero.VAD.load()
