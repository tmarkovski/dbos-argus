# Single-stage runtime: install dbos-argus from PyPI and run.
#
# The wheel ships the SvelteKit console SPA inside the package at
# dbos_argus/_console/, so there is no separate JS build stage anymore.
#
# CI passes ARGUS_VERSION=<tag without v prefix> on tagged builds. Local
# `docker build .` without --build-arg installs whatever PyPI marks as latest.

FROM python:3.12-slim

ARG ARGUS_VERSION=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN if [ -n "$ARGUS_VERSION" ]; then \
      pip install "dbos-argus==${ARGUS_VERSION}"; \
    else \
      pip install dbos-argus; \
    fi

EXPOSE 8090

CMD ["dbos-argus", "--host", "0.0.0.0", "--port", "8090"]
