import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Selection, SelectionOption } from "./api";
import { addDays, range } from "./format";
import { OrderTimeline } from "./OrderTimeline";

const T = "2026-11-16"; // a Monday
const opt = (
  rows: Record<string, [string, string, number, string[], boolean?]>,
  extra: Partial<SelectionOption> = {},
): SelectionOption => ({
  orders: Object.keys(rows),
  value: 0,
  start: T,
  end: T,
  days: 1,
  alongside: 0,
  idle_days: 0,
  idle_machines: [],
  utilisation: 0,
  bottlenecks: 0,
  bottleneck_names: [],
  late: [],
  contribution: 0,
  margin: 0,
  per_day: 0,
  dropped: {},
  rows: Object.fromEntries(
    Object.entries(rows).map(([id, [start, finish, late_days, route, idle_fill]]) => [
      id,
      { start, finish, late_days, route, idle_fill: !!idle_fill },
    ]),
  ),
  ...extra,
});
const order = (number: string) => ({
  number,
  customer: "C",
  product: "P",
  qty: 1,
  unit: "pcs",
  value: 1,
  deadline: T,
  priority: "high",
  est_margin: 1,
});

const selection: Selection = {
  orders: { a: order("ORD-1"), b: order("ORD-2"), c: order("ORD-3") },
  selected: ["a"],
  base: ["a", "b"],
  using: "own",
  running: [
    {
      id: "r",
      number: "ORD-9",
      customer: "Bajaj",
      product: "P",
      progress: 50,
      start: addDays(T, -3),
      finish: addDays(T, 1),
      machines: ["CNC 01"],
      machine: "CNC 01",
    },
  ],
  options: {
    own: opt({
      a: [T, addDays(T, 2), 0, ["Press 01", "CNC 01"]],
      b: [addDays(T, 2), addDays(T, 4), 1, ["CNC 01"]],
    }),
    part: opt({
      a: [T, addDays(T, 2), 0, ["Press 01", "CNC 01"]],
      b: [addDays(T, 2), addDays(T, 4), 1, ["CNC 01"]],
      c: [T, T, 0, ["CNC 02"], true],
    }),
    full: opt(
      { c: [T, T, 0, ["CNC 02"], true] },
      { dropped: { a: "low margin", b: "ships late" } },
    ),
    best: "full",
    criteria: ["late"],
  },
};

test("timeline: running row, routes, late, idle-machine fill, left out, tags, highlight", () => {
  const onFocus = vi.fn();
  render(<OrderTimeline selection={selection} today={T} focus="own" onFocus={onFocus} />);
  // running bar starts before the range: clipped, still labelled with machine + customer
  expect(screen.getByText("CNC 01 · Bajaj")).toBeInTheDocument();
  expect(screen.getAllByText("Press 01 → CNC 01")).toHaveLength(2);
  expect(screen.getAllByText("CNC 01 · 1 day late")).toHaveLength(2);
  expect(screen.getAllByText("CNC 02 · idle machine")).toHaveLength(2);
  expect(screen.getByText("Left out · low margin")).toBeInTheDocument();
  expect(screen.getByText("Current")).toBeInTheDocument();
  expect(screen.getByText("Best score")).toBeInTheDocument();
  expect(screen.getByText(`keeps your 2 + 1 · ${range(T, T)}`)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Highlight Fully optimized" }));
  expect(onFocus).toHaveBeenCalledWith("full");
});

test("timeline: from/to range sets the day columns (default 3 weeks)", () => {
  render(<OrderTimeline selection={selection} today={T} focus="own" onFocus={() => {}} />);
  expect(screen.getByText("21 days")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Timeline to"), { target: { value: addDays(T, 6) } });
  expect(screen.getByText("7 days")).toBeInTheDocument();
});
