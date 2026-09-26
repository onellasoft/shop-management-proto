# Track 2 Implementation Summary

## Goal
Wire frontend authentication to real backend APIs, replacing mock login with real JWT flows (email/password and OTP), seed with mobile numbers, create an API client layer, rewrite AppContext with real auth state, rewrite Login page with two tabs, and replace all frontend role strings with backend-driven values.

---

## ✅ Completed (All 7 Tasks)

### 1. Mapped frontend blast radius
- Identified all files using role strings or auth state
- Files modified: AppContext.jsx, AppLayout.jsx, CommandPalette.jsx, Login.jsx, App.jsx
- Strategy: Replace all hardcoded `super_admin` → `superadmin`, `business_admin` → `agencyadmin`

### 2. Updated seed with mobile numbers
- **File:** `backend/app/scripts/seed.py`
- Added mobile numbers to all seeded users:
  - superadmin@onella.test → +919561311757
  - agencyadmin@onella.test → +917588611478
  - admin.apex@onella.test → +919876543210
  - admin.grocers@onella.test → +919123456789
- Backfill logic: idempotent, runs on every seed, adds mobiles to existing users if missing
- Seed is now **safe to run repeatedly**

### 3. Created API client layer
- **File:** `frontend/src/lib/api.js`
- Thin wrapper around native fetch
- Features:
  - `request()` helper with default headers, error handling
  - `authRequest()` for endpoints requiring access token
  - `ApiError` class for structured error handling
  - Auto-uses `VITE_API_URL` (defaults to `/api`)
- Implemented endpoints:
  - `login(email, password)` → returns JWT pair
  - `requestOtp(mobile)` → requests OTP for mobile
  - `verifyOtp(mobile, otp)` → verifies OTP, returns JWT pair
  - `refreshTokens(refreshToken)` → issues new access token
  - `logout(refreshToken)` → revokes refresh family
  - `getModuleCatalog()` → lists modules (for subscription UI)
  - `addSubscription(customerId, moduleId)`, `removeSubscription(customerId, moduleId)`

### 4. Rewrote AppContext with real auth state
- **File:** `frontend/src/context/AppContext.jsx`
- Real auth state (from JWT):
  - `accessToken`, `refreshToken` stored in localStorage (keys: `onella_access`, `onella_refresh`)
  - `userInfo` decoded from JWT claims: `sub` (user ID), `email`, `role_type`, `agency_id`
  - `isAuthenticated` derived from token validity
  - `authLoading` during token refresh on mount
- Silent refresh on mount: automatically restores session from localStorage if refresh token is valid
- Real JWT decode with expiry check
- Role helpers:
  - `ROLES` constant: `{ superadmin, agencyadmin, customeradmin }`
  - `isSuperAdmin()`, `isAgencyAdmin()` functions
- Login flow:
  - `handleLoginSuccess()` navigates by `role_type` from JWT
  - superadmin → `/dashboard`
  - agencyadmin/customeradmin → `/home`
- Real logout: `POST /auth/logout` + clear localStorage + clear state
- Workspace switch: `setCurrentRole` applies a UI override (`roleOverride`), doesn't re-login
- `effectiveRole` = `roleOverride ?? userInfo.role_type` (JWT is source of truth for authorization)

### 5. Replaced all role strings
- **Files modified:** AppContext.jsx, AppLayout.jsx, CommandPalette.jsx, App.jsx
- Replacements:
  - `super_admin` → `superadmin`
  - `business_admin` → `agencyadmin` (with context, `customeradmin` for customer-level users)
- All role checks now use `isSuperAdmin()` helper or direct comparison against `ROLES` constants
- Backend JWT `role_type` is **single source of truth** for authorization
- No hardcoded role maps in frontend

### 6. Rewrote Login.jsx
- **File:** `frontend/src/pages/Login.jsx`
- Two-tab interface:
  - **OTP Tab** (default on load):
    - Mobile number input
    - "Send OTP" button → calls `requestOtp(mobile)` 
    - OTP input component (6-digit)
    - "Verify OTP" button → calls `verifyOtp(mobile, otp)`
    - Dev quick-fill for mobile (fills number from seeded list)
    - Dev hint: "OTP in dev: `docker compose exec redis redis-cli GET "otp:code:+919561311757"`"
  - **Email/Password Tab**:
    - Email input
    - Password input (with show/hide toggle)
    - "Login" button → calls `login(email, password)`
    - Dev quick-fill for email (fills email + password)
- Error handling: displays API error messages to user
- Loading states: buttons disabled during request
- On success: JWT pair stored, context updated, user navigated by role

### 7. Verified end-to-end
All flows tested against running stack (`docker compose up`):

| Test | Result |
|---|---|
| Email/password login (superadmin) | ✅ JWT with `role_type: superadmin` |
| Email/password login (agencyadmin) | ✅ JWT with `role_type: agencyadmin` |
| Wrong password | ✅ 401 Unauthorized |
| Token refresh | ✅ New access token issued |
| Refresh token reuse | ✅ 401 (reuse detection) |
| Logout | ✅ 204 No Content |
| OTP request | ✅ 202 Accepted, OTP in Redis |
| OTP verify | ✅ Read from Redis → verify → JWT issued |
| Frontend health check | ✅ `/api/health` → `{"status":"ok"}` |
| Frontend serves login | ✅ HTTP 200 |

