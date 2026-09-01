# Shop Management SaaS

A multi-tenant shop management platform, split into an async FastAPI backend
and a React single-page frontend. The backend (Onella) handles authentication,
role-based access control, multi-tenancy, impersonation, and asynchronous
append-only audit logging. The frontend delivers super-admin and business-admin
dashboards for managing businesses, users, subscriptions, contacts, campaigns,
and WhatsApp messaging.

## Repository Layout

```
.
|-- backend/     FastAPI async service (Onella)
`-- frontend/    React + Vite + Tailwind SPA
```

## Running with Docker (recommended)

The whole stack — Postgres, Redis, the FastAPI backend, a Celery worker, and
the frontend — is orchestrated with Docker Compose.

### First run

    cp .env.example .env       # then edit values as needed
    docker compose up --build

This starts:

| Service    | URL / port                | Notes                                  |
| ---------- | ------------------------- | -------------------------------------- |
| frontend   | http://localhost:4300     | Vite dev server (HMR)                  |
| backend    | http://localhost:8000     | FastAPI (health at `/health`)          |
| postgres   | localhost:5432            | data persisted in a named volume       |
| redis      | localhost:6379            | Celery broker/backend, caches          |
| worker     | —                         | Celery worker for async tasks          |

The frontend proxies `/api/*` to the backend, so browser calls hit a single
origin. Source directories are bind-mounted, so backend and frontend changes
hot-reload without rebuilding.

### Database migrations

Migrations run automatically when the backend container starts
(`alembic upgrade head`). This is **idempotent** — Alembic records applied
revisions, so re-running has no effect once the database is at head.

To run them manually instead, set `RUN_MIGRATIONS=0` in `.env` and use:

    # one-off container
    docker compose run --rm backend alembic upgrade head

    # against the running backend
    docker compose exec backend alembic upgrade head

    # roll back one revision
    docker compose exec backend alembic downgrade -1

### Seeding development data

An idempotent seed script populates a demo agency, customers, and admin users
with their roles, module subscriptions, and mobile numbers (safe to run repeatedly):

When the stack is running:

    docker compose exec backend python -m app.scripts.seed

Or as a one-off (if the stack isn't running):

    docker compose run --rm backend python -m app.scripts.seed

Seeded credentials (all with password `Password123!`):

| Email | Mobile | Role |
|-------|--------|------|
| `superadmin@onella.test` | +919561311757 | superadmin |
| `agencyadmin@onella.test` | +917588611478 | agencyadmin |
| `admin.apex@onella.test` | +919876543210 | customeradmin |
| `admin.grocers@onella.test` | +919123456789 | customeradmin |

Login on the frontend using either **email + password** or **mobile + OTP**. For OTP, read the code from Redis:

    docker compose exec redis redis-cli GET "otp:code:+919561311757"

### Production

A production override builds lean, non-root images, serves the frontend via
nginx, and applies migrations with a dedicated one-shot `migrate` service (so
scaled backend replicas don't race on startup):

    export JWT_SECRET=<a-strong-secret>
    docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d

## Backend (`backend/`)

FastAPI async service providing auth, RBAC, multi-tenancy, impersonation, and
async audit logging.

**Stack:** FastAPI + Uvicorn, PostgreSQL via async SQLAlchemy + Alembic, Redis
(OTP store, caches, Celery broker), Celery, PyJWT, Pydantic v2, passlib[bcrypt].

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
tests/         unit / integration / property
```

### Setup

    cd backend
    python -m venv .venv && source .venv/bin/activate
    pip install -e ".[test]"

### Run

    uvicorn app.main:app --reload

The app exposes a health probe at `GET /health` plus auth and module routers.

### Test

    pytest

## Frontend (`frontend/`)

React 19 SPA built with Vite and styled with Tailwind CSS. Uses React Router,
Recharts for reporting, Framer Motion for animation, and lucide/react-icons.

### Setup

    cd frontend
    npm install

### Run

    npm run dev

The Vite server starts on port 4300.

### Build

    npm run build      # outputs to dist/
    npm run preview    # preview the production build

## Environment

Copy any provided `.env.example` files to `.env` in the respective package
before running. Environment files are git-ignored.
