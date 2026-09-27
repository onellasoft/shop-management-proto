# Onella SaaS

A multi-tenant B2B SaaS platform for WhatsApp marketing and customer engagement. Agencies onboard and manage businesses (customers); businesses manage contacts, segments, templates, and campaigns.

---

## Architecture

```
Platform (superadmin)
  └── Agency (agencyadmin)
        └── Customer / Business (customeradmin + custom roles)
```

| Component | Purpose | Stack |
|-----------|---------|-------|
| **Backend** | REST API, auth, RBAC, multi-tenancy, impersonation, audit | FastAPI, PostgreSQL, Redis, Celery |
| **Frontend** | Web dashboards (SPA) | React 19, Vite, Tailwind CSS, React Router |

```
[Browser] → [Vite :4300] → [/api/* proxy] → [FastAPI :8000]
                                                    ↓
                                           [PostgreSQL] + [Redis]
                                           [Celery worker]
```

---

## Quick Start

### Prerequisites
- Docker & Docker Compose

### Run the stack

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:4300 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

### Seed test data

```bash
docker compose exec backend python -m app.scripts.seed
```

#### Test credentials (password: `Password123!`)

| Email | Mobile | Role |
|-------|--------|------|
| `superadmin@onella.test` | +919561311757 | superadmin |
| `agencyadmin@onella.test` | +917588611478 | agencyadmin |
| `admin.apex@onella.test` | +919876543210 | customeradmin (Apex Retail) |
| `admin.grocers@onella.test` | +919123456789 | customeradmin (Local Grocers) |

#### OTP login (development)

1. Enter a mobile number and click **Send OTP**
2. Read the OTP from Redis:
   ```bash
   docker compose exec redis redis-cli GET "otp:code:+919561311757"
   ```
3. Enter the OTP and click **Verify OTP**

---

## Backend

### Stack

FastAPI (async) · PostgreSQL via SQLAlchemy 2 + Alembic · Redis · Celery · PyJWT · Pydantic v2 · bcrypt

### Project layout

```
backend/
  app/
    core/          config, security (JWT/bcrypt), errors, TenantContext
    db/            async engine, session factory, mixins, tenant_query helper
    models/        SQLAlchemy ORM models (all 5 phases)
    schemas/       Pydantic request/response schemas
    services/      auth, authorization, impersonation, audit
    api/
      deps.py      require_permission, get_tenant_context, get_current_user
      routers/     auth, modules, impersonation, audit
    middleware/    AuthTenantMiddleware (JWT decode + TenantContext build)
    cache/         redis client, OTP store, agency customer-list cache
    audit/         mutation_capture (SQLAlchemy events, old/new diff, enqueue)
    tasks/         celery_app, audit_tasks (write_audit_log)
  alembic/         migrations (6 revisions, head: 5audit01)
  tests/
    unit/          297 tests
    property/      10 Hypothesis property-test files (31 properties, Phases 3–5)
```

### Database migrations (6 revisions)

| Revision | Description |
|----------|-------------|
| `fc94b119d8b4` | Core tables: agencies, customers, users, customer_users |
| `2fabperm01` | Permission graph (modules/submodules/resources/actions) + roles seed |
| `3fabsubs01` | Customer subscriptions |
| `3refresh01` | Refresh tokens (rotation + reuse detection) |
| `4imprs01` | Impersonation sessions |
| `5audit01` | Audit logs + audit failures + append-only DB trigger |

### API endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/auth/login` | — | Email + password → JWT pair |
| `POST` | `/auth/otp/request` | — | Request OTP (mobile) |
| `POST` | `/auth/otp/verify` | — | Verify OTP → JWT pair |
| `POST` | `/auth/refresh` | Bearer | Rotate refresh token |
| `POST` | `/auth/logout` | Bearer | Revoke token + chain |
| `GET` | `/modules/catalog` | Bearer | Module catalog with subscription state |
| `POST` | `/modules/subscriptions` | Bearer | Subscribe a customer to a module |
| `DELETE` | `/modules/subscriptions` | Bearer | Remove subscription |
| `POST` | `/impersonation/start` | Bearer | Start impersonation session |
| `POST` | `/impersonation/end` | Bearer | End active session |
| `GET` | `/impersonation/current` | Bearer | Current session indicator |
| `GET` | `/audit/logs` | Bearer | Query audit logs (tenant-isolated) |
| `GET` | `/audit/logs/export` | Bearer | Export logs as CSV or JSON |

