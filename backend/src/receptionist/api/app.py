"""The app, and the routers it includes.

Two routers: liveness, and the one call the texted link points at. The app serves JSON
and never markup — the SPA is a separate origin, deployed separately, which is why CORS
is configured here at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from receptionist.api.routes import calls, health
from receptionist.core.db.engine import dispose, require_database
from receptionist.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Refuse to start without a database, and give the pool back on the way out.

    Checked here rather than on the first request for the same reason the worker checks
    it before registering: a misconfigured process that boots looks healthy to whatever
    is watching it, and only the caller who follows their link finds out otherwise.
    """
    require_database()
    yield
    await dispose()


app = FastAPI(title="Receptionist", docs_url=None, redoc_url=None, lifespan=lifespan)

# The SPA is hosted elsewhere, so the browser calls this from another origin. Read-only
# and unauthenticated, so there is nothing to protect with credentials — the allowlist is
# here to keep the surface named rather than to guard anything.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(calls.router)
