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

### Feature 2 — Planning (2026-11-14) · awaiting owner review
- One connected plan, 5 steps (updated mockup): Selected orders (timeline, yours / partly /
  fully optimized, generate), Proposed sequence (overview, feasibility, hint, rules, start date,
  drag, lock, parallel runs), Production schedule (day-by-day chart, drag rows, drag bar edge to
  set a finish date, warning popup / "cleared" toast, overloads, deadlines, machine load, undo),
  Financial analysis (before / with fixes, cost breakdown, adjustments with fix choices, profit by
  order), Final plan approval (summary, readiness checklist, raise PO now, approve with open items,
  history).
- Every change (here or in Orders / stock / factory set-up / rules) recalculates the plan: banner
  "Plan updated · N tabs changed", dots on changed tabs, changed numbers highlight, history entry,
  approved plans go to "needs re-approval".
- Factory setup page; company rules via small comment icons (late penalty fixed or %, overheads,
  packaging, minimum margin). Purchase requests recorded for the future Purchasing module.
- Company switcher removed (one company per website).
- Owner feedback round 1 (fixed): Send to Planning from Orders shows in Planning (both ways,
  also after approval → next plan), "Use this selection" switches and moves "Current", Custom
  sequencing, order timeline rebuilt like the mockup (machine routes, idle-machine fills, left-out
  reasons, click to highlight), approval no longer flags itself for re-approval.
- Tests: 233 pytest, 32 Vitest, 14 Playwright.

## Next
- Planning v1 archived in `archive/planning-v1/` (owner request); `/planning` shows Coming soon
  until the rebuild from scratch. Backend planning module still live.
- Owner review of Feature 2 (Planning).
- Later: Dashboard tab (owner will specify), Purchasing, Production, Billing, Finance,
  AI assistant panel.

## Trial
- Layout template (OCR, no AI) for the Maruti Suzuki PO sample: `samples/templates/`. Not a default.

## Known follow-ups
- Frontend bundle: split per module with lazy routes (now worth doing).
- E-invoice QR: payload is decoded and cross-checked; verifying the IRP signature needs
  the NIC public key certificate (follow-up).
- Customer list metrics are computed per request in Python (fine for hundreds to a few
  thousand customers; move to SQL/materialised views if a tenant grows past that).
- User management UI (invite users, change roles) is not built yet; users come from the seed.
- Planning: setup time is shown in the tooltip, not as a separate striped bar; the schedule has
  no week paging (scrolls); the optimizer is a greedy search (fine for tens of orders).
- Planning: per-order late-penalty override not built (company rule only, as agreed).
- Key rotation for tenant data keys is designed for (versioned `tenant_keys`) but not built.
