import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import type { Plan, SeqRow } from "./api";
import { generatedLabel, groupReason } from "./format";
import { SequenceStep } from "./SequenceStep";

const row = (
  id: string,
  rank: number,
  machines: string[],
  extra: Partial<SeqRow> = {},
): SeqRow => ({
  id,
  rank,
  start: "2026-11-16",
  finish: "2026-11-18",
  deadline: "2026-11-20",
  buffer: 2,
  late_days: 0,
  group: 0,
  machines,
  warn_machines: [],
  locked: false,
  pinned: null,
  status: "on_time" as const,
  ...extra,
});

const order = (number: string) => ({
  number,
  customer: "Tata Motors",
  product: "M8 nylock nuts",
  qty: 5000,
  unit: "pcs",
  value: 1,
  deadline: "2026-11-20",
  priority: "high",
  est_margin: 22,
});

function makePlan(over: Partial<Plan["result"]["sequence"]> = {}): Plan {
  const sequence = {
    rule: "value",
    start: "2026-11-16",
    rows: [
      row("a", 1, ["Press 01", "CNC 01"], { warn_machines: ["CNC 01"] }),
      row("b", 2, ["CNC 01", "QC"], {
        warn_machines: ["CNC 01"],
        late_days: 1,
        buffer: -1,
        status: "late",
        finish: "2026-11-21",
      }),
    ],
    groups: [{ orders: ["a", "b"], shared: ["CNC 01"], conflict: ["CNC 01"] }],
    hint: {
      sequence: ["b", "a"],
      title: "Run ORD-2 before ORD-1",
      text: "All 2 orders ship on time.",
      moved: "b",
      dismissed: false,
    },
    overview: {
      orders: 2,
      start: "2026-11-16",
      end: "2026-11-21",
      days: 6,
      utilisation: 94,
      on_time: 1,
      bottlenecks: 1,
      parallel: 1,
      late: 1,
    },
    feasibility: {
      ok: false,
      lines: [
        {
          kind: "constraint",
          tone: "bad",
          text: "CNC 01 over capacity by 8 hrs, 16–18 Nov",
          orders: ["b"],
          machine: "CNC 01",
        },
        {
          kind: "late",
          tone: "warn",
          text: "ORD-2 ships 1 day late",
          orders: ["b"],
          machine: null,
        },
      ],
    },
    ...over,
  };
  return {
    id: "p1",
    number: "PLAN-001",
    status: "generated",
    needs_reapproval: false,
    rule: "value",
    start_date: "2026-11-16",
    version: 3,
    generated_at: new Date().toISOString(),
    approved_at: null,
    approval_note: null,
    last_change: null,
    result: {
      selection: { orders: { a: order("ORD-1"), b: order("ORD-2") } },
      sequence,
    },
  } as unknown as Plan;
}

const signedIn = () => [
  route("POST", "/api/auth/refresh", () =>
    json({ access_token: "tok", token_type: "bearer", expires_in: 900 }),
  ),
  route("GET", "/api/auth/me", () =>
    json({ ...ME, permissions: ["planning.read", "planning.write"] }),
  ),
];

test("group reason and generated label", () => {
  const rows = [
    { id: "a", machines: ["CNC 01"] },
    { id: "b", machines: ["CNC 01", "QC"] },
    { id: "c", machines: ["Assembly 2"] },
  ];
  expect(groupReason({ orders: ["a", "c"], shared: [], conflict: [] }, rows)).toBe(
    "different lines, same days",
  );
  expect(groupReason({ orders: ["a", "b"], shared: ["CNC 01"], conflict: ["CNC 01"] }, rows)).toBe(
    "both need CNC 01, which causes the overload",
  );
  expect(groupReason({ orders: ["a", "b", "c"], shared: ["CNC 01"], conflict: [] }, rows)).toBe(
    "both need CNC 01, one after the other",
  );
  const now = new Date("2026-11-16T20:00:00");
  expect(generatedLabel("2026-11-16T19:58:00", now)).toBe("today, 19:58");
  expect(generatedLabel("2026-11-15T09:10:00", now)).toBe("yesterday, 09:10");
});

test("step 2: overview, feasibility, hint, parallel group, routes; apply shows the effect with Undo", async () => {
  const before = makePlan();
  const after = makePlan({
    rule: "custom",
    rows: [row("b", 1, ["CNC 01", "QC"]), row("a", 2, ["Press 01", "CNC 01"])],
    groups: [{ orders: ["b", "a"], shared: ["CNC 01"], conflict: [] }],
    hint: null,
    overview: {
      orders: 2,
      start: "2026-11-16",
      end: "2026-11-20",
      days: 5,
      utilisation: 94,
      on_time: 2,
      bottlenecks: 0,
      parallel: 1,
      late: 0,
    },
    feasibility: { ok: true, lines: [] },
  });
  const { calls } = mockApi(
    ...signedIn(),
    route("PATCH", "/api/planning/plans/p1", () => json({ plan: after, diff: {}, tabs: [2] })),
  );
  renderApp(<SequenceStep plan={before} go={vi.fn()} />);
  expect(await screen.findByText("CNC 01 over capacity by 8 hrs, 16–18 Nov")).toBeInTheDocument();
  expect(screen.getByText("Needs adjustment")).toBeInTheDocument();
  expect(screen.getByText("See hint ↓")).toBeInTheDocument();
  expect(screen.getByText("· both need CNC 01, which causes the overload")).toBeInTheDocument();
  expect(screen.getByText("Late · 1 day")).toBeInTheDocument();
  expect(screen.getByText("Start: Mon 16 Nov")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Highest value" })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  fireEvent.click(await screen.findByRole("button", { name: "Apply this order" }));
  await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
  const patch = calls.find((c) => c.method === "PATCH")!;
  expect(await patch.json()).toEqual({ apply_hint: true });
  // the parent passes the new plan in a real page; here the banner reads the response
  expect(
    await screen.findByText("Late deliveries 1 → 0 · Plan 6 → 5 days · Bottlenecks 1 → 0", {
      exact: false,
    }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
});

test("step 2: lock, rule and dismiss send the right edits", async () => {
  const { calls } = mockApi(
    ...signedIn(),
    route("PATCH", "/api/planning/plans/p1", () => json({ plan: makePlan(), diff: {}, tabs: [] })),
  );
  renderApp(<SequenceStep plan={makePlan()} go={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Lock ORD-1" }));
  await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(1));
  fireEvent.click(screen.getByRole("tab", { name: "Deadline" }));
  await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(2));
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(3));
  const bodies = await Promise.all(calls.filter((c) => c.method === "PATCH").map((c) => c.json()));
  expect(bodies).toEqual([{ lock: { a: true } }, { rule: "deadline" }, { dismiss_hint: true }]);
});

test("step 2: a dismissed hint is hidden and the feasibility card says so", async () => {
  mockApi(...signedIn());
  const p = makePlan({
    hint: {
      sequence: ["b", "a"],
      title: "Run ORD-2 before ORD-1",
      text: "x",
      moved: "b",
      dismissed: true,
    },
  });
  renderApp(<SequenceStep plan={p} go={vi.fn()} />);
  expect(await screen.findByText("ORD-2 ships 1 day late")).toBeInTheDocument();
  expect(screen.queryByText("Run ORD-2 before ORD-1")).toBeNull();
  expect(screen.queryByText("See hint ↓")).toBeNull();
});
