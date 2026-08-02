# syntax=docker/dockerfile:1
#
# One image, two processes:
#
#   agent.py start   the LiveKit voice worker — answers calls, dials OUT to LiveKit,
#                    exposes no ports
#   fastapi run      the JSON API the SPA reads — needs an inbound port
#
# Both talk to the same CockroachDB cluster (RECEPTIONIST_DATABASE_URL): the worker
# writes each finished call, the web process serves the one a texted link refers to.
# Nothing is stored in the container, so there is no volume to mount.
#
#   docker build -t receptionist .                      # context: backend/
#   docker compose -f deploy/docker-compose.yml up -d    # both services
#
# See deploy/README.md for env vars and SIP setup.

ARG PYTHON_VERSION=3.13
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base
# UV_NO_SYNC: `uv run` re-syncs by default AND pulls in the dev group, which would undo
# `uv sync --no-dev` and reinstall pytest/mypy/ruff on every container start. With deps
# installed explicitly below, this keeps startup instant, offline and dev-free.
# HF_HOME under /app so model weights baked at build time land in the final image and
# stay readable by the non-root runtime user.
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_SYNC=1 \
    HF_HOME=/app/.cache/huggingface

FROM base AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ python3-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Third-party deps first, in a layer keyed only on the lockfile, so source-only changes
# don't reinstall them. --no-install-project: our own package needs src/, not copied yet.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
RUN uv sync --locked --no-dev
# Bake the Silero VAD weights in so a cold container doesn't make the first caller wait.
# Invoked through the module, not `agent.py download-files`, which livekit-agents
# deprecated in 1.5.10 — and the module form fetches all three plugins, not just one.
RUN uv run python -m livekit.agents download-files

FROM base
ARG UID=10001
# onnxruntime (Silero VAD) needs libgomp at runtime; not in the slim base.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN adduser --disabled-password --gecos "" --home /app --shell /sbin/nologin --uid ${UID} appuser
WORKDIR /app
COPY --from=build --chown=appuser:appuser /app /app
USER appuser
# The voice worker by default. A fixed CMD with no wrapper script, so LiveKit's graceful
# drain on SIGTERM reaches the process and live calls aren't cut off mid-sentence.
CMD ["uv", "run", "agent.py", "start"]
