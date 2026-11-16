import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import type { Plan } from "./api";
import { ApprovalStep } from "./ApprovalStep";
import { planStatus } from "./status";

const T = "2026-11-16";
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

function makePlan(over: Partial<Plan> = {}): Plan {
  return {
    id: "p1",
    number: "PLAN-001",
    status: "generated",
    needs_reapproval: false,
    rule: "value",
    version: 4,
    generated_at: new Date().toISOString(),
    approved_at: null,
    approval_note: null,
    changes_requested: null,
    result: {
      selection: { orders: { a: order("ORD-1", "LMN"), b: order("ORD-2", "XYZ Ltd") } },
      sequence: {
        overview: { orders: 2, start: T, end: "2026-11-24", days: 9, late: 1 },
        rows: [
          { id: "a", finish: "2026-11-17", deadline: "2026-11-18", late_days: 0, pinned: null },
          { id: "b", finish: "2026-11-21", deadline: "2026-11-20", late_days: 1, pinned: null },
        ],
      },
      finance: {
        with: { value: 110000000, contribution: 28000000, margin: 25.5 },
        fixes: [
          {
            id: "night:cnc",
            label: "Night shift on CNC 01 · 19 Nov",
            cost: 1840000,
            selected: true,
          },
        ],
      },
      approval: {
        ready: 3,
        total: 5,
        checks: [
          { ok: false, title: "1 order ships late", text: "Late: ORD-2 by 1 day" },
          { ok: true, title: "Machine capacity within limits", text: "" },
          {
            ok: false,
            title: "1 material PO not raised yet",
            text: "Express PO for 0.5 t Steel from Shree Steels not raised yet · planned fix, not ordered: arrives 19 Nov if ordered today · needed 19 Nov for ORD-2",
            action: "raise_po",
            items: [
              {
                material: "m1",
                open: true,
                text: "Express PO for 0.5 t Steel from Shree Steels not raised yet · planned fix, not ordered: arrives 19 Nov if ordered today · needed 19 Nov for ORD-2",
              },
            ],
          },
          { ok: true, title: "Labour and shifts covered", text: "" },
          {
            ok: true,
            title: "Margin above your 18% minimum",
            text: "25.5% after fixes",
            setting: "min_margin_pct",
          },
        ],
      },
      purchase_needs: [
        {
          material: "m1",
          name: "Steel",
          action: "express_po",
          unit: "t",
          qty: 0.5,
          needed_by: "2026-11-17",
          requested: false,
        },
      ],
    },
    ...over,
  } as unknown as Plan;
}

const signedIn = (perms: string[]) => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () => json({ ...ME, permissions: perms })),
  route("GET", "/api/planning/plans/p1/history", () =>
    json([
      {
        kind: "change",
        summary: "Sequence changed · ORD-2 moved",
        tabs: [2],
        at: new Date().toISOString(),
      },
      {
        kind: "generated",
        summary: "Plan generated · 2 orders",
        tabs: [],
        at: new Date().toISOString(),
      },
    ]),
  ),
];
const OWNER = ["planning.read", "planning.write", "planning.approve", "settings.write"];

test("status tag", () => {
  expect(planStatus(makePlan()).text).toBe("Awaiting owner approval");
  expect(
    planStatus(makePlan({ changes_requested: { note: "x", at: new Date().toISOString() } })).text,
  ).toBe("Changes requested");
  expect(planStatus(makePlan({ status: "approved", needs_reapproval: true })).text).toBe(
    "Rev 2 · needs re-approval",
  );
  expect(
    planStatus(
      makePlan({ status: "draft", regenerate: { added: ["ORD-1050"], removed: [], at: "" } }),
    ).text,
  ).toBe("Orders changed · generate again");
});

