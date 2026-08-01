"""Which Google service-account credential to use, and in what shape.

Two channels, because deploying and developing want different things:

    GOOGLE_CREDENTIALS_JSON       the key file's contents, in one variable
    GOOGLE_CREDENTIALS_FILE_PATH  a path to that file on disk

**Inline JSON wins when both are set.** It is the deploy-time channel, injected per
environment by whatever runs the container; the path is the local one, living in a `.env`
that gets copied between machines and easily names a file that does not exist inside a
container. If the path won, setting the JSON on a platform would appear to do nothing.

Inline also exists because a path is not always mountable. Coolify rejects variable
substitution in a compose volume source outright, so the usual `${CREDS}:/secrets/sa.json`
recipe cannot be expressed there at all — see deploy/README.md.

Malformed JSON raises instead of falling back to the path: quietly authenticating as a
stale identity is worse than a loud failure.

Vendor imports stay inside the functions, as in booking/google.py — importing
this module must not drag google-auth into processes that never speak to Google.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from receptionist.settings import settings


class CredentialsError(RuntimeError):
    """GOOGLE_CREDENTIALS_JSON is set but cannot be used."""


def _service_account_info() -> dict[str, Any] | None:
    """The parsed inline key, or None when it is unset or blank.

    Blank counts as unset: a platform UI that holds an empty string for a variable is
    saying the same thing as one that has no variable at all.
    """
    raw = settings.google_credentials_json.strip()
    if not raw:
        return None

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        # `exc` carries a position, never document content — do not widen this message to
        # include the value, a prefix of it, or its length.
        raise CredentialsError(
            f"GOOGLE_CREDENTIALS_JSON is not valid JSON ({exc}). It must be the whole "
            "service-account key on a single line — `jq -c . < service-account.json`. In "
            ".env leave it unquoted or single-quoted, never double-quoted."
        ) from exc

    if not isinstance(info, dict):
        raise CredentialsError(
            "GOOGLE_CREDENTIALS_JSON must be the service-account JSON object, not a "
            f"{type(info).__name__}."
        )
    return info


def credential_kwargs() -> dict[str, Any]:
    """Keyword arguments naming the credential, splatted into the livekit google plugins.

    The key is **omitted** when nothing is configured, never passed as None. livekit's
    `is_given()` is `not isinstance(obj, NotGiven)`, so an explicit None counts as *given*:
    `google.STT` would skip its Application Default Credentials preflight and then hand
    that None to `load_credentials_from_file` at first use — a crash mid-call rather than
    the intended fallback. Omitting the key is what actually reaches ADC.
    """
    info = _service_account_info()
    if info is not None:
        return {"credentials_info": info}
    if settings.google_credentials_file_path:
        return {"credentials_file": settings.google_credentials_file_path}
    return {}


def service_account_credentials(scopes: Sequence[str]) -> Any:
    """google-auth credentials for the configured service account, or None if there is none.

    Returns before importing the vendor package when nothing is configured, so the caller
    gets to raise its own error on a machine where google-auth is absent.
    """
    info = _service_account_info()
    path = settings.google_credentials_file_path
    if info is None and not path:
        return None

    from google.oauth2.service_account import Credentials

    if info is not None:
        return Credentials.from_service_account_info(info, scopes=list(scopes))
    return Credentials.from_service_account_file(path, scopes=list(scopes))
