"""What build_stt/build_tts actually hand the vendor.

Constructing the real plugins would authenticate, so the plugin classes are swapped for
recorders. The point of these tests is the credential kwarg — including its absence — and
that the model/voice constants survive the `**kwargs` splat.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from receptionist.agent import providers
from receptionist.settings import settings

KEY = {"type": "service_account", "client_email": "bot@example.iam.gserviceaccount.com"}


class Recorder:
    last: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).last = kwargs


@pytest.fixture
def stt(monkeypatch: pytest.MonkeyPatch) -> type[Recorder]:
    Recorder.last = {}
    monkeypatch.setattr(providers.google, "STT", Recorder)
    return Recorder


@pytest.fixture
def tts(monkeypatch: pytest.MonkeyPatch) -> type[Recorder]:
    Recorder.last = {}
    monkeypatch.setattr(providers.google, "TTS", Recorder)
    return Recorder


def test_stt_omits_credentials_when_unconfigured(stt: type[Recorder]) -> None:
    """Neither key present is what reaches Application Default Credentials.

    `credentials_file=None` would not: livekit's is_given(None) is True, so STT skips its
    ADC preflight and later crashes on load_credentials_from_file(None).
    """
    providers.build_stt()
    assert "credentials_file" not in stt.last
    assert "credentials_info" not in stt.last


def test_tts_omits_credentials_when_unconfigured(tts: type[Recorder]) -> None:
    providers.build_tts()
    assert "credentials_file" not in tts.last
    assert "credentials_info" not in tts.last


def test_stt_passes_inline_json(monkeypatch: pytest.MonkeyPatch, stt: type[Recorder]) -> None:
    monkeypatch.setattr(settings, "google_credentials_json", json.dumps(KEY))
    providers.build_stt()
    assert stt.last["credentials_info"] == KEY
    assert "credentials_file" not in stt.last


def test_tts_passes_inline_json(monkeypatch: pytest.MonkeyPatch, tts: type[Recorder]) -> None:
    monkeypatch.setattr(settings, "google_credentials_json", json.dumps(KEY))
    providers.build_tts()
    assert tts.last["credentials_info"] == KEY


def test_stt_passes_path(monkeypatch: pytest.MonkeyPatch, stt: type[Recorder]) -> None:
    monkeypatch.setattr(settings, "google_credentials_file_path", "/creds/sa.json")
    providers.build_stt()
    assert stt.last["credentials_file"] == "/creds/sa.json"
    assert "credentials_info" not in stt.last


def test_stt_keeps_its_constants(stt: type[Recorder]) -> None:
    providers.build_stt()
    assert stt.last["model"] == providers.STT_MODEL
    assert stt.last["languages"] == providers.STT_LANGUAGES
    assert stt.last["location"] == providers.STT_LOCATION


def test_tts_keeps_its_constants(tts: type[Recorder]) -> None:
    providers.build_tts()
    assert tts.last["voice_name"] == providers.TTS_VOICE
    assert tts.last["model_name"] == providers.TTS_MODEL
