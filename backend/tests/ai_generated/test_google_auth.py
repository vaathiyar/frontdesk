"""Credential resolution: which of the two channels wins, and in what shape.

The absence assertions matter as much as the presence ones. `credential_kwargs()` must
OMIT a key rather than set it to None, because livekit treats an explicit None as a
supplied value and skips its Application Default Credentials fallback.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from receptionist.settings import Settings, settings
from receptionist.worker.lib.google_auth import (
    CredentialsError,
    credential_kwargs,
    service_account_credentials,
)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
KEY = {"type": "service_account", "client_email": "bot@example.iam.gserviceaccount.com"}


@pytest.fixture
def inline(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(settings, "google_credentials_json", json.dumps(KEY))
    return KEY


@pytest.fixture
def path(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "google_credentials_file_path", "/creds/sa.json")
    return "/creds/sa.json"


def test_nothing_configured_omits_both_keys() -> None:
    """The regression test for the None-is-given bug: {} is not {"credentials_file": None}."""
    assert credential_kwargs() == {}


def test_path_only(path: str) -> None:
    assert credential_kwargs() == {"credentials_file": path}


def test_json_only(inline: dict[str, Any]) -> None:
    assert credential_kwargs() == {"credentials_info": inline}


def test_json_beats_path(inline: dict[str, Any], path: str) -> None:
    kwargs = credential_kwargs()
    assert kwargs == {"credentials_info": inline}
    assert "credentials_file" not in kwargs


def test_blank_json_falls_through_to_path(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.setattr(settings, "google_credentials_json", "   \n ")
    assert credential_kwargs() == {"credentials_file": path}


def test_malformed_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_credentials_json", "{not json")
    with pytest.raises(CredentialsError, match="GOOGLE_CREDENTIALS_JSON"):
        credential_kwargs()


def test_malformed_json_never_leaks_the_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_credentials_json", '{"private_key": "SUPERSECRET"')
    with pytest.raises(CredentialsError) as exc:
        credential_kwargs()
    assert "SUPERSECRET" not in str(exc.value)


def test_malformed_json_does_not_fall_back_to_path(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """A typo must fail loudly, not silently authenticate as whatever the path names."""
    monkeypatch.setattr(settings, "google_credentials_json", "{not json")
    with pytest.raises(CredentialsError):
        credential_kwargs()


@pytest.mark.parametrize("value", ["[]", '"a string"', "null", "12"])
def test_json_that_is_not_an_object_raises(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(settings, "google_credentials_json", value)
    with pytest.raises(CredentialsError, match="JSON object"):
        credential_kwargs()


class RecordingCredentials:
    """Stands in for google.oauth2.service_account.Credentials."""

    calls: list[tuple[str, Any, Any]] = []

    @classmethod
    def from_service_account_info(cls, info: Any, scopes: Any = None) -> str:
        cls.calls.append(("info", info, scopes))
        return "creds-from-info"

    @classmethod
    def from_service_account_file(cls, filename: Any, scopes: Any = None) -> str:
        cls.calls.append(("file", filename, scopes))
        return "creds-from-file"


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> type[RecordingCredentials]:
    RecordingCredentials.calls = []
    monkeypatch.setattr(
        "google.oauth2.service_account.Credentials", RecordingCredentials, raising=True
    )
    return RecordingCredentials


def test_no_credentials_returns_none_without_importing_a_vendor() -> None:
    assert service_account_credentials(SCOPES) is None


def test_credentials_from_inline_json(
    inline: dict[str, Any], recorder: type[RecordingCredentials]
) -> None:
    assert service_account_credentials(SCOPES) == "creds-from-info"
    assert recorder.calls == [("info", inline, SCOPES)]


def test_credentials_from_path(path: str, recorder: type[RecordingCredentials]) -> None:
    assert service_account_credentials(SCOPES) == "creds-from-file"
    assert recorder.calls == [("file", path, SCOPES)]


def test_env_var_is_unprefixed() -> None:
    """Vendor credentials keep their own names; only app settings take RECEPTIONIST_."""
    loaded = Settings(_env_file=None, GOOGLE_CREDENTIALS_JSON="{}")  # type: ignore[call-arg]
    assert loaded.google_credentials_json == "{}"
