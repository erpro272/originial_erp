# Project context for any AI coding assistant

Give this file (plus the repository) to an AI assistant to continue the work. It describes what has been
built, how the code is organised, the rules the owner has set, and briefs for the next work: an agentic AI layer
and WhatsApp / Tally integrations. Read it fully before changing anything.

More detail lives in the repo:
- `CLAUDE.md`: working notes, conventions and gotchas (keep it updated).
- `docs/DECISIONS.md`: 63 numbered decisions with the reasons behind them.
- `docs/PROGRESS.md`: what is done and what is next.
- `backend/app/ai/assistant/guide.md`: user-level guide to every screen and rule.

Status as of 2026-11-18: branch `claude/sweet-thompson-f1hjgv` of `erpro272/originial_erp`, 71 commits.

---

## 1. The product

A manufacturing ERP for small and mid-sized Indian manufacturers (fasteners, bolts, nuts, steel assemblies). Money
is in ₹ with Indian grouping (lakh / crore). The financial year runs from April to March. GST rules apply (GSTIN, state
codes, CGST / SGST / IGST, e-invoice IRN and QR, e-way bill).

- **Top menu:** Orders · Planning · Purchasing · Production · Billing · Finance · Dashboard, plus ✦ AI Assistant and a
  sun / moon theme toggle.
- **One company per website:** there is no company picker in the UI. The backend is still fully multi-tenant (the
  demo seed has two companies to prove isolation).
- **Brand:** a neutral placeholder, "Brand" (`VITE_BRAND_NAME` overrides it). The design language is "Clean Kri",
  taken from the mockups in `docs/mockups/`.

## 2. Working agreement with the owner (follow it)

1. **Plan first:** data model, endpoints, screens, tests. Wait for the owner's OK. Ask questions when anything is
   unclear or the requirements conflict; don't guess.
2. **Build completely:** backend, frontend, migrations, seed data.
3. **Test it yourself:** pytest, Vitest and Playwright (run ×3, since e2e tests must be rerunnable on the same DB),
   then look at the screens against the mockups.
4. **Hand over:** what was built, how to run it, a manual test checklist and your assumptions. Then **stop**.
5. **Apply feedback**, re-run everything, and only then start the next feature.

House rules:
- Commit after each working step. Update `CLAUDE.md`, `docs/PROGRESS.md`, `docs/DECISIONS.md` and the assistant
  guide (`guide.md`) after each feature.
