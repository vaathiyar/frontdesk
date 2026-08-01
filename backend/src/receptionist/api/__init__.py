"""The web process: FastAPI.

    app.py      the app, and the routers it includes
    routes/     one module per resource

Only the health check exists today. The JSON API the SPA reads is specified in
`docs/frontend_spec.md` §7 and lands here as `routes/calls.py` plus its response schemas.
"""
