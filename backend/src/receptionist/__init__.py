"""An AI receptionist: a caller phones a small business and the agent handles the call.

Two processes ship from one image, and the top level is exactly that split:

    worker/      THE VOICE AGENT  (`agent.py start`) — answers calls, books, texts
    api/         THE WEB SERVICE  (`fastapi run`)    — serves those calls back
    core/        what both speak: the CallRecord, and where it is stored
    settings.py  the one place that reads the environment

Four things at the top, and three of them are a process or the seam between them. If a
module is not in `core/`, exactly one process owns it.

The seam is deliberately narrow — `core/` is two modules — and kept that way on
purpose: `CallRecord.business_name` is stamped at call start precisely so the web process
never has to import the agent to render one. A test asserts it doesn't.
"""
