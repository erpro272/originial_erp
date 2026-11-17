# How this ERP works (the assistant's built-in guide)

Each section: `## Title`, then `keywords:` (extra search words), `needs:` (permission to DO it; reading may need less),
`screen:` (where it is), optional `setting:` (company rule shown live). Keep it true to the code; update it with
every feature.

## The modules and who can use them
keywords: overview, modules, tabs, menu, navigation, roles, what can i do, permissions, access, owner, planner, purchaser, accountant
screen: /
The top menu has Orders, Planning, Purchasing, Production, Billing, Finance and Dashboard, plus ✦ for this assistant.
Roles: the owner can do everything (and is the only one who approves plans, purchase orders and supplier payments,
and sees the Dashboard). The planner reads orders / customers / purchasing and edits orders and plans. The purchaser
raises and follows up purchase orders and reads billing. The accountant handles billing (receipts, follow-ups,
supplier invoices, issuing sales invoices) and may see full bank / UPI / PAN numbers; others see them masked.
Every screen only shows one company's data, and every change is written to the audit log.

## Orders received: the list, statuses and signals
keywords: orders, order list, status, signal, behind, material short, waiting, ready to plan, planned, in production, shipped, cancelled, lifecycle, why is my order red
screen: /orders
Orders shows current orders (new, accepted, planned, in production) and past ones (completed, shipped, cancelled).
Status can move new -> accepted -> planned -> in production -> completed -> shipped (back steps allowed before
production; cancel any time before production). Each order gets one signal, checked in this order:
1) Behind: work left (processing days, reduced by % done when in production) is more than the working days left
   before the ship date (Sundays and closed days don't count).
2) Waiting on <material>: stock is allocated to open orders by earliest ship date (then priority) and this order is
   short, but a purchase order that is on its way (ordered, confirmed, dispatched or at the gate) is due to arrive.
   3) Material short: short and no PO on its way (a PO still awaiting the owner's approval doesn't count yet; approving it turns the signal into
   Waiting). Raise PO is offered.
4) Otherwise In production · x% / Planned / Ready to plan.
Money (value, cost, profit) is recalculated only when quantity, price or cost change.

## Add or edit an order
keywords: new order, create order, add order, edit order, change ship date, change quantity, cancel order
needs: orders.write
screen: /orders
Orders -> "+ New order" (top right): customer, product, quantity, price, ship date, priority (high / medium / low).
A new order starts with status New; the statuses are only New, Accepted, Planned, In production, Completed, Shipped and
Cancelled (there is no draft or approval step for orders). Open an order to edit it or move its status; cancelling
asks for a reason. The planner and the owner can add and edit orders (same rights for both).

## How orders are ranked (top priority orders)
keywords: ranking, rank, priority score, top orders, priority cards, weights, which order first, order ranking logic
needs: settings.write
screen: /orders
setting: order-ranking
The priority cards on Orders rank current orders. In "weighted" mode each order gets five factors scaled 0..1 across
the open orders: requirement (its quantity / the largest quantity), customer (key 1, standard 0.5, occasional 0),
profit (its profit / the largest profit), deadline (1 - days to ship / 30, so due within a day = 1, 30+ days = 0) and
priority (high 1, medium 0.5, low 0). Score = weighted average with the company's weights; ties go to the earlier
ship date. You can also rank by one factor only. Change it with the "Order ranking settings" button on the cards.

## Send orders to Planning
keywords: send to planning, mark for planning, tick orders, plan these orders, add order to plan
needs: planning.write
screen: /orders
Tick orders on Orders and use Send to Planning: they go into the working plan (a new draft is started if there is
none). Ticks and the plan's order list stay in sync both ways.

