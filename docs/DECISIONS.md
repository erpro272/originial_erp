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
35. **Planning rebuild, step 1 only** (owner): steps 2–5 visible but locked. Running rows include
    in-production and already-planned orders. Bar dates come from machine capacity + routes (demo data;
    Factory setup screen later). Selection saved on the server; owner + planner edit.
36. **"Best score" is a company setting** (`planning-objective`: ordered criteria). Default = mockup rule
    (no late deliveries, then contribution per production day over one window shared by all options,
    then filling idle machines, then fewer bottlenecks). An AI method can plug into the same setting.
37. **Planning demo is an idempotent upsert** (`python -m seed.planning_demo`): machines, routes, BOMs,
    stock and the 7 candidates are updated in place by natural keys; nothing is dropped. Material prices
    are derived from each order's value and conversion cost so margins land near the demo targets;
    screens compute margins from costs.
38. **Scheduler**: route steps strictly in order with a time-of-day hand-off (step k starts when k-1 ends,
    on its own machine's queue); running orders take capacity first; Sundays/downtime have no capacity.
    Window = earliest planned start to latest finish (calendar days); idle machine-days count production
    machines only (QC is `inspection`), during the running orders' dates; utilisation = all scheduled
    hours / all capacity in the window.
39. **Options**: Your selection = ticked orders in the plan's order (default rule: highest value, as the
    mockup). Partly = never drops yours, best sequence (deadline / slack / shortest + swaps), adds orders
    only with no new late delivery or bottleneck. Fully = every subset of up to 10 accepted orders, each
    with its best sequence; clean plans (no late, no bottleneck) first, then the Best-score rule.
    "Best score" uses the same ranking. `ENGINE_VERSION` is part of the plan fingerprint.