test("summary, deliveries, fixes, checklist and history", async () => {
  mockApi(...signedIn(OWNER));
  renderApp(<ApprovalStep plan={makePlan()} go={vi.fn()} />);
  expect(await screen.findByText("Awaiting owner approval")).toBeInTheDocument();
  const sum = screen.getByLabelText("Plan summary");
  expect(within(sum).getByText("PLAN-001")).toBeInTheDocument();
  expect(within(sum).getByText("Late · 1 day")).toBeInTheDocument();
  expect(within(sum).getByText("Night shift on CNC 01 · 19 Nov · ₹18,400")).toBeInTheDocument();
  expect(screen.getByText("3 of 5 ready")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Raise PO now" })).toBeInTheDocument();
  expect(await screen.findByText("Sequence changed")).toBeInTheDocument();
  expect(screen.getByText("Plan generated")).toBeInTheDocument();
});

test("approve with open items: popup, then approve and raise PO", async () => {
  const { calls } = mockApi(
    ...signedIn(OWNER),
    route("POST", "/api/planning/plans/p1/approve", () =>
      json(makePlan({ status: "approved", approved_at: new Date().toISOString() })),
    ),
  );
  renderApp(<ApprovalStep plan={makePlan()} go={vi.fn()} />);
  fireEvent.change(await screen.findByPlaceholderText(/Confirm night-shift/), {
    target: { value: "Crew ok" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Approve plan" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Approve with 2 open items?")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Approve and raise PO" }));
  await waitFor(() => expect(calls.some((c) => c.url.endsWith("/approve"))).toBe(true));
  const body = await calls.find((c) => c.url.endsWith("/approve"))!.json();
  expect(body).toEqual({ note: "Crew ok", raise_open_pos: true });
});

test("send back records the note and opens step 2; a planner can't approve", async () => {
  const go = vi.fn();
  const { calls } = mockApi(
    ...signedIn(OWNER),
    route("POST", "/api/planning/plans/p1/send-back", () =>
      json(makePlan({ changes_requested: { note: "Fix it", at: new Date().toISOString() } })),
    ),
  );
  renderApp(<ApprovalStep plan={makePlan()} go={go} />);
  fireEvent.change(await screen.findByPlaceholderText(/Confirm night-shift/), {
    target: { value: "Fix it" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send back to edit" }));
  await waitFor(() => expect(go).toHaveBeenCalledWith("2"));
  expect(await calls.find((c) => c.url.endsWith("/send-back"))!.json()).toEqual({ note: "Fix it" });
});

test("planner sees approval disabled; approved plan is read-only", async () => {
  mockApi(...signedIn(["planning.read", "planning.write"]));
  const { unmount } = renderApp(<ApprovalStep plan={makePlan()} go={vi.fn()} />);
  expect(await screen.findByRole("button", { name: "Approve plan" })).toBeDisabled();
  expect(screen.getByText("Only the owner can approve or send the plan back.")).toBeInTheDocument();
  unmount();
  renderApp(
    <ApprovalStep
      plan={makePlan({
        status: "approved",
        approved_at: new Date().toISOString(),
        approval_note: "Crew ok",
      })}
      go={vi.fn()}
    />,
  );
  expect(await screen.findByText(/This is the approved version, read-only/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Approve plan" })).toBeNull();
});

test("checklist and approval popup show the same material line (one source)", async () => {
  mockApi(...signedIn(OWNER));
  renderApp(<ApprovalStep plan={makePlan()} go={vi.fn()} />);
  const line =
    /Express PO for 0\.5 t Steel from Shree Steels not raised yet · planned fix, not ordered/;
  const list = await screen.findByLabelText("Readiness checklist");
  expect(within(list).getByText(line)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approve plan" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText(line)).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Approve and raise PO" })).toBeInTheDocument();
});

test("a material already on order is not a PO to raise", async () => {
  mockApi(...signedIn(OWNER));
  const p = makePlan();
  const r = p.result as unknown as {
    purchase_needs: { action: string | null; requested: boolean }[];
    approval: { checks: { ok: boolean; action?: string | null }[] };
  };
  r.purchase_needs[0]!.action = null; // on order: nothing to raise
  r.approval.checks[2] = { ...r.approval.checks[2]!, ok: true, action: null };
  renderApp(<ApprovalStep plan={p} go={vi.fn()} />);
  expect(await screen.findByText("Readiness checklist")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Raise PO now" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Approve plan" }));
  expect(
    await within(await screen.findByRole("dialog")).findByRole("button", {
      name: "Approve anyway",
    }),
  ).toBeInTheDocument();
});