---

## 📋 What Remains (Track 2 scope)

### Not Implemented Yet
1. **Real mobile number OTP delivery**
   - Current: MockSmsSender logs OTP (visible in Redis for dev)
   - Needed: Integrate real SMS provider (Twilio, AWS SNS, etc.)
   - Work: Update backend OTP sender service, add provider credentials to `.env`

2. **Frontend OTP flow refinement**
   - OTP tab currently shows a dev hint for reading Redis
   - Polish: Hide the hint in production, add countdown timer for resend, improve UX

3. **Impersonation UI** (if needed for Track 2)
   - Backend impersonation endpoints exist (`/impersonation/login`, `/impersonation/exit`)
   - Frontend: Command Palette has stub "Switch Role" action → could wire to impersonation if needed
   - Decision: Verify if this is in Track 2 scope

4. **Audit logging UI** (if needed for Track 2)
   - Backend appends audit logs (async Celery tasks)
   - Frontend: No UI for viewing audit logs yet
   - Decision: Verify if this is in Track 2 scope

5. **Multi-tenant workspace switching**
   - Backend supports multiple agencies/customers per user
   - Frontend: `setCurrentRole` is UI-only override (doesn't switch backend tenant context)
   - Needed if user has access to multiple businesses: fetch list, UI selector, context update

### Clarification Needed
- Is **impersonation** part of Track 2? (Backend ready, needs frontend UI)
- Is **audit log viewing** part of Track 2? (Backend ready, needs frontend UI)
- Is **multi-tenant switching** part of Track 2? (Backend ready, frontend stub exists)

---

## How to Use

### Start the stack
```bash
docker compose up --build
```

### Seed database
```bash
docker compose exec backend python -m app.scripts.seed
```

### Login options

**Email + Password:**
1. Click the email/password tab
2. Click "Fill" to auto-populate test credentials, or type manually
3. Password: `Password123!`
4. Click "Login"

**Mobile + OTP:**
1. OTP tab is default
2. Click "Fill" to select a mobile number from the seeded list, or type manually
3. Click "Send OTP"
4. Read OTP from Redis:
   ```bash
   docker compose exec redis redis-cli GET "otp:code:+919561311757"
   ```
5. Paste 6-digit code into OTP input
6. Click "Verify OTP"

### JWT payload
After login, JWT is stored in localStorage and decoded. Check browser DevTools → Application → Local Storage → `onella_access` to see:
```json
{
  "sub": "user-id-uuid",
  "email": "user@onella.test",
  "role_type": "superadmin|agencyadmin|customeradmin",
  "agency_id": "uuid or null",
  "customer_id": "uuid or null",
  "token_type": "access",
  "iat": 1788282210,
  "exp": 1788283410
}
```

### Seeded users
| Email | Password | Mobile | Role |
|-------|----------|--------|------|
| superadmin@onella.test | Password123! | +919561311757 | superadmin |
| agencyadmin@onella.test | Password123! | +917588611478 | agencyadmin |
| admin.apex@onella.test | Password123! | +919876543210 | customeradmin |
| admin.grocers@onella.test | Password123! | +919123456789 | customeradmin |

---

## Files Modified

```
backend/
  app/scripts/seed.py                 # Add mobile numbers, idempotent backfill

frontend/
  src/lib/api.js                      # New: API client layer
  src/context/AppContext.jsx          # Rewrite: real auth state, JWT decode, silent refresh
  src/pages/Login.jsx                 # Rewrite: two-tab login (OTP + email/pass)
  src/layouts/AppLayout.jsx           # Replace role strings, use real userInfo from JWT
  src/components/CommandPalette.jsx   # Replace role strings
  src/App.jsx                         # Replace role strings
```

---

## Technical Notes

### Security
- JWT refresh token reuse detection enabled (backend)
- Refresh token family revocation on logout (backend)
- localStorage used for token persistence (acceptable for SPA, not for highly sensitive apps)
- CORS configured for frontend ↔ backend
- Password hashing: bcrypt (backend)

### Performance
- Silent refresh on mount: single API call if session valid
- Token expiry: 20 min (access), 14 days (refresh)
- API client caches VITE_API_URL to avoid repeated env lookups
- No unnecessary re-renders: AppContext uses React Context API (not Redux)

### Error Handling
- ApiError class: `status`, `message`, `details`
- Login errors: invalid credentials → 401, server error → 500
- OTP errors: invalid OTP → 400, expired OTP → 400, not found → 404
- Network errors: caught and shown to user

---

## Next Steps (if Track 2 continues)

1. **Verify scope:** Confirm impersonation, audit logs, multi-tenant switching are in Track 2
2. **Real OTP delivery:** Wire SMS provider
3. **Impersonation UI:** Wire Command Palette "Switch Role" to backend `/impersonation/login`
4. **Audit log UI:** Create audit viewer component, wire to backend `/audit/logs`
5. **Multi-tenant UI:** Add workspace selector if user has multiple businesses
6. **Testing:** E2E tests with Cypress/Playwright, unit tests for AppContext
7. **Production:** Set strong `JWT_SECRET`, enable HTTPS, configure real SMS provider

