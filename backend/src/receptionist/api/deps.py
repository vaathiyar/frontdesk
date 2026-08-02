"""What the routes depend on.

One dependency today. It is declared as the `CallStore` **protocol** rather than the
concrete `SqlCallStore` so a route can be exercised against a double via
`app.dependency_overrides` — which is what keeps the suite free of a database.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from receptionist.core.db.store import CallStore, SqlCallStore


def call_store() -> CallStore:
    return SqlCallStore()


StoreDep = Annotated[CallStore, Depends(call_store)]
