# syntax=docker/dockerfile:1
#
# Receptionist LiveKit voice-agent worker (self-hosted LiveKit).
#
#   Build context: backend/     ->  docker build -t receptionist-agent .
#
# The worker dials OUT to your livekit-server over a WebSocket and registers as the
# agent "receptionist" (explicit dispatch). It exposes NO inbound ports.
#
# Required runtime env:
#   LIVEKIT_URL                     wss:// URL of your self-hosted livekit-server
#   LIVEKIT_API_KEY                 API key for that server
#   LIVEKIT_API_SECRET             API secret for that server
#   GOOGLE_API_KEY                  Gemini API key (the agent's "brain")
#   GOOGLE_CREDENTIALS_FILE_PATH  path to the GCP service-account JSON for Cloud
#                                   Speech-to-Text + Text-to-Speech. Mount the JSON
#                                   as a file/secret and point this var at it, e.g.
#                                     -v /abs/sa.json:/secrets/sa.json \
#                                     -e GOOGLE_CREDENTIALS_FILE_PATH=/secrets/sa.json
#
# See deploy/README.md for the full build/run + SIP setup guide.

ARG PYTHON_VERSION=3.13
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base
# UV_NO_SYNC makes `uv run` use the venv exactly as we built it, instead of re-syncing.
# Why it matters: `uv run` re-syncs the environment by default and INCLUDES the `dev`
# dependency group — so it would undo our `uv sync --no-dev`, reinstalling mypy/ruff/pytest
# into the runtime image AND rebuilding the project + recompiling bytecode on every
# container start. With deps installed explicitly (below) this keeps both the build's
# download-files step and the runtime CMD dev-free, offline, and instant to start.
# HF_HOME keeps any downloaded model cache under /app so weights baked at build time are
# copied into the final image and stay readable by the non-root runtime user. (Silero VAD's
# own ONNX weights ship inside the livekit-plugins-silero wheel, so they are baked in too.)
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_SYNC=1 \
    HF_HOME=/app/.cache/huggingface

FROM base AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ python3-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# 1) Install third-party deps first, in a layer keyed only on the lockfile so it is
#    cached across source-only changes. --no-install-project: our own package needs
#    src/, which isn't copied yet.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
# 2) Add the source and install the project itself.
COPY . .
RUN uv sync --locked --no-dev
# 3) Bake Silero VAD (and any turn-detector) weights into the image for fast cold starts.
#    UV_NO_SYNC (set in `base`) makes this run in the --no-dev venv from step 2 without
#    re-syncing, so no dev deps leak in here.
RUN uv run agent.py download-files

FROM base
ARG UID=10001
# onnxruntime (Silero VAD) needs libgomp at runtime; not pulled in by the slim base.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN adduser --disabled-password --gecos "" --home /app --shell /sbin/nologin --uid ${UID} appuser
WORKDIR /app
COPY --from=build --chown=appuser:appuser /app /app
USER appuser
# The worker dials OUT to LiveKit over WebSocket; no inbound ports are needed.
CMD ["uv", "run", "agent.py", "start"]
