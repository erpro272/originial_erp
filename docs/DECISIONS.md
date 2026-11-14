# Decisions

Short records of choices and the reason for each. Newest at the bottom.

1. **Planning has 6 tabs** (mockup), not the 7 steps on slide 10. What-if analysis is
   covered by Plan comparison. *Owner confirmed.*
2. **Dashboard** is a 7th top-nav item at the end; "Coming soon" until the owner specifies it.
   *Owner request.*
3. **Brand name** is a neutral placeholder ("Brand"), configurable via `VITE_BRAND_NAME`.
   *Owner request.*
4. **Multi-tenancy with two security layers** (owner's diagram): user → backend authorisation
   (membership + role) → Layer 1 PostgreSQL RLS → Layer 2 AES-256-GCM per company.
   - RLS is `FORCE`d and the API connects as `erp_app` (NOSUPERUSER, NOBYPASSRLS), so a
     missing `WHERE tenant_id = …` can't leak data. The tenant is set with
     `set_config('app.tenant_id', …, true)`, so it is local to the transaction and can't
     leak through pooled connections.
   - `users` and `tenants` are global identity tables. `memberships` and `tenants` have
     their own RLS policies (visible to the bound company, or to the signed-in user).
   - Background jobs list tenants through a `SECURITY DEFINER` function that returns ids
     only, then process each tenant with RLS still on. No role bypasses RLS at runtime.
   - Envelope encryption: each company's data key is stored wrapped by the master key
     (AAD = tenant id). Field ciphertext is bound to tenant + field (AAD), so copying
     ciphertext between rows, fields or companies fails to decrypt.
   - Encryption is applied to sensitive fields (bank account, UPI, …), not whole rows:
     the rest must stay queryable, sortable and reportable, and RLS already isolates it.
5. **Money** is stored as integer paise (`BIGINT`).
6. **Refresh token in an httpOnly cookie, access token in memory**: JavaScript can't read
   the long-lived token; the cookie is SameSite=Strict and scoped to `/api/auth`.
7. **Audit log is append-only at the database level** (the app role has no UPDATE/DELETE),
   and sensitive keys are redacted before writing.
8. **MinIO image**: the official images are no longer on Docker Hub, so we use the
   community-maintained `pgsty/minio` pinned by digest. Any S3-compatible store works.
9. **TypeScript 5.9**: openapi-typescript requires TS 5, and typescript-eslint doesn't
   support TS 7 yet.
10. **Invoice extraction model** is `claude-sonnet-5-5`, as specified by the owner, with the
    API's server-side refusal fallback enabled.
11. **Orders page layout follows the updated mockup** (`docs/mockups/orders-customers.html`):
    tabs directly under the title; KPI box inside each tab. *Owner request.*
12. **"Requirement" in the ranking = order quantity** (slide 9 "Requirement: 50 Nutbolts").
    Order priority (high/medium/low) is an extra factor. Default: weighted mix.
13. **Sales figures on Customers come from invoices**, not orders (orders are a pipeline).
    Outstanding = sum of balance due on invoices, as of today (not period-bound).
14. **Units sold counts pieces only** (PCS/NOS/…), per the mockup "pcs · this period".
15. **Health rules** (owner's note, editable): New = first purchase in the period;
    Repeat = 2+ purchases and bought in the last 60 days; Inactive = previously regular,
    60–90 days; Dormant = 90+ days; High-value = top 10% by period sales; Declining =
    period sales under 70% of the previous equal period. A customer can have several
    tags; the table shows the most urgent (dormant > inactive > declining > new >
    high-value > repeat).
16. **Order status signals** are computed: stock is allocated to open orders by ship date;
    "behind" compares remaining work with working days left (Sunday off). Machine-down
    messages come with Production.
17. **The AI returns text exactly as printed; code normalises it** (Indian day-first dates,
    paise, state codes). Keeps "the AI never does maths" and makes normalisation testable.
18. **Invoice files are encrypted with the company key before storage** (Layer 2 also for
    files); S3 server-side encryption is optional on top.
19. **Duplicates**: exact (same seller GSTIN + number + FY, or same IRN) blocks saving;
    possible (same customer + date + total) needs confirmation. Duplicate customers are
    merged, not deleted.
20. **Read-only joins across modules for display** (orders list shows customer and product
    names via SQL joins). Writes never cross modules: merges call each module's service.
21. **Layout templates (trial)**: a known layout can be read with OCR (Tesseract) from fixed
    boxes, lined up to the scan by two anchor words, before any AI call. Only one trial
    template exists (`invoices/templates.py`, Maruti Suzuki PO); it applies only when its
    signature words are on the page, so every other upload goes to the AI as before. A
    purchase order read this way is shown for review but blocked from saving as an invoice.
22. **Startup seeding is data-safe**: it checks each demo company for business data (not "any company
    exists"), so an old database volume gets its demo data after `git pull`; a company with any
    data is never touched; demo seeding is opt-in (`ERP_SEED_DEMO`), so a real deployment never
    gets fake data; wiping (`--reset`) is refused in production. `.gitattributes` keeps `*.sh` on
    Unix line endings for Windows checkouts.
23. **One company per website; no company switcher.** Each company gets its own website later
    (owner's direction). The login picker, the "Switch company" menu and the switch-company API
    are removed. Row-level security and per-company keys stay as a safety layer. A user who still
    belongs to two companies (old local database) gets "Choose a company to sign in to." — run
    `seed.run --reset` locally.
24. **Planning has 5 steps** (updated mockup `docs/mockups/planning.html`): plan comparison is gone;
    the 3 selection options in step 1 compare choices instead. *Owner's mockup.*
25. **One plan, recalculated from the database on every read and edit.** A fingerprint of every input
    decides whether something changed; no tab can show stale numbers, and no background sync is
    needed. Changes are versioned with the tabs they moved.
26. **Finite-capacity scheduling.** Machines are never overloaded by the scheduler itself; orders wait
    instead (and may be late). Overloads appear only when the owner forces a finish date (bar edge)
    or a lock, and then show as bottlenecks with a night-shift fix.
27. **Optimizer objective:** no late deliveries where possible, then the most contribution, then fewer
    bottlenecks, then a shorter plan. "Per production day" is shown for comparison.
28. **Company-discretion numbers** (late penalty fixed or % per day, overheads %, packaging per piece,
    minimum margin) are company rules edited from a small comment icon next to where they are used.
    *Owner request.* Factory data (machines, routes, labour, material and express costs, downtime) is
    edited on the Factory setup page. *Owner chose option B.*
29. **Purchase requests** are recorded now (material, quantity, needed-by, express, plan, orders,
    who/when, status) for the Purchasing module to turn into POs later. *Owner request.*
30. **One working plan at a time**; approved plans are kept as history. *Owner chose option A.*
31. **Planning ticks == "In planning" in Orders** (one fact, synced both ways): ticking/unticking in
    Planning writes the flag through the Orders service; Send to / Remove from Planning in Orders
    ticks/unticks in the working plan. *Owner feedback: sending from Orders must show in Planning.*
32. **"Send to Planning" accepts New orders** (only accepted orders can be planned, and sending one is
    the owner's decision to accept it). Planned / in-production / closed orders are refused.
33. **Selection options keep the owner's own picks** as the optimizer's starting point; "Use this
    selection" switches the ticked orders and moves "Current"; "Your selection" switches back.
34. **Orders sent to Planning when no plan is being worked on start the next plan** (PLAN-002, …)
    automatically. An approved plan only looks at its own orders and needs re-approval only when its
    sequence, schedule, money or checklist change; the approval itself is the new baseline.
