"""The web process: FastAPI.

    app.py      the app, the CORS allowlist, and the routers it includes
    deps.py     what routes depend on — the CallStore seam
    routes/     one module per resource: health.py, calls.py

`GET /api/calls/{id}` is the whole API. It returns `CallRecord` directly, and it is what
the link in every confirmation text resolves to. Serving markup is not this process's
job: the SPA is a separate origin.
"""
