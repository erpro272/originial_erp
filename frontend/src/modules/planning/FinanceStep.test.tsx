import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import type { Plan } from "./api";
import { FinanceStep } from "./FinanceStep";

const order = (number: string, customer: string) => ({
  number,
  customer,
  product: "P",
  qty: 1,
  unit: "pcs",
  value: 1,
  deadline: "2026-11-20",
  priority: "high",
  est_margin: 20,
});
const fin = (penalty: number, fix: number) => {
  const rows = [
    {
      id: "a",
      value: 50000000,
      cost: 37500000,
      penalty: 0,
      fix_cost: 0,
      contribution: 12500000,
      margin: 25,
      late_days: 0,
    },
    {
      id: "b",
      value: 60000000,
      cost: 43200000,
      penalty,
      fix_cost: fix,
      contribution: 16800000 - penalty - fix,
      margin: Number(((100 * (16800000 - penalty - fix)) / 60000000).toFixed(1)),
      late_days: penalty ? 1 : 0,
    },
    {
      id: "c",
      value: 120000000,
      cost: 98400000,
      penalty: 0,
      fix_cost: 0,
      contribution: 21600000,
      margin: 18,
      late_days: 0,
    },
  ];
  const value = 230000000;
  const mfg = 179100000;
  const contribution = value - mfg - penalty - fix;
  return {
    rows,
    value,
    cost: mfg + fix,
    mfg_cost: mfg,
    breakdown: {
      materials: 113000000,
      labour: 28000000,
      machine: 20000000,
      overheads: 12000000,
      packaging: 6100000,
    },
    base_contribution: value - mfg,
    penalty,
    fix_cost: fix,
    contribution,
    margin: Number(((100 * contribution) / value).toFixed(1)),
    per_day: 0,
    fixes: [],
    min_margin: 18,
    penalty_rule: { mode: "fixed", value: 2000000 },
  };
};

function makePlan(selected: boolean): Plan {
  return {
    id: "p1",
    status: "generated",
    rule: "value",
    version: 2,
    generated_at: new Date().toISOString(),
    result: {
      selection: {
        orders: {
          a: order("ORD-1", "LMN"),
          b: order("ORD-2", "XYZ Ltd"),
          c: order("ORD-3", "PQR"),
        },
      },
      sequence: { overview: { late: selected ? 0 : 1 } },
      finance: {
        before: fin(2000000, 0),
        with: selected ? fin(0, 1840000) : fin(2000000, 0),
        fixes: [
          {
            id: "night:cnc",
            label: "Night shift on CNC 01 · 19 Nov",
            cost: 1840000,
            penalty_avoided: 2000000,
            solves: ["ORD-2 ships 1 day late"],
            selected,
          },
          {
            id: "express:steel",
            label: "Express steel",
            cost: 620000,
            penalty_avoided: 0,
            solves: ["Steel short 0.5 t"],
            selected: false,
          },
        ],
      },
    },
  } as unknown as Plan;
}

const signedIn = () => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () =>
    json({ ...ME, permissions: ["planning.read", "planning.write", "settings.write"] }),
  ),
  route("GET", "/api/me/preferences/table.planning-profit.columns", () =>
    json({ key: "x", value: {} }),
  ),
];

test("before fixes: KPIs, cost breakdown, penalty line, margins against the minimum", async () => {
  mockApi(...signedIn());
  renderApp(<FinanceStep plan={makePlan(false)} go={vi.fn()} />);
  expect((await screen.findAllByText("₹23.0 L")).length).toBe(2); // KPI + table total
  expect(screen.getByText("After ₹20,000 penalty at risk")).toBeInTheDocument();
  expect(screen.getByText("ORD-2 · 1 day × ₹20,000")).toBeInTheDocument();
  const costs = screen.getByLabelText("Cost breakdown");
  expect(within(costs).getByText("Raw materials")).toBeInTheDocument();
  expect(within(costs).getByText("63.1%")).toBeInTheDocument();
  expect(screen.getByText("With selected fixes (0)")).toBeInTheDocument();
  expect(screen.getByText(/No fixes chosen yet/)).toBeInTheDocument();
  expect(screen.getByText("ORD-3")).toBeInTheDocument();
  expect(screen.getByText("Total for 3 orders")).toBeInTheDocument();
});

test("ticking a fix applies it to the plan", async () => {
  const { calls } = mockApi(
    ...signedIn(),
    route("PATCH", "/api/planning/plans/p1", () =>
      json({ plan: makePlan(true), diff: {}, tabs: [2, 3, 4, 5] }),
    ),
  );
  renderApp(<FinanceStep plan={makePlan(false)} go={vi.fn()} />);
  fireEvent.click(await screen.findByLabelText("Apply Night shift on CNC 01 · 19 Nov"));
  await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
  const body = await calls.find((c) => c.method === "PATCH")!.json();
  expect(body).toEqual({ fixes: ["night:cnc"] });
});

test("with selected fixes: fix cost line, no penalty, the insight compares cost and penalty", async () => {
  mockApi(...signedIn());
  renderApp(<FinanceStep plan={makePlan(true)} go={vi.fn()} />);
  expect(await screen.findByText("With selected fixes (1)")).toBeInTheDocument();
  expect(screen.getByText("No penalties · all on time")).toBeInTheDocument();
  expect(screen.getByText("Incl. ₹18,400 in fixes")).toBeInTheDocument();
  expect(screen.getByText("−₹18,400")).toBeInTheDocument();
  expect(
    screen.getByText(
      "The fixes cost ₹1,600 less than the penalty they avoid, and every order ships on time.",
    ),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Before fixes" }));
  expect(screen.getByText("After ₹20,000 penalty at risk")).toBeInTheDocument();
});

test("each fix shows its effect in the current plan", async () => {
  mockApi(...signedIn());
  const p = makePlan(true);
  const fixes = (p.result.finance as unknown as { fixes: Record<string, unknown>[] }).fixes;
  fixes[0] = { ...fixes[0], status: "no_effect", effect: "No effect: ORD-2 still 1 day late" };
  fixes[1] = {
    ...fixes[1],
    status: "planned",
    effect: "Covers the Steel shortage with an express PO (planned: the PO still has to be raised)",
  };
  renderApp(<FinanceStep plan={p} go={vi.fn()} />);
  expect(await screen.findByText("No effect")).toBeInTheDocument();
  expect(screen.getByText("No effect: ORD-2 still 1 day late")).toBeInTheDocument();
  expect(screen.getByText("Planned · PO needed")).toBeInTheDocument();
});
