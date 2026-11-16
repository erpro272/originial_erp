import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import { BillingPage } from "./BillingPage";

const period = { month: "2026-11", start: "2026-11-01", as_of: "2026-11-16", live: true };
const AR = {
  period,
  cards: {
    total_paise: 4_07_78_149_00,
    total_customers: 33,
    total_invoices: 93,
    overdue_paise: 1_69_18_246_00,
    overdue_customers: 25,
    oldest_overdue_days: 418,
    expected_week_paise: 93_31_025_00,
    week_from: "2026-11-16",
    week_to: "2026-11-22",
    received_paise: 13_09_773_00,
    receipts: 3,
  },
  rows: [
    {
      customer_id: "c1",
      name: "Mahindra",
      gstin: "27AAACM5678C1ZG",
      phone: null,
      outstanding_paise: 82_48_278_00,
      open_invoices: 10,
      earliest_due: "2026-01-09",
      days_overdue: 310,
      status: "overdue",
      part_paid: true,
      has_promise: true,
      latest_update: "Promised ₹6,43,094 by 22 Nov",
      latest_at: "2026-11-13",
    },
    {
      customer_id: "c2",
      name: "Chakan Sheet Metal Works",
      gstin: null,
      phone: null,
      outstanding_paise: 25_01_609_00,
      open_invoices: 4,
      earliest_due: "2026-11-18",
      days_overdue: 0,
      status: "due_week",
      part_paid: false,
      has_promise: false,
      latest_update: null,
      latest_at: null,
    },
  ],
  counts: { all: 2, overdue: 1, due_week: 1, promise: 1, part_paid: 1 },
};
const CUSTOMER = {
  customer_id: "c1",
  name: "Mahindra",
  gstin: "27AAACM5678C1ZG",
  phone: "+91 99",
  email: null,
  city: "Mumbai",
  payment_terms_days: 60,
  period,
  invoices: [
    {
      id: "i1",
      number: "DMC/2025-26/0155",
      invoice_date: "2025-12-11",
      due_date: "2026-01-10",
      total_paise: 11_21_018_00,
      received_paise: 8_40_764_00,
      outstanding_paise: 2_80_254_00,
      days_overdue: 310,
      promised_on: "2026-11-22",
      expected_on: "2026-11-22",
      status: "overdue",
      part_paid: true,
      deal_id: "d1",
      deal_number: "TXN-1025",
      promises: [
        {
          amount_paise: 6_43_094_00,
          promised_on: "2026-11-22",
          note: null,
          at: "2026-11-13T10:00:00Z",
          by: "Rahul",
        },
      ],
      receipts: [],
    },
  ],
  interactions: [],
};
const AP_SUP = {
  supplier_id: "s1",
  name: "Mukand Wires",
  gstin: null,
  period,
  interactions: [],
  invoices: [
    {
      id: "si1",
      number: "MW/26-27/584",
      supplier_id: "s1",
      supplier: "Mukand Wires",
      po_id: "p1",
      po_number: "PO-3130",
      grn: "GRN-4432",
      deal_id: null,
      deal_number: null,
      invoice_date: "2026-09-06",
      due_date: "2026-10-21",
      quantity: "8.000",
      unit: "t",
      rate_paise: 4_00_000_00,
      taxable_paise: 32_00_000_00,
      gst_paise: 5_76_000_00,
      total_paise: 37_76_000_00,
      paid_paise: 0,
      scheduled_paise: 0,
      outstanding_paise: 37_76_000_00,
      days_overdue: 25,
      status: "pending_owner",
      stage: 3,
      match: [
        { check: "supplier", ok: true, text: "Supplier is the one on PO-3130" },
        { check: "quantity", ok: true, text: "Billed 8 t of 8 t accepted (GRN-4432)" },
      ],
      match_ok: true,
      hold_reason: null,
      payments: [],
      events: [],
    },
  ],
};
const DEALS = {
  kpis: { active: 38, total: 39, awaiting_response: 3, documents_received: 74, invoices_issued: 5 },
  rows: [
    {
      id: "d1",
      number: "TXN-1062",
      kind: "sale",
      name: "M16 hex nuts – ORD-1044",
      reference: "ORD-1044",
      company_id: "c1",
      company: "Escorts Kubota",
      documents: 5,
      latest_activity: "Order ORD-1044 received in Orders",
      latest_at: "2026-11-14T10:00:00Z",
      latest_direction: "incoming",
      value_paise: 9_00_000_00,
      status: "Order Confirmed",
      provisional: false,
      archived: false,
    },
  ],
  companies: ["Escorts Kubota"],
  statuses: ["Order Confirmed"],
};
const DEAL = {
  row: DEALS.rows[0],
  customer_id: "c1",
  supplier_id: null,
  order_id: "o1",
  po_id: null,
  item: "M16 hex nuts",
  quantity: "75000.000",
  unit: "pcs",
  dispatched_qty: "0",
  received_qty: null,
  payment_terms_days: 45,
  billing_basis: "consolidated",
  contact: null,
  note: null,
  on_hold: false,
  hold_reason: null,
  cancelled_reason: null,
  created_at: "2026-11-14T10:00:00Z",
  ship_date: "2026-11-26",
  invoice: null,
  invoice_block:
    "No dispatch recorded yet: the order is accepted. It is billed when all 75,000 pcs are dispatched (order marked Shipped).",
  payable: null,
  documents: [
    {
      key: "order:o1",
      kind: "customer_po",
      name: "Customer PO / sales order",
      number: "ORD-1044",
      direction: "incoming",
      status: "Accepted",
      date: "2026-11-14",
      amount_paise: 9_00_000_00,
      source: "Orders",
    },
  ],
  interactions: [],
  activity: [
    {
      at: "2026-11-14T10:00:00Z",
      title: "Order ORD-1044 received in Orders",
      direction: "incoming",
      source: "Orders",
      by: null,
      milestone: true,
      document_key: null,
    },
  ],
};

