"""The voice agent: one process, one job per call. Run by `agent.py start`.

    voice/        LiveKit — the phone line and the speech stack
    agent/        LangGraph — the loop, the prompt, the tools
    booking/      the calendar it books against
    messaging/    the confirmation text it sends afterwards
    profiles/     which businesses we answer as, and what each agent may do
    lib/          time, phone numbers, Google credentials — no domain state
    lifecycle.py  what happens when a call ends: text, then persist

`lifecycle.py` is the only module at this level on purpose: it is the spine, coordinating
`messaging/` and `core/` once the call is over. It holds no LiveKit, which is why it sits
here rather than in `voice/` — a second way for a call to arrive would reuse it unchanged.

Nothing under `api/` imports anything from here, and nothing here is needed to read a
finished call.
"""
