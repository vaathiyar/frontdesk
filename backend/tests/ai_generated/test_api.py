"""The web process. One route so far, and the seam that keeps it small."""

from __future__ import annotations

import subprocess
import sys

from fastapi.testclient import TestClient

from receptionist.api.app import app

client = TestClient(app)


def test_healthz_is_answerable() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_an_unknown_route_is_not_found() -> None:
    """Nothing else is served yet — the JSON API lands beside the health router."""
    assert client.get("/c/whatever").status_code == 404


def test_the_web_process_does_not_import_the_agent() -> None:
    """`CallRecord.business_name` is stamped at call start precisely so this holds.

    Reaching into `worker/profiles/` for that one string costs ~600ms of boot and 188
    langchain/langgraph modules, because a profile carries its agent's tools. A failure
    here means something under `api/` reached into `worker/`.

    Run in a subprocess: this test session has already imported everything.
    """
    probe = (
        "import receptionist.api.app, sys;"
        "print('\\n'.join(sorted(m for m in sys.modules if m.startswith("
        "('langchain', 'langgraph', 'livekit', 'googleapiclient', 'receptionist.worker')"
        "))))"
    )
    leaked = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    ).stdout.strip()

    assert leaked == "", f"importing the api dragged in:\n{leaked}"
