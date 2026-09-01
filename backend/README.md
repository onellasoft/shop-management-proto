# Onella Backend

FastAPI async backend providing authentication, RBAC, multi-tenancy,
impersonation, and asynchronous append-only audit logging.

## Stack

- FastAPI (async) + Uvicorn
- PostgreSQL via SQLAlchemy (async) + Alembic
- Redis (OTP store, agency customer-list cache, Celery broker)
- Celery (async audit logging)
- PyJWT, Pydantic v2, passlib[bcrypt]

## Layout

```
app/
  core/        config, security, errors, tenant context
  db/          async engine, session, base, mixins
  models/      SQLAlchemy models
  schemas/     Pydantic request/response models
  services/    auth, authorization, impersonation, audit
  api/         deps + routers
  middleware/  auth + tenant middleware
  cache/       redis client + caches
  tasks/       celery app + audit tasks
tests/
  unit/  integration/  property/
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest
```
