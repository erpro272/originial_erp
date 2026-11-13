# Progress

## Done

### Step 0 — Foundations (2026-11-13) · awaiting owner review
- Repo layout (modular monolith backend, Vite frontend, Playwright e2e), docker compose
  (postgres, redis, minio, api, worker, web), Makefile, CI (GitHub Actions), pre-commit.
- **Security model** (owner's two-layer design):
  - Auth: JWT access token (15 min, memory only) + refresh token (7 days, httpOnly
    SameSite=Strict cookie), company memberships, company picker and switcher, login rate
    limit, logout-everywhere. Behind an `AuthProvider` interface (OIDC later).
  - Layer 1: PostgreSQL row-level security (forced) on every tenant table; API uses a
    non-privileged DB role; tenant bound per transaction.
  - Layer 2: per-company AES-256-GCM data keys, wrapped by a master key via a
    `KeyProvider` interface (swap for a cloud KMS in production).
- Roles: owner, planner, purchaser, accountant, with a permission matrix.
- Audit log (append-only, redacts sensitive fields), transactional outbox + worker,
  tenant settings and per-user preferences (JSONB).
- AI service wrapper with mock mode.
- Design system from the mockups + shared components, app shell, login, "Coming soon"
  pages for all modules (+ Dashboard), owner-only Audit log page, `/_design` gallery.
- Tests: 61 pytest (real Postgres), 29 Vitest, 5 Playwright.

## Next
- **Feature 1 — Orders**: 1A Orders received (cards, ranking settings, table with views and
  filters, create/edit/cancel), 1B Customers + invoice upload/extraction/verification.
  Starts with a plan for owner approval.
- Then Feature 2 — Planning (6 tabs + plan comparison).
- Later: Dashboard tab (owner will specify), Purchasing, Production, Billing, Finance,
  AI assistant panel.

## Known follow-ups
- Frontend bundle is one ~615 KB chunk (≈190 KB gzip); split per module with lazy routes
  once modules exist.
- User management UI (invite users, change roles) is not built yet; users come from the seed.
- Key rotation for tenant data keys is designed for (versioned `tenant_keys`) but not built.