/** Like `route`, with a pattern for the path. */
const rx = (method: string, re: RegExp, respond: (req: Request) => Response) => (req: Request) =>
  req.method === method && re.test(new URL(req.url).pathname) ? respond(req) : undefined;

const signedIn = (perms: string[]) => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () => json({ ...ME, permissions: perms })),
  rx("GET", /\/api\/me\/preferences\/.*/, () => json({ key: "x", value: {} })),
  rx("GET", /\/api\/billing\/receivables(\?.*)?$/, () => json(AR)),
  rx("GET", /\/api\/billing\/receivables\/customers\/c1/, () => json(CUSTOMER)),
  rx("GET", /\/api\/billing\/payables(\?.*)?$/, () =>
    json({
      period,
      cards: {
        total_paise: 0,
        total_suppliers: 0,
        total_invoices: 0,
        overdue_paise: 0,
        overdue_suppliers: 0,
        due_week_paise: 0,
        week_from: "2026-11-16",
        week_to: "2026-11-22",
        paid_paise: 0,
        payments: 0,
      },
      rows: [],
      counts: { all: 0 },
    }),
  ),
  rx("GET", /\/api\/billing\/payables\/suppliers\/s1/, () => json(AP_SUP)),
  rx("GET", /\/api\/billing\/deals(\?.*)?$/, () => json(DEALS)),
  rx("GET", /\/api\/billing\/deals\/d1$/, () => json(DEAL)),
];
const ACCOUNTANT = ["billing.read", "billing.write", "billing.issue", "purchasing.read"];
const OWNER = [...ACCOUNTANT, "billing.approve"];

test("Receivables: cards, status chips (promise = has a promise), customer table", async () => {
  mockApi(...signedIn(ACCOUNTANT));
  renderApp(<BillingPage />, { path: "/billing" });
  expect(await screen.findByText("₹4,07,78,149")).toBeInTheDocument();
  expect(screen.getByText("25 customers · oldest 418 days")).toBeInTheDocument();
  expect(screen.getByText("As of 16 Nov 2026")).toBeInTheDocument();
  const table = await screen.findByRole("table");
  expect(within(table).getByText("310 days overdue")).toBeInTheDocument();
  expect(within(table).getByText("Part-paid")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^Promise Made/ }));
  expect(within(screen.getByRole("table")).getByText("Mahindra")).toBeInTheDocument();
  expect(within(screen.getByRole("table")).queryByText("Chakan Sheet Metal Works")).toBeNull();
});

