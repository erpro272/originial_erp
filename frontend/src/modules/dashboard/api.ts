import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, unwrap, type Schemas } from "@/api/client";
import { ALERTS as DEMO_ALERTS } from "@/modules/production/demoData";

export type Dashboard = Schemas["DashboardOut"];
export type Timeline = Schemas["Timeline"];
export type TimelineRow = Schemas["TimelineRow"];
export type MachineLoad = Schemas["MachineLoad"];
export type CashMonth = Schemas["CashMonth"];
export type Alert = Schemas["Alert"];
export type DashAlert = Alert & { demo?: boolean; time?: string };

export function useDashboard(from: string | null, to: string | null) {
  return useQuery({
    queryKey: ["dashboard", from, to],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/dashboard", {
          params: { query: { from: from ?? undefined, to: to ?? undefined } },
        }),
      ),
  });
}

// ---- date range (kept in the URL: ?from=YYYY-MM-DD&to=YYYY-MM-DD; none = this week and next)

export const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const parse = (s: string) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y!, m! - 1, d!);
};
const add = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const monday = (d: Date) => add(d, -((d.getDay() + 6) % 7));

export interface Preset {
  key: string;
  label: string;
  from: string;
  to: string;
}

export function presets(today = new Date()): Preset[] {
  const mon = monday(today);
  const first = new Date(today.getFullYear(), today.getMonth(), 1);
  const last = new Date(today.getFullYear(), today.getMonth() + 1, 0);
  return [
    { key: "two_weeks", label: "This week and next", from: iso(mon), to: iso(add(mon, 12)) },
    { key: "week", label: "This week", from: iso(mon), to: iso(add(mon, 5)) },
    { key: "next14", label: "Next 14 days", from: iso(today), to: iso(add(today, 13)) },
    { key: "month", label: "This month", from: iso(first), to: iso(last) },
    { key: "next30", label: "Next 30 days", from: iso(today), to: iso(add(today, 29)) },
  ];
}

export function useRange() {
  const [params, setParams] = useSearchParams();
  const from = params.get("from");
  const to = params.get("to");
  const set = (f: string | null, t: string | null) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (f && t) {
          n.set("from", f);
          n.set("to", t);
        } else {
          n.delete("from");
          n.delete("to");
        }
        return n;
      },
      { replace: true },
    );
  return { from, to, set };
}

export function rangeLabel(from: string, to: string) {
  const a = parse(from);
  const b = parse(to);
  const day = (d: Date) => d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return `${day(a)} – ${day(b)} ${b.getFullYear()}`;
}

/** API alerts + the Production tab's demo alerts (marked as demo until Production has a backend). */
export function withDemo(alerts: Alert[]): DashAlert[] {
  const demo: DashAlert[] = DEMO_ALERTS.map((a, i) => ({
    id: `demo-${i}`,
    source: "production",
    tone: a.tone,
    title: a.title,
    text: a.text,
    at: null,
    time: a.at,
    link: "/production",
    demo: true,
  }));
  const order = { hi: 0, md: 1, bl: 2, ok: 3 } as const;
  return [...alerts, ...demo].sort((a, b) => order[a.tone] - order[b.tone]);
}

/** Where a schedule row opens: the plan's schedule (step 3), else the order in Orders. */
export function rowLink(t: Timeline, r: TimelineRow) {
  const plan = t.source === "approved" ? t.plan : (t.draft ?? t.plan);
  return plan ? `/planning/${plan.id}?step=3` : `/orders?q=${r.number}`;
}
