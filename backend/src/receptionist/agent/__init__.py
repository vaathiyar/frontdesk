"""The brain: the LangGraph loop, the tools it can call, and the prompt behind it.

    graph.py    build_graph + Conversation — the two-node loop and its text driver
    tools.py    what the agent can actually do, and the per-call CallContext
    prompt.py   the one system prompt

Deliberately empty of re-exports. A profile owns its own `book` tool, so
`receptionist.profiles` imports `receptionist.agent.tools`, while `graph.py` imports
`receptionist.profiles` — re-exporting `graph` from here would close that loop into a
circular import. Import the module you want directly.
"""
