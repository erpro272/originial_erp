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
  ],
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
        },
      ],
    },
  ],
  categories: ["Bar", "Wire rod"],
  suppliers: ["Shree Steels"],
  today: "2026-11-16",
};
INV.attention = [INV.materials[0], INV.materials[1]];

const signedIn = (perms: string[]) => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () => json({ ...ME, permissions: perms })),
  route("GET", "/api/me/preferences/table.purchasing-inventory.columns", () =>
    json({ key: "x", value: {} }),
  ),
  route("GET", "/api/purchasing/inventory", () => json(INV)),
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
    within(screen.getByTestId("po-PO-0002")).getByText("Awaiting approval"),
  ).toBeInTheDocument();
  expect(
    within(screen.getByTestId("po-PO-0002")).getByRole("button", { name: "Approve" }),
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
  });
  expect(await screen.findByText("PO-0003 raised")).toBeInTheDocument();
});

test("a purchaser can raise but not approve; the other tabs come next", async () => {
  mockApi(...signedIn(["purchasing.read", "purchasing.write"]));
  renderApp(
    <WithTopBar>
      <PurchasingPage />
    </WithTopBar>,
    { path: "/purchasing" },
  );
  const po = await screen.findByTestId("po-PO-0002");
  expect(within(po).queryByRole("button", { name: "Approve" })).toBeNull();
  expect(within(po).getByText("Owner approves")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "+ Raise PO" })).toBeInTheDocument();
});