test("Receivable drawer: three dates kept apart, follow-up posts to the invoice", async () => {
  const { calls } = mockApi(
    ...signedIn(ACCOUNTANT),
    route("POST", "/api/billing/receivables/customers/c1/follow-ups", () => json({ id: "x" }, 201)),
  );
  renderApp(<BillingPage />, { path: "/billing?customer=c1" });
  const dates = await screen.findByRole("region", { name: "Three dates" });
  expect(within(dates).getByText("10 Jan 2026")).toBeInTheDocument(); // original due date
  expect(within(dates).getByText("22 Nov 2026")).toBeInTheDocument(); // promised
  expect(within(dates).getByText("Not paid yet")).toBeInTheDocument(); // actual
  expect(screen.getByText("TXN-1025 →")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Log follow-up" }));
  const dialog = await screen.findByRole("dialog", { name: /Log follow-up/ });
  fireEvent.change(within(dialog).getByLabelText("What was said"), {
    target: { value: "Cheque on Friday" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save follow-up" }));
  await waitFor(() => expect(calls.some((c) => c.url.endsWith("/follow-ups"))).toBe(true));
  expect(await calls.find((c) => c.url.endsWith("/follow-ups"))!.json()).toMatchObject({
    invoice_id: "i1",
    channel: "call",
    note: "Cheque on Friday",
  });
});

test("Payable drawer: stepper and match; only the owner sees Approve", async () => {
  mockApi(...signedIn(ACCOUNTANT));
  const { unmount } = renderApp(<BillingPage />, { path: "/billing?mode=ap&supplier=s1" });
  const steps = await screen.findByRole("region", { name: "Where this payment is" });
  expect(within(steps).getByText("Owner approval").closest("li")).toHaveAttribute(
    "aria-current",
    "step",
  );
  expect(screen.getByText("Billed 8 t of 8 t accepted (GRN-4432)")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Approve payment" })).toBeNull();
  unmount();
  mockApi(...signedIn(OWNER));
  renderApp(<BillingPage />, { path: "/billing?mode=ap&supplier=s1" });
  expect(await screen.findByRole("button", { name: "Approve payment" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Hold / Reject" })).toBeInTheDocument();
});

test("Invoice / E-bill: KPIs, deal list, drawer explains why it can't be invoiced yet", async () => {
  mockApi(...signedIn(ACCOUNTANT));
  renderApp(<BillingPage />, { path: "/billing/ebill" });
  expect(await screen.findByText("Active deals")).toBeInTheDocument();
  expect(screen.getByText("of 39 in all months")).toBeInTheDocument();
  const table = await screen.findByRole("table");
  fireEvent.click(within(table).getByText("M16 hex nuts – ORD-1044"));
  expect(await screen.findByText(/No dispatch recorded yet/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Generate invoice" })).toBeDisabled();
  fireEvent.click(screen.getByRole("tab", { name: "Documents (1)" }));
  expect(screen.getByText("Customer PO / sales order")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Activity" }));
  expect(screen.getAllByText("Order ORD-1044 received in Orders").length).toBeGreaterThan(0);
});

test("Create deal: a look-alike asks before creating anyway", async () => {
  let n = 0;
  const { calls } = mockApi(
    ...signedIn(ACCOUNTANT),
    route("POST", "/api/billing/deals", () =>
      ++n === 1
        ? json(
            {
              error: {
                code: "conflict",
                message: "TXN-1067 looks the same. Create anyway?",
                details: { deal_id: "d1", warning: true },
              },
            },
            409,
          )
        : json(DEAL, 201),
    ),
  );
  renderApp(<BillingPage />, { path: "/billing/ebill" });
  fireEvent.click(await screen.findByRole("button", { name: "Create deal ▾" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Sale deal" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText(/Customer/), {
    target: { value: "Hero MotoCorp" },
  });
  fireEvent.change(within(dialog).getByLabelText("Product"), {
    target: { value: "Bulk fasteners" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Create deal" }));
  expect(await within(dialog).findByText(/looks the same/)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Create anyway" }));
  await waitFor(() =>
    expect(calls.filter((c) => c.method === "POST").length).toBeGreaterThanOrEqual(3),
  );
  const bodies = await Promise.all(
    calls
      .filter((c) => c.url.endsWith("/api/billing/deals") && c.method === "POST")
      .map((c) => c.json()),
  );
  expect(bodies.map((b) => b.force)).toEqual([false, true]);
});
