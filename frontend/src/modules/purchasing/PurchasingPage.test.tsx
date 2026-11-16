import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { expect, test } from "vitest";
import { PageActionsSlotProvider } from "@/components/layout/PageActions";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import { PurchasingPage } from "./PurchasingPage";

function WithTopBar({ children }: { children: ReactNode }) {
  const [el, setEl] = useState<HTMLElement | null>(null);
  return (
    <>
      <div ref={setEl} />
      {el && <PageActionsSlotProvider value={el}>{children}</PageActionsSlotProvider>}
    </>
  );
}

const mat = (code: string, name: string, status: string, extra: Record<string, unknown> = {}) => ({
  id: code,
  code,
  name,
  unit: "t",
  category: "Wire rod",
  grade: `${code} grade`,
  in_stock: "0.600",
  reserved: "0.000",
  free: "0.600",
  on_order: "0.000",
  awaiting_approval: "0.000",
  reorder_level: "3.000",
  price_per_unit_paise: 6000000,
  stock_value_paise: 3600000,
  status,
  reason: "Below the reorder level of 3 t",
  shortfall: null,
  next_need: null,
  incoming: [],
  suggested_qty: "2.400",
  supplier: "Shree Steels",
  ...extra,
});
const INV = {
  kpis: {
    skus: 3,
    below_reorder: 2,
    on_order: 1,
    awaiting_approval: 1,
    stock_value_paise: 142000000_00,
  },
  materials: [
    mat("WR8", "Steel wire rod", "critical_short", {
      reason: "Short by 2.4 t for ORD-1041 (Tata Motors)",
      shortfall: {
        order_id: "o1",
        number: "ORD-1041",
        customer: "Tata Motors",
        needed_by: "2026-11-19",
        short: "2.400",
      },
    }),
    mat("EN8", "EN8 steel", "in_transit", {
      reason: "Arriving Sun 22 Nov · Shree Steels",
      on_order: "8.000",
      incoming: [
        {
          po_id: "p1",
          po_number: "PO-0001",
          status: "confirmed",
          supplier: "Shree Steels",
          quantity: "8.000",
          expected_date: "2026-11-22",
          confirmed: true,
        },
      ],
    }),
    mat("BSW", "Boron steel wire", "adequate", { category: "Bar", in_stock: "12.000" }),
  ].map((m) => ({
    needs:
      m.code === "WR8"
        ? [{ number: "ORD-1041", customer: "Tata Motors", needed_by: "2026-11-19", qty: "3.000" }]
        : [],
    ...m,
  })),
  attention: [] as unknown[],
  purchase_orders: [
    {
      id: "p2",
      number: "PO-0002",
      supplier: "Shree Steels",
      status: "awaiting_approval",
      expected_date: "2026-11-23",
      confirmed: false,
      note: null,
      source: "planning",
      created_at: "2026-11-16T10:00:00Z",
      approved_at: null,
      cancel_reason: null,
      value_paise: 14400000,
      lines: [
        {
          id: "l2",
          material_id: "WR8",
          material: "Steel wire rod",
          code: "WR8",
          quantity: "2.400",
          unit: "t",
          price_per_unit_paise: 6000000,
          received_qty: "0.000",
          rejected_qty: "0.000",
        },
      ],
      stage: "pending_approval",
      stage_text: "Delivery Mon 23 Nov",
      priority: "high",
      orders: ["ORD-1041"],
      needed_by: "2026-11-19",
      open_value_paise: 14400000,
      dispatched_at: null,
      gate_qty: null,
      gate_ref: null,
      gate_at: null,
    },
  ],
  categories: ["Bar", "Wire rod"],
  suppliers: ["Shree Steels"],
  today: "2026-11-16",
};
INV.attention = [INV.materials[0], INV.materials[1]];

