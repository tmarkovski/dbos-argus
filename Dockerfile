# syntax=docker/dockerfile:1.7

# ---------- stage 1: build the Svelte console into static files ----------
FROM node:22-slim AS console-builder

RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

WORKDIR /repo

# Install deps first for layer caching.
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* turbo.json ./
COPY apps/console/package.json ./apps/console/
COPY packages/ui/package.json ./packages/ui/
COPY packages/client-ts/package.json ./packages/client-ts/

RUN pnpm install --no-frozen-lockfile

COPY apps/console ./apps/console
COPY packages/ui ./packages/ui
COPY packages/client-ts ./packages/client-ts

RUN pnpm --filter console build

# ---------- stage 2: Python runtime with FastAPI serving the console ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARGUS_CONSOLE_DIR=/app/console

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /app

# Resolve deps from workspace manifests first for caching.
COPY pyproject.toml ./
COPY packages/server/pyproject.toml packages/server/README.md ./packages/server/

RUN mkdir -p packages/server/dbos_argus \
 && touch packages/server/dbos_argus/__init__.py

RUN uv sync

COPY packages/server ./packages/server

RUN uv sync

# Bring the built console into the image at ARGUS_CONSOLE_DIR.
COPY --from=console-builder /repo/apps/console/build /app/console

WORKDIR /app/packages/server

EXPOSE 8090

CMD ["sh", "-c", "uv run --project /app alembic -c alembic.ini upgrade head && uv run --project /app uvicorn dbos_argus.main:app --host 0.0.0.0 --port 8090"]
