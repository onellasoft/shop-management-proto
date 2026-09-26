# Onella: Shop Management SaaS

A multi-tenant shop management platform for agencies and businesses to manage WhatsApp contacts, campaigns, and subscriptions. Built with a production-grade async FastAPI backend and a modern React frontend.

**Key features:**
- Multi-tenant architecture with role-based access control (RBAC)
- JWT-based authentication with email/password and mobile OTP login
- Admin dashboards for superadmins, agency admins, and customer admins
- Module subscriptions and role-based feature access
- Asynchronous audit logging (append-only)
- Staff impersonation for support and testing
- WhatsApp contact and campaign management

## Architecture Overview

The platform is split into two independently deployable services:

| Component | Role | Tech |
|-----------|------|------|
| **Backend (Onella)** | REST API, auth, multi-tenancy, audit | FastAPI, PostgreSQL, Redis, Celery |
| **Frontend (SPA)** | Web dashboard, real-time UI | React 19, Vite, Tailwind, React Router |
| **Infrastructure** | Persistence, job queue, caching | PostgreSQL, Redis, Celery worker |

**Data flow:**
```
[Browser] → [Vite dev server] → [/api/* proxy] → [FastAPI backend]
                                                      ↓
                                              [PostgreSQL] + [Redis]
                                              [Celery worker for async jobs]
```

## Quick Start

### Prerequisites
- Docker & Docker Compose
- (Optional) Python 3.11+ and Node.js 18+ for local development

### First run (with Docker)

```bash
cp .env.example .env       # Configure environment (optional, defaults work)
docker compose up --build   # Start entire stack
```

This boots:

| Service | URL | Purpose |
|---------|-----|---------|
| Frontend | http://localhost:4300 | React SPA (Vite dev server with HMR) |
| Backend | http://localhost:8000 | FastAPI REST API |
| PostgreSQL | localhost:5432 | Primary database (persisted) |
| Redis | localhost:6379 | OTP/token store, Celery broker |
| Celery Worker | — | Async job processor |