- **Never show hard-coded numbers on a screen:** everything comes from the API / DB. The one exception is the
  Production page, which is a frontend-only preview with demo data (at the owner's request).
- The owner writes in plain, sometimes informal English (and Hindi). Explain in plain words and avoid jargon.
- **Security rules from the owner:**
  - Bank account numbers, UPI IDs, PAN and phone numbers are personal or financial data.
  - Encrypt bank account numbers at application level.
  - Show them masked (e.g. `XXXXXX4417`) except to roles allowed to see them.
  - Never write them to logs.
  - Uploaded files are viewed only through short-lived signed URLs.
- **The owner's Groq API key** lives only in `backend/.env` / root `.env` (both gitignored). Never commit it, print
  it, or put it in `.env.example`.

## 3. Stack and how to run

| Layer | Tech |
|---|---|
| Backend `backend/` | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async (asyncpg), Alembic, ARQ worker on Redis, boto3 → MinIO/S3, LangGraph + httpx (AI), uv for dependencies |
| DB | PostgreSQL 16 + pgvector (`pgvector/pgvector:pg16`). Money is integer **paise** (`BIGINT`), never float. JSONB for owner-editable settings |
| Frontend `frontend/` | React 18 + TS 5.9 (pinned), Vite 8, React Router 6, TanStack Query / Table / Virtual, Tailwind v4 (tokens in `src/styles.css`), Radix, dnd-kit, react-hook-form + zod, openapi-fetch (generated types) |
| E2E `e2e/` | Playwright 1.63 against the running stack |
| Files / OCR | Pillow + pillow-heif, pypdfium2, zxing-cpp (QR), rapidfuzz, Tesseract (worker) |
| AI | Groq's OpenAI-compatible API (free tier), owner's choice. **No Anthropic SDK** |

Commands (`make help`):
```
make up          # whole stack in docker: web :5173, api :8000/api/docs, minio :9001
make infra       # only postgres/redis/minio; then `make api`, `make worker`, `make web`
make test        # pytest (real Postgres, DB erp_test, recreated per run) + vitest
make e2e         # playwright against a running stack
make lint typecheck format
make gen-api     # after ANY API change: regenerates backend/openapi.json + frontend TS types
make seed        # wipe + reseed dev DB      make reset-db  # drop the DB volume
```
- **Seed logins** (password `Demo@12345`): `owner@demo.example`, `planner@demo.example`, `purchaser@demo.example`,
  `accountant@demo.example`; second company `owner@second.example`.
- **Environment:** `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_PRIMARY_MODEL`, `LLM_FALLBACK_MODEL`, `LLM_VISION_MODEL`,
  `EMBEDDINGS_BACKEND` (auto | fastembed | hash), and `ERP_*` settings in `backend/app/core/config.py` (production
  refuses unsafe defaults).
- **Mock mode:** with no `LLM_API_KEY` all AI runs on mocks. Tests always do: `conftest` sets the key to an empty
  string. Run e2e against `LLM_API_KEY= make api`.

## 4. Architecture

### 4.1 Backend: a modular monolith
`backend/app/<module>/{models,schemas,service,router}.py`. Business logic lives in services, never routers. Modules
talk through service functions and domain events, **never by querying another module's tables**.

| Module | What it does |
|---|---|
| `core/` | auth (JWT access token 15 min in memory + refresh cookie 7 days), `permissions.py` (matrix), `rls.py`, `db.py` (`TenantDB`, `tenant_session`, `global_session`), `crypto.py` / `keys.py` (per-tenant AES-256-GCM keys wrapped by a master key via a `KeyProvider`), `audit.py`, `events.py` (outbox), `jobs.py`, `storage.py` (encrypted MinIO objects), `filetokens.py` (signed 5-minute file URLs), `gst.py` (GSTIN / PAN checks, state codes, money parsing), `clock.py` (today, pinnable in tests), `counters.py` (per-tenant numbering), `routers/` (auth, admin: audit log, settings, `/me/preferences`, health) |
| `catalog/` | products, materials, BOM, stock (minimal) |
| `orders/` | order lifecycle, signals, ranking, KPIs |
| `customers/` | master data, health tags, period metrics (from invoices), follow-ups, merge |
| `invoices/` | customer invoice upload → AI / OCR extraction → review → save; ledger, stats |
| `planning/` | the plan engine (pure), plan service, factory setup, company rules, purchase requests |
| `purchasing/` | suppliers, POs, stock ledger, gate entry / QC, supplier scoring, quotes |
| `billing/` | receivables, payables (3-way match, approval workflow), deals (TXN), sales invoices |
| `dashboard/` | read-only overview composed from the other modules |
| `ai/` | `llm.py` (provider client), `service.py` (invoice reader), `mock.py`, `assistant/`, `rag/` |
| `production/`, `finance/` | empty placeholders (not built) |
| `worker.py` | ARQ worker: jobs `extract_invoice`, `ingest_document`; cron `outbox_job` every 5 s; startup re-indexes stale documents |

Rules every backend change must follow:
- **Tenancy (RLS):**
  - Every business table uses the `TenantScoped` mixin, and its migration calls `enable_tenant_rls("<table>")`.
  - The API connects as `erp_app` (no BYPASSRLS), with one transaction per request and `app.tenant_id` set.
  - A test fails if any table with `tenant_id` lacks forced RLS and a policy.
  - The seed role is a superuser, so seed code must filter by `tenant_id` explicitly.
- **Encryption:** sensitive fields are stored as `LargeBinary`, encrypted with `cipher.encrypt(value, field=...)`.
  They are shown masked (`crypto.mask_tail`) unless the user has `Permission.SENSITIVE_VIEW`.
- **Audit:** every create / update / delete calls `core.audit.record(...)` in the same transaction (values are
  auto-redacted). `audit_log` is append-only for the app role.
- **Permissions:** use `Depends(require(Permission.X))`, never role names.
- **Errors:** raise `DomainError` subclasses, which become `{"error": {"code", "message", "details"}}`.
- **Routes and history tables:** all routes are under `/api`. History tables are insert-only.
- **Events:** `core.events.emit(session, "type", payload)` writes to the outbox in the same transaction. The worker
  dispatches events to `@subscribe("type")` handlers per tenant, with RLS active.

### 4.2 Roles and permissions (`core/permissions.py`)
Roles: **owner** (everything), **planner**, **purchaser**, **accountant**.

| Permission | Roles |
|---|---|
| `orders.read` | all roles |
| `orders.write` | planner, owner |
| `customers.read` | all roles |
| `planning.read` | all roles |
| `planning.write` | planner, owner |
| `planning.approve` | owner only |
| `purchasing.read` | planner, purchaser, accountant, owner |
| `purchasing.write` | purchaser, owner |
| `purchasing.approve` | owner only |
| `billing.read` | owner, accountant, purchaser |
| `billing.write`, `billing.issue` | accountant, owner |
| `billing.approve` | owner only |
| `dashboard.read` | owner only |
| `sensitive.view` | accountant, owner |
| `ai.use` | all roles |
| `settings.write` | owner |

### 4.3 Frontend
- `src/modules/<module>/` holds the pages. Shared UI is in `src/components/ui` (Button, Modal, Sheet, Menu, Tag,
  Tabs, Toast...), `components/data-table` (DataTable with a column picker saved per user) and `components/kit`
  (KPI cards, Panel, icons).
- The API is called with `api.GET/POST(...)` from `src/api/client.ts` + `unwrap()`. Types are generated, never
  hand-written. Server state goes through TanStack Query.
- **Design tokens only.** ESLint blocks raw hex colours.
  - Panels use `bg-card` (never `bg-white`).
  - Dark-on-light chips, toasts and the dark button use `bg-inverse text-on-inverse`.
  - Text on a solid status fill uses `text-on-tone`.
  - Tag tones are `hi | md | lo | ok | bl`; chart series are `s1..s5`.
  - A new colour token must also be added to `COLORS` in `src/lib/cn.ts`.
- **Dark mode** is done at token level. Every token has a dark value under `:root[data-theme="dark"]`. The choice
  (light / dark / system) is set in `lib/theme.ts`, stored in localStorage `erp.theme` and in the account
  preference `ui.theme`. The toggle is `ThemeToggle` in the top bar, and a script in `index.html` prevents a flash.
- **Charts** are hand-rolled SVG with a hover tooltip and an sr-only table.
- **Routes:**
  - `/orders`, `/orders/customers[/:id]`, `/orders/customers/imports[/:uploadId]`
  - `/planning`, `/planning/history`, `/planning/:planId?step=1..5`
  - `/purchasing` (inventory), `/purchasing/purchase[?po=]`, `/purchasing/suppliers`
  - `/billing[?mode=ar|ap&customer=&supplier=]`, `/billing/ebill[?deal=]`, `/billing/gst` (coming soon)
  - `/production` (demo preview), `/dashboard[?from&to]` (owner only), `/assistant[?c=<conversation>]`
  - `/finance` (coming soon), `/_design` (dev gallery)

## 5. Modules in detail (all built and tested)

### Orders (`orders/`)
- **Lifecycle:** new → accepted → planned → in_production → completed → shipped. Cancel is allowed before
  production. Rules are in `TRANSITIONS`.
- **Signals** (one per order, checked in order):
  1. Behind: work left > working days to the ship date (Sundays and closed days don't count).
  2. Waiting on material: stock is allocated by ship date and the order is short, but a PO on its way covers it.
  3. Material short: short, no PO on its way (offers Raise PO).
  4. Otherwise In production / Planned / Ready.
- **Ranking:** the `order-ranking` setting: weighted factors (requirement, customer tier, profit, deadline,
  priority) or a single factor.
- KPIs, saved views and CSV export. "Send to Planning" ticks = `Order.marked_for_planning`, synced with the plan.

### Customers (`customers/`)
- Master data (GSTIN checksum), contacts and addresses, merging duplicates.
- **Follow-ups:** call, WhatsApp, email, note, reminder.
- **Period metrics** come from invoices only, via `invoices/stats.py`.
- **Health tags** (`customer-health` setting; pure logic in `health.py`): new, repeat, high value, declining,
  inactive, dormant.

### Customer invoices (`invoices/`)
- **Pipeline:** upload (PDF / JPG / PNG / HEIC) → ARQ `extract_invoice` → review screen (`/check` has no side
  effects) → save (one transaction).
- **Extraction paths:**
  - A known layout is read by an OCR template, with no AI.
  - Otherwise, live: Tesseract OCR lines plus positions go to the text model, which returns compact JSON
    (`fields.TEXT_FORMAT`).
  - The vision model is the fallback when Tesseract is missing.
- **Validation:** the e-invoice QR is decoded and cross-checked in code, and all maths is done in code.
- **Storage:** files and page images are encrypted per company and served via `/api/files/<signed token>`.
- `fields.py` (the Appendix A field spec) drives the AI schema, normalisation and the review UI.

### Planning (`planning/`)
- **One working plan** (draft or awaiting approval) per company, enforced by a unique index plus an advisory lock.
- **Five steps:** selected orders (options compared by the "Best score" criteria) → sequence → production schedule
  (finite capacity, drag to reorder, locks) → financial analysis → approval checklist.
- **Engine:** `engine.py` is pure; bump `ENGINE_VERSION` when its logic changes. `service.py` fingerprints every
  input and recalculates on every read or edit. It saves versions and `plan_events`, and tells the UI which tabs
  changed.
- **Fixes:** night shift, express material; what-if previews via `PATCH ?preview=true`.
- **Company rules:** `planning-rules` (late penalty fixed or %, overhead %, packaging, minimum margin, re-approval
  limit) and `planning-objective`.
- **Approval** sets promised dates, records purchase requests and emits `plan.approved`. A frozen `plan_snapshots`
  row is kept, and approval can't be undone.
- Re-approval when live data drifts (`revision.py`). Factory setup holds departments, machines, routes, material
  prices and downtime.

### Purchasing (`purchasing/`)
- Suppliers and POs (with lines).
- **Stock ledger:** `stock_movements` is insert-only; `post_movement` keeps `material_stock.on_hand` equal to its
  total.
- **PO lifecycle:** awaiting_approval → ordered (owner approves) → confirmed → dispatched → at_gate (gate entry) →
  received (QC accepts into stock; rejected quantity stays owed). Every step is logged in `po_events` + audit.
  QC emits `purchasing.material_received`.
- `sync_incoming` puts the earliest PO on its way into `material_stock.next_arrival_*`, which Orders and Planning
  read.
- **Supplier comparison:** `scoring.py` is pure. Price, lead time, on-time and quality are weighted by the
  `supplier-scoring` setting, with risk flags. Also quotes and preferred supplier per material (pre-fills Raise PO).

### Billing (`billing/`)
- **Receivables:** outstanding = invoice total − `invoice_receipts` (never stored). Also receipts, payment
  promises, follow-ups and interactions.
- **Payables:** supplier invoices against POs, with a three-way match (PO ↔ QC-accepted quantity ↔ bill). Workflow:
  `pending_verif → pending_owner → approved → scheduled → executed (UTR) → bank-confirmed = paid`, plus on_hold /
  rejected.
  - Only the owner approves.
  - The approver can't also execute the same payment unless the owner overrides with a logged reason.
  - Only bank confirmation counts as paid.
- **Deals:** `TXN-####` per order or PO, with a derived status. Sales invoices go draft → verified → issued → sent
  (`channel: email | whatsapp`, recorded only, nothing is actually sent yet).
- **History tables:** `invoice_receipts`, `payment_promises`, `interactions` (channel call / whatsapp / email /
  visit / meeting, direction in / out), `payable_events` and `deal_events` are all insert-only.

### Dashboard (`dashboard/`)
- Owner only. It stores nothing.
- Shows the order timeline (current plan vs after new orders), machine load, cash flow by month, customer health
  and alerts from every module.

### Production (`/production`)
- **Frontend preview only.** The factory layout with hover cards uses placeholder numbers from
  `modules/production/demoData.ts`. There is no backend yet.

### Finance / GST
- Not built ("coming soon").

## 6. The AI layer as it exists today

### 6.1 Provider (`app/ai/llm.py`)
- **One OpenAI-compatible client** (`OpenAICompatibleLLM`), Groq's free tier.
  - Defaults: `openai/gpt-oss-120b` (assistant and invoice text), fallback `openai/gpt-oss-20b`, vision
    `qwen/qwen3.8-27b`.
  - Groq retired its Llama chat models.
- **Free-tier limits shape the design:**
  - About 8,000 tokens per minute per model, and Groq counts input + `max_tokens`.
  - The vision model allows only 1,000 output tokens per minute.
  - In practice that means about 1–2 assistant questions per minute. Groq's paid Dev tier removes the limit with no
    code change.
- **Rate-limit handling:**
  - A 429 switches to the fallback model, or waits briefly (≤ 15 s) for the main model.
  - It then waits what Groq asks (`retry-after` / `x-ratelimit-reset-tokens`), shown in the UI as a step.
  - It never retries when Groq sends `x-should-retry: false`.
- `max_tokens` is 1400; reasoning effort is medium for the assistant and low for extraction.
- **Hard rules:** the AI never does maths (code does), and every company fact comes from a tool.
- **Mock mode:** `app/ai/mock.py` (`ScriptedLLM`) picks tools by keyword rules and answers with the tools' own
  summaries. It is deterministic, used by all tests and e2e.

### 6.2 Assistant (`app/ai/assistant/`)
- **Graph (`graph.py`):** a LangGraph `StateGraph`, agent ↔ tools.
  - At most 2 tool rounds.
  - Tools run in parallel (`asyncio.gather`), each in its own tenant-bound transaction, with a 25 s timeout and
    isolated failures.
  - The last 8 messages of history are kept.
  - Tool results sent to the model are compacted: the summary plus about 1,800 characters (3,600 for `erp_guide`).
- **System prompt:**
  - Answer directly, then give steps or reasoning, the live state that matters, and where to do it.
  - Never invent names, statuses, screens or examples; no guessed causes.
  - Data questions get the number from a tool, defaulting to the financial year to date.
  - Reply in the language of the user's latest message.
  - The prompt lists the only screens that exist.
- **Tools (`tools.py`):**
  - Read-only or dry-run, each with a permission, each calling module services only.
  - Each returns `ToolOut(summary, data, widgets, related, context, actions, citations)`.
  - The 20 tools: `machine_schedule`, `machine_load`, `order_details`, `why_delayed`, `orders_at_risk`,
    `shippable_orders`, `plan_summary`, `plan_fixes`, `simulate_plan`, `best_sequence`, `capacity_check`,
    `material_coverage`, `purchase_orders`, `supplier_comparison`, `sales`, `receivables`, `payables`,
    `search_documents`, `erp_guide`, `cost_trend`.
- **ERP guide** (`guide.md` + `guide.py`):
  - One section per screen, task and rule, each with a `needs:` permission, `screen:` and `setting:`.
  - Keyword search. The best 3 sections are injected into the system prompt for every question.
  - The `erp_guide` tool adds the company's live rule values via `company_rule()`.
  - **Update `guide.md` whenever a feature or rule changes.**
- **Write actions (`actions.py`): the assistant never changes anything itself.** Tools suggest actions, which are
  stored as proposals in `ai_action_proposals`.
  - Kinds: `plan_fix`, `plan_sequence`, `raise_po`, `follow_up`, each with its module permission.
  - Flow: preview (live re-check) → approve (same user, permission, reviewed payload hash, row lock, re-validation,
    savepoint, idempotent) → executes through the owning module's service only. Proposals can also be rejected and
    expire after 24 h.
- **Chat service and screen:**
  - `service.py`: conversations private to each user, stored in `ai_conversations` / `ai_messages`. `chat()` streams
    typed SSE events: start, tool_start, tool_result, ui_widget, token, approval_required, citations,
    related_records, context_update, error, done.
  - UI `/assistant`: history sidebar, chat with widgets (table / bar_chart / key_values / section only), and a
    context panel with ERP cards and quick prompts. Recommended actions open a review dialog.

### 6.3 Company documents (RAG, `app/ai/rag/`)
- **Upload:** PDF / Word / text, choosing which roles may read each document.
- **Indexing:** the ARQ `ingest_document` job extracts, chunks and embeds.
  - Embeddings: fastembed `BAAI/bge-small-en-v1.5` (384 dimensions), with a hashing embedder as fallback.
  - Tables `ai_documents` and `ai_document_chunks` (pgvector HNSW plus a generated tsvector).
- **Retrieval:** hybrid vector + full-text search merged with RRF, filtered by role and tenant in SQL. Answers cite
  document and page.

### 6.4 Invoice reading (`app/ai/service.py`)
- `get_ai_client()` returns `VisionAIClient` (OCR text → text model, or images → vision model) or `MockAIClient`
  (fixtures in `app/ai/fixtures/invoice/`).

## 7. Data model (tables, all tenant-scoped except identity tables)
- **Identity / core:** tenants, users, memberships, tenant_keys, tenant_settings, user_preferences, tenant_counters,
  audit_log, outbox_events
- **Catalog / orders:** products, materials, product_materials, material_stock, orders
- **Customers:** customers, customer_contacts, customer_addresses, customer_followups
- **Invoices:** invoice_uploads, extraction_runs, invoices, invoice_lines, invoice_parties, invoice_transport,
  invoice_payments, invoice_receipts
- **Planning:** plans, plan_events, plan_snapshots, purchase_requests, departments, machines, route_steps, downtime
- **Purchasing:** suppliers, purchase_orders, purchase_order_lines, po_events, stock_movements, supplier_quotes,
  preferred_suppliers
- **Billing:** deals, deal_events, payment_promises, interactions, supplier_invoices, supplier_payments,
  payable_events
- **AI:** ai_conversations, ai_messages, ai_action_proposals, ai_documents, ai_document_chunks

Migrations are `backend/alembic/versions/0001…0015`. The next one is 0016, and it must call `enable_tenant_rls`
for each new table.

## 8. Events, jobs, API
- **Domain events emitted today:** `plan.approved`, `purchasing.material_received`, `invoice.created`,
  `invoice.draft_created`, `invoice.sent`, `payable.approved`, `payable.scheduled`, `payment.executed`,
  `payment.bank_confirmed`, `three_way_match.failed`. Few handlers subscribe yet. **This is the natural hook for
  agents and integrations.**
- **Background jobs (ARQ):** `extract_invoice`, `ingest_document`, and the outbox dispatcher every 5 s. Add new jobs
  in `app/worker.py`.
- **API:** about 100 endpoints under `/api`. See `backend/openapi.json`, or `/api/docs` when the stack runs.
  - Notable endpoints: `/api/ai/chat` (SSE) and `/api/ai/proposals/*`, plus `/api/billing/deals/{id}/invoice/send`
    and `/api/billing/deals/{id}/interactions` (both relevant for WhatsApp).
  - Settings: `/api/settings/{key}`; per-user preferences: `/api/me/preferences/{key}`.

## 9. Tests and quality gates (must stay green)
- **Backend:** ruff, mypy (strict), 326 pytest tests on real Postgres. Never run two pytest sessions at once, and
  "today" is pinned to `conftest.TODAY`.
- **Frontend:** tsc, eslint, prettier, 81 Vitest tests.
- **E2E:** 31 Playwright tests, run ×3 with `--grep-invert "upload → verify"`, against a mock-mode API. They never
  approve the demo plan (approval can't be undone).

## 10. What is not built / known follow-ups
- Production backend, Finance, GST filing.
- User management UI.
- Real sending of emails or WhatsApp; bank feeds.
- E-invoice IRP signature verification; key rotation.
- POs with several materials; "close short" for rejected material.
- Planning per-order penalty override.
- Lazy-loaded frontend routes.

---

## 11. Next work: briefs for the new features

These are starting points. Per the working agreement, **write a plan and ask the owner** before building. The
questions to ask are listed at the end of each brief.

### 11.1 Agentic AI layer
**Goal:** move from a chat assistant that answers and suggests to agents that watch the business, prepare work and
act within limits, always under the owner's control.

**Build on what exists, don't replace it:**
- **Triggers:** subscribe to outbox events (`core/events.subscribe`) and add ARQ cron jobs for schedules (morning
  brief, overdue sweep).
- **Reasoning:** reuse the LangGraph graph, the tools and the guide. A new agent is mostly a new system prompt plus a
  subset of tools.
- **Acting:** every write goes through `actions.py` proposals. The proposal kinds are the safety boundary: add new
  kinds (e.g. `send_reminder`, `draft_po_from_shortage`, `reschedule`) each with their permission, re-check and
  idempotency.
- **Autonomy levels per kind:** suggest only (default) → auto-run within limits the owner sets, as a new
  owner-editable setting (e.g. auto-raise POs under ₹X from the preferred supplier).
  - Every automatic action must be audited and reversible where possible, and visible in a new "Agent activity"
    feed.
- **Where results appear:** a notifications / inbox table and screen, the Dashboard alerts, and later WhatsApp to
  the owner.

**Agent ideas:**
- Morning brief.
- Shortage watcher (approved plan + stock → draft POs).
- Collections agent (overdue receivables → reminders).
- Supplier delay watcher (PO past the committed date → follow-up).
- Plan drift agent (re-approval needed → explanation and fixes).

**Constraints:**
- Free-tier Groq allows about 1–2 model calls a minute, so agents must be batched or event-driven, or the owner moves
  to Groq's paid Dev tier. Deterministic checks belong in code, with the model used only to explain or draft.
- Tenancy: agent runs execute per tenant (`tenant_session`), as a system actor recorded in the audit log.

**Ask the owner:** which agents first; the autonomy limits; where notifications go; whether to upgrade the Groq tier.

### 11.2 WhatsApp integration
**Goal:** send invoices, payment reminders and PO follow-ups over WhatsApp. Receive replies (payment promises,
delivery confirmations) and possibly let the owner query the assistant from WhatsApp.

**Hooks that already exist:**
- `interactions` (channel `whatsapp`, direction incoming / outgoing, contact, summary, links to deal / customer /
  supplier / invoice).
- Customer follow-ups (kind `whatsapp`).
- Sales invoice send (`channel: whatsapp`, currently only recorded).
- Receivables promises; PO follow-up endpoint; customer and supplier phone numbers.

**Suggested shape:**
- A new module `app/integrations/whatsapp/` with a provider interface: Meta WhatsApp Cloud API directly, or a BSP
  such as Gupshup, Interakt, AiSensy or Twilio.
- Outbound sending runs as ARQ jobs, triggered by outbox events or approved proposals. Templates come from Meta's
  approved templates (business-initiated messages need them; free text is allowed only inside the 24-hour customer
  window).
- A delivery / read status webhook updates the interaction.
- An inbound webhook at `/api/integrations/whatsapp/webhook`:
  - Verify the signature (`X-Hub-Signature-256`).
  - Map the sender to a tenant via the phone-number-id / business account.
  - Store the message as an incoming interaction.
  - Optionally route it to the assistant, which may only answer and suggest.
- Opt-in / consent per contact.
- Phone numbers are personal data: mask them in the UI for roles without `sensitive.view`, never log them, and keep
  the access token encrypted per tenant.
- Documents (invoice PDFs) are sent via media upload or a short-lived signed link.

**Ask the owner:** which provider (cost, whether a business number already exists); which messages first; whether
replies should create payment promises automatically or as proposals; whether the owner wants to chat with the
assistant over WhatsApp.

### 11.3 Tally integration
**Goal:** keep Tally (Tally Prime / ERP 9, which most Indian MSME accountants use) in step with this ERP's sales
invoices, receipts, supplier bills and payments, and ledgers (customers / suppliers), and avoid double entry.

**Facts:**
- Tally exposes an **XML / HTTP interface** on the machine where it runs (default port 9000). It imports vouchers and
  ledgers as `ENVELOPE` XML and exports reports.
- Tally is usually on the accountant's own Windows PC, not reachable from the cloud. The usual pattern is therefore a
  small **connector / agent on that PC** that polls this ERP's API over HTTPS (outbound only) and talks to Tally
  locally. The alternatives are a file export (XML / Excel) for manual import, or Tally's TDL / cloud-sync add-ons.

**Mapping:**

| This ERP | Tally |
|---|---|
| customers / suppliers | ledgers under Sundry Debtors / Sundry Creditors (GSTIN, state, address) |
| issued sales invoices | Sales vouchers (items or accounting mode, with HSN / GST rates, CGST / SGST / IGST ledgers, round-off) |
| `invoice_receipts` | Receipt vouchers |
| supplier invoices | Purchase vouchers |
| bank-confirmed `supplier_payments` | Payment vouchers |

**Suggested shape:**
- A new module `app/integrations/tally/`: XML builders (pure, unit-tested against Tally samples), a sync queue table
  (`tally_sync` with entity, version, status, last error, Tally voucher id / GUID), and a mapping settings screen
  (ledger names, GST ledgers, voucher types, the company name in Tally).
- Endpoints for the connector to pull pending items and report results, authenticated with a per-tenant connector
  token.
- Trigger syncing from outbox events (`invoice.created` / `invoice.sent`, `payment.bank_confirmed`...).
- Make it idempotent: always send the ERP id as the voucher's reference, and never create duplicates on retry.
- Start with a one-way push (ERP → Tally). Pulling from Tally (e.g. opening balances, ledger matching) comes second.
- Money is converted from paise exactly. GST is split as on the invoice, never recomputed by AI.

**Ask the owner:** Tally Prime or ERP 9, and which release; is Tally on one PC or a server; does the accountant
already keep masters in Tally (ledger names must match); which vouchers first; one-way or two-way; is a file export
acceptable for a first version.

### 11.4 General checklist for any new module
- **Backend:**
  - `models.py` with the `TenantScoped` mixin, and a migration `0016_*` that calls `enable_tenant_rls` for each new
    table.
  - `schemas.py`, `service.py` (all logic), `router.py` (thin, with `require(Permission...)`).
  - Audit on every write; events through the outbox; secrets encrypted with the tenant key; nothing sensitive in
    logs.
- **API types:** run `make gen-api`, then use only the generated TS types.
- **Frontend:** token classes only (dark mode then works automatically); reuse the shared components; no hard-coded
  numbers.
- **Assistant:** add a section to `guide.md`; add tools / proposal kinds if the assistant should know or do it.
- **Tests:** pytest (including tenancy isolation), Vitest, Playwright ×3. Then docs: `CLAUDE.md`, `PROGRESS.md`,
  `DECISIONS.md`.
