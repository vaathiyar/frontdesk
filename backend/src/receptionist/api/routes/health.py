"""Liveness, for the platform's health check.

Deliberately says nothing about the call database: this answers "is the process up",
which is the only question a load balancer should be asking it.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}
