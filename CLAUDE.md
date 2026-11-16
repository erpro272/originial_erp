# CLAUDE.md — working notes for this repo

Manufacturing ERP for small/mid Indian manufacturers (fasteners, bolts, nuts, steel
assemblies). Modules: **Orders, Planning, Purchasing, Production, Billing, Finance** (+ a
Dashboard tab at the end of the nav, added later). Built **one feature at a time**; see
`docs/PROGRESS.md` for status and `docs/DECISIONS.md` for the why behind choices.

## Workflow (agreed with the owner)
1. Plan first (data model, endpoints, screens, tests) → wait for OK.
2. Build completely (backend, frontend, migrations, seed).
3. Test it yourself: pytest, Vitest, Playwright, and look at the screens vs the mockups.
4. Hand over (what was built, how to run, manual test checklist, assumptions) and **stop**.
5. Apply feedback, re-run everything, only then start the next feature.
- Commit after each working step. Update this file and `docs/PROGRESS.md` after each feature.
- Never show hard-coded numbers on a screen: everything comes from the API/DB.
- If attachments/requirements conflict, **ask** instead of guessing.

## Stack
- **Backend** `backend/`: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async, asyncpg),
  Alembic, ARQ worker on Redis, boto3 → S3/MinIO, Anthropic SDK (`app/ai/`). uv for deps.
- **DB**: PostgreSQL 16. Money = integer **paise** (`BIGINT`), never float. JSONB for
  owner-customisable settings.
- **Frontend** `frontend/`: React 18 + TS (Vite 8), React Router 6, TanStack Query/Table/
  Virtual, Tailwind v4 (tokens in `src/styles.css`), Radix (shadcn-style components in
  `src/components/ui`), dnd-kit, react-hook-form + zod, openapi-fetch.
- **E2E** `e2e/`: Playwright 1.63 against the running stack (tests are rerunnable on the same DB).
- **Invoice files**: Pillow + pillow-heif (HEIC), pypdfium2 (PDF pages), zxing-cpp (QR),
  rapidfuzz (customer name matching).
- TypeScript is pinned to 5.9: openapi-typescript needs TS 5 and typescript-eslint
  doesn't support TS 7 yet.

## Commands (see `make help`)
```
make up            # whole stack in docker: web :5173, api :8000/api/docs, minio :9001
make infra         # only postgres/redis/minio; then `make api`, `make worker`, `make web`
make test          # pytest (real Postgres, needs infra) + vitest
make e2e           # playwright against a running stack
make lint typecheck format
make gen-api       # after ANY API change: regenerates backend/openapi.json + TS types
make seed          # wipe + reseed dev DB      make reset-db  # drop the DB volume
```
Seed logins (password `Demo@12345`): `owner@demo.example`, `planner@`, `purchaser@`,
`accountant@demo.example` (demo company); `owner@second.example` (second company, used to prove
isolation). One company per website: no company picker or switcher in the UI.

## Backend conventions
- Modular monolith: `app/<module>/{models,schemas,service,router}.py`. Business logic in
  services, never in routers. Modules talk via service functions + domain events
  (`core/events.emit`, transactional outbox), never by querying another module's tables.
- All routes under `/api`. Errors: raise `core.errors.DomainError` subclasses →
  `{"error": {"code", "message", "details"}}`. Validation errors use the same shape.
- **Tenancy (Layer 1, RLS)**: every business table uses the `TenantScoped` mixin and its
  migration MUST call `enable_tenant_rls("<table>")` (`app/core/rls.py`). The API connects
  as `erp_app` (not owner, no BYPASSRLS); each request runs in one transaction with
  `app.tenant_id` set (`get_db` / `TenantDB`). `tenant_id` fills itself from that setting.
  A test asserts every table with `tenant_id` has forced RLS + a policy.
- **Encryption (Layer 2)**: sensitive fields (bank account no., UPI, etc.) are encrypted with
  the tenant's AES-256-GCM key: `cipher = await keys.get_cipher(db, tenant_id)`,
  `cipher.encrypt(value, field="bank_account")`. Store bytes (`LargeBinary`). Show masked
  (`crypto.mask_tail`) unless `Permission.SENSITIVE_VIEW`.