const po = (number: string, stage: string, extra: Record<string, unknown> = {}) => ({
  ...INV.purchase_orders[0]!,
  id: number,
  number,
  stage,
  ...extra,
});
const PURCHASES = {
  kpis: { open: 3, pending_approval: 1, in_transit: 1, open_spend_paise: 28_50_000_00 },
  attention: [
    po("PO-0002", "pending_approval"),
    po("PO-0003", "delayed", {
      supplier: "Mukand Wires",
      status: "dispatched",
      stage_text: "1 day behind schedule (overdue)",
      orders: ["ORD-1040"],
      priority: "medium",
    }),
    po("PO-0004", "at_gate", {
      supplier: "Jindal Steel",
      status: "at_gate",
      stage_text: "Gate entry logged · CH-4471 · ready for QC",
      gate_qty: "2.000",
      gate_ref: "CH-4471",
      orders: [],
      priority: "low",
    }),
  ],
  purchase_orders: [] as unknown[],
  suppliers: ["Jindal Steel", "Mukand Wires", "Shree Steels"],
  today: "2026-11-16",
};
PURCHASES.purchase_orders = PURCHASES.attention;

const signedIn = (perms: string[]) => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () => json({ ...ME, permissions: perms })),
  route("GET", "/api/me/preferences/table.purchasing-inventory.columns", () =>
    json({ key: "x", value: {} }),
  ),
  route("GET", "/api/purchasing/inventory", () => json(INV)),
  route("GET", "/api/purchasing/purchases", () => json(PURCHASES)),
  route("GET", "/api/me/preferences/table.purchasing-pos.columns", () =>
    json({ key: "x", value: {} }),
  ),
];
const OWNER = ["purchasing.read", "purchasing.write", "purchasing.approve"];

test("KPIs, needs-attention cards, the stock table and open POs; filters", async () => {
  mockApi(...signedIn(OWNER));
  renderApp(
    <WithTopBar>
      <PurchasingPage />
    </WithTopBar>,
    { path: "/purchasing" },
  );
  expect(await screen.findByText("Short by 2.4 t for ORD-1041 (Tata Motors)")).toBeInTheDocument();
  expect(screen.getByText("Total SKUs")).toBeInTheDocument();
  expect(screen.getByText("PO-0001 confirmed")).toBeInTheDocument();
  expect(
    within(screen.getByTestId("po-PO-0002")).getByText("Pending approval"),
  ).toBeInTheDocument();
  expect(
    within(screen.getByTestId("po-PO-0002")).getByRole("button", { name: "Approve PO" }),
  ).toBeInTheDocument();
  const table = screen.getAllByRole("table")[0]!;
  expect(within(table).getByText("Boron steel wire")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Category"), { target: { value: "Bar" } });
  expect(within(screen.getAllByRole("table")[0]!).queryByText("Steel wire rod")).toBeNull();
});

test("Raise PO from a card is prefilled from the shortfall and sent for approval", async () => {
  const { calls } = mockApi(
    ...signedIn(OWNER),
    route("POST", "/api/purchasing/purchase-orders", () =>
      json({ ...INV.purchase_orders[0], number: "PO-0003" }),
    ),
  );
  renderApp(
    <WithTopBar>
      <PurchasingPage />
    </WithTopBar>,
    { path: "/purchasing" },
  );
  const card = await screen.findByTestId("attention-WR8");
  fireEvent.click(within(card).getByRole("button", { name: "Raise PO" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByLabelText(/Quantity/)).toHaveValue("2.4");
  expect(within(dialog).getByLabelText("Needed by")).toHaveValue("2026-11-19");
  fireEvent.click(within(dialog).getByRole("button", { name: "Raise PO" }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/purchase-orders"))).toBe(true),
  );
  const body = await calls
    .find((c) => c.method === "POST" && c.url.endsWith("/purchase-orders"))!
    .json();
  expect(body).toMatchObject({
    material_id: "WR8",
    supplier: "Shree Steels",
    quantity: "2.4",
    price_per_unit_paise: 6000000,
    expected_date: "2026-11-19",
    order_numbers: ["ORD-1041"], // the shortfall's order, so the PO gets its priority
    priority: null,
  });
  expect(await screen.findByText("PO-0003 raised")).toBeInTheDocument();
});

test("a purchaser can raise but not approve", async () => {
  mockApi(...signedIn(["purchasing.read", "purchasing.write"]));
  renderApp(
    <WithTopBar>
      <PurchasingPage />
    </WithTopBar>,
    { path: "/purchasing" },
  );
  const po = await screen.findByTestId("po-PO-0002");
  expect(within(po).queryByRole("button", { name: "Approve PO" })).toBeNull();
  expect(within(po).getByText("Owner approves")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "+ Raise PO" })).toBeInTheDocument();
});

test("Raw Material Purchase: KPIs, attention cards by stage, all POs, filters", async () => {
  mockApi(...signedIn(OWNER));
  renderApp(
    <WithTopBar>
      <PurchasingPage />
    </WithTopBar>,
    { path: "/purchasing/purchase" },
  );
  expect(await screen.findByText("Open POs")).toBeInTheDocument();
  expect(screen.getByText("Open spend")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "+ New PO" })).toBeInTheDocument();
  const pending = screen.getByTestId("card-PO-0002");
  expect(within(pending).getByText("Action required")).toBeInTheDocument();
  expect(within(pending).getByRole("button", { name: "Approve PO" })).toBeInTheDocument();
  expect(within(pending).getByText(/Linked: ORD-1041/)).toBeInTheDocument();
  const late = screen.getByTestId("card-PO-0003");
  expect(within(late).getByText("Delayed")).toBeInTheDocument();
  expect(within(late).getByText(/1 day behind schedule/)).toBeInTheDocument();
  expect(within(late).getByRole("button", { name: "Follow up vendor" })).toBeInTheDocument();
  const gate = screen.getByTestId("card-PO-0004");
  expect(within(gate).getByText("Ready for QC")).toBeInTheDocument();
  const table = screen.getByRole("table");
  expect(within(table).getAllByRole("row")).toHaveLength(4); // header + 3
  fireEvent.change(screen.getByLabelText("Supplier"), { target: { value: "Mukand Wires" } });
  expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);
  fireEvent.change(screen.getByLabelText("Supplier"), { target: { value: "all" } });
  fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "high" } });
  expect(within(screen.getByRole("table")).getByText("PO-0002")).toBeInTheDocument();
  expect(within(screen.getByRole("table")).queryByText("PO-0004")).toBeNull();
});

