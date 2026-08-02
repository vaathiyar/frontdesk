"""One call, by id — what the link in every confirmation text resolves to.

The response model is `CallRecord` itself, not a view of it. The agent's tools write that
type, the SMS is composed from it, and the SPA renders it; giving the API its own schema
would be a fourth shape to keep in step with the other three.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from receptionist.api.deps import StoreDep
from receptionist.core.models import CallRecord

router = APIRouter(prefix="/api", tags=["calls"])


@router.get("/calls/{call_id}")
async def get_call(call_id: UUID, store: StoreDep) -> CallRecord:
    """The whole record, straight out of the blob.

    Unauthenticated by design: knowing the id is the only thing standing between a
    stranger and this call. The id is a random UUID and the link goes out to the caller's
    own phone, which is the level of protection a demo warrants — but it is protection by
    obscurity, and it is worth saying so out loud rather than leaving it to be inferred.
    """
    record = await store.get(call_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return record