40. **Step 2 feasibility (owner's choice)**: the scheduler never books a machine above its hours, so a
    competing order waits and ships late. "CNC 01 over capacity by N hrs, dates" = the machine hours the
    late order can't fit before its deadline (re-plan forced to the deadline, route hand-off respected),
    blamed on the machine it queued longest for, over the days it queued. Counted as a bottleneck on
    step 1 too, so both steps agree.
41. **Step 2 edits (owner's choices)**: using an optimizer option runs its scored order (rule = Custom);
    drag applies at once with an Undo banner (late / plan length / bottlenecks before → after); every
    change recalculates automatically, ↻ Recalculate = Generate again (latest data + new timestamp).
    Locked orders keep their slot under every rule; a dismissed suggestion stays hidden until the
    suggestion changes.
42. **Step 3 (owner's choices)**: reorder / finish-date moves warn first (popup, as the mockup); step 2
    keeps apply + Undo. Edits are live (all steps update); ↶ Undo walks back the last changes;
    "Save schedule" is a checkpoint in the history (Final approval will compare against it). A queued
    late order is drawn as hatched waiting days + ringed machine-load cells; real >100% loads only come
    from a forced finish date (bar edge = set the finish date, earlier squeezes the hours = overtime).
    A step forced into fewer clock hours than its day has (it can't start before the previous step
    ends) counts that overflow as machine load.
43. **Step 4 (owner's choices)**: each fix (night shift on a machine for given days, express material)
    is ticked on its own and applies to the whole plan (steps 2-3 change with it); the Before / With
    switch only changes which numbers are shown. Night-shift cost = the machine's clock time past its
    normal hours (a step that waits for the previous route step runs later in the day) x the night
    premium. Margin bars: red below the company minimum, blue above it, green from minimum + 5 points.
44. **Step 5 (owner's choices)**: open checklist items warn but don't block (popup; the open items are
    saved in the approval's history entry; un-raised POs are raised on approval). "Send back to edit"
    is recorded with its note and shows "Changes requested" until the next edit. An approved plan is
    read-only (edits, generate, save, send back refused by the API); data changes later still mark it
    "Needs re-approval" and the owner can approve again; "+ New plan" starts the next one. Only the
    owner role has `planning.approve`. Approval stores its time and note.
45. **Material readiness (owner's report: express fix applied, popup still said "PO not raised")**.
    Three separate states, never mixed: actual stock + the delivery on order (`material_stock`), the
    plan's fixes (simulated: an express fix assumes an express PO arriving `express_days` after it is
    ordered — the actual request day, else today — and the order can't start before), and purchasing
    records (`purchase_requests`: status, request day). Each need has an action: `po`, `express_po`,
    `expedite` (bring a delivery on order forward) or none (already on order: nothing to raise; before
    this fix it wrongly asked for a PO). The readiness check carries one line per material (`items`);
    the checklist and the approval popup render the same lines. Until Purchasing is built a request
    stays "requested, not received yet"; stock only changes when Purchasing records a receipt. Known
    gap: open requests from another plan are not yet counted as incoming supply for the next plan.
46. **Night-shift fixes are intents for one order** (owner's report: CNC 01 night shift "avoids ₹20,000",
    yet ORD-1041 stayed late once express steel was added). Before: the fix stored a fixed date window
    worked out from the plan without fixes, any order could take the extra hours, and its "avoids ₹X"
    was judged alone. Now `night:<machine>:for:<order>`: on every recalculation `resolve_night()` finds
    the fewest night shifts, as close to the order's deadline as possible, that put it on time with the
    plan's other fixes in place; only that order may use those hours; its cost is the hours it used.
    Each fix shows its effect in the current plan (with all chosen fixes vs without this one):
    resolves / not enough / no effect / not needed / planned (express: PO still to be raised). Older
    fixed windows made for one late order are upgraded to its intent. A fix never marks an order on
    time by itself: lateness always comes from the recalculated schedule.
47. **Plans dashboard (owner's choices)**: `/planning` lists every plan by stage (Draft, Awaiting approval,
    Approved, Needs re-approval, Completed, Cancelled); `/planning/:planId?step=1..5` opens one. One plan
    is worked on at a time ("+ New plan" opens it instead of starting a second). Each approval writes an
    insert-only `plan_snapshots` row (v1, v2...; the app role has no UPDATE/DELETE): approved and
    completed plans open on their latest approved version; "See what changed" shows the recalculation.
    "Needs re-approval" = the business data it was approved on changed (its orders' qty / value /
    deadline / route / materials, factory data and stock, rules, the owner's choices), compared by a
    fingerprint stored at approval; not a day passing, and not once its orders are in production
    (Production carries it out). A plan completes itself when all its orders are shipped (or
    cancelled). The owner can cancel a draft / awaiting plan with a reason; its orders go back to
    accepted, not in planning. Approved plans can't be cancelled.
48. **Deleting plans (owner's choices)**: only never-approved plans (draft, awaiting approval, cancelled),
    by the owner (`planning.approve`). Approved / needs re-approval / completed plans and their snapshots
    are never deleted (no button; the API refuses). Delete hides the plan from every screen and API
    read (`plans.deleted_at` / `deleted_by` kept in the row), writes an audit entry, and sends a deleted
    draft's orders back to accepted, not in planning. Plan numbers are never reused.
49. **Purchasing, Inventory tab (owner's choices)**: stock is a ledger (`stock_movements`, insert-only:
    opening / receipt / issue / adjustment); `material_stock.on_hand` is a cache of its total.
    *Reserved* = materials for orders of approved plans not issued yet; demand also comes from the working
    plan and from orders marked for planning, so shortages show before a plan exists. Status per material,
    walking demand in date order and adding deliveries that arrive in time: **critical short** (an order
    can't be covered), **in transit** (covered only by a delivery on order), **low stock** (below the
    reorder level), else **adequate**. POs: raised by Purchasing (purchaser / owner) -> **awaiting
    approval** (not counted as on order) -> owner approves -> **ordered** -> supplier date -> **confirmed**
    -> received (partial receipts allowed, never more than ordered) / cancelled (open ones, before any
    receipt). Ordered / confirmed POs set the material's next delivery that Planning reads, and a PO raised
    for a material links the plan's purchase requests (`po_number`): requested -> po_raised -> ordered ->
    confirmed -> received; cancelling sends them back to requested. Migration 0008 turns existing
    on-hand into opening balances and existing next arrivals into confirmed POs, so nothing is lost.
    Raw Material Purchase and Supplier Comparison tabs come next.
50. **One active plan; approved plans are history (owner's rules, supersedes the dashboard landing of 47)**:
    one draft / awaiting plan per company, enforced by a partial unique index (`uq_plans_one_active`) and a
    per-company advisory lock. Nothing starts a plan by itself: only "+ New plan" or Send to Planning (which
    adds the orders to the active plan, or starts it). Approval freezes the snapshot, plans the orders
    (promised dates, "sent to Planning" mark cleared) and leaves no active plan. Orders of an approved plan
    in force can't be sent to another plan (the refusal names the plan). Orders added / removed after
    Generate send the plan back to draft ("generate again"; undoing it restores awaiting approval).
    `/planning` opens the active plan straight away (or "No active plan" + "+ New plan"); `/planning/history`
    lists the rest. Re-approval is a revision of the same plan (Rev N = approved versions + 1), checked for
    every approved plan in force against its last approved version (`planning/revision.py`, pure): only
    significant changes ask for it (later / newly late, newly short material, machine over capacity, order
    cancelled or quantity / price / ship date changed, contribution down more than the company's
    `reapproval_margin_drop_pct`, default 5%); improvements are shown "for information". Each change lists
    why: the data changes (`_basis` stored in every result: orders, materials, machines, downtime,
    competing orders, rules) that touch the same orders, materials or machines, and penalties / costs for
    money. The approved version stays in force (promised dates) until re-approved. An approved plan is
    recalculated around plans approved before it, never after, so a later plan can't disturb it.
51. **Planning shows the plan in force when nothing is being worked on (owner's OK)**: `/planning` shows the
    active plan if there is one (with an "In force: PLAN-x →" line for approved plans still being made);
    otherwise the most recently approved plan in force, read-only, with "+ New plan" in the top bar and links
    to any other plans in force; the empty "No active plan" page only when nothing is active or in force.
    "In force" = approved (incl. needs re-approval) and not completed. A brand-new plan is tagged
    "Draft · not generated yet" (it used to say "Awaiting owner approval").
52. **Raw Material Purchase (owner's choices)**: PO lifecycle raised (awaiting approval) -> owner approves
    ("PO sent", every PO) -> supplier's date (confirmed) -> dispatched (in transit) -> **gate entry** (quantity +
    challan / vehicle no.; not in stock yet) -> **QC**: accepted quantity goes into stock through the ledger,
    rejected quantity is recorded with a reason and stays owed -> received when everything is accepted (a
    partial QC sends the PO back to confirmed / ordered for the rest). Cancel: open POs, not at the gate,
    nothing received. Edit only while awaiting approval. Screen stages are worked out, not stored:
    **Delayed** = past its expected date and not arrived, or the supplier's date is later than a linked order
    needs the material ("N days behind schedule"); Arriving today; Ready for QC (at the gate). **Priority** =
    highest priority of the linked orders (from Planning's requests, or picked when raising), else the PO's own.
    Every step goes into `po_events` (insert-only timeline) and the audit log. QC acceptance emits
    `purchasing.material_received` (PO, material, quantity, orders) for Production. Demo POs at each stage come
    from `seed/purchase_demo.py` (dev seed only; it doesn't change the demo plan's schedule).
53. **Supplier comparison (owner's choices)**: per supplier and material, rate = latest valid quote, else the
    last price paid; lead time = average actual days from PO sent to first gate entry, else quoted. Per supplier:
    on-time % = POs whose first gate entry was on or before `promised_date` (the date at approval, replaced by
    the supplier's first confirmation; later follow-ups don't move it; a replacement for rejected goods isn't a
    new delivery); defect rate = QC rejected / inspected; quality score = 10 x (1 - 10 x defect rate).
    `scoring.py` (pure): components relative to the material's other suppliers, overall = the owner's weights
    (company rule `supplier-scoring`, default price 40 / on-time 25 / quality 25 / lead 10, re-normalised over
    what is known: no made-up history), risk flags (late < 90% on time, quality > 1% rejected), stars capped at 4
    with a risk flag. Badges go to their real winners (one card can carry several). Saved (30d) = POs approved
    in the last 30 days vs the material's average rate over 90 days (all quotes and prices). "+ Request Quote"
    records requests; replies are entered by the purchaser (no e-mail). Select vendor = preferred supplier per
    material: Raise PO pre-fills it and its rate; the owner still approves every PO. The "Priority" filter of the
    mockup is a Rating filter (suppliers have no priority).

