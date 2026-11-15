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
- v1 archived (`archive/planning-v1/`); rebuild one step at a time:
  - Step 1 Selected orders (2026-11-14): finite-capacity timeline, the three options, demo upsert.
  - Step 2 Proposed manufacturing sequence (2026-11-15) · awaiting owner review: Generate plan opens
    it (locked panel before), overview, feasibility (machine hours missing to be on time, material,
    late), suggested move (apply / dismiss), rules (deadline, value, margin, customer priority,
    custom) with locks keeping their slot, start date, drag with Undo banner, parallel groups with the
    machine that causes the overload, ↻ Recalculate. Using a step-1 option runs it in its scored order.
    Steps 3–5 locked ("coming next"). Tests: 252 pytest, 36 Vitest, 14 Playwright.
  - Step 3 Production schedule (2026-11-15) · awaiting owner review: day-by-day chart (running orders
    locked, each route step a coloured bar on its machine's days, half days at hand-overs, setup
    stripe, deadline markers, material "!", hover details), problem chips, machine load grid (over
    100% red, "Over"; days a late order queued are ringed, "Full"), ‹ › week range, drag ⋮⋮ to
    reorder and drag a bar's edge to set its finish date, both checked first (warning popup: Cancel /
    Continue; better-only changes apply with a "bottleneck cleared" toast; locked slot, before plan
    start or before material arrival are refused), ↶ Undo (multi-step), Save schedule (history
    checkpoint). Steps 4–5 locked. Tests: 255 pytest, 39 Vitest, 15 Playwright (invoice upload test
    left aside for now at the owner's request).
  - Step 4 Financial analysis (2026-11-15) · awaiting owner review: Before fixes | With selected fixes
    (N) switch, 4 KPIs (sales value, manufacturing cost incl. fixes, expected contribution after
    penalties, margin), cost breakdown (materials, labour, machine, overheads, packaging, plan fixes),
    plan adjustments (base contribution, late penalty per late order "1 day × ₹20,000", each suggested
    fix with a tick box that applies it to the whole plan, expected contribution, insight: fix cost
    vs penalty avoided), profit by order (column picker, margin bar vs the company minimum), comment
    icons for the company rules. Step 5 locked. Tests: 256 pytest, 42 Vitest, 16 Playwright.
  - Step 5 Final plan approval (2026-11-15) · awaiting owner review: status tag (Awaiting owner
    approval / Changes requested / Approved / Needs re-approval), plan summary (orders, production
    days, value, contribution, margin, deliveries, fixes applied), readiness checklist (Raise PO now),
    owner approval with note: open items -> "Approve with N open items?" popup, un-raised POs go to
    Purchasing; Send back to edit (recorded with the note, opens step 2); history. Approved plan =
    read-only on all steps, "+ New plan". All 5 planning steps are now live.
    Tests: 257 pytest, 47 Vitest, 17 Playwright (invoice upload test still left aside).
  - Fix (owner feedback): material readiness distinguishes stock / deliveries on order, the plan's
    express fix (a simulated express PO with a real delivery time) and actual purchase requests (status,
    expected arrival); materials on order no longer ask for a PO; checklist and popup share one source.
    Tests: 264 pytest, 49 Vitest, 16 Playwright.

## Next
- Planning v1 archived in `archive/planning-v1/` (owner request). Rebuild in progress:
  **Step 1 Selected orders done (awaiting owner review)**: order timeline (running/planned orders +
  your selection / partly / fully optimized, from/to range, default today + 3 weeks), "In this plan"
  table synced both ways with Orders received, options comparison with "Use this selection",
  swappable "Best score" rule (`planning-objective` setting). Steps 2–5 locked (coming soon).
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
