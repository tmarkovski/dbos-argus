# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /app

# Copy workspace manifests first so the uv resolver cache is reused on source-only changes.
COPY pyproject.toml ./
COPY packages/server/pyproject.toml packages/server/README.md ./packages/server/

# Stub so uv can resolve the workspace member during the first sync.
RUN mkdir -p packages/server/dbos_argus \
 && touch packages/server/dbos_argus/__init__.py

RUN uv sync

# Now add real source.
COPY packages/server ./packages/server

RUN uv sync

WORKDIR /app/packages/server

EXPOSE 8090

CMD ["sh", "-c", "uv run --project /app alembic -c alembic.ini upgrade head && uv run --project /app uvicorn dbos_argus.main:app --host 0.0.0.0 --port 8090"]
