import { fireEvent, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import { DashboardPage } from "./DashboardPage";

const days = Array.from({ length: 13 }, (_, i) => `2026-11-${String(16 + i).padStart(2, "0")}`);
const DASH = {
  range: { start: "2026-11-16", end: "2026-11-28", days, today: "2026-11-16" },
  kpis: {
    utilization: {
      value: 61,
      unit: "%",
      note: "Average machine load, 12 working days",
      trend: [50, 61, 70],
    },
    in_progress: { value: 204000, unit: "pcs", note: "4 orders in production", trend: [] },
    cycle_time: {
      value: 2.8,
      unit: "days",
      note: "Planned (no finished production recorded yet)",
      trend: [],
    },
    delayed: {
      value: 1,
      unit: "orders",
      note: "Open orders at risk of missing their date",
      trend: [],
    },
    delayed_orders: [
      {
        id: "o9",
        number: "ORD-1046",
        customer: "Tata Motors",
        due: "2026-11-13",
        reason: "3 days past the 13 Nov due date",
      },
    ],
  },
  timeline: {
    source: "committed",
    plan: null,
    draft: {
      id: "p1",
      number: "PLAN-001",
      status: "awaiting",
      orders: ["ORD-1044"],
      approved_at: null,
      needs_reapproval: false,
    },
    rows: [
      {
        order_id: "o1",
        number: "ORD-1035",
        customer: "Ashok Leyland",
        status: "in_production",
        start: "2026-11-16",
        finish: "2026-11-20",
        due: "2026-11-24",
        progress_pct: 40,
        late: false,
      },
    ],
    machines: [
      {
        machine: "m1",
        name: "CNC 01",
        current: 90,
        after: 120,
        peak_after: 150,
        peak_day: "2026-11-18",
        over: true,
        days: [{ day: "2026-11-18", current: 90, after: 150 }],
        orders: [
          { number: "ORD-1035", customer: "Ashok Leyland", hours: 20, added: false },
          { number: "ORD-1044", customer: "Escorts Kubota", hours: 12, added: true },
        ],
      },
      {
        machine: "m2",
        name: "Press 01",
        current: 40,
        after: 55,
        peak_after: 80,
        peak_day: "2026-11-17",
        over: false,
        days: [],
        orders: [],
      },
    ],
  },
  cash_flow: ["06", "07", "08", "09", "10", "11"].map((m, i) => ({
    month: `2026-${m}`,
    label: ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov"][i],
    invoiced: 2e9,
    collected: 1.8e9,
    payables: 1e9,
    paid: 9e8,
  })),
  customers: {
    period_label: "FY to date (1 Apr – 16 Nov)",
    high_value: 3,
    repeat: 28,
    inactive: 4,
    top: { id: "c1", name: "Mahindra", sales_paise: 2.6e9 },
    total_orders: 44,
  },
  alerts: [
    {
      id: "load-m1",
      source: "planning",
      tone: "hi",
      title: "CNC 01 over capacity",
      text: "150% on 18 Nov",
      at: "2026-11-18",
      link: "/planning/p1?step=3",
    },
    {
      id: "po-1",
      source: "purchasing",
      tone: "md",
      title: "PO-0058 awaiting your approval",
      text: "JSW Steel",
      at: "2026-11-16",
      link: "/purchasing/purchase?po=x",
    },
  ],
};

test("executive dashboard: KPIs, timeline, machine overload detail, customers and alerts that link to the source", async () => {
  const { calls } = mockApi(
    route("POST", "/api/auth/refresh", () =>
      json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
    ),
    route("GET", "/api/auth/me", () => json({ ...ME, permissions: ["dashboard.read"] })),
    route("GET", "/api/dashboard", () => json(DASH)),
  );
  renderApp(<DashboardPage />, { path: "/dashboard" });
  expect(await screen.findByRole("heading", { name: "Operations Dashboard" })).toBeInTheDocument();
  expect(await screen.findByText("61%")).toBeInTheDocument();
  expect(screen.getByText("2,04,000")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /Date range: 16 Nov – 28 Nov 2026/ }),
  ).toBeInTheDocument();

  // delayed orders open the list with the reason, linking to the order
  fireEvent.click(screen.getByRole("button", { name: /Delayed Orders/ }));
  const dlg = await screen.findByRole("dialog", { name: "Delayed orders" });
  expect(within(dlg).getByText("3 days past the 13 Nov due date")).toBeInTheDocument();
  expect(within(dlg).getByRole("link", { name: /ORD-1046/ })).toHaveAttribute(
    "href",
    "/orders?q=ORD-1046",
  );
  fireEvent.keyDown(dlg, { key: "Escape" });

  // timeline mirrors the schedule; the working plan's orders are explained
  expect(screen.getByRole("link", { name: /ORD-1035 · Ashok Leyland/ })).toHaveAttribute(
    "href",
    "/planning/p1?step=3",
  );
  expect(screen.getByText(/has 1 new order not approved yet/)).toBeInTheDocument();

  // overloaded machine: what causes it
  fireEvent.click(
    screen.getByRole("button", {
      name: /CNC 01: current plan 90%, after new orders 120%, over capacity/,
    }),
  );
  const m = await screen.findByRole("dialog", { name: /CNC 01 · machine load/ });
  expect(
    within(m).getByText(/Over capacity after the new orders: 150% on .*18 Nov/),
  ).toBeInTheDocument();
  expect(within(m).getByText("New order · PLAN-001")).toBeInTheDocument();
  expect(within(m).getByRole("link", { name: /Open PLAN-001's schedule/ })).toHaveAttribute(
    "href",
    "/planning/p1?step=3",
  );
  fireEvent.keyDown(m, { key: "Escape" });

  // customers: chips open the Customers list filtered
  expect(screen.getByRole("link", { name: /High-value\s*3/ })).toHaveAttribute(
    "href",
    "/orders/customers?health=high_value",
  );
  expect(screen.getByRole("link", { name: /Mahindra/ })).toHaveAttribute(
    "href",
    "/orders/customers/c1",
  );

  // alerts: each links to its source; View All opens the full list in a drawer, with the demo production alerts
  expect(screen.getByRole("link", { name: /CNC 01 over capacity/ })).toHaveAttribute(
    "href",
    "/planning/p1?step=3",
  );
  fireEvent.click(screen.getByRole("button", { name: /View All/ }));
  const sheet = await screen.findByRole("dialog", { name: "Alerts & Updates" });
  expect(
    within(sheet).getByRole("link", { name: /PO-0058 awaiting your approval/ }),
  ).toHaveAttribute("href", "/purchasing/purchase?po=x");
  expect(within(sheet).getAllByText(/Production · demo/).length).toBeGreaterThan(0);
  expect(calls.some((c) => new URL(c.url).pathname === "/api/dashboard")).toBe(true);
});

test("the dashboard is the owner's view", async () => {
  mockApi(
    route("POST", "/api/auth/refresh", () =>
      json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
    ),
    route("GET", "/api/auth/me", () =>
      json({ ...ME, role: "planner", permissions: ["orders.read"] }),
    ),
  );
  const { App } = await import("@/app/App");
  renderApp(<App />, { path: "/dashboard" });
  expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
});
