#!/usr/bin/env bash
# ============================================================================
# Backend container entrypoint.
#
# Optionally applies database migrations, then execs the given command
# (uvicorn by default, or a celery worker, or a one-off management command).
#
# Migrations:
#   `alembic upgrade head` is idempotent -- Alembic tracks applied revisions in
#   the `alembic_version` table, so re-running has no effect once at head.
#   Controlled by RUN_MIGRATIONS (default "1"). Set RUN_MIGRATIONS=0 to skip and
#   run migrations manually instead (see README).
#
# NOTE: For multi-replica production, prefer a dedicated one-shot `migrate`
# service (see docker-compose.prod.yml) and set RUN_MIGRATIONS=0 on the app
# replicas so they don't race each other applying migrations on boot.
# ============================================================================
set -euo pipefail

RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"

if [ "${RUN_MIGRATIONS}" = "1" ]; then
    echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
    alembic upgrade head
    echo "[entrypoint] Migrations up to date."
else
    echo "[entrypoint] RUN_MIGRATIONS=0 -> skipping migrations."
fi

echo "[entrypoint] Starting: $*"
exec "$@"
