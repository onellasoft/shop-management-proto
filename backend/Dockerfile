# syntax=docker/dockerfile:1

# ============================================================================
# Onella backend image (multi-stage)
#
#   base  -> shared runtime + installed dependencies
#   dev   -> hot-reload uvicorn, test deps, runs as root for volume-mounted code
#   prod  -> lean, non-root, no reload
#
# Build a specific stage with:  docker build --target dev  (or --target prod)
# ============================================================================

# ---------------------------------------------------------------------------
# base: common runtime + Python deps
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS base

# - PYTHONDONTWRITEBYTECODE: no .pyc files
# - PYTHONUNBUFFERED: stream logs straight to stdout/stderr
# - PIP_NO_CACHE_DIR: smaller image
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps: build tools for any C-extension wheels (bcrypt, asyncpg) and
# curl for container healthchecks. Removed from the layer once pip is done.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# deps: install the project so its dependency tree is baked into a layer.
# Copying only pyproject.toml first maximizes Docker layer caching: deps are
# only reinstalled when pyproject.toml changes, not on every source edit.
# ---------------------------------------------------------------------------
FROM base AS deps
COPY pyproject.toml ./
# README is referenced by pyproject (readme = "README.md"); copy it so the
# editable install metadata step succeeds.
COPY README.md ./
# Create a placeholder package tree so `pip install -e` can resolve the
# package before the real source is mounted/copied.
RUN mkdir -p app && touch app/__init__.py

# ---------------------------------------------------------------------------
# dev: development image with reload + test extras. Source is bind-mounted by
# docker-compose, so we only need the environment here.
# ---------------------------------------------------------------------------
FROM deps AS dev
RUN pip install -e ".[test]"
# Copy the source as a fallback for running without a bind mount.
COPY . .
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------------------------------------------------------------------------
# prod: lean runtime, no test deps, non-root user, no reload.
# ---------------------------------------------------------------------------
FROM deps AS prod
RUN pip install .
COPY . .
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