- **Audit**: every create/update/delete calls `core.audit.record(...)` in the same
  transaction (before/after, auto-redacted). `audit_log` is append-only for the app role.
- **Permissions**: check `Depends(require(Permission.X))`, never raw roles. Matrix in
  `core/permissions.py`.
- Use `TenantDB` (dependency with `scope="function"`) so commits finish before the response.
- AI: only through `app/ai/service.get_ai_client()`. Mock mode (fixtures in
  `app/ai/fixtures/<task>/`) when `ANTHROPIC_API_KEY` is unset; tests always use mock.
  Extraction model: `claude-sonnet-5-5` (owner's choice). AI never does maths; code does.
- Never log secrets/PII: logging has a redacting filter; don't put bank numbers in messages.
- Tests: `backend/tests`, real Postgres DB `erp_test` (recreated per run), seed via
  `seed.run.seed()`. Use helpers in `tests/conftest.py` (`login`, `owner`, `planner`).

## Modules built so far
- `catalog/` products, materials, BOM, stock (minimal; Purchasing will own it).
- `orders/` lifecycle (`TRANSITIONS`), signals (stock allocated by ship date -> shortage /
  waiting / behind; working days skip Sundays), ranking (`order-ranking` setting), KPIs.
  Money is recalculated only when quantity/price/cost change.
- `customers/` master data, health rules (`customer-health` setting, `health.py` is pure),
  period metrics read from invoices via `invoices/stats.py` only, follow-ups, merge.
- `invoices/` Appendix A spec in `fields.py` drives the AI schema + normalisation + review
  UI. Pipeline: upload -> ARQ job `extract_invoice` -> review (`/check` is side-effect free)
  -> save (one transaction). Files and page images are encrypted with the company key
  (`put_encrypted`); served only via `/api/files/<signed token>` (5 min).
  Sample invoices: `samples/invoices/*` + matching mock fixtures; regenerate both with
  `uv run python -m scripts.make_sample_invoices`.
- `planning/` one working plan (`Plan.inputs` = owner's choices, `Plan.result` = engine output).
  `engine.py` is pure (scheduler, bottlenecks, hint, fixes, selection options, financials,
  checklist); `service.py` loads DB data, fingerprints every input and recalculates on each read
  or edit, saves versions + `plan_events` with the tabs that changed (approved -> needs
  re-approval). `PATCH /planning/plans/{id}?preview=true` simulates without saving (reorder
  warning). Approval -> `orders.service.set_planned` (promised dates) + `purchase_requests`
  (recorded for the future Purchasing module) + `plan.approved` event. Factory setup
  (departments, machines, routes, material costs, downtime) and company rules
  (`planning-rules`: late penalty fixed or %, overhead %, packaging, minimum margin).
  Ticks == `Order.marked_for_planning` (synced both ways); `inputs.base` = owner's own picks the
  optimizer starts from; `selection.using` = option in use. No working plan + orders sent → new draft.
- `purchasing/` suppliers, purchase orders (+ lines), `stock_movements` ledger (insert-only; `post_movement`
  keeps `material_stock.on_hand` = its total). `sync_incoming` mirrors the earliest ordered/confirmed PO
  into `material_stock.next_arrival_*` (what Planning reads). Demand/reserved come from
  `planning.service.material_demand()`; PO steps update the plan's requests via `planning.link_requests` /
  `update_requests`. Permissions: `purchasing.read` (planner, purchaser, accountant, owner),
  `purchasing.write` (purchaser, owner), `purchasing.approve` (owner).
- Seed: `seed/demo_data.py` (dates relative to today; mirrors the Orders mockup). Planning demo:
  `seed/planning_demo.py` (idempotent upsert; `python -m seed.planning_demo` fixes an old DB in place).
  Bump `engine.ENGINE_VERSION` whenever engine logic changes (saved results then recalculate). Startup
  (`seed.run --if-empty`) only runs with `ERP_SEED_DEMO=true` (compose/dev), fills demo data into
  demo companies with no business data, never touches a company with data (exception: a demo company
  seeded with an older planning demo gets the current one ONCE — bump `planning_demo.DEMO_VERSION` when the
  scenario changes); `--reset` is refused
  when `ERP_ENV=prod`. The seed role is a superuser (RLS does not filter it): always filter by
  `tenant_id` explicitly in seed code and seed tests.

## Frontend conventions
- Design system = the two mockups. Use tokens only (`bg-primary`, `text-ink`, `border-line`,
  `rounded-card`, tag tones `hi|md|lo|ok|bl`). ESLint blocks raw hex colours.
  If you add a colour token, also add it to `COLORS` in `src/lib/cn.ts` (tailwind-merge).
- Shared components in `src/components/ui` and `src/components/data-table` — reuse them.
  Tables: `DataTable` (column picker saved per user via `table.<id>.columns` preference).
- API: `api.GET/POST(...)` from `src/api/client.ts` + `unwrap()`. Types are generated —
  never hand-write API types. Server state via TanStack Query.
- Module pages replace the "Coming soon" route in `src/app/App.tsx`; nav in `src/app/nav.ts`.
- Page-level top-bar actions (e.g. "+ New order") via `<PageActions>`.
- Brand: neutral placeholder `Brand` (`VITE_BRAND_NAME`).
- Tests: Vitest + RTL next to components (`*.test.tsx`); `src/test/utils.tsx` mocks fetch.
- `/_design` (dev only) shows every shared component.
- Orders module routes: `/orders` (received), `/orders/customers`, `/orders/customers/:id`,
  `/orders/customers/imports`, `/orders/customers/imports/:uploadId` (review).
- Reporting period lives in the URL (`?period=fytd|this_month|...&from&to`).
- Charts: hand-rolled SVG, one validated hue, hover tooltip + sr-only table (see dataviz rules).
  Categorical series colours `s1..s5` (validated); machine colours `in/bl/te/ai/lo` by machine order.
- Purchasing routes: `/purchasing` (Inventory), `/purchasing/purchase` and `/purchasing/suppliers` (coming next).
  `modules/purchasing/`: `PurchasingPage` (KPIs, Needs attention, inventory table, open POs), `PoDialogs`.
- Planning UI v1 is archived in `archive/planning-v1/`. Rebuild: `modules/planning/` has step 1
  (`SelectedOrders`: `OrderTimeline`, `OrdersInPlan`, `OptionsTable`), step 2 (`SequenceStep`) and
  step 3 (`ScheduleStep`, warning popup in `reorder.tsx`), step 4 (`FinanceStep`, company rules via
  `RuleButton`), step 5 (`ApprovalStep`, status tag in `status.ts`); 2–5 open after Generate plan.
  Routes: `/planning` = `PlanningHome` (the one active plan, or "No active plan" + "+ New plan"),
  `/planning/history` = `PlanHistory`, `/planning/:planId?step=1..5[&view=live]` = `PlanningPage`.
  One active plan (draft/generated) per company: unique index + `_lock_drafts`; only "+ New plan" or Send to
  Planning (`planning.service.send_orders` / `place_in_draft`, called from the Orders router) start one.
  Re-approval: `revision.py` (pure) compares with the last snapshot; `RevisionPanel` shows it. Only draft / awaiting plans are editable
  (`isWorking`); approved / completed plans open on their frozen `plan_snapshots` row (insert-only). E2E never
  approves the demo plan (approval can't be undone; tests must stay rerunnable). Engine: `constraints()` sizes machine competition,
  `feasibility()` writes the lines, `keep_locked()` holds locked slots under any rule.
  Old notes: routes `/planning?step=1..5`, `/planning/factory`. Every planning number comes from the
  plan result; after any edit the response says which tabs changed (dots + banner + `Flash`).
  Company-discretion numbers get a small comment icon (`RuleButton`) that opens a dialog.

## Gotchas
- Official MinIO images are gone from Docker Hub; compose uses the community build
  `pgsty/minio` pinned by digest. The API creates the bucket on startup.
- In this cloud sandbox, Docker builds need the proxy CA (not needed on a normal machine).
- Tesseract is needed by the worker for layout templates (installed in the backend Dockerfile).
  In this sandbox Debian mirrors are blocked, so the worker runs on the host (`make worker`).
