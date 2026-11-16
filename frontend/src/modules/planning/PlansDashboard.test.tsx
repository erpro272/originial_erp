import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { expect, test } from "vitest";
import { PageActionsSlotProvider } from "@/components/layout/PageActions";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import { PlansDashboard } from "./PlansDashboard";

const row = (number: string, stage: string, extra: Record<string, unknown> = {}) => ({
  id: number,
  number,
  status: stage === "awaiting" ? "generated" : stage === "needs_reapproval" ? "approved" : stage,
  stage,
  created_at: "2026-11-10T09:00:00Z",
  orders: 4,
  start: "2026-11-16",
  end: "2026-11-26",
  approved_at:
    stage === "approved" || stage === "completed" || stage === "needs_reapproval"
      ? "2026-11-12T10:00:00Z"
      : null,
  completed_at: null,
  cancelled_at: null,
  value: 4360000_00,
  contribution: 98771100,
  margin: 22.7,
  snapshot_version: stage === "needs_reapproval" ? 2 : stage === "approved" ? 1 : null,
  ...extra,
});
const PLANS = [
  row("PLAN-005", "draft"),
  row("PLAN-004", "needs_reapproval"),
  row("PLAN-003", "approved"),
  row("PLAN-002", "completed"),
  row("PLAN-001", "cancelled"),
];
/** The app's top bar slot (where "+ New plan" goes). */
function WithTopBar({ children }: { children: ReactNode }) {
  const [el, setEl] = useState<HTMLElement | null>(null);
  return (
    <>
      <div ref={setEl} />
      {el && <PageActionsSlotProvider value={el}>{children}</PageActionsSlotProvider>}
    </>
  );
}

const signedIn = () => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () =>
    json({ ...ME, permissions: ["planning.read", "planning.write", "planning.approve"] }),
  ),
  route("GET", "/api/me/preferences/table.planning-plans.columns", () =>
    json({ key: "x", value: {} }),
  ),
  route("GET", "/api/planning/plan", () => json(null)),
];

test("lists every plan with its stage, money and approval; filters by stage", async () => {
  mockApi(
    ...signedIn(),
    route("GET", "/api/planning/plans", () => json(PLANS)),
  );
  renderApp(
    <WithTopBar>
      <PlansDashboard />
    </WithTopBar>,
  );
  expect(await screen.findByText("PLAN-004")).toBeInTheDocument();
  expect(screen.getAllByText("Needs re-approval").length).toBeGreaterThan(0);
  expect(screen.getByText(/· v2/)).toBeInTheDocument(); // the approved version the money comes from
  expect(screen.getByText("Continue planning →")).toBeInTheDocument(); // the draft being worked on
  fireEvent.click(screen.getByRole("button", { name: /^Completed/ }));
  const table = screen.getByRole("table");
  expect(within(table).getByText("PLAN-002")).toBeInTheDocument();
  expect(within(table).queryByText("PLAN-003")).toBeNull();
});

test("+ New plan opens the plan being worked on instead of starting a second", async () => {
  const { calls } = mockApi(
    ...signedIn(),
    route("GET", "/api/planning/plans", () => json(PLANS)),
  );
  renderApp(
    <WithTopBar>
      <PlansDashboard />
    </WithTopBar>,
  );
  expect(await screen.findByText("PLAN-004")).toBeInTheDocument(); // the list has loaded
  fireEvent.click(screen.getByRole("button", { name: "+ New plan" }));
  expect(await screen.findByText("PLAN-005 is still being worked on")).toBeInTheDocument();
  expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/api/planning/plans"))).toBe(
    false,
  );
});

test("+ New plan starts one when nothing is being worked on", async () => {
  const { calls } = mockApi(
    ...signedIn(),
    route("GET", "/api/planning/plans", () => json(PLANS.slice(1))),
    route("POST", "/api/planning/plans", () =>
      json({ id: "new", number: "PLAN-006", status: "draft" }),
    ),
  );
  renderApp(
    <WithTopBar>
      <PlansDashboard />
    </WithTopBar>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "+ New plan" }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/api/planning/plans"))).toBe(
      true,
    ),
  );
});

test("Delete is offered only for never-approved plans and asks first", async () => {
  const { calls } = mockApi(
    ...signedIn(),
    route("GET", "/api/planning/plans", () => json(PLANS)),
    route("DELETE", "/api/planning/plans/PLAN-001", () => new Response(null, { status: 204 })),
  );
  renderApp(
    <WithTopBar>
      <PlansDashboard />
    </WithTopBar>,
  );
  expect(await screen.findByText("PLAN-004")).toBeInTheDocument();
  // draft and cancelled: yes; approved, needs re-approval, completed: never
  expect(screen.getByRole("button", { name: "Delete PLAN-005" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Delete PLAN-001" })).toBeInTheDocument();
  for (const n of ["PLAN-004", "PLAN-003", "PLAN-002"])
    expect(screen.queryByRole("button", { name: `Delete ${n}` })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Delete PLAN-001" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Delete PLAN-001?")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete plan" }));
  await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  expect(await screen.findByText("PLAN-001 deleted")).toBeInTheDocument();
});
