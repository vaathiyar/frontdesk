"""The brain: the LangGraph loop, the tools it can call, and the prompt behind it.

    graph.py    build_graph — the two-node loop
    tools.py    what the agent can actually do, and the per-call CallContext
    prompt.py   the one system prompt

Nothing here knows about telephony; `worker/voice/` drives this on a real call, and the
suite drives the same compiled graph by text.

Deliberately empty of re-exports. A profile owns its own `book` tool, so
`worker/profiles/` imports `worker/agent/tools.py`, while `graph.py` imports
`worker/profiles/` — re-exporting `graph` from here would close that loop into a circular
import. Import the module you want directly.
"""
