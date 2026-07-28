"""Serve the call-detail page that confirmation texts link to.

    uv run python serve.py

Reads RECEPTIONIST_PUBLIC_BASE_URL (what the links in texts point at),
RECEPTIONIST_LINK_SECRET (must match the worker's, or every link 404s) and
RECEPTIONIST_DATABASE_PATH (the SQLite file the worker writes).
"""

import os

import dotenv
import uvicorn

dotenv.load_dotenv()

if __name__ == "__main__":
    uvicorn.run(
        "receptionist.web.app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