**Note:** The frontend proxies all `/api/*` requests to the backend, so browser API calls stay on the same origin (http://localhost:4300).

### Seed development data

After the stack starts, populate test data:

```bash
docker compose exec backend python -m app.scripts.seed
```

This creates demo agencies, customers, and seeded admin users with roles and module subscriptions (idempotent, safe to run repeatedly).

#### Seeded test credentials

All users have password `Password123!`. Log in with either **email + password** or **mobile + OTP**:

| Email | Mobile | Role | Notes |
|-------|--------|------|-------|
| `superadmin@onella.test` | +919561311757 | superadmin | Platform admin |
| `agencyadmin@onella.test` | +917588611478 | agencyadmin | Agency admin (Onella Inc) |
| `admin.apex@onella.test` | +919876543210 | customeradmin | Business admin (Apex Retail) |
| `admin.grocers@onella.test` | +919123456789 | customeradmin | Business admin (Local Grocers) |

#### Testing OTP login

1. On the login page, go to the "OTP" tab (default)
2. Click "Fill" to select a mobile number
3. Click "Send OTP"
4. Read the 6-digit OTP from Redis:
   ```bash
   docker compose exec redis redis-cli GET "otp:code:+919561311757"
   ```
5. Paste the OTP and click "Verify OTP"

**Note:** In development, OTP is mocked (stored in Redis, not sent via SMS). For production, integrate a real SMS provider (Twilio, AWS SNS, etc.).

### View the app

1. Open http://localhost:4300 in your browser
2. Log in with seeded credentials above
3. Dashboards auto-route based on role:
   - **superadmin:** Dashboard showing platform overview
   - **agencyadmin/customeradmin:** Home showing agency/customer details

## Development Guide

### Database migrations

Migrations run automatically when the backend container starts (`alembic upgrade head`). This is **idempotent** — applied revisions are recorded, so re-running is safe.

To manage manually:

```bash
# Manually apply migrations
docker compose exec backend alembic upgrade head

# Roll back one revision (use with caution)
docker compose exec backend alembic downgrade -1

# See migration status
docker compose exec backend alembic current
```

### Backend development

**Local setup** (without Docker):
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
```

**Run locally:**
```bash
uvicorn app.main:app --reload
```

The backend exposes:
- `GET /health` — Health probe
- `POST /auth/login`, `POST /auth/logout`, `POST /auth/refresh` — Auth endpoints
- `POST /auth/otp/request`, `POST /auth/otp/verify` — OTP flow
- `GET /modules` — Module catalog
- `POST /subscriptions`, `DELETE /subscriptions/{id}` — Subscription management
- And more — see FastAPI auto-docs at http://localhost:8000/docs

**Test:**
```bash
pytest
```

### Frontend development

**Local setup** (without Docker):
```bash
cd frontend
npm install
```

**Run locally:**
```bash
npm run dev
```

The Vite server starts on http://localhost:4300 with hot module reloading.

**Build for production:**
```bash
npm run build      # outputs to dist/
npm run preview    # preview production build
```

### Hot reload with Docker

Both backend and frontend directories are bind-mounted in Docker containers, so:
- Backend changes auto-reload (Uvicorn watch mode)
- Frontend changes auto-reload (Vite HMR)

No rebuild needed unless you change dependencies.

### Environment configuration

Configuration is managed via `.env` files (git-ignored):

```bash
# Root .env for Docker Compose
POSTGRES_PASSWORD=dev
REDIS_PASSWORD=dev
JWT_SECRET=dev-secret-key
```

```bash
# frontend/.env (if running locally without Docker)
VITE_API_URL=http://localhost:8000/api
```

```bash
# backend/.env (if running locally without Docker)
DATABASE_URL=postgresql+asyncpg://postgres:dev@localhost:5432/onella
REDIS_URL=redis://localhost:6379
JWT_SECRET=dev-secret-key
```

See `.env.example` files in each directory for all available options.

## Backend (`backend/`)

FastAPI async service providing auth, RBAC, multi-tenancy, impersonation, and async audit logging.

**Stack:** FastAPI + Uvicorn, PostgreSQL via async SQLAlchemy + Alembic, Redis (OTP store, caches, Celery broker), Celery, PyJWT, Pydantic v2, passlib[bcrypt].

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

**Key endpoints:**

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/auth/login` | None | Email + password login |
| `POST` | `/auth/otp/request` | None | Request OTP for mobile |
| `POST` | `/auth/otp/verify` | None | Verify OTP, get JWT |
| `POST` | `/auth/refresh` | Bearer token | Refresh access token |
| `POST` | `/auth/logout` | Bearer token | Revoke refresh token |
| `GET` | `/modules` | Bearer token | List module catalog |
| `POST` | `/subscriptions` | Bearer token | Add module to customer |
| `DELETE` | `/subscriptions/{id}` | Bearer token | Remove module from customer |
| `GET` | `/audit/logs` | Bearer token | View audit log (superadmin) |

## Frontend (`frontend/`)

React 19 SPA built with Vite and styled with Tailwind CSS. Uses React Router, Recharts for reporting, Framer Motion for animation, and lucide/react-icons.

### Directory structure

```
src/
  pages/           Login, Dashboard, Home, etc.
  components/      Reusable UI components
  layouts/         AppLayout (sidebar, header)
  context/         AppContext (auth, app state)
  lib/             API client, utilities
  App.jsx          Router, role-based routes
```

### Key components

- **Login.jsx:** Two-tab login (OTP + email/password) with dev quick-fill
- **AppLayout.jsx:** Sidebar, header, breadcrumbs, user menu (uses real user info from JWT)
- **CommandPalette.jsx:** Command search (Cmd/Ctrl+K), workspace switching
- **AppContext.jsx:** Central auth and app state management

---

## Track 2: Implementation Status

### ✅ Completed (All 7 tasks)

**Track 2 goal:** Wire frontend authentication to real backend APIs, replace mock login with real JWT flows, seed with mobile numbers, create API client layer, rewrite auth state management, rewrite login page with two tabs, and replace hardcoded role strings with backend-driven values.

#### 1. Frontend blast radius mapped
- Identified all files using role strings or auth state
- Files to modify: AppContext.jsx, AppLayout.jsx, CommandPalette.jsx, Login.jsx, App.jsx

#### 2. Seed updated with mobile numbers
Backend seed now populates mobile numbers for all test users (idempotent, backfills on existing users):
- `superadmin@onella.test` → +919561311757
- `agencyadmin@onella.test` → +917588611478
- `admin.apex@onella.test` → +919876543210
- `admin.grocers@onella.test` → +919123456789

#### 3. API client layer created
**File:** `frontend/src/lib/api.js`

Thin wrapper around native fetch with:
- `request()` helper with error handling
- `authRequest()` for token-protected endpoints
- `ApiError` class for structured errors
- Implemented endpoints:
  - `login(email, password)` → JWT pair
  - `requestOtp(mobile)` → sends OTP
  - `verifyOtp(mobile, otp)` → JWT pair
  - `refreshTokens(refreshToken)` → new access token
  - `logout(refreshToken)` → revokes token
  - `getModuleCatalog()`, `addSubscription()`, `removeSubscription()`

#### 4. AppContext rewritten with real auth state
**File:** `frontend/src/context/AppContext.jsx`

Now manages real JWT-based auth:
- **State:** `accessToken`, `refreshToken` (localStorage), `userInfo` (decoded JWT claims), `isAuthenticated`, `authLoading`
- **Silent refresh on mount:** Restores session from localStorage if refresh token is valid
- **JWT decode:** Extracts `sub` (user ID), `email`, `role_type`, `agency_id`, `customer_id`
- **Real login:** Calls `POST /auth/login` or `POST /auth/otp/verify`, stores tokens, navigates by role
- **Real logout:** Calls `POST /auth/logout`, clears localStorage and state
- **Workspace switch:** `setCurrentRole` applies UI-level override (`roleOverride`), doesn't re-login
- **Authorization source of truth:** `effectiveRole` = `roleOverride ?? userInfo.role_type` (backend JWT always governs)

#### 5. All role strings replaced
- `super_admin` → `superadmin`
- `business_admin` → `agencyadmin` (or `customeradmin` for customer-level users)
- Files updated: AppContext.jsx, AppLayout.jsx, CommandPalette.jsx, App.jsx
- All role checks now use `isSuperAdmin()` helper or imported `ROLES` constants
- Backend `role_type` in JWT is single source of truth

#### 6. Login page rewritten with two tabs
**File:** `frontend/src/pages/Login.jsx`

Two-tab interface:
- **OTP Tab (default):**
  - Mobile number input with "Fill" quick-select (dev feature)
  - "Send OTP" button → `requestOtp(mobile)`
  - 6-digit OTP input with auto-focus
  - "Verify OTP" button → `verifyOtp(mobile, otp)`
  - Dev hint: Shows Redis command to read OTP in development
- **Email/Password Tab:**
  - Email input with "Fill" quick-select (dev feature)
  - Password input with show/hide toggle
  - "Login" button → `login(email, password)`
  - Dev quick-fill populates email and password
- Error handling: Displays API error messages
- Loading states: Buttons disabled during requests
- On success: Tokens stored, context updated, navigation by role

#### 7. End-to-end verification
All flows tested against running stack:

| Test | Result |
|------|--------|
| Email/password login | ✅ JWT with `role_type` |
| Wrong password | ✅ 401 Unauthorized |
| Token refresh | ✅ New access token issued |
| Logout | ✅ Clears tokens and state |
| OTP request | ✅ OTP stored in Redis |
| OTP verification | ✅ JWT issued on match |
| Silent refresh on mount | ✅ Restores session from localStorage |
| Role-based routing | ✅ superadmin→/dashboard, others→/home |

### 📋 Remaining (Track 2 scope TBD)

Features implemented in backend, awaiting frontend UI or scope confirmation:

1. **Real OTP SMS delivery**
   - Backend has MockSmsSender (logs to console, stores in Redis)
   - **Needed:** Integrate SMS provider (Twilio, AWS SNS, etc.) and add provider credentials
   - **Impact:** Production OTP login requires real phone numbers and provider account

2. **Staff impersonation UI**
   - Backend endpoints ready: `POST /impersonation/login`, `POST /impersonation/exit`
   - **Needed:** Wire Command Palette "Switch Role" action to impersonation endpoints
   - **Use case:** Support staff testing, admin debugging
   - **Status:** Awaiting scope confirmation — is this part of Track 2?

3. **Audit log viewer UI**
   - Backend appends audit logs asynchronously (Celery task)
   - **Needed:** Create audit log viewer component, wire to `GET /audit/logs` endpoint
   - **Use case:** Compliance, debugging, activity tracking
   - **Status:** Awaiting scope confirmation — is this part of Track 2?

4. **Multi-tenant workspace switching**
   - Backend supports users with multiple businesses/agencies
   - Frontend stub: `setCurrentRole` applies UI-level override only
   - **Needed:** Fetch user's accessible businesses, add workspace selector UI, update tenant context
   - **Status:** Awaiting scope confirmation — is this part of Track 2?

5. **OTP login UX polish**
   - Current: Works end-to-end, shows dev Redis hint
   - **Polish items:**
     - Hide Redis hint in production
     - Add countdown timer for OTP expiry
     - Add "Resend OTP" button with rate limiting
     - Improve mobile number formatting (E.164)

### How to verify Track 2 completion

1. Start stack: `docker compose up --build`
2. Seed: `docker compose exec backend python -m app.scripts.seed`
3. Test email+password login:
   - Go to http://localhost:4300
   - Email tab → use superadmin@onella.test / Password123!
   - Verify JWT in localStorage (DevTools → Application → Local Storage → `onella_access`)
   - Verify role-based routing (superadmin → /dashboard)
4. Test OTP login:
   - OTP tab (default) → use +919561311757
   - Click "Send OTP" → read from `docker compose exec redis redis-cli GET "otp:code:+919561311757"`
   - Enter OTP → verify JWT issued
5. Test logout:
   - Click user avatar → "Logout"
   - Verify localStorage cleared, redirected to /login
6. Test workspace switch (UI-only):
   - Command Palette (Cmd/Ctrl+K) → "Switch Role"
   - Verify role UI updates (sidebar, navigation)
   - Verify backend JWT still governs authorization (try accessing restricted feature)

## Production Deployment

### Docker production build

```bash
export JWT_SECRET=<generate-strong-secret-key>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

**What changes:**
- Backend: Non-root user, optimized image
- Frontend: Built to static dist/, served by Nginx
- Migrations: One-shot `migrate` service (doesn't race on backend startup)
- No hot reload, no Vite dev server

### Configuration for production

Update `.env`:

```bash
# Database
POSTGRES_PASSWORD=<strong-password>
POSTGRES_DB=onella_prod

# Redis
REDIS_PASSWORD=<strong-password>

# Auth
JWT_SECRET=<strong-secret-key>
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=20
JWT_REFRESH_EXPIRY_DAYS=14

# OTP (integrate real provider)
SMS_PROVIDER=twilio  # or: aws_sns, custom
TWILIO_ACCOUNT_SID=<your-account-sid>
TWILIO_AUTH_TOKEN=<your-auth-token>
TWILIO_PHONE_NUMBER=<your-twilio-number>

# Email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=<your-email>
SMTP_PASSWORD=<app-specific-password>

# Frontend
VITE_API_URL=https://api.yourdomain.com/api
```

### Monitoring & debugging

```bash
# View backend logs
docker compose logs -f backend

# View worker logs
docker compose logs -f worker

# Access backend docs
curl http://localhost:8000/docs

# Check database connection
docker compose exec backend alembic current

# See current users
docker compose exec postgres psql -U postgres -d onella -c "SELECT email, role_type FROM users;"
```
