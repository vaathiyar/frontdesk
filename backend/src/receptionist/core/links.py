"""Signed, unguessable — but non-expiring — links to a call's detail view.

The same secret signs (in the agent, to build the email hardlink) and verifies
(in the web app). No expiry, per design: a stable link owners can revisit.
"""

from __future__ import annotations

import hashlib
import hmac
from uuid import UUID

from receptionist.core.settings import settings


def sign(call_id: UUID, secret: str | None = None) -> str:
    key = (secret or settings.link_secret).encode()
    return hmac.new(key, str(call_id).encode(), hashlib.sha256).hexdigest()


def verify(call_id: UUID, token: str, secret: str | None = None) -> bool:
    """Constant-time comparison so a bad token leaks no timing signal."""
    return hmac.compare_digest(sign(call_id, secret), token)
