"""An AI receptionist: a caller phones a small business and the agent handles the call.

Two processes ship from one image, and the top level is exactly that split:

    worker/      THE VOICE AGENT  (`agent.py start`) — answers calls, books, texts
    api/         THE WEB SERVICE  (`fastapi run`)    — serves those calls back as JSON
    core/        what both speak: the CallRecord, and the database it lives in
    settings.py  the one place that reads the environment

Four things at the top, and three of them are a process or the seam between them. If a
module is not in `core/`, exactly one process owns it.

The seam is deliberately narrow — `core/` is two entries — and kept that way on
purpose: `CallRecord.business_name` is stamped at call start precisely so the web process
never has to import the agent to render one. A test asserts it doesn't.

`CallRecord` is also what `GET /api/calls/{id}` returns, so the shape the agent writes,
the shape the confirmation text is built from, and the shape the SPA renders are one
object. The SPA itself is not in here: it is a separate origin in `frontend/`, and this
package serves JSON, never markup.
"""
