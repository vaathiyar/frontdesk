"""The app, and the routers it includes.

A health check and nothing else today. The server-rendered call-detail page this used to
serve has been retired, and the JSON API that replaces it is not built yet — when it is,
it is one more `include_router` below.
"""

from __future__ import annotations

from fastapi import FastAPI

from receptionist.api.routes import health

app = FastAPI(title="Receptionist", docs_url=None, redoc_url=None)
app.include_router(health.router)
