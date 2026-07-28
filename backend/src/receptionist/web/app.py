"""The web app: the call-detail page that every confirmation text links to.

One route that matters. Every way of failing to produce a page — malformed id, missing
token, wrong token, unknown call, a profile we no longer serve — returns the *same* 404,
so the response can never be used to work out which call ids exist.
"""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from receptionist.links import verify
from receptionist.models import CallRecord
from receptionist.profiles import UnknownProfile, get_profile
from receptionist.store import CallStore
from receptionist.web import page

app = FastAPI(title="Receptionist", docs_url=None, redoc_url=None)


@lru_cache
def store() -> CallStore:
    """Opened on first request, not at import, so nothing creates a database file just
    by importing this module."""
    return CallStore()


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/c/{call_id}", response_class=HTMLResponse)
async def call_detail(call_id: str, t: str = "") -> HTMLResponse:
    record = await _authorised(call_id, t)
    if record is None:
        return HTMLResponse(page.not_found(), status_code=404)
    try:
        profile = get_profile(record.profile_id)
    except UnknownProfile:
        return HTMLResponse(page.not_found(), status_code=404)
    return HTMLResponse(page.render(profile, record))


async def _authorised(call_id: str, token: str) -> CallRecord | None:
    try:
        wanted = UUID(call_id)
    except ValueError:
        return None
    if not token or not verify(wanted, token):
        return None
    return await store().get(wanted)