### Running locally without Docker

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
uvicorn app.main:app --reload    # starts on :8000
pytest tests/unit                # fast unit tests (~15s, no infra needed)
```

---

## Frontend

### Stack

React 19 · Vite · Tailwind CSS · React Router · Recharts · Framer Motion · lucide-react

### Running locally

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev    # starts on :4300
```

---

## What each role sees on the UI

### Superadmin

Platform-level administrator. Routes to `/super-admin/*`.

| Screen | What they can do |
|--------|-----------------|
| **Dashboard** | Platform-wide stats: total agencies, active agencies, total messages sent, campaigns |
| **Business Management** | View all businesses across all agencies; activate / suspend any |
| **Platform Users** | View and manage all users across the platform |
| **Module Management** | Manage the global module / submodule / resource / action catalog |
| **Subscription Plans** | Define and manage subscription plans |
| **Audit Logs** | Full audit history across all agencies and customers |
| **Settings** | Platform-wide settings |
| **KYC Verification** | Review and approve KYC submissions |
| **Impersonation** | Can start a session impersonating any agency or any customer; UI shows an "IMPERSONATING" banner with EXIT button |

### Agencyadmin

Scoped to their single agency. Routes to `/agency/*`.

| Screen | What they can do |
|--------|-----------------|
| **Dashboard** | Agency stats: active businesses, total broadcasts, total contacts, delivery rates |
| **Business Management** | View and manage only businesses under their agency; add / suspend businesses |
| **Audit Logs** | Audit history scoped to their agency only |
| **Settings** | Agency-level settings |
| **Impersonation** | Can start a session impersonating any customer they manage; UI shows banner + EXIT |

### Customeradmin

Scoped to their assigned businesses. Routes to `/business/*`.

| Screen | What they can do |
|--------|-----------------|
| **Dashboard** | Business metrics: total contacts, segments, templates, campaigns run, delivery success %, live message log |
| **Contacts** | View, import, and manage customer contacts |
| **Groups / Segments** | Create and manage contact segments |
| **Templates** | Browse and manage message templates (Marketing / Utility / Auth) |
| **Campaigns** | Create, schedule, and broadcast campaigns to segments |
| **Import Wizard** | Bulk import contacts via CSV |
| **WhatsApp Numbers** | Connect and manage WhatsApp business numbers |
| **Campaign Reports** | Per-campaign delivery stats |
| **Audit Logs** | Audit history scoped to their business only |
| **Settings** | Business-level settings |

---

## Flexible roles (custom roles for customeradmin)

### What's implemented in the backend ✅

The backend fully implements the custom roles system:

- **Default roles seeded:** `finance_manager`, `staff`, `inventory_manager` available to every customer out of the box
- **CRUD operations:** customeradmin can create, edit, clone, and delete custom roles within their business via `AuthorizationService`
- **Subscription-gated assignment:** when assigning actions to a custom role, only actions from modules the customer is currently subscribed to can be assigned
- **Module removal handling:** if a subscription expires or is removed, affected actions become non-usable but their definitions are retained — they reactivate if the module is re-added
- **Permission enforcement:** every request checks DB permissions in real-time; revoking a role takes effect on the very next request
- **Tenant isolation:** custom roles are scoped to a single customer with no cross-customer leakage

### What's missing: the roles router ❌

Task 11.3 (Add role management router) was tracked but not yet executed. The service logic and data model are complete; what's missing is wiring them to HTTP:

| Endpoint | Purpose |
|----------|---------|
| `GET /roles` | List fixed + custom roles for a customer |
| `POST /roles` | Create a custom role |
| `POST /roles/{id}/clone` | Clone an existing role |
| `PATCH /roles/{id}` | Rename a custom role |
| `DELETE /roles/{id}` | Delete a custom role |
| `PUT /roles/{id}/actions` | Assign action grants (subscription-gated) |
| `GET /permissions/tree` | Full module → submodule → resource → action catalog |

