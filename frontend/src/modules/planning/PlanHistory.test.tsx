import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { expect, test } from "vitest";
import { PageActionsSlotProvider } from "@/components/layout/PageActions";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import { PlanHistory } from "./PlanHistory";
import { PlanningHome } from "./PlanningHome";

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
  row("PLAN-004", "needs_reapproval", {
    revision: 2,
    reapproval_reason: "ORD-1041 now finishes 26 Nov",
  }),
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

test("history lists previous plans; the active plan is one card on top", async () => {
  mockApi(
    ...signedIn(),
    route("GET", "/api/planning/plans", () => json(PLANS)),
  );
  renderApp(
    <WithTopBar>
      <PlanHistory />
    </WithTopBar>,
  );
  const table = await screen.findByRole("table");
  expect(await within(table).findByText("PLAN-004")).toBeInTheDocument();
  expect(within(table).queryByText("PLAN-005")).toBeNull(); // the active plan isn't history
  expect(screen.getByText(/Active plan:/)).toBeInTheDocument();
  expect(within(table).getByText("Rev 2 · needs re-approval")).toBeInTheDocument();
  expect(within(table).getByText("ORD-1041 now finishes 26 Nov")).toBeInTheDocument();
  expect(screen.getByText(/· v2/)).toBeInTheDocument(); // the approved version the money comes from
  // only one active plan: no "+ New plan" while PLAN-005 is open
  expect(screen.queryByRole("button", { name: "+ New plan" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /^Completed/ }));
  expect(within(table).getByText("PLAN-002")).toBeInTheDocument();
  expect(within(table).queryByText("PLAN-003")).toBeNull();
});

test("+ New plan starts one when there is no active plan", async () => {
  const { calls } = mockApi(
    ...signedIn(),
    route("GET", "/api/planning/plans", () => json(PLANS.slice(1))),
    route("POST", "/api/planning/plans", () =>
      json({ id: "new", number: "PLAN-006", status: "draft" }),
    ),
  );
  renderApp(
    <WithTopBar>
      <PlanHistory />
    </WithTopBar>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "+ New plan" }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/api/planning/plans"))).toBe(
      true,
    ),
  );
});

test("Planning with no active plan: start one or open history; never starts one by itself", async () => {
  const { calls } = mockApi(
    ...signedIn(),
    route("GET", "/api/planning/plans", () => json(PLANS.slice(1))),
  );
  renderApp(<PlanningHome />);
  expect(await screen.findByText("No active plan")).toBeInTheDocument();
  expect(await screen.findByText(/PLAN-004/)).toBeInTheDocument();
  expect(
    screen.getByText(/Rev 2 needs re-approval: ORD-1041 now finishes 26 Nov/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "+ New plan" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Plan history" })).toHaveAttribute(
    "href",
    "/planning/history",
  );
  expect(calls.some((c) => c.method === "POST" && c.url.includes("/api/planning/"))).toBe(false);
});

test("Delete is offered only for never-approved plans and asks first", async () => {
  const { calls } = mockApi(
    ...signedIn(),
    route("GET", "/api/planning/plans", () => json(PLANS)),
    route("DELETE", "/api/planning/plans/PLAN-001", () => new Response(null, { status: 204 })),
  );
  renderApp(
    <WithTopBar>
      <PlanHistory />
    </WithTopBar>,
  );
  expect(await screen.findByText("PLAN-004")).toBeInTheDocument();
  // cancelled: yes; approved, needs re-approval, completed: never
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