## Create a new plan
keywords: new plan, start a plan, create plan, can i create a plan, another plan, draft plan, second plan, make plan
needs: planning.write
screen: /planning
Planning -> "+ New plan" starts a draft with the orders ticked for planning. Only ONE active plan (draft or awaiting
approval) can exist per company: if one exists you are taken to it / told to approve it first or keep editing it.
Approved and completed plans don't block a new one; they stay in force and are listed under Plan history. Sending
orders to Planning also starts a draft when there is none. The planner and the owner can create plans; only the owner
approves. To start over instead, only the owner can cancel the active plan (with a reason) or delete a plan that was
never approved; its orders go back to accepted, not in planning. Approved / completed plans are kept for good.

## The 5 planning steps
keywords: planning steps, how planning works, plan tabs, step 1, step 2, step 3, step 4, step 5, generate plan, selected orders, sequence, schedule, financial analysis, final approval
needs: planning.write
screen: /planning
1 Selected orders: timeline of running / planned orders, the orders in this plan, and options (which orders to take)
  compared by the "Best score" rule; "Use this selection". Then Generate plan opens steps 2-5.
2 Sequence: the order in which orders are scheduled (by deadline, value, margin, priority or your own drag order);
  locked orders keep their slot.
3 Production schedule: machines x days; dragging changes the sequence, with a warning showing what gets late.
4 Financial analysis: value, cost breakdown, late penalties, fixes and contribution, before / with fixes.
5 Final approval: checklist (late orders, minimum margin, material, capacity...), send back to edit, or approve.
Every number is recalculated from live data on each open or edit; tabs that changed get a dot.

## How the plan is scheduled and costed
keywords: scheduler, how is the schedule made, capacity, machine hours, contribution, margin, cost, penalty, late penalty, overhead, packaging, plan logic, engine
screen: /planning
setting: planning-rules
Orders are placed in sequence on their route's machines, day by day, within each machine's hours (minus downtime;
Sundays and closed days off), after running orders; material must be in stock or arriving (express fixes bring it
earlier). Cost per order = materials (BOM qty x material price) + machine hours x machine cost/h + labour (hours x
operators x department cost/h) + overheads (% of those) + packaging per unit. Late penalty per late day = a fixed
amount or a % of order value (company rule). Contribution = value - cost - penalties - fix costs; margin =
contribution / value. A plan below the minimum margin is flagged at approval.

## How "Best score" picks the order selection
keywords: best score, options, selection options, objective, which orders to include, planning objective, why was this option chosen
screen: /planning
setting: planning-objective
Step 1 compares selection options with the company's criteria in priority order (default: fewest late orders, then
most contribution per production day, then using machines left idle by running orders, then fewest bottlenecks).
Earlier criteria win; later ones only break ties.