test("QC from the card: accepted + rejected must match the gate entry, rejection needs a reason", async () => {
  const { calls } = mockApi(
    ...signedIn(OWNER),
    route("POST", "/api/purchasing/purchase-orders/PO-0004/qc", () =>
      json({ ...PURCHASES.attention[2], status: "received", stage: "received", events: [] }),
    ),
  );
  renderApp(
    <WithTopBar>
      <PurchasingPage />
    </WithTopBar>,
    { path: "/purchasing/purchase" },
  );
  const gate = await screen.findByTestId("card-PO-0004");
  fireEvent.click(within(gate).getByRole("button", { name: "QC" }));
  const dialog = await screen.findByRole("dialog");
  const save = within(dialog).getByRole("button", { name: "Save QC" });
  fireEvent.change(within(dialog).getByLabelText(/Accepted/), { target: { value: "1.5" } });
  expect(save).toBeDisabled(); // 1.5 + 0 isn't the 2 t at the gate
  fireEvent.change(within(dialog).getByLabelText(/Rejected/), { target: { value: "0.5" } });
  expect(save).toBeDisabled(); // a rejection needs a reason
  fireEvent.change(within(dialog).getByLabelText("Why rejected"), { target: { value: "Rusty" } });
  fireEvent.click(save);
  await waitFor(() => expect(calls.some((c) => c.url.endsWith("/qc"))).toBe(true));
  const body = await calls.find((c) => c.url.endsWith("/qc"))!.json();
  expect(body).toEqual({ accepted: "1.5", rejected: "0.5", reason: "Rusty" });
});

test("a PO opens with its timeline and next steps", async () => {
  mockApi(
    ...signedIn(OWNER),
    route("GET", "/api/purchasing/purchase-orders/PO-0003", () =>
      json({
        ...PURCHASES.attention[1],
        events: [
          {
            kind: "raised",
            summary: "Raised · 3 t Boron steel wire",
            at: "2026-11-10T09:00:00Z",
            by: "Arjun",
          },
          {
            kind: "approved",
            summary: "Approved by the owner · PO sent to the supplier",
            at: "2026-11-11T09:00:00Z",
            by: "Owner",
          },
        ],
      }),
    ),
  );
  renderApp(
    <WithTopBar>
      <PurchasingPage />
    </WithTopBar>,
    { path: "/purchasing/purchase" },
  );
  fireEvent.click(await within(await screen.findByRole("table")).findByText("PO-0003"));
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText("Raised · 3 t Boron steel wire")).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Gate entry" })).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Follow up vendor" })).toBeInTheDocument();
});