### What this means for the UI

There are no roles management screens yet. Once the roles router is added, the UI would need:

- A **Roles** screen in the business portal listing default and custom roles
- A role editor with a module/action tree (showing only subscribed modules)
- Clone and delete actions per role
- A staff/user management screen to assign roles to team members

---

## Impersonation (backend fully implemented)

- Superadmin can impersonate any agency or any customer
- Agencyadmin can impersonate any customer they manage
- Session is recorded with explicit start/end timestamps; 60-minute automatic expiry
- The impersonated entity's tenant boundary is always enforced (even a superadmin is restricted to that entity's data)
- Sensitive actions (configurable `is_sensitive` flag per action) are blocked during impersonation with an explicit error
- Every response during an active session carries impersonation indicator headers (`X-Impersonating`, `X-Impersonated-Type`, `X-Impersonated-Id`, `X-Impersonation`) for the UI banner

**Frontend todo:** Read `X-Impersonating` on responses → show banner + EXIT button wired to `POST /impersonation/end`.

---

## Audit Logging (backend fully implemented)

- Every mutation (create / update / delete) is logged asynchronously via Celery — never blocks the request
- Captures: user, role, module, sub-module, resource, action, old value, new value, timestamp, tenant identifiers, impersonation flag + impersonator id
- Append-only at the DB level (PostgreSQL trigger) and application level
- Retries up to 3× on write failure; writes a durable `audit_failures` record on exhaustion
- Query API: tenant-isolated, AND-combined filters (date range, action, user, resource), timestamp-desc pagination (default 50, max 200)
- Export: CSV or JSON, capped at 100,000 records

**Frontend:** `AuditLogs.jsx` exists (currently mock data). Needs wiring to `GET /audit/logs` and `GET /audit/logs/export`.

---

## Development

### Run tests

```bash
cd backend

# Fast unit tests (no infra required, ~15s)
pytest tests/unit

# Property-based tests by phase (Hypothesis, 100–200 iterations each)
pytest tests/property/test_tenant_context_derivation_property.py   # Phase 3: tenancy
pytest tests/property/test_no_cross_tenant_access_property.py       # Phase 3: isolation
pytest tests/property/test_customer_list_cache_consistency_property.py  # Phase 3: cache
pytest tests/property/test_impersonation_lifecycle_property.py      # Phase 4: lifecycle
pytest tests/property/test_impersonation_enforcement_property.py    # Phase 4: security
pytest tests/property/test_audit_logging_property.py               # Phase 5: write path
pytest tests/property/test_audit_query_export_property.py          # Phase 5: read path
```

### Migrations

```bash
docker compose exec backend alembic upgrade head    # apply all
docker compose exec backend alembic downgrade -1   # roll back one
docker compose exec backend alembic current        # show state
```

### Environment variables

```bash
# .env (root — Docker Compose)
POSTGRES_PASSWORD=dev
REDIS_PASSWORD=dev
JWT_SECRET=dev-secret-key
ENVIRONMENT=development

# backend/.env (local dev without Docker)
DATABASE_URL=postgresql+asyncpg://postgres:dev@localhost:5432/onella
REDIS_URL=redis://localhost:6379
JWT_SECRET=dev-secret-key
ENVIRONMENT=development
ACCESS_TOKEN_TTL_MIN=20
REFRESH_TOKEN_TTL_DAYS=14

# frontend/.env (local dev without Docker)
VITE_API_URL=http://localhost:8000
```

---

## What's next

1. **Roles router** — expose `GET/POST /roles`, `PUT /roles/{id}/actions`, `GET /permissions/tree` so the UI can manage staff roles
2. **Impersonation UI** — read `X-Impersonating` header → show banner + wire EXIT button
3. **Audit log UI** — wire `AuditLogs.jsx` to the real API
4. **Staff / user management UI** — assign custom roles to team members within a business
5. **Real SMS provider** — replace `MockSmsSender` with Twilio/AWS SNS for production OTP delivery
6. **Frontend wiring** — modules, subscriptions, and impersonation endpoints all have backend APIs ready but no frontend integration yet