## Plan fixes and what-ifs
keywords: fixes, night shift, express, express material, what if, simulate, improve plan, suggestions, fix late order
needs: planning.write
screen: /planning
Planning suggests fixes for late orders and bottlenecks: a night shift on a machine (for the days needed, costed at
the machine's night cost) or express material (earlier delivery at a cost). Each shows its cost and the penalty it
avoids; applying one recalculates the whole plan. In the assistant, fixes appear as Recommended actions you review and
confirm; nothing changes before that.

## Approving a plan and re-approval
keywords: approve plan, approval, who approves, re-approval, needs re-approval, approved plan changed, send back, promised dates
needs: planning.approve
screen: /planning
Only the owner approves (step 5, "Approve plan"). Approval sets the orders' promised dates, records purchase requests
for short material, and freezes a snapshot (approved plans open read-only on that snapshot). If live data later
changes an approved plan significantly (orders late, contribution down more than the company's limit), it needs
re-approval and the What changed panel explains why. Approval can't be undone.

## Factory setup
keywords: factory, machines, departments, routes, downtime, machine hours, cost per hour, material cost, setup
needs: planning.write
screen: /planning
Factory setup holds departments (hours, labour cost/h), machines (hours/day, cost/h, operators), product routes (which
machines, setup and run hours) , material prices and downtime days. The scheduler and the costs read it directly.

## Inventory and material coverage
keywords: inventory, stock, on hand, reserved, shortage, material coverage, enough material, stock ledger
screen: /purchasing
Purchasing -> Inventory shows each material: on hand (the total of the stock ledger: receipts at QC, issues,
adjustments), reserved / demand from the working plan, incoming purchase orders and a status (Adequate, Low stock,
Critical short) with the reason.

## Raise a purchase order
keywords: raise po, create po, new po, new purchase order, buy material, order material, can i raise a po, purchase request, fix material short, material shortage, shortage fix
needs: purchasing.write
screen: /purchasing/purchase
Purchasing -> Raise PO (or from a shortage / the plan's purchase requests): material, quantity, supplier (pre-filled
with the best-scoring supplier), rate, needed-by date. The purchaser and the owner can raise POs; the owner approves
them before they go to the supplier.

## Purchase order lifecycle
keywords: po status, po lifecycle, awaiting approval, ordered, confirmed, dispatched, at gate, gate entry, qc, received, delayed, arriving today, rejected material
needs: purchasing.write
screen: /purchasing/purchase
awaiting approval -> ordered (owner approved, sent) -> confirmed (supplier committed a date) -> dispatched -> at gate
(gate entry) -> received (QC accepts into stock; rejected quantity stays owed). "Delayed" = past the committed date
and not at the gate; "Arriving today" = due today. Every step is logged in the PO timeline. The earliest
PO on its way per material (ordered, confirmed, dispatched or at the gate) is what Orders and Planning count as
the next arrival; a PO awaiting approval doesn't count yet.

## How suppliers are scored
keywords: supplier score, best overall, supplier comparison, vendor rating, stars, late risk, quality risk, why is this supplier recommended, scorecard
screen: /purchasing/suppliers
setting: supplier-scoring
Per supplier and material: price = cheapest rate / this rate (rate = latest valid quote, else last price paid); lead =
shortest lead time / this one (actual days PO -> gate, else quoted); on-time = share of deliveries at the gate by the
committed date; quality = 1 - 10 x defect rate (QC rejected / inspected). Overall % = weighted average of the known
parts with the company's weights (re-normalised for a supplier with no history). Stars 1-5 from overall (max 4 with a
risk flag). Flags: Late risk (on-time below the limit), Quality risk (defects above the limit), No history yet.
The owner changes the weights with "Change" on the score rule.

## Customers and customer health
keywords: customer health, repeat, high value, declining, dormant, inactive, new customer, health rules, customer tags
needs: customers.write
screen: /orders/customers
setting: customer-health
Tags come from sales invoices: New (first invoice in the period), Repeat (at least N invoices and bought recently),
High value (in the top X% of period sales), Declining (period sales down more than Y% vs the previous period),
Inactive (no invoice for the inactive-days limit, for a repeat buyer), Dormant (none for the dormant-days limit).
The most important tag is shown first. Change the limits with "Edit rules" on the Customers tab (owner).

## Sales figures (how much we sold)
keywords: sales, total sales, revenue, turnover, sold, sales for a customer, sales this year, fiscal year, financial year, fy, monthly sales, customer sales, top customers
screen: /orders/customers
Sales = the customer invoices recorded in the ERP (uploaded and saved, or issued from Billing), by invoice date. The
Customers tab shows each customer's sales, invoices, average invoice, change vs the previous period, lifetime sales and
outstanding for the reporting period chosen at the top (this month, this quarter, financial year to date, last 12
months or custom dates; the financial year starts on 1 April). A customer's page shows monthly sales and top products.
Orders' values are order values (what was ordered), not invoiced sales. The assistant's sales tool returns the same
numbers.

## Import customer invoices
keywords: upload invoice, import invoices, read invoice, ocr, scan invoice, invoice upload, review invoice, ai invoice reading
needs: invoices.write
screen: /orders/customers/imports
Orders -> Customers -> Upload invoices (PDF, JPG, PNG, HEIC). The AI reads each one in the background, then you review the
fields (low-confidence ones are highlighted, checks for totals / GST / QR), match the customer and save. Nothing is
saved without your review. Files are encrypted and opened only through short-lived links.

## Receivables: what customers owe
keywords: receivables, outstanding, overdue, ageing, collections, follow up, payment promise, record receipt, customer payment
needs: billing.write
screen: /billing
Billing -> Payments (mode AR). Outstanding = invoice total - receipts recorded (never typed in). Each customer drawer
shows invoices, receipts, payment promises and follow-ups (call / email / WhatsApp notes). The accountant and the
owner record receipts and follow-ups; the purchaser can read.

## Payables: paying suppliers
keywords: payables, payments, supplier payments, approve supplier payment, approve payment, who approves payments, pay a bill, supplier invoice, pay supplier, three way match, 3-way match, owner approval, schedule payment, utr, bank confirmation, on hold, payment workflow
needs: billing.write
screen: /billing
Billing -> Payments (mode AP) -> "Add supplier invoice" (linked to its PO). Workflow: received -> accounts
verification (three-way match: PO vs QC-accepted quantity at the gate vs the bill must be clean) -> owner approval ->
scheduled -> executed (UTR) -> bank confirmed = paid. Only the owner approves, holds or rejects; the approver can't
also execute the same payment unless the owner overrides with a logged reason. Only bank confirmation counts as paid.

## Deals and sales invoices (Invoice / E-bill)
keywords: deal, txn, transaction, sales invoice, e-bill, issue invoice, verify invoice, provisional deal
needs: billing.issue
screen: /billing/ebill
Every order and PO gets a deal (TXN-####) that tracks its commercial status. Sales invoices go draft -> verified ->
issued -> sent; issuing needs billing.issue (accountant, owner). A shipped order = fully dispatched.

## Production
keywords: production, factory layout, stations, shop floor, oee, production status
screen: /production
Production shows the factory layout; hovering a stage or station shows its card. It is a preview with demo numbers
for now (the production backend isn't built yet), so the assistant doesn't quote production numbers.

## Dashboard
keywords: dashboard, kpis, cash flow, alerts, executive dashboard, overview screen
needs: dashboard.read
screen: /dashboard
Owner only. Order timeline (current plan vs after the working plan's new orders), machine load, cash flow (invoicing,
collections, supplier bills, payments by month), customer health and alerts from every module, each linking to its
record. It stores nothing; it reads the modules live.

## Finance
keywords: finance, accounts, gst, gst filing, ledger, profit and loss
screen: /billing/gst
The Finance tab and GST filing are not built yet ("coming soon"). Money questions today come from Billing (receivables,
payables, cash) and Planning (contribution and margin).

## This assistant: what it can do
keywords: assistant, ai, what can you do, help, how do you work, can you change, actions, recommended actions, apply, approve suggestion, demo mode
screen: /assistant
It answers from live ERP data with your role's access (tools), from company documents you uploaded (cited), and
from this guide for how-to and logic questions. It never changes anything by itself: suggested changes (plan fixes,
a better sequence, raising a PO, logging a follow-up) appear as Recommended actions; you tick one, review a fresh
re-check, and confirm. Conversations are private to you.

## Company documents for the assistant
keywords: documents, upload document, sop, policy, manual, knowledge base, rag, sources, citations
needs: ai.use
screen: /assistant
📎 Documents in the assistant: upload PDF / Word / text files and choose which roles may read them. They are indexed
in the background; answers quote them with the document and page.

## Dark mode / light mode
keywords: dark mode, light mode, theme, night mode, appearance, black background, change colours
screen: /
The sun / moon button in the top bar (next to ✦) switches between Light, Dark and System (follow this device's
setting). Every screen supports both. The choice is saved on your account, so it follows you to other devices; each
user picks their own.

## Settings and company rules you can change
keywords: settings, company rules, change rule, configure, customise, weights, thresholds, minimum margin, penalty
needs: settings.write
screen: /
Owner-editable rules: order ranking (Orders), customer health rules (Customers), supplier score rule (Supplier
comparison), planning rules (late penalty fixed or %, overhead %, packaging, minimum margin, re-approval limit) and the
"Best score" objective (the small comment icons in Planning). Changes apply on the next read; plans recalculate.
