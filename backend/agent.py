"""LiveKit worker entrypoint file (LiveKit CLI convention).

Run with the standard subcommands:

    uv run agent.py dev             # dev worker against a LiveKit server
    uv run agent.py start           # production worker
    uv run agent.py download-files  # fetch model files (e.g. Silero VAD weights)

Every call arrives over SIP: the dispatch rule says which business it is for, so there is
no local no-telephony mode. The worker refuses to start unless every registered profile
has a Google Calendar configured.

`.env` is loaded into the process environment first so the LiveKit SDK sees its connection
vars (LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET). Gemini and the Google Cloud
clients get their credentials via settings (GOOGLE_API_KEY, and the service account from
GOOGLE_CREDENTIALS_JSON or GOOGLE_CREDENTIALS_FILE_PATH), which reads `.env` directly.
This runs before importing the worker, which pulls in settings/providers at import time.
"""

import dotenv

dotenv.load_dotenv()

from receptionist.worker.voice.session import main  # noqa: E402  (must follow load_dotenv)

if __name__ == "__main__":
    main()
