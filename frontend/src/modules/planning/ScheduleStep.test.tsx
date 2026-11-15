import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { json, ME, mockApi, renderApp, route } from "@/test/utils";
import type { Plan } from "./api";
import { hrs, range } from "./format";
import { ScheduleStep } from "./ScheduleStep";

const T = "2026-11-16";
const order = (number: string, customer: string) => ({
  number,
  customer,
  product: "M8 nylock nuts",
  qty: 5000,
  unit: "pcs",
  value: 800000,
  deadline: "2026-11-20",
  priority: "high",
  est_margin: 22,
});
const step = (machine: string, name: string, start: string, finish: string, setup = 0) => ({
  machine,
  name,
  start,
  finish,
  hours: { [start]: 8, [finish]: 8 },
  setup,
});

function makePlan(): Plan {
  return {
    id: "p1",
    number: "PLAN-001",
    status: "generated",
    needs_reapproval: false,
    rule: "value",
    start_date: T,
    version: 3,
    generated_at: new Date().toISOString(),
    approved_at: null,
    approval_note: null,
    last_change: null,
    schedule_saved_at: null,
    result: {
      selection: {
        orders: { a: order("ORD-1", "Tata Motors"), b: order("ORD-2", "Eicher") },
        running: [
          {
            id: "r",
            number: "ORD-9",
            customer: "Bajaj Auto",
            product: "P",
            progress: 60,
            start: T,
            finish: T,
            machines: ["CNC 01"],
            machine: "CNC 01",
          },
        ],
      },
      sequence: {
        rows: [
          {
            id: "a",
            rank: 1,
            start: T,
            finish: "2026-11-17",
            deadline: "2026-11-20",
            buffer: 3,
            late_days: 0,
            group: 0,
            machines: ["Press 01", "CNC 01"],
            warn_machines: [],
            locked: false,
            pinned: null,
            status: "material",
          },
          {
            id: "b",
            rank: 2,
            start: "2026-11-19",
            finish: "2026-11-21",
            deadline: "2026-11-20",
            buffer: -1,
            late_days: 1,
            group: 1,
            machines: ["CNC 01"],
            warn_machines: ["CNC 01"],
            locked: false,
            pinned: null,
            status: "late",
          },
        ],
      },
      schedule: {
        days: [T],
        today: T,
        rows: [
          {
            id: "r",
            running: true,
            steps: [step("m2", "CNC 01", T, T)],
            start: T,
            finish: T,
            deadline: null,
            over_days: [],
            short: false,
            wait: [],
          },
          {
            id: "a",
            running: false,
            steps: [
              step("m1", "Press 01", T, T, 4),
              step("m2", "CNC 01", "2026-11-17", "2026-11-17"),
            ],
            start: T,
            finish: "2026-11-17",
            deadline: "2026-11-20",
            over_days: [],
            short: true,
            wait: [],
          },
          {
            id: "b",
            running: false,
            steps: [step("m2", "CNC 01", "2026-11-19", "2026-11-21")],
            start: "2026-11-19",
            finish: "2026-11-21",
            deadline: "2026-11-20",
            over_days: [],
            short: false,
            wait: [{ machine: "CNC 01", from: T, to: "2026-11-18" }],
          },
        ],
        load: [
          { machine: "m1", name: "Press 01", days: { [T]: 40 }, over: false },
          { machine: "m2", name: "CNC 01", days: { [T]: 100, "2026-11-17": 150 }, over: true },
        ],
        bottlenecks: [],
        constraints: [],
        chips: [
          {
            kind: "constraint",
            tone: "bad",
            title: "CNC 01 over capacity",
            text: "16–18 Nov · +8 hrs · ORD-2 waits",
          },
          {
            kind: "material",
            tone: "warn",
            title: "Steel short 0.5 t",
            text: "needed 16 Nov for ORD-1",
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
    json({ ...ME, permissions: ["planning.read", "planning.write"] }),
  ),
];

test("helpers: hours and same-day ranges", () => {
  expect(hrs(1)).toBe("1 hr");
  expect(hrs(2.25)).toBe("2.3 hrs");
  expect(hrs(15)).toBe("15 hrs");
  expect(range("2026-11-25", "2026-11-25")).toBe("25 Nov");
});

test("schedule: chips, running + planned rows, statuses, routes, load and the queue", async () => {
  mockApi(...signedIn());
  renderApp(<ScheduleStep plan={makePlan()} go={vi.fn()} />);
  expect(await screen.findByText("CNC 01 over capacity")).toBeInTheDocument();
  expect(screen.getByText("Steel short 0.5 t")).toBeInTheDocument();
  expect(screen.getByText("ORD-9")).toBeInTheDocument();
  expect(screen.getByText("Ongoing")).toBeInTheDocument();
  const a = screen.getByTestId("gantt-ORD-1");
  expect(within(a).getByText("Material short")).toBeInTheDocument();
  expect(within(a).getByText("Setup")).toBeInTheDocument();
  expect(within(screen.getByTestId("gantt-ORD-2")).getByText("Late 1 day")).toBeInTheDocument();
  expect(screen.getByTitle("Waiting for CNC 01: fully booked 16–18 Nov")).toBeInTheDocument();
  expect(screen.getByText("150%")).toBeInTheDocument();
  expect(screen.getByText("Over")).toBeInTheDocument();
  expect(screen.getByText(/16 Nov – 3 Dec 2026/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Later week" }));
  expect(screen.getByText(/23 Nov – 10 Dec 2026/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "↶ Undo" })).toBeDisabled();
});

test("schedule: save is a checkpoint", async () => {
  const { calls } = mockApi(
    ...signedIn(),
    route("POST", "/api/planning/plans/p1/save-schedule", () =>
      json({ ...makePlan(), schedule_saved_at: new Date().toISOString() }),
    ),
  );
  renderApp(<ScheduleStep plan={makePlan()} go={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Save schedule" }));
  await waitFor(() => expect(calls.some((c) => c.url.endsWith("/save-schedule"))).toBe(true));
  expect(await screen.findByText("Schedule saved")).toBeInTheDocument();
});
