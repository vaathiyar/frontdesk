"""The phone line: everything LiveKit, and nothing else.

    session.py  the job entrypoint, the Agent subclass, and the session wiring
    speech.py   STT / TTS / VAD — the only place a speech vendor is named

Kept apart from `agent/` because these change for different reasons: `agent/` changes
when the receptionist should behave differently, this changes when telephony does.
"""
