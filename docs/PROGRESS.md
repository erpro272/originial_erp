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

### Feature 1 — Orders (2026-11-14) · awaiting owner review
- **Orders received** (updated mockup: tabs under the title): KPI box, top-3 "needs attention"
  cards ranked by the owner's settings, status lines from real stock/schedule logic with
  Raise PO, orders table (current/past, filters, saved views, 16 columns, CSV, paging,
  bulk send to Planning), create/edit/cancel with lifecycle rules.
- **Customers** (owner's spec + mockup): reporting period, metrics, health chips (new,
  repeat, high-value, declining, inactive, dormant; editable rules), customers table (34
  fields), profile (sales chart, invoices, orders, details, follow-ups: call/WhatsApp/email/
  note/reminder), add/edit with GSTIN checksum, merge duplicates.
- **Invoice upload**: bulk upload (photo/scan/PDF/HEIC, camera), background extraction
  (Claude `claude-sonnet-5-5`; mock mode without a key), QR decoded in code, normalisation
  in code, every Appendix A field, deterministic checks, verification screen with
  click-to-highlight, customer matching, duplicate detection, single-transaction save,
  versioned extraction record, encrypted files and bank details.
- Tests: 206 pytest, 30 Vitest, 12 Playwright.

## Next
- Feature 2 — Planning (6 tabs + plan comparison), after the owner's review of Feature 1.
- Later: Dashboard tab (owner will specify), Purchasing, Production, Billing, Finance,
  AI assistant panel.

## Known follow-ups
- Frontend bundle: split per module with lazy routes (now worth doing).
- E-invoice QR: payload is decoded and cross-checked; verifying the IRP signature needs
  the NIC public key certificate (follow-up).
- Customer list metrics are computed per request in Python (fine for hundreds to a few
  thousand customers; move to SQL/materialised views if a tenant grows past that).
- User management UI (invite users, change roles) is not built yet; users come from the seed.
- Key rotation for tenant data keys is designed for (versioned `tenant_keys`) but not built.
